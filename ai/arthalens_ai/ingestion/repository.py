"""PostgreSQL persistence for ingestion (runs as the ``app_ai`` role).

Parameterised SQL only (threat model T-13). Each IPO is saved in one transaction, so a
failure never leaves a half-written snapshot.
"""

import hashlib
import re
import unicodedata
from typing import Any
from uuid import UUID

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from arthalens_ai.domain.resolve import ResolvedField
from arthalens_ai.ingestion.models import LoadedDocument
from arthalens_ai.ingestion.pipeline import RunStatus, SaveOutcome, SnapshotDraft
from arthalens_ai.ingestion.searchport import Blocked
from arthalens_ai.policy.exclusion import EntityRef, ExclusionPolicy, evaluate, normalize_name


def _required(row: Any, what: str) -> Any:
    """Asserts disappear under ``python -O``; a missing row must always be an error."""
    if row is None:
        raise RuntimeError(f"expected a row from {what}")
    return row


def slugify(normalized_name: str) -> str:
    ascii_name = unicodedata.normalize("NFKD", normalized_name).encode("ascii", "ignore").decode()
    base = re.sub(r"[^a-z0-9]+", "-", ascii_name.lower()).strip("-")[:70].strip("-") or "ipo"
    # Suffix from the full normalized name keeps slugs unique and stable across runs.
    return f"{base}-{hashlib.sha256(normalized_name.encode()).hexdigest()[:6]}"


