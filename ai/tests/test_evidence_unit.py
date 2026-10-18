"""Evidence ledger building blocks that need no database."""

import asyncio
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from arthalens_ai.domain.resolve import EvidenceDoc, RawObservation, expand
from arthalens_ai.evidence.blobstore import BlobIntegrityError, LocalBlobStore, blob_key
from arthalens_ai.evidence.canonical import source_key, upload_source_key
from arthalens_ai.evidence.extract import Extraction, ExtractionError, PageText, extract
from arthalens_ai.evidence.freshness import freshness
from arthalens_ai.evidence.passages import to_passages
from arthalens_ai.evidence.sandbox import SandboxError, SandboxLimits, run_sandboxed
from tests.pdfgen import text_pdf

# --- canonical source keys ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("url", "key"),
    [
        ("HTTPS://WWW.SEBI.GOV.IN/filings/rhp.pdf", "https://www.sebi.gov.in/filings/rhp.pdf"),
        ("https://www.sebi.gov.in:443/a", "https://www.sebi.gov.in/a"),
        ("https://www.sebi.gov.in./a#page=4", "https://www.sebi.gov.in/a"),
        ("https://x.test/a?b=2&a=1", "https://x.test/a?a=1&b=2"),
        ("https://x.test/a?utm_source=mail&id=7&fbclid=z", "https://x.test/a?id=7"),
        ("https://x.test", "https://x.test/"),
        ("http://x.test:8080/a", "http://x.test:8080/a"),
    ],
)
def test_source_key(url: str, key: str) -> None:
    assert source_key(url) == key


def test_query_pairs_are_kept_raw_not_reencoded() -> None:
    # Matches the SQL canonical_source_key used by the backfill: no decode/re-encode.
    assert source_key("https://x.test/a?q=a%20b&p=c+d") == "https://x.test/a?p=c+d&q=a%20b"
    assert source_key("https://x.test/a?&&b=1&") == "https://x.test/a?b=1"


def test_tenant_keys_never_collide_with_public_keys() -> None:
    from uuid import uuid4

    from arthalens_ai.evidence.canonical import tenant_source_key

    url = "https://www.sebi.gov.in/rhp.pdf"
    key = tenant_source_key(uuid4(), url)
    assert key != source_key(url) and key.startswith("tenant:") and key.endswith(source_key(url))


@pytest.mark.parametrize("url", ["ftp://x.test/a", "file:///etc/passwd", "https:///nohost"])
def test_source_key_rejects(url: str) -> None:
    with pytest.raises(ValueError):
        source_key(url)


def test_upload_keys_are_tenant_scoped() -> None:
    from uuid import uuid4

    sha = "a" * 64
    assert upload_source_key(uuid4(), sha) != upload_source_key(uuid4(), sha)


# --- write-once blob store ----------------------------------------------------------------

DATA = b"SYNTHETIC source bytes"


def sha_of(data: bytes) -> str:
    import hashlib

    return hashlib.sha256(data).hexdigest()


def test_blob_put_get_round_trip(tmp_path: Path) -> None:
    store = LocalBlobStore(tmp_path)
    key = store.put(sha_of(DATA), DATA)
    assert key == blob_key(sha_of(DATA))
    assert store.get(key) == DATA
    assert store.put(sha_of(DATA), DATA) == key  # idempotent


def test_blob_rejects_bytes_that_do_not_match_hash(tmp_path: Path) -> None:
    with pytest.raises(BlobIntegrityError):
        LocalBlobStore(tmp_path).put(sha_of(b"other"), DATA)


def test_blob_detects_tampering(tmp_path: Path) -> None:
    store = LocalBlobStore(tmp_path)
    key = store.put(sha_of(DATA), DATA)
    path = tmp_path / key
    os.chmod(path, 0o640)
    path.write_bytes(b"tampered")
    with pytest.raises(BlobIntegrityError, match="altered"):
        store.get(key)


def test_blob_files_are_read_only(tmp_path: Path) -> None:
    key = LocalBlobStore(tmp_path).put(sha_of(DATA), DATA)
    assert (tmp_path / key).stat().st_mode & 0o222 == 0


