"""End-to-end ingestion over the synthetic fixtures, with the clock fixed at 18 Oct 2026 IST."""

import asyncio
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

import pytest

from arthalens_ai.ingestion.pipeline import IngestionPipeline, RunReport
from arthalens_ai.ingestion.providers.files import FileImportProvider
from arthalens_ai.ingestion.searchport import EntityBlockedError, SearchPort
from arthalens_ai.policy.exclusion import load_policy
from tests.fakes import InMemoryRepo

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "ipos"
NOW = datetime(2026, 10, 18, 6, 0, tzinfo=UTC)  # 11:30 IST


def run(repo: InMemoryRepo, fixtures: Path = FIXTURES) -> RunReport:
    provider = FileImportProvider.fixtures(fixtures)
    port = SearchPort({"fixtures": provider}, load_policy())
    return asyncio.run(
        IngestionPipeline(port, repo, load_policy(), clock=lambda: NOW).run("fixtures")
    )


@pytest.fixture(scope="module")
def ingested() -> tuple[InMemoryRepo, RunReport]:
    repo = InMemoryRepo()
    return repo, run(repo)


def test_run_counts(ingested: tuple[InMemoryRepo, RunReport]) -> None:
    _, report = ingested
    assert report.status == "succeeded", report.errors
    assert report.counts == {
        "discovered": 8,
        "quarantined": 2,
        "created": 6,
        "unchanged": 0,
        "failed": 0,
        "withdrawn": 0,
    }


def test_excluded_entities_are_quarantined_without_reading_documents(
    ingested: tuple[InMemoryRepo, RunReport],
) -> None:
    """Their fixture points at a document file that does not exist. Any attempt to load it
    would have failed the run, so a clean run proves documents were never touched."""
    repo, _ = ingested
    jio = repo.quarantine["Jio Platforms Limited (SYNTHETIC TEST ENTITY)"].result
    lookalike = repo.quarantine["J1O Digital Networks Limited (SYNTHETIC TEST ENTITY)"].result
    assert (jio.decision, jio.reason) == ("excluded", "token")
    assert (lookalike.decision, lookalike.reason) == ("quarantined", "confusable")
    assert not (FIXTURES / "docs" / "must-never-be-read.txt").exists()
    names = {d[-1].company_name for d in repo.snapshots.values()}
    assert not any("jio" in n.lower() or "j1o" in n.lower() for n in names)


@pytest.mark.parametrize(
    ("company", "status"),
    [
        ("Synthetic Alpha Foods Limited", "open"),
        ("Synthetic Beta Logistics Limited", "upcoming"),
        ("Synthetic Gamma Textiles Limited", "listed"),
        ("Synthetic Delta Chemicals Limited", "withdrawn"),
        ("Synthetic Epsilon Power Limited", "upcoming"),
        ("Synthetic Zeta Retail Limited", "unverified"),
    ],
)
def test_derived_status(
    ingested: tuple[InMemoryRepo, RunReport], company: str, status: str
) -> None:
    snap = ingested[0].latest(company)
    assert snap.status == status
    assert snap.status_as_of.isoformat() == "2026-10-18"


def test_every_verified_field_has_grounded_provenance(
    ingested: tuple[InMemoryRepo, RunReport],
) -> None:
    """AC-2.2: no field is verified without a document, a quote found in it, and a time."""
    repo, _ = ingested
    checked = 0
    for history in repo.snapshots.values():
        snap = history[-1]
        texts = {d.ref: d.text for d in snap.documents}
        for f in snap.resolution.fields.values():
            if f.status == "verified":
                assert f.winner is not None and f.value is not None
                assert f.winner.quote_verified
                assert " ".join(f.winner.quote.split()) in " ".join(texts[f.winner.doc.key].split())
                checked += 1
        assert snap.checked_at == NOW
    assert checked > 30


def test_alpha_fields(ingested: tuple[InMemoryRepo, RunReport]) -> None:
    fields = ingested[0].latest("Synthetic Alpha Foods Limited").resolution.fields
    values = {name: (f.status, f.value) for name, f in fields.items()}
    assert values["price_band_low"] == ("verified", "28500")
    assert values["price_band_high"] == ("verified", "30000")
    assert values["lot_size"] == ("verified", 50)
    assert values["issue_size"] == ("verified", str(1200 * 10**7 * 100))
    assert values["fresh_issue_size"] == ("verified", str(800 * 10**7 * 100))
    assert values["ofs_size"] == ("verified", str(400 * 10**7 * 100))
    assert values["listing_date_basis"] == ("verified", "estimated")
    assert values["exchanges"] == ("verified", ["BSE", "NSE"])
    assert values["official_status"] == ("unavailable", None)


