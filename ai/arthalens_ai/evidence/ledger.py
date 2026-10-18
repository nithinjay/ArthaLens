"""Evidence ledger: write side. Only the retrieval and ingestion layer holds one (brief section 9).

``record`` is idempotent and append-only:
- same source + same bytes      -> the existing document; a retrieval is logged
- same source + different bytes -> a new version that supersedes the previous one
- bytes are stored once by hash; their text is stored once as page-anchored passages
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
from arthalens_ai.evidence.canonical import source_key, upload_source_key
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
        key = (
            upload_source_key(source.tenant_id, sha)
            if (source.retrieval_method == "upload" and source.tenant_id)
            else source_key(source.url)
        )
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
                "SELECT id, version FROM evidence_documents"
                " WHERE source_key = %s AND content_sha256 = %s",
                (key, sha),
            )
            existing = await cur.fetchone()
            if existing:
                await self._log_retrieval(
                    cur, existing["id"], source, retrieved_at, ingestion_run_id
                )
                return EvidenceRef(
                    existing["id"], existing["version"], sha, key, False, content_created
                )

            await cur.execute(
                "SELECT id, version FROM evidence_documents WHERE source_key = %s"
                " ORDER BY version DESC LIMIT 1",
                (key,),
            )
            latest = await cur.fetchone()
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
