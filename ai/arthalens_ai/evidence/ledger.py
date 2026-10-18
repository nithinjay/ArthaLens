"""Evidence ledger: write side. Only the retrieval and ingestion layer holds one (brief section 9).

``record`` is idempotent and append-only:
- same bytes as the source's latest version -> that document; a retrieval is logged
- different bytes                           -> a new version superseding the latest, even
  if the bytes match an older version (A -> B -> A is v1, v2, v3: versions are a timeline)
- bytes are stored once by hash; their text is stored once as page-anchored passages
- tenant records live in their tenant's key namespace and never touch the public chain
Nothing is ever updated or deleted (the database refuses; see the immutability triggers).
"""

import hashlib
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any
from uuid import UUID

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from arthalens_ai.evidence.blobstore import BlobStore
from arthalens_ai.evidence.canonical import source_key, tenant_source_key, upload_source_key
from arthalens_ai.evidence.extract import EXTRACTOR_VERSION, Extraction
from arthalens_ai.evidence.passages import to_passages


@dataclass(frozen=True)
class SourceRecord:
    """Everything known about where a document came from."""

    url: str
    title: str
    publisher: str
    published_at: date | None
    source_type: str
    authority: str
    retrieval_method: str
    provider: str
    display_rights: str
    is_synthetic: bool
    mime_type: str
    tenant_id: UUID | None = None  # set for tenant-private uploads
    request_metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def visibility(self) -> str:
        return "public" if self.tenant_id is None else "tenant"


@dataclass(frozen=True)
class EvidenceRef:
    document_id: UUID
    version: int
    content_sha256: str
    source_key: str
    created: bool  # a new document (version) was written
    content_created: bool  # these bytes had never been seen before


def _key_for(source: SourceRecord, sha: str) -> str:
    if source.tenant_id is None:
        return source_key(source.url)
    if source.retrieval_method == "upload":
        return upload_source_key(source.tenant_id, sha)
    return tenant_source_key(source.tenant_id, source.url)


def _one(row: dict[str, Any] | None, what: str) -> dict[str, Any]:
    if row is None:
        raise RuntimeError(f"expected a row from {what}")
    return row


class EvidenceLedger:
    def __init__(self, conn: psycopg.AsyncConnection[Any], blobs: BlobStore | None) -> None:
        self._conn = conn
        self._blobs = blobs

    async def record(
        self,
        source: SourceRecord,
        content: bytes,
        extraction: Extraction,
        retrieved_at: datetime,
        ingestion_run_id: UUID | None = None,
    ) -> EvidenceRef:
        sha = hashlib.sha256(content).hexdigest()
        key = _key_for(source, sha)
        # Bytes first: write-once and content-addressed, so a later DB failure leaves only a
        # harmless orphan, never a document pointing at missing bytes.
        storage_key = self._blobs.put(sha, content) if self._blobs else None

        async with self._conn.transaction(), self._conn.cursor(row_factory=dict_row) as cur:
            if source.tenant_id is not None:
                await cur.execute(
                    "SELECT set_config('app.tenant_id', %s, true)", (str(source.tenant_id),)
                )
            content_created = await self._insert_content(
                cur, sha, content, source, extraction, storage_key
            )

            # Serialise version numbering per source.
            await cur.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (key,))
            await cur.execute(
                "SELECT id, version, content_sha256 FROM evidence_documents WHERE source_key = %s"
                " ORDER BY version DESC LIMIT 1",
                (key,),
            )
            latest = await cur.fetchone()
            if latest and latest["content_sha256"] == sha:
                await self._log_retrieval(cur, latest["id"], source, retrieved_at, ingestion_run_id)
                return EvidenceRef(
                    latest["id"], latest["version"], sha, key, False, content_created
                )

            version = latest["version"] + 1 if latest else 1
            await cur.execute(
                """
                INSERT INTO evidence_documents (content_sha256, canonical_url, source_key, version,
                    supersedes_id, title, publisher, published_at, retrieved_at, source_type,
                    authority, retrieval_method, provider, display_rights, is_synthetic,
                    visibility, tenant_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    sha,
                    source.url,
                    key,
                    version,
                    latest["id"] if latest else None,
                    source.title,
                    source.publisher,
                    source.published_at,
                    retrieved_at,
                    source.source_type,
                    source.authority,
                    source.retrieval_method,
                    source.provider,
                    source.display_rights,
                    source.is_synthetic,
                    source.visibility,
                    source.tenant_id,
                ),
            )
            doc_id: UUID = _one(await cur.fetchone(), "evidence_documents")["id"]
            await self._log_retrieval(cur, doc_id, source, retrieved_at, ingestion_run_id)
            return EvidenceRef(doc_id, version, sha, key, True, content_created)

    @staticmethod
    async def _insert_content(
        cur: psycopg.AsyncCursor[dict[str, Any]],
        sha: str,
        content: bytes,
        source: SourceRecord,
        extraction: Extraction,
        storage_key: str | None,
    ) -> bool:
        """Store the bytes' metadata and passages once. Returns True if the bytes were new.

        Goes through evidence_put_content (see the migration for why a plain INSERT can't).
        """
        passages = [
            {
                "page_number": p.page_number,
                "passage_index": p.passage_index,
                "text": p.text,
                "extraction": p.extraction,
                "ocr_confidence": p.ocr_confidence,
            }
            for p in to_passages(extraction)
        ]
        await cur.execute(
            "SELECT evidence_put_content(%s, %s, %s, %s, %s, %s, %s, %s) AS inserted",
            (
                sha,
                source.mime_type,
                len(content),
                extraction.page_count,
                extraction.method,
                EXTRACTOR_VERSION,
                storage_key,
                Jsonb(passages),
            ),
        )
        return bool(_one(await cur.fetchone(), "evidence_put_content")["inserted"])

    @staticmethod
    async def _log_retrieval(
        cur: psycopg.AsyncCursor[dict[str, Any]],
        document_id: UUID,
        source: SourceRecord,
        retrieved_at: datetime,
        ingestion_run_id: UUID | None,
    ) -> None:
        await cur.execute(
            """
            INSERT INTO evidence_retrievals (document_id, retrieved_at, retrieval_method, provider,
                ingestion_run_id, request_metadata)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                document_id,
                retrieved_at,
                source.retrieval_method,
                source.provider,
                ingestion_run_id,
                Jsonb(source.request_metadata),
            ),
        )
