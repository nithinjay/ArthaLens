"""Evidence ledger against a real, migrated PostgreSQL (AC-3.1 to AC-3.4).

Run with scripts/test-integration.sh, which creates a throwaway database, migrates it and
points these URLs at it. Skipped when the URLs are not set.
    TEST_DB_AI_URL     app_ai (the ledger's role)
    TEST_DB_API_URL    app_api (the backend's role)
    TEST_DB_ADMIN_URL  app_migrate (table owner; used for setup and the owner-bypass checks)
"""

import asyncio
import hashlib
import os
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest

from arthalens_ai.evidence.extract import Extraction, PageText
from arthalens_ai.evidence.ledger import EvidenceLedger, SourceRecord
from arthalens_ai.evidence.reader import EvidenceReader
from arthalens_ai.evidence.sets import EvidenceSets

AI_URL = os.environ.get("TEST_DB_AI_URL")
API_URL = os.environ.get("TEST_DB_API_URL")
ADMIN_URL = os.environ.get("TEST_DB_ADMIN_URL")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not (AI_URL and API_URL and ADMIN_URL), reason="no test database"),
]

NOW = datetime(2026, 10, 18, 6, 0, tzinfo=UTC)
Conn = psycopg.AsyncConnection[Any]


def run(test: Callable[[Conn, Conn, Conn], Awaitable[None]]) -> None:
    async def main() -> None:
        ai = await psycopg.AsyncConnection.connect(str(AI_URL), autocommit=True)
        api = await psycopg.AsyncConnection.connect(str(API_URL), autocommit=True)
        admin = await psycopg.AsyncConnection.connect(str(ADMIN_URL), autocommit=True)
        try:
            await test(ai, api, admin)
        finally:
            for c in (ai, api, admin):
                await c.close()

    asyncio.run(main())


def source(url: str, tenant: UUID | None = None, method: str = "mock_fixture") -> SourceRecord:
    return SourceRecord(
        url=url,
        title="[SYNTHETIC] test document",
        publisher="SYNTHETIC FIXTURE",
        published_at=None,
        source_type="exchange_notice",
        authority="official_exchange",
        retrieval_method=method,
        provider="test",
        display_rights="excerpt",
        is_synthetic=True,
        mime_type="text/plain",
        tenant_id=tenant,
        request_metadata={"http_status": 200},
    )


def pages(*texts: str) -> Extraction:
    return Extraction(
        "pdf_text", len(texts), tuple(PageText(i + 1, t) for i, t in enumerate(texts))
    )


def url() -> str:
    return f"https://fixtures.arthalens.test/it/{uuid4()}.txt"


async def scalar(conn: Conn, sql: str, *params: Any) -> Any:
    cur = await conn.execute(sql, params)
    row = await cur.fetchone()
    return row[0] if row else None


async def make_tenant(admin: Conn) -> UUID:
    return UUID(
        str(
            await scalar(
                admin,
                "INSERT INTO tenants (name, kind)"
                " VALUES ('SYNTHETIC IT tenant', 'personal') RETURNING id",
            )
        )
    )


async def expect_error(coro: Awaitable[Any], fragment: str) -> None:
    with pytest.raises(psycopg.Error) as info:
        await coro
    assert fragment in str(info.value)


# --- AC-3.2: de-duplication, versions, stable labels --------------------------------------


def test_same_source_same_bytes_is_one_document_with_two_retrievals() -> None:
    async def t(ai: Conn, api: Conn, admin: Conn) -> None:
        ledger, u, body = EvidenceLedger(ai, None), url(), b"SYNTHETIC v1"
        first = await ledger.record(source(u), body, pages("v1"), NOW)
        second = await ledger.record(source(u + "#ignored-fragment"), body, pages("v1"), NOW)
        assert first.document_id == second.document_id and second.created is False
        assert (
            await scalar(
                admin,
                "SELECT count(*) FROM evidence_retrievals WHERE document_id = %s",
                first.document_id,
            )
            == 2
        )

    run(t)


def test_changed_bytes_make_a_new_version_that_supersedes() -> None:
    async def t(ai: Conn, api: Conn, admin: Conn) -> None:
        ledger, u = EvidenceLedger(ai, None), url()
        v1 = await ledger.record(source(u), b"SYNTHETIC v1", pages("v1"), NOW)
        v2 = await ledger.record(source(u), b"SYNTHETIC v2", pages("v2"), NOW)
        assert (v1.version, v2.version, v2.created) == (1, 2, True)
        doc = await EvidenceReader(ai, now=NOW).document(v2.document_id)
        assert doc is not None and doc.supersedes_id == v1.document_id
        back = await ledger.record(source(u), b"SYNTHETIC v1", pages("v1"), NOW)
        assert back.document_id == v1.document_id  # reverting content reuses the old version

    run(t)