@pytest.mark.parametrize(
    "key", ["../../etc/passwd", "sha256/zz/" + "a" * 64, "sha256/ab/" + "c" * 64]
)
def test_blob_rejects_malformed_keys(tmp_path: Path, key: str) -> None:
    with pytest.raises(ValueError):
        LocalBlobStore(tmp_path).get(key)


# --- passages -----------------------------------------------------------------------------


def test_passages_keep_page_numbers_and_all_text() -> None:
    long_page = " ".join(f"word{i}" for i in range(1000))  # ~6900 chars
    extraction = Extraction("pdf_text", 2, (PageText(1, "short page"), PageText(2, long_page)))
    passages = to_passages(extraction, limit=2000)
    assert passages[0].page_number == 1 and passages[0].passage_index == 0
    page2 = [p for p in passages if p.page_number == 2]
    assert [p.passage_index for p in page2] == list(range(len(page2)))
    assert all(len(p.text) <= 2000 for p in passages)
    assert " ".join(p.text for p in page2).split() == long_page.split()  # nothing dropped


def test_empty_pages_produce_no_passages() -> None:
    assert to_passages(Extraction("pdf_text", 1, (PageText(1, "   "),))) == []


def test_ocr_passages_keep_confidence() -> None:
    extraction = Extraction("pdf_text_ocr", 1, (PageText(1, "Lot size: 50", "ocr", 88.5),))
    [p] = to_passages(extraction)
    assert (p.extraction, p.ocr_confidence) == ("ocr", 88.5)


# --- freshness ----------------------------------------------------------------------------

T0 = datetime(2026, 10, 18, 6, 0, tzinfo=UTC)


def test_exchange_notice_goes_stale_after_a_day() -> None:
    assert freshness("exchange_notice", T0, T0 + timedelta(hours=23)).status == "fresh"
    stale = freshness("exchange_notice", T0, T0 + timedelta(hours=25))
    assert stale.status == "stale" and stale.stale_after == T0 + timedelta(hours=24)


def test_offer_documents_do_not_expire_by_age() -> None:
    assert freshness("offer_document", T0, T0 + timedelta(days=900)).status == "no_expiry"


def test_unknown_source_type_is_an_error() -> None:
    with pytest.raises(ValueError):
        freshness("tweet", T0, T0)


# --- sandbox ------------------------------------------------------------------------------


def py(code: str) -> list[str]:
    return [sys.executable, "-I", "-c", code]


def test_sandbox_returns_stdout() -> None:
    assert (
        asyncio.run(
            run_sandboxed(py("import sys; sys.stdout.write(sys.stdin.read()[::-1])"), b"abc")
        )
        == b"cba"
    )


def test_sandbox_kills_on_timeout() -> None:
    limits = SandboxLimits(wall_seconds=0.5)
    with pytest.raises(SandboxError) as info:
        asyncio.run(run_sandboxed(py("import time; time.sleep(30)"), b"", limits))
    assert info.value.code == "timeout"


def test_sandbox_reports_crashes() -> None:
    with pytest.raises(SandboxError) as info:
        asyncio.run(run_sandboxed(py("raise SystemExit('boom')"), b""))
    assert info.value.code == "worker_failed" and "boom" in str(info.value)


def test_sandbox_caps_output() -> None:
    limits = SandboxLimits(max_output_bytes=1000)
    with pytest.raises(SandboxError) as info:
        asyncio.run(run_sandboxed(py("print('x' * 5000)"), b"", limits))
    assert info.value.code == "output_too_large"


def test_sandbox_does_not_inherit_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://app_ai:supersecret@db/x")
    monkeypatch.setenv("GEMINI_API_KEY", "not-a-real-key")
    out = asyncio.run(
        run_sandboxed(py("import os, json; print(json.dumps(dict(os.environ)))"), b"")
    )
    assert b"supersecret" not in out and b"not-a-real-key" not in out


