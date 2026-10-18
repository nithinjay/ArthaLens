"""Evidence ledger: read side. This is the only evidence interface research agents get.

There are no write methods, by design: agents may read evidence but can't create source ids
or rewrite source content (brief section 9). Every query runs with the caller's tenant
context, so row-level security decides what is visible; a document another tenant uploaded
simply doesn't exist from here.
"""

import itertools
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

from arthalens_ai.domain.resolve import squash
from arthalens_ai.evidence.freshness import Freshness, freshness


@dataclass(frozen=True)
class DocumentView:
    id: UUID
    source_key: str
    version: int
    supersedes_id: UUID | None
    url: str
    title: str
    publisher: str
    published_at: date | None
    retrieved_at: datetime
    source_type: str
    authority: str
    retrieval_method: str
    display_rights: str
    is_synthetic: bool
    content_sha256: str
    page_count: int | None
    extraction_method: str
    freshness: Freshness


@dataclass(frozen=True)
class PassageView:
    page_number: int | None
    passage_index: int
    text: str
    extraction: str
    ocr_confidence: float | None


@dataclass(frozen=True)
class Location:
    page_number: int | None
    passage_index: int


class EvidenceReader:
    def __init__(
        self,
        conn: psycopg.AsyncConnection[Any],
        tenant_id: UUID | None = None,
        now: datetime | None = None,
    ) -> None:
        self._conn = conn
        self._tenant_id = tenant_id
        self._now = now

    @asynccontextmanager
    async def _cursor(self) -> AsyncIterator[psycopg.AsyncCursor[dict[str, Any]]]:
        async with self._conn.transaction(), self._conn.cursor(row_factory=dict_row) as cur:
            # Always set it, even to empty: a stale value from earlier on this connection must
            # never leak into this read.
            await cur.execute(
                "SELECT set_config('app.tenant_id', %s, true)",
                (str(self._tenant_id) if self._tenant_id else "",),
            )
            yield cur

    async def document(self, document_id: UUID) -> DocumentView | None:
        async with self._cursor() as cur:
            await cur.execute(
                """
                SELECT d.id, d.source_key, d.version, d.supersedes_id, d.canonical_url, d.title,
                       d.publisher, d.published_at, d.retrieved_at, d.source_type, d.authority,
                       d.retrieval_method, d.display_rights, d.is_synthetic, d.content_sha256,
                       c.page_count, c.extraction_method
                  FROM evidence_documents d
                  JOIN evidence_contents c ON c.sha256 = d.content_sha256
                 WHERE d.id = %s
                """,
                (document_id,),
            )
            row = await cur.fetchone()
        if row is None:
            return None
        now = self._now or datetime.now(UTC)
        return DocumentView(
            id=row["id"],
            source_key=row["source_key"],
            version=row["version"],
            supersedes_id=row["supersedes_id"],
            url=row["canonical_url"],
            title=row["title"],
            publisher=row["publisher"],
            published_at=row["published_at"],
            retrieved_at=row["retrieved_at"],
            source_type=row["source_type"],
            authority=row["authority"],
            retrieval_method=row["retrieval_method"],
            display_rights=row["display_rights"],
            is_synthetic=row["is_synthetic"],
            content_sha256=row["content_sha256"],
            page_count=row["page_count"],
            extraction_method=row["extraction_method"],
            freshness=freshness(row["source_type"], row["retrieved_at"], now),
        )

    async def passages(
        self, document_id: UUID, pages: Sequence[int] | None = None
    ) -> list[PassageView]:
        """Passages of a document, optionally only some pages. ``pages=[]`` means no pages
        (an empty selection returns nothing, never the whole document)."""
        if pages is not None and len(pages) == 0:
            return []
        page_filter = list(pages) if pages is not None else None
        async with self._cursor() as cur:
            await cur.execute(
                """
                SELECT p.page_number, p.passage_index, p.text, p.extraction, p.ocr_confidence
                  FROM evidence_documents d
                  JOIN evidence_passages p ON p.content_sha256 = d.content_sha256
                 WHERE d.id = %s AND (%s::int[] IS NULL OR p.page_number = ANY(%s::int[]))
                 ORDER BY coalesce(p.page_number, 0), p.passage_index
                """,
                (document_id, page_filter, page_filter),
            )
            rows = await cur.fetchall()
        return [
            PassageView(
                page_number=r["page_number"],
                passage_index=r["passage_index"],
                text=r["text"],
                extraction=r["extraction"],
                ocr_confidence=float(r["ocr_confidence"])
                if r["ocr_confidence"] is not None
                else None,
            )
            for r in rows
        ]

    async def locate(self, document_id: UUID, quote: str) -> Location | None:
        """Where a verbatim quote appears, if it does: the page and the passage it starts in.

        Matches across passage boundaries within a page, and across a page break (cited to
        the page the quote starts on), using the same normalisation as quote verification.
        """
        needle = squash(quote)
        if not needle:
            return None
        by_page: dict[int | None, list[PassageView]] = {}
        for p in await self.passages(document_id):
            by_page.setdefault(p.page_number, []).append(p)

        def starts(page: int | None, offset: int) -> Location:
            seen = 0
            for p in by_page[page]:
                seen += len(squash(p.text)) + 1
                if offset < seen:
                    return Location(page, p.passage_index)
            return Location(page, by_page[page][-1].passage_index)

        joined = {page: " ".join(squash(p.text) for p in ps) for page, ps in by_page.items()}
        for page, text in joined.items():
            offset = text.find(needle)
            if offset != -1:
                return starts(page, offset)
        # A quote running across a page break is cited to the page it starts on.
        numbered = sorted((n, t) for n, t in joined.items() if n is not None)
        for (page, text), (_, following) in itertools.pairwise(numbered):
            offset = f"{text} {following}".find(needle)
            if offset != -1 and offset < len(text):
                return starts(page, offset)
        return None

    async def set_labels(self, set_id: UUID) -> dict[str, UUID]:
        async with self._cursor() as cur:
            await cur.execute(
                "SELECT label, document_id FROM evidence_set_items WHERE set_id = %s"
                " ORDER BY position",
                (set_id,),
            )
            return {r["label"]: r["document_id"] for r in await cur.fetchall()}