def test_identical_bytes_from_two_sources_share_one_content() -> None:
    async def t(ai: Conn, api: Conn, admin: Conn) -> None:
        ledger, body = EvidenceLedger(ai, None), f"SYNTHETIC mirror {uuid4()}".encode()
        a = await ledger.record(source(url()), body, pages("mirror"), NOW)
        b = await ledger.record(source(url()), body, pages("mirror"), NOW)
        assert a.document_id != b.document_id and a.content_sha256 == b.content_sha256
        assert (a.content_created, b.content_created) == (True, False)
        n = await scalar(
            admin,
            "SELECT count(*) FROM evidence_passages WHERE content_sha256 = %s",
            a.content_sha256,
        )
        assert n == 1  # passages stored once per content

    run(t)


def test_labels_are_stable_idempotent_and_gap_free_under_concurrency() -> None:
    async def t(ai: Conn, api: Conn, admin: Conn) -> None:
        ledger = EvidenceLedger(ai, None)
        docs = [
            (
                await ledger.record(source(url()), f"SYNTHETIC {uuid4()}".encode(), pages("x"), NOW)
            ).document_id
            for _ in range(6)
        ]
        set_id = await EvidenceSets(ai).create("test")
        conns = [await psycopg.AsyncConnection.connect(str(AI_URL), autocommit=True) for _ in docs]
        try:
            labels = await asyncio.gather(
                *(EvidenceSets(c).add(set_id, d) for c, d in zip(conns, docs, strict=True))
            )
        finally:
            for c in conns:
                await c.close()
        assert sorted(labels, key=lambda lab: int(lab[1:])) == [f"d{i}" for i in range(1, 7)]
        again = await EvidenceSets(ai).add(set_id, docs[0])
        assert again == labels[0]  # re-adding returns the original label
        mapping = await EvidenceReader(ai).set_labels(set_id)
        assert mapping == {lab: d for lab, d in zip(labels, docs, strict=True)}

    run(t)


# --- AC-3.1: immutability ------------------------------------------------------------------


def test_evidence_cannot_be_changed_even_by_the_table_owner() -> None:
    async def t(ai: Conn, api: Conn, admin: Conn) -> None:
        ref = await EvidenceLedger(ai, None).record(
            source(url()), f"SYNTHETIC {uuid4()}".encode(), pages("p"), NOW
        )
        d = ref.document_id
        await expect_error(
            ai.execute("UPDATE evidence_documents SET title = 'x' WHERE id = %s", (d,)),
            "permission denied",
        )
        await expect_error(
            ai.execute("DELETE FROM evidence_documents WHERE id = %s", (d,)), "permission denied"
        )
        for sql in (
            "UPDATE evidence_documents SET title = 'x' WHERE id = %s",
            "DELETE FROM evidence_documents WHERE id = %s",
        ):
            await expect_error(admin.execute(sql, (d,)), "EVIDENCE_IMMUTABLE")
        await expect_error(
            admin.execute(
                "UPDATE evidence_passages SET text = 'rewritten' WHERE content_sha256 = %s",
                (ref.content_sha256,),
            ),
            "EVIDENCE_IMMUTABLE",
        )
        await expect_error(admin.execute("TRUNCATE evidence_retrievals"), "EVIDENCE_IMMUTABLE")
        await expect_error(
            admin.execute(
                "UPDATE evidence_contents SET byte_size = 0 WHERE sha256 = %s",
                (ref.content_sha256,),
            ),
            "EVIDENCE_IMMUTABLE",
        )

    run(t)