def test_sandbox_stops_a_flood_without_buffering_it() -> None:
    """Review finding: the cap must apply while reading, not after buffering everything."""
    import resource
    import time

    flood = (
        "import sys\nchunk = b'x' * (1 << 20)\nfor _ in range(2048): sys.stdout.buffer.write(chunk)"
    )
    started = time.monotonic()
    with pytest.raises(SandboxError) as info:
        asyncio.run(run_sandboxed(py(flood), b"", SandboxLimits(max_output_bytes=8 << 20)))
    assert info.value.code == "output_too_large"
    assert time.monotonic() - started < 10
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    rss_mb = rss / (1 << 20) if sys.platform == "darwin" else rss / 1024
    assert rss_mb < 1024  # a 2 GB flood never lands in this process


def test_sandbox_keeps_only_the_tail_of_stderr() -> None:
    noisy = "import sys\nsys.stderr.write('x' * (8 << 20) + '\\nlast line')\nraise SystemExit(2)"
    with pytest.raises(SandboxError) as info:
        asyncio.run(run_sandboxed(py(noisy), b""))
    assert info.value.code == "worker_failed" and "last line" in str(info.value)


@pytest.mark.skipif(sys.platform != "linux", reason="RLIMIT_AS is only enforced on Linux")
def test_sandbox_enforces_memory_limit() -> None:
    limits = SandboxLimits(memory_bytes=256 * 1024**2)
    with pytest.raises(SandboxError) as info:
        asyncio.run(run_sandboxed(py("x = bytearray(1024 ** 3)"), b"", limits))
    assert info.value.code == "worker_failed"


# --- PDF extraction (sandboxed worker) ----------------------------------------------------

RHP = text_pdf(
    [
        ["SYNTHETIC RED HERRING PROSPECTUS", "Risk factors follow."],
        ["THE OFFER", "Price Band: Rs 285 to Rs 300 per equity share"],
        ["Minimum Bid Lot: 50 Equity Shares"],
    ]
)


def test_pdf_pages_are_numbered() -> None:
    x = asyncio.run(extract(RHP, "application/pdf"))
    assert (x.method, x.page_count) == ("pdf_text", 3)
    assert [p.page_number for p in x.pages] == [1, 2, 3]
    assert "Price Band" in x.pages[1].text


def test_observation_records_the_page_its_quote_is_on() -> None:
    x = asyncio.run(extract(RHP, "application/pdf"))
    doc = EvidenceDoc("rhp", "issuer_filing", None, x.text, x.page_texts())
    raw = RawObservation("lot_size", "50 Equity Shares", "Minimum Bid Lot: 50 Equity Shares", doc)
    [obs] = expand(raw)
    assert (obs.quote_verified, obs.page) == (True, 3)


def test_quote_across_a_page_break_is_cited_to_its_first_page() -> None:
    from arthalens_ai.domain.resolve import page_of, squash

    pages = (
        (11, "Intro."),
        (12, "Section 4. The Price Band: Rs 100"),
        (13, "to Rs 105 per share."),
    )
    squashed = tuple((n, squash(t)) for n, t in pages)
    assert page_of(squash("Price Band: Rs 100 to Rs 105"), squashed) == 12
    assert page_of(squash("Rs 105 per share"), squashed) == 13
    assert page_of(squash("not in the document"), squashed) is None
    assert page_of("", squashed) is None


def test_unverified_quote_has_no_page() -> None:
    x = asyncio.run(extract(RHP, "application/pdf"))
    doc = EvidenceDoc("rhp", "issuer_filing", None, x.text, x.page_texts())
    [obs] = expand(RawObservation("lot_size", "60", "Minimum Bid Lot: 60 Equity Shares", doc))
    assert (obs.quote_verified, obs.page) == (False, None)


def test_malformed_pdf_fails_inside_the_sandbox() -> None:
    with pytest.raises(ExtractionError, match="could not be parsed"):
        asyncio.run(extract(b"%PDF-1.7\n" + b"\x00garbage" * 100, "application/pdf"))


def test_pdf_over_page_limit_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    import arthalens_ai.evidence.extract as ex

    monkeypatch.setattr(ex, "MAX_PDF_PAGES", 2)
    with pytest.raises(ExtractionError):
        asyncio.run(extract(RHP, "application/pdf"))