class PostgresIngestionRepository:
    def __init__(self, conn: psycopg.AsyncConnection[Any]) -> None:
        self._conn = conn

    @classmethod
    async def connect(cls, dsn: str) -> "PostgresIngestionRepository":
        conn = await psycopg.AsyncConnection.connect(dsn, autocommit=True, connect_timeout=5)
        return cls(conn)

    async def close(self) -> None:
        await self._conn.close()

    async def start_run(self, provider: str) -> UUID:
        cur = await self._conn.execute(
            "INSERT INTO ingestion_runs (provider) VALUES (%s) RETURNING id", (provider,)
        )
        row = _required(await cur.fetchone(), "row")
        return UUID(str(row[0]))

    async def finish_run(
        self, run_id: UUID, status: RunStatus, counts: dict[str, int], error: str | None
    ) -> None:
        await self._conn.execute(
            "UPDATE ingestion_runs SET status = %s, counts = %s, error = %s, finished_at = now()"
            " WHERE id = %s",
            (status, Jsonb(counts), error, run_id),
        )

    async def record_quarantine(self, run_id: UUID, blocked: Blocked) -> None:
        r, c = blocked.result, blocked.candidate
        await self._conn.execute(
            """
            INSERT INTO quarantined_entities (entity_kind, raw_name, normalized_name, decision,
                reason, rule_id, policy_version, provider, source_url, last_ingestion_run_id)
            VALUES ('ipo', %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (entity_kind, normalized_name, rule_id) DO UPDATE SET
                raw_name = EXCLUDED.raw_name, decision = EXCLUDED.decision,
                reason = EXCLUDED.reason, policy_version = EXCLUDED.policy_version,
                provider = EXCLUDED.provider, source_url = EXCLUDED.source_url,
                last_ingestion_run_id = EXCLUDED.last_ingestion_run_id,
                last_seen_at = now(), seen_count = quarantined_entities.seen_count + 1
            """,
            (
                c.name[:300],
                normalize_name(c.name),
                r.decision,
                r.reason,
                r.rule_id,
                r.policy_version,
                c.provider,
                c.source_url,
                run_id,
            ),
        )

    async def save_snapshot(self, run_id: UUID, draft: SnapshotDraft) -> SaveOutcome:
        async with self._conn.transaction(), self._conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                """
                INSERT INTO ipos (slug, company_name, normalized_name, policy_version, is_synthetic)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (normalized_name) DO UPDATE SET
                    company_name = EXCLUDED.company_name,
                    policy_version = EXCLUDED.policy_version
                RETURNING id, current_snapshot_id
                """,
                (
                    slugify(draft.normalized_name),
                    draft.company_name,
                    draft.normalized_name,
                    draft.policy_version,
                    draft.is_synthetic,
                ),
            )
            ipo = _required(await cur.fetchone(), "ipo")
            ipo_id: UUID = ipo["id"]

            await cur.execute(
                "SELECT content_fingerprint, version FROM ipo_snapshots WHERE id = %s",
                (ipo["current_snapshot_id"],),
            )
            current = await cur.fetchone()
            if current and current["content_fingerprint"] == draft.fingerprint:
                return SaveOutcome(ipo_id=ipo_id, version=current["version"], created=False)

            evidence_ids = {d.ref: await self._insert_evidence(cur, d) for d in draft.documents}

            await cur.execute(
                "SELECT coalesce(max(version), 0) + 1 AS v FROM ipo_snapshots WHERE ipo_id = %s",
                (ipo_id,),
            )
            version_row = _required(await cur.fetchone(), "version_row")
            version: int = version_row["v"]

            await cur.execute(
                """
                INSERT INTO ipo_snapshots (ipo_id, version, derived_status, status_as_of,
                    content_fingerprint, ingestion_run_id)
                VALUES (%s, %s, %s, %s, %s, %s) RETURNING id
                """,
                (ipo_id, version, draft.status, draft.status_as_of, draft.fingerprint, run_id),
            )
            snap = _required(await cur.fetchone(), "snap")
            snapshot_id: UUID = snap["id"]

            for resolved in draft.resolution.fields.values():
                await self._insert_field(cur, snapshot_id, resolved, evidence_ids, draft)

            await cur.execute(
                "UPDATE ipos SET current_snapshot_id = %s WHERE id = %s", (snapshot_id, ipo_id)
            )
            return SaveOutcome(ipo_id=ipo_id, version=version, created=True)

    @staticmethod
    async def _insert_evidence(cur: psycopg.AsyncCursor[Any], d: LoadedDocument) -> UUID:
        s = d.spec
        await cur.execute(
            """
            INSERT INTO evidence_documents (content_sha256, canonical_url, title, publisher,
                published_at, retrieved_at, source_type, authority, retrieval_method, provider,
                mime_type, byte_size, text_content, display_rights, is_synthetic)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (content_sha256, canonical_url) DO NOTHING
            RETURNING id
            """,
            (
                d.sha256,
                s.url,
                s.title,
                s.publisher,
                s.published_at,
                d.retrieved_at,
                s.source_type,
                s.authority,
                d.retrieval_method,
                d.provider,
                s.mime_type,
                d.byte_size,
                d.text,
                s.display_rights,
                d.is_synthetic,
            ),
        )
        row = await cur.fetchone()
        if row is None:  # same document already stored: reuse it (append-only, no update)
            await cur.execute(
                "SELECT id FROM evidence_documents"
                " WHERE content_sha256 = %s AND canonical_url = %s",
                (d.sha256, s.url),
            )
            row = _required(await cur.fetchone(), "row")
        return UUID(str(row["id"]))

    @staticmethod
    async def _insert_field(
        cur: psycopg.AsyncCursor[Any],
        snapshot_id: UUID,
        f: ResolvedField,
        evidence_ids: dict[str, UUID],
        draft: SnapshotDraft,
    ) -> None:
        winner = f.winner
        await cur.execute(
            """
            INSERT INTO ipo_snapshot_fields (snapshot_id, field, value, status, evidence_id,
                evidence_quote, checked_at, note)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                snapshot_id,
                f.field,
                Jsonb(f.value) if f.value is not None else None,
                f.status,
                evidence_ids[winner.doc.key] if winner else None,
                winner.quote if winner else None,
                draft.checked_at,
                f.note,
            ),
        )
        for o in f.observations:
            await cur.execute(
                """
                INSERT INTO ipo_field_observations (snapshot_id, field, value, raw_value,
                    evidence_id, evidence_quote, quote_verified, parse_error, observed_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    snapshot_id,
                    o.field,
                    Jsonb(o.value) if o.value is not None else None,
                    o.raw_value,
                    evidence_ids[o.doc.key],
                    o.quote,
                    o.quote_verified,
                    o.parse_error,
                    draft.checked_at,
                ),
            )

    async def reconcile_policy(self, policy: ExclusionPolicy) -> int:
        """Exclusion layer L6: hide stored IPOs that a newer policy version blocks."""
        cur = await self._conn.execute(
            "SELECT id, company_name FROM ipos WHERE exclusion_status = 'allowed'"
        )
        withdrawn = 0
        for ipo_id, name in await cur.fetchall():
            if evaluate(policy, EntityRef(name=name), "ipo").blocked:
                await self._conn.execute(
                    "UPDATE ipos SET exclusion_status = 'withdrawn_by_policy', policy_version = %s"
                    " WHERE id = %s",
                    (policy.version, ipo_id),
                )
                withdrawn += 1
        return withdrawn