def test_retained_bytes_can_be_attached_once_and_nothing_else_changes() -> None:
    async def t(ai: Conn, api: Conn, admin: Conn) -> None:
        body = f"SYNTHETIC {uuid4()}".encode()
        first = await EvidenceLedger(ai, None).record(source(url()), body, pages("p"), NOW)
        sha = first.content_sha256
        assert (
            await scalar(admin, "SELECT storage_key FROM evidence_contents WHERE sha256 = %s", sha)
            is None
        )

        class Blobs:
            def put(self, sha256: str, data: bytes) -> str:
                return f"sha256/{sha256[:2]}/{sha256}"

            def get(self, key: str) -> bytes:
                raise NotImplementedError

        await EvidenceLedger(ai, Blobs()).record(source(url()), body, pages("p"), NOW)
        key = await scalar(
            admin, "SELECT storage_key FROM evidence_contents WHERE sha256 = %s", sha
        )
        assert key == f"sha256/{sha[:2]}/{sha}"
        other = f"sha256/{'0' * 2}/{'0' * 64}"
        await expect_error(  # once set, the key can't be replaced...
            admin.execute(
                "UPDATE evidence_contents SET storage_key = %s WHERE sha256 = %s", (other, sha)
            ),
            "EVIDENCE_IMMUTABLE",
        )
        await expect_error(  # ...and attaching a key can't smuggle in another change
            admin.execute(
                "UPDATE evidence_contents SET storage_key = NULL, byte_size = 1 WHERE sha256 = %s",
                (sha,),
            ),
            "EVIDENCE_IMMUTABLE",
        )

    run(t)


def test_label_assignments_cannot_be_rewritten() -> None:
    async def t(ai: Conn, api: Conn, admin: Conn) -> None:
        ledger = EvidenceLedger(ai, None)
        a = await ledger.record(source(url()), f"SYNTHETIC {uuid4()}".encode(), pages("a"), NOW)
        b = await ledger.record(source(url()), f"SYNTHETIC {uuid4()}".encode(), pages("b"), NOW)
        sets = EvidenceSets(ai)
        set_id = await sets.create("test")
        await sets.add(set_id, a.document_id)
        await expect_error(
            admin.execute(
                "UPDATE evidence_set_items SET document_id = %s WHERE set_id = %s",
                (b.document_id, set_id),
            ),
            "EVIDENCE_IMMUTABLE",
        )
        await expect_error(
            admin.execute("UPDATE evidence_sets SET next_position = 1 WHERE id = %s", (set_id,)),
            "EVIDENCE_IMMUTABLE",
        )

    run(t)


def test_retention_purge_is_the_only_way_to_delete() -> None:
    async def t(ai: Conn, api: Conn, admin: Conn) -> None:
        ref = await EvidenceLedger(ai, None).record(
            source(url()), f"SYNTHETIC {uuid4()}".encode(), pages("p"), NOW
        )
        async with admin.transaction():
            await admin.execute("SET LOCAL arthalens.evidence_retention = 'on'")
            await admin.execute(
                "DELETE FROM evidence_retrievals WHERE document_id = %s", (ref.document_id,)
            )
            await admin.execute("DELETE FROM evidence_documents WHERE id = %s", (ref.document_id,))
        assert (
            await scalar(
                admin, "SELECT count(*) FROM evidence_documents WHERE id = %s", ref.document_id
            )
            == 0
        )
        # The opt-in is transaction-local: the next statement is protected again.
        await expect_error(
            admin.execute(
                "DELETE FROM evidence_passages WHERE content_sha256 = %s", (ref.content_sha256,)
            ),
            "EVIDENCE_IMMUTABLE",
        )

    run(t)


# --- AC-3.3: page-level provenance ---------------------------------------------------------


def test_passages_and_quote_location_keep_page_numbers() -> None:
    async def t(ai: Conn, api: Conn, admin: Conn) -> None:
        extraction = Extraction(
            "pdf_text_ocr",
            2,
            (
                PageText(1, "Cover page"),
                PageText(2, "Minimum Bid Lot: 50 Equity Shares", "ocr", 87.25),
            ),
        )
        ref = await EvidenceLedger(ai, None).record(
            source(url()), f"SYNTHETIC {uuid4()}".encode(), extraction, NOW
        )
        reader = EvidenceReader(ai, now=NOW)
        page2 = await reader.passages(ref.document_id, pages=[2])
        assert [(p.page_number, p.extraction, p.ocr_confidence) for p in page2] == [
            (2, "ocr", 87.25)
        ]
        loc = await reader.locate(ref.document_id, "minimum bid lot:  50 equity SHARES")
        assert loc is not None and loc.page_number == 2
        assert await reader.locate(ref.document_id, "Lot: 60") is None
        doc = await reader.document(ref.document_id)
        assert doc is not None and (doc.page_count, doc.extraction_method) == (2, "pdf_text_ocr")
        assert doc.freshness.status == "fresh"

    run(t)


# --- AC-3.4: tenant isolation --------------------------------------------------------------


