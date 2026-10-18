"""PostgreSQL persistence for research runs (role ``app_ai``).

Every transaction sets ``app.tenant_id`` first, so row-level security applies to the worker
too: a bug can't read or write another tenant's report. The only cross-tenant step is
claiming a job, done by the ``claim_research_job`` function.

Saving a section is one transaction: the section, its claims, their citations and the
``section.completed`` event commit together or not at all. That is what makes a crash safe:
a section is either fully saved (and skipped on retry) or not saved at all.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

from arthalens_ai.evidence.sets import EvidenceSets
from arthalens_ai.research.catalog import CATALOG
from arthalens_ai.research.contracts import (
    FinalCitation,
    FinalClaim,
    SectionId,
    SectionResult,
    UsageRecord,
)
from arthalens_ai.research.planner import LabelledPassage
from arthalens_ai.research.structure import SnapshotField

Cursor = psycopg.AsyncCursor[dict[str, Any]]


@dataclass(frozen=True)
class ClaimedJob:
    job_id: UUID
    report_id: UUID
    tenant_id: UUID
    attempt: int


@dataclass(frozen=True)
class ReportContext:
    report_id: UUID
    tenant_id: UUID
    ipo_id: UUID
    company_name: str
    ipo_exclusion_status: str
    snapshot_id: UUID
    snapshot_evidence_set_id: UUID | None
    evidence_set_id: UUID | None
    status: str
    started_at: datetime | None


class ResearchStore:
    def __init__(self, pool: AsyncConnectionPool[Any]) -> None:
        self.pool = pool

    @asynccontextmanager
    async def tenant_tx(self, tenant_id: UUID) -> AsyncIterator[Cursor]:
        async with self.pool.connection() as conn, conn.transaction():
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute("SELECT set_config('app.tenant_id', %s, true)", (str(tenant_id),))
                yield cur

    # --- jobs -------------------------------------------------------------------------------

    async def claim(self, worker: str, lease_s: int) -> ClaimedJob | None:
        async with self.pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            await cur.execute("SELECT fail_exhausted_research_jobs()")
            await cur.execute("SELECT * FROM claim_research_job(%s, %s)", (worker, lease_s))
            row = await cur.fetchone()
        if row is None:
            return None
        return ClaimedJob(row["job_id"], row["report_id"], row["tenant_id"], row["attempt"])

    async def renew_lease(self, job: ClaimedJob, worker: str, lease_s: int) -> bool:
        async with self.tenant_tx(job.tenant_id) as cur:
            await cur.execute(
                "UPDATE research_jobs SET lease_expires_at = now() + make_interval(secs => %s)"
                " WHERE id = %s AND lease_owner = %s AND status = 'running'",
                (lease_s, job.job_id, worker),
            )
            return cur.rowcount == 1

    async def finish_job(
        self, job: ClaimedJob, worker: str, status: str, error: str | None
    ) -> None:
        async with self.tenant_tx(job.tenant_id) as cur:
            await cur.execute(
                "UPDATE research_jobs SET status = %s, lease_owner = NULL, lease_expires_at = NULL,"
                " last_error = %s WHERE id = %s AND lease_owner = %s",
                (status, error, job.job_id, worker),
            )

    async def retry_later(self, job: ClaimedJob, worker: str, delay_s: int, error: str) -> None:
        async with self.tenant_tx(job.tenant_id) as cur:
            await cur.execute(
                "UPDATE research_jobs SET status = 'queued', lease_owner = NULL,"
                " lease_expires_at = NULL, last_error = %s,"
                " next_run_at = now() + make_interval(secs => %s)"
                " WHERE id = %s AND lease_owner = %s",
                (error[:1000], delay_s, job.job_id, worker),
            )

    # --- report context ---------------------------------------------------------------------

    async def load_report(self, job: ClaimedJob) -> ReportContext:
        async with self.tenant_tx(job.tenant_id) as cur:
            await cur.execute(
                """
                SELECT r.id, r.tenant_id, r.ipo_id, r.snapshot_id, r.evidence_set_id, r.status,
                       r.started_at, i.company_name, i.exclusion_status,
                       s.evidence_set_id AS snapshot_set
                  FROM research_reports r
                  JOIN ipos i ON i.id = r.ipo_id
                  JOIN ipo_snapshots s ON s.id = r.snapshot_id
                 WHERE r.id = %s
                """,
                (job.report_id,),
            )
            row = await cur.fetchone()
        if row is None:
            raise LookupError(f"report {job.report_id} not visible to its job's tenant")
        return ReportContext(
            row["id"],
            row["tenant_id"],
            row["ipo_id"],
            row["company_name"],
            row["exclusion_status"],
            row["snapshot_id"],
            row["snapshot_set"],
            row["evidence_set_id"],
            row["status"],
            row["started_at"],
        )

    async def set_report(self, ctx: ReportContext, **values: Any) -> None:
        allowed = {"status", "error", "evidence_set_id", "started_at", "completed_at"}
        if not values or set(values) - allowed:
            raise ValueError(f"unexpected report columns: {sorted(set(values) - allowed)}")
        columns = sorted(values)
        assignments = ", ".join(f"{c} = %s" for c in columns)  # names from the allow-list only
        async with self.tenant_tx(ctx.tenant_id) as cur:
            await cur.execute(
                f"UPDATE research_reports SET {assignments} WHERE id = %s",  # noqa: S608
                (*[values[c] for c in columns], ctx.report_id),
            )

    async def ensure_evidence_set(self, ctx: ReportContext) -> UUID:
        """The report's own evidence set: the snapshot's documents, same order, labels d1..dn."""
        if ctx.evidence_set_id:
            return ctx.evidence_set_id
        async with self.pool.connection() as conn:
            sets = EvidenceSets(conn, ctx.tenant_id)
            set_id = await sets.create("research_report")
            if ctx.snapshot_evidence_set_id:
                async with conn.transaction(), conn.cursor(row_factory=dict_row) as cur:
                    await cur.execute(
                        "SELECT document_id FROM evidence_set_items"
                        " WHERE set_id = %s ORDER BY position",
                        (ctx.snapshot_evidence_set_id,),
                    )
                    documents = [r["document_id"] for r in await cur.fetchall()]
                for document_id in documents:
                    await sets.add(set_id, document_id)
        await self.set_report(ctx, evidence_set_id=set_id)
        return set_id

    async def load_passages(self, ctx: ReportContext, set_id: UUID) -> list[LabelledPassage]:
        async with self.tenant_tx(ctx.tenant_id) as cur:
            await cur.execute(
                """
                SELECT it.label, d.id::text AS document_id, d.source_type, p.page_number,
                       p.passage_index, p.text
                  FROM evidence_set_items it
                  JOIN evidence_documents d ON d.id = it.document_id
                  JOIN evidence_passages p ON p.content_sha256 = d.content_sha256
                 WHERE it.set_id = %s
                 ORDER BY it.position, coalesce(p.page_number, 0), p.passage_index
                """,
                (set_id,),
            )
            rows = await cur.fetchall()
        return [
            LabelledPassage(
                r["label"],
                r["document_id"],
                r["source_type"],
                r["page_number"],
                r["passage_index"],
                r["text"],
            )
            for r in rows
        ]

    async def load_snapshot_fields(
        self, ctx: ReportContext, set_id: UUID
    ) -> dict[str, SnapshotField]:
        async with self.tenant_tx(ctx.tenant_id) as cur:
            await cur.execute(
                """
                SELECT f.field, f.status, f.value, f.evidence_id::text AS document_id,
                       f.evidence_page, f.evidence_quote, it.label
                  FROM ipo_snapshot_fields f
                  LEFT JOIN evidence_set_items it
                         ON it.set_id = %s AND it.document_id = f.evidence_id
                 WHERE f.snapshot_id = %s
                """,
                (set_id, ctx.snapshot_id),
            )
            rows = await cur.fetchall()
        return {
            r["field"]: SnapshotField(
                r["field"],
                r["status"],
                r["value"],
                r["document_id"],
                r["label"],
                r["evidence_page"],
                r["evidence_quote"],
            )
            for r in rows
        }

    async def load_done_sections(self, ctx: ReportContext) -> dict[SectionId, SectionResult]:
        async with self.tenant_tx(ctx.tenant_id) as cur:
            await cur.execute(
                "SELECT section, status, validation, reason, missing, prompt_version, model"
                " FROM research_sections WHERE report_id = %s",
                (ctx.report_id,),
            )
            sections = await cur.fetchall()
            await cur.execute(
                """
                SELECT c.id, c.section, c.position, c.text, c.claim_type, c.status, c.status_reason,
                       cc.label, cc.document_id::text AS document_id, cc.page, cc.quote
                  FROM evidence_claims c
                  LEFT JOIN claim_citations cc ON cc.claim_id = c.id
                 WHERE c.report_id = %s
                 ORDER BY c.section, c.position, cc.label
                """,
                (ctx.report_id,),
            )
            claim_rows = await cur.fetchall()
        claims: dict[str, dict[UUID, dict[str, Any]]] = {}
        for r in claim_rows:
            entry = claims.setdefault(r["section"], {}).setdefault(
                r["id"], {"row": r, "citations": []}
            )
            if r["label"]:
                entry["citations"].append(
                    FinalCitation(r["label"], r["document_id"], r["page"], r["quote"])
                )
        done: dict[SectionId, SectionResult] = {}
        for s in sections:
            final = tuple(
                FinalClaim(
                    e["row"]["text"],
                    e["row"]["claim_type"],
                    e["row"]["status"],
                    e["row"]["status_reason"],
                    tuple(e["citations"]),
                )
                for e in claims.get(s["section"], {}).values()
            )
            done[s["section"]] = SectionResult(
                s["section"],
                s["status"],
                s["validation"],
                s["reason"],
                final,
                tuple(s["missing"]),
                s["prompt_version"],
                s["model"],
            )
        return done

    # --- writes ------------------------------------------------------------------------------

    async def _event(
        self, cur: Cursor, ctx: ReportContext, type_: str, payload: dict[str, Any]
    ) -> int:
        # One writer per report at a time is not enough: sections run in parallel. The
        # advisory lock makes sequence numbers gap-free and unique.
        await cur.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 1))", (str(ctx.report_id),)
        )
        await cur.execute(
            "SELECT coalesce(max(seq), 0) + 1 AS seq FROM research_events WHERE report_id = %s",
            (ctx.report_id,),
        )
        row = await cur.fetchone()
        seq = int(row["seq"]) if row else 1
        await cur.execute(
            "INSERT INTO research_events (report_id, tenant_id, seq, type, payload)"
            " VALUES (%s, %s, %s, %s, %s)",
            (ctx.report_id, ctx.tenant_id, seq, type_, Jsonb(payload)),
        )
        # Wakes SSE listeners; the payload is only the report id (no data crosses tenants).
        await cur.execute("SELECT pg_notify('research_events', %s)", (str(ctx.report_id),))
        return seq

    async def event(self, ctx: ReportContext, type_: str, payload: dict[str, Any]) -> int:
        async with self.tenant_tx(ctx.tenant_id) as cur:
            return await self._event(cur, ctx, type_, payload)

    async def save_section(
        self, ctx: ReportContext, result: SectionResult, attempt: int, started: datetime
    ) -> bool:
        """Persist a section, its claims, citations, usage and completion event atomically.
        Returns False if the section was already saved (a retried job), writing nothing."""
        async with self.tenant_tx(ctx.tenant_id) as cur:
            await cur.execute(
                """
                INSERT INTO research_sections (report_id, tenant_id, section, title, status,
                    validation, reason, missing, prompt_version, model, attempt, started_at,
                    completed_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (report_id, section) DO NOTHING
                """,
                (
                    ctx.report_id,
                    ctx.tenant_id,
                    result.section,
                    CATALOG[result.section].title,
                    result.status,
                    result.validation,
                    (result.reason or "")[:500] or None,
                    Jsonb(list(result.missing)),
                    result.prompt_version,
                    result.model,
                    attempt,
                    started,
                    datetime.now(UTC),
                ),
            )
            if cur.rowcount == 0:
                return False
            for position, claim in enumerate(result.claims, start=1):
                await cur.execute(
                    """
                    INSERT INTO evidence_claims (report_id, tenant_id, section, position, text,
                        claim_type, status, status_reason)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id
                    """,
                    (
                        ctx.report_id,
                        ctx.tenant_id,
                        result.section,
                        position,
                        claim.text[:2000],
                        claim.claim_type,
                        claim.status,
                        (claim.status_reason or "")[:500] or None,
                    ),
                )
                row = await cur.fetchone()
                if row is None:
                    raise RuntimeError("claim insert returned no id")
                for c in {c.label: c for c in claim.citations}.values():
                    await cur.execute(
                        "INSERT INTO claim_citations"
                        " (claim_id, tenant_id, label, document_id, page, quote)"
                        " VALUES (%s, %s, %s, %s, %s, %s)",
                        (
                            row["id"],
                            ctx.tenant_id,
                            c.label,
                            c.document_id,
                            c.page,
                            (c.quote or "")[:1000] or None,
                        ),
                    )
            for u in result.usage:
                await self._usage(cur, ctx, result.section, u)
            await self._event(
                cur,
                ctx,
                "section.completed",
                {
                    "section": result.section,
                    "status": result.status,
                    "validation": result.validation,
                    "claims": sum(1 for c in result.claims if c.status != "quarantined"),
                    "quarantined": sum(1 for c in result.claims if c.status == "quarantined"),
                },
            )
            return True

    @staticmethod
    async def _usage(cur: Cursor, ctx: ReportContext, section: str, u: UsageRecord) -> None:
        await cur.execute(
            """
            INSERT INTO usage_records (tenant_id, report_id, section, provider, model, input_tokens,
                output_tokens, latency_ms, estimated_cost_usd, outcome)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                ctx.tenant_id,
                ctx.report_id,
                section,
                u.provider,
                u.model,
                u.input_tokens,
                u.output_tokens,
                u.latency_ms,
                u.estimated_cost_usd,
                u.outcome,
            ),
        )
