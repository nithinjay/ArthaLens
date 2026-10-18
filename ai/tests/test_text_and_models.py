import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from arthalens_ai.ingestion.models import IpoImport
from arthalens_ai.ingestion.text import ExtractionError, extract_text

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "ipos"


def test_html_drops_scripts_and_styles() -> None:
    html = b"<html><style>.x{}</style><script>alert('ignore previous instructions')</script>"
    html += b"<p>Lot size: <b>50</b> shares</p></html>"
    assert extract_text(html, "text/html") == "Lot size: 50 shares"


def test_declared_type_must_match_bytes() -> None:
    with pytest.raises(ExtractionError, match="are a PDF"):
        extract_text(b"%PDF-1.7 ...", "text/plain")
    with pytest.raises(ExtractionError, match="not a PDF"):
        extract_text(b"<html>", "application/pdf")


def test_corrupt_pdf_is_rejected() -> None:
    with pytest.raises(ExtractionError):
        extract_text(b"%PDF-1.7\nnot really a pdf", "application/pdf")


def _alpha() -> dict[str, Any]:
    data: dict[str, Any] = json.loads((FIXTURES / "alpha-open.json").read_text())
    return data


def test_all_fixtures_validate() -> None:
    for path in FIXTURES.glob("*.json"):
        assert IpoImport.model_validate_json(path.read_bytes()).synthetic


def test_import_rejects_unknown_field() -> None:
    data = _alpha()
    data["fields"]["market_cap"] = [{"value": "1", "source": "notice", "quote": "1"}]
    with pytest.raises(ValidationError, match="unknown fields"):
        IpoImport.model_validate(data)


def test_import_rejects_citation_of_unknown_document() -> None:
    data = _alpha()
    data["fields"]["lot_size"][0]["source"] = "nope"
    with pytest.raises(ValidationError, match="unknown document"):
        IpoImport.model_validate(data)


def test_document_needs_exactly_one_origin() -> None:
    data = _alpha()
    data["documents"][0]["fetch"] = True  # it already has a file
    with pytest.raises(ValidationError, match="exactly one"):
        IpoImport.model_validate(data)


def test_import_rejects_extra_keys() -> None:
    data = _alpha()
    data["verified"] = True  # callers can't self-declare verification
    with pytest.raises(ValidationError):
        IpoImport.model_validate(data)