def test_private_evidence_is_invisible_to_other_tenants() -> None:
    async def t(ai: Conn, api: Conn, admin: Conn) -> None:
        tenant_a, tenant_b = await make_tenant(admin), await make_tenant(admin)
        body = f"SYNTHETIC private upload {uuid4()}".encode()
        ref = await EvidenceLedger(ai, None).record(
            source(url(), tenant=tenant_a, method="upload"), body, pages("Secret lot size 77"), NOW
        )
        assert ref.source_key.startswith(f"upload:{tenant_a}:")

        assert await EvidenceReader(ai, tenant_a).document(ref.document_id) is not None
        assert await EvidenceReader(ai, tenant_b).document(ref.document_id) is None
        assert await EvidenceReader(ai, None).document(ref.document_id) is None
        assert await EvidenceReader(ai, tenant_b).passages(ref.document_id) == []
        assert await EvidenceReader(ai, tenant_b).locate(ref.document_id, "Secret lot size") is None

        # The backend role sees nothing either, with or without another tenant's context.
        for tenant in ("", str(tenant_b)):
            async with api.transaction():
                await api.execute("SELECT set_config('app.tenant_id', %s, true)", (tenant,))
                n = await scalar(
                    api, "SELECT count(*) FROM evidence_documents WHERE id = %s", ref.document_id
                )
            assert n == 0

    run(t)


def test_a_set_cannot_cite_another_tenants_document() -> None:
    async def t(ai: Conn, api: Conn, admin: Conn) -> None:
        tenant_a, tenant_b = await make_tenant(admin), await make_tenant(admin)
        ref = await EvidenceLedger(ai, None).record(
            source(url(), tenant=tenant_a, method="upload"),
            f"SYNTHETIC {uuid4()}".encode(),
            pages("a"),
            NOW,
        )
        b_sets = EvidenceSets(ai, tenant_b)
        b_set = await b_sets.create("research_report")
        await expect_error(b_sets.add(b_set, ref.document_id), "EVIDENCE_NOT_VISIBLE")
        # Even the owner, bypassing RLS, can't put tenant A's document in tenant B's set.
        await expect_error(
            admin.execute(
                "INSERT INTO evidence_set_items (set_id, position, document_id) VALUES (%s, 1, %s)",
                (b_set, ref.document_id),
            ),
            "EVIDENCE_NOT_VISIBLE",
        )
        assert (
            await EvidenceSets(ai, tenant_a).add(
                await EvidenceSets(ai, tenant_a).create("test"), ref.document_id
            )
            == "d1"
        )

    run(t)


def test_tenant_cannot_see_or_use_another_tenants_set() -> None:
    async def t(ai: Conn, api: Conn, admin: Conn) -> None:
        tenant_a, tenant_b = await make_tenant(admin), await make_tenant(admin)
        a_set = await EvidenceSets(ai, tenant_a).create("research_report")
        public = await EvidenceLedger(ai, None).record(
            source(url()), f"SYNTHETIC {uuid4()}".encode(), pages("p"), NOW
        )
        with pytest.raises(LookupError):
            await EvidenceSets(ai, tenant_b).add(a_set, public.document_id)
        assert await EvidenceReader(ai, tenant_b).set_labels(a_set) == {}

    run(t)


def test_a_tenant_cannot_write_evidence_as_another_tenant() -> None:
    async def t(ai: Conn, api: Conn, admin: Conn) -> None:
        tenant_a, tenant_b = await make_tenant(admin), await make_tenant(admin)
        sha = hashlib.sha256(f"SYNTHETIC {uuid4()}".encode()).hexdigest()
        await admin.execute(
            "INSERT INTO evidence_contents"
            " (sha256, mime_type, byte_size, extraction_method, extractor_version)"
            " VALUES (%s, 'text/plain', 1, 'plain_text', 'test')",
            (sha,),
        )
        async with ai.transaction():
            await ai.execute("SELECT set_config('app.tenant_id', %s, true)", (str(tenant_b),))
            await expect_error(
                ai.execute(
                    """INSERT INTO evidence_documents (content_sha256, canonical_url, source_key,
                        version, title, publisher, retrieved_at, source_type, authority,
                        retrieval_method, provider, display_rights, visibility, tenant_id)
                       VALUES (%s, 'https://x.test/', %s, 1, 't', 'p', now(), 'other', 'unofficial',
                        'upload', 'test', 'excerpt', 'tenant', %s)""",
                    (sha, f"upload:{tenant_a}:{sha}", tenant_a),
                ),
                "row-level security",
            )

    run(t)