def test_addendum_supersedes_original_notice(ingested: tuple[InMemoryRepo, RunReport]) -> None:
    close = ingested[0].latest("Synthetic Beta Logistics Limited").resolution.fields["close_date"]
    assert (close.status, close.value) == ("verified", "2026-10-30")
    assert close.note and "differ" in close.note


def test_pdf_source_cites_the_page_of_its_quote(ingested: tuple[InMemoryRepo, RunReport]) -> None:
    snap = ingested[0].latest("Synthetic Beta Logistics Limited")
    fresh = snap.resolution.fields["fresh_issue_size"]
    assert (fresh.status, fresh.value) == ("verified", str(2500 * 10**7 * 100))
    assert fresh.winner is not None and fresh.winner.page == 2
    rhp = next(d for d in snap.documents if d.ref == "rhp")
    assert (rhp.extraction.method, rhp.extraction.page_count) == ("pdf_text", 3)


def test_missing_fields_are_unavailable_not_guessed(
    ingested: tuple[InMemoryRepo, RunReport],
) -> None:
    fields = ingested[0].latest("Synthetic Beta Logistics Limited").resolution.fields
    assert (fields["ofs_size"].status, fields["ofs_size"].value) == ("unavailable", None)
    assert (fields["issue_size"].status, fields["issue_size"].value) == ("unavailable", None)


def test_equal_exchanges_disagreeing_is_conflict(ingested: tuple[InMemoryRepo, RunReport]) -> None:
    fields = ingested[0].latest("Synthetic Epsilon Power Limited").resolution.fields
    assert (fields["lot_size"].status, fields["lot_size"].value) == ("conflict", None)
    band = fields["price_band_low"]
    assert (band.status, band.value) == ("verified", "45000")  # exchange beats news
    assert band.note and "differ" in band.note


def test_stale_news_dates_stay_unverified(ingested: tuple[InMemoryRepo, RunReport]) -> None:
    fields = ingested[0].latest("Synthetic Zeta Retail Limited").resolution.fields
    assert fields["open_date"].status == "unverified"
    assert fields["official_status"].value == "upcoming"


def test_rerun_with_same_sources_writes_no_new_snapshots(
    ingested: tuple[InMemoryRepo, RunReport],
) -> None:
    repo, _ = ingested
    again = run(repo)
    assert again.counts["created"] == 0
    assert again.counts["unchanged"] == 6
    assert all(len(h) == 1 for h in repo.snapshots.values())


def test_one_broken_fixture_makes_the_run_partial(tmp_path: Path) -> None:
    fixtures = tmp_path / "ipos"
    shutil.copytree(FIXTURES, fixtures)
    (fixtures / "docs" / "alpha-rhp.txt").unlink()
    report = run(InMemoryRepo(), fixtures)
    assert report.status == "partial"
    assert report.counts["failed"] == 1 and report.counts["created"] == 5
    assert "Synthetic Alpha Foods Limited" in report.errors[0]


def test_fixture_provider_refuses_non_synthetic_data(tmp_path: Path) -> None:
    data = json.loads((FIXTURES / "alpha-open.json").read_text())
    data["synthetic"] = False
    (tmp_path / "real.json").write_text(json.dumps(data))
    provider = FileImportProvider.fixtures(tmp_path)
    with pytest.raises(ValueError, match="must be marked synthetic"):
        provider.candidates()


def test_searchport_rechecks_exclusion_before_loading() -> None:
    provider = FileImportProvider.fixtures(FIXTURES)
    port = SearchPort({"fixtures": provider}, load_policy())
    jio = next(c for c in provider.candidates() if "Jio" in c.name)
    with pytest.raises(EntityBlockedError):
        asyncio.run(port.load_documents(jio))


def test_document_paths_cannot_escape_import_directory(tmp_path: Path) -> None:
    data = json.loads((FIXTURES / "alpha-open.json").read_text())
    data["documents"][0]["file"] = "../../etc/passwd"
    (tmp_path / "evil.json").write_text(json.dumps(data))
    provider = FileImportProvider.fixtures(tmp_path)
    candidate = provider.candidates()[0]
    with pytest.raises(ValueError, match="escapes the import directory"):
        asyncio.run(provider.load_documents(candidate))
