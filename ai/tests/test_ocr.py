"""OCR of scanned pages. Needs the tesseract binary, so it runs in the ai-test container."""

import asyncio
import shutil

import pytest

from arthalens_ai.evidence.extract import extract
from arthalens_ai.evidence.passages import to_passages
from tests.pdfgen import scanned_pdf, text_pdf

pytestmark = [
    pytest.mark.ocr,
    pytest.mark.skipif(shutil.which("tesseract") is None, reason="tesseract not installed"),
]

SCAN = scanned_pdf(
    [
        ["SYNTHETIC SCANNED NOTICE", "Bid opens on 27 October 2026"],
        ["Minimum Bid Lot: 50 Equity Shares", "Price Band: Rs 285 to Rs 300"],
    ]
)


def test_scanned_pages_are_ocrd_with_page_numbers_and_confidence() -> None:
    x = asyncio.run(extract(SCAN, "application/pdf"))
    assert x.method == "pdf_text_ocr"
    assert [p.page_number for p in x.pages] == [1, 2]
    assert all(p.extraction == "ocr" for p in x.pages)
    assert all(p.ocr_confidence is not None and 50 <= p.ocr_confidence <= 100 for p in x.pages)
    assert "Minimum Bid Lot" in x.pages[1].text
    assert "50 Equity Shares" in x.pages[1].text


def test_ocr_confidence_survives_into_passages() -> None:
    passages = to_passages(asyncio.run(extract(SCAN, "application/pdf")))
    assert passages and all(p.extraction == "ocr" and p.ocr_confidence for p in passages)


def test_ocr_can_be_disabled() -> None:
    x = asyncio.run(extract(SCAN, "application/pdf", ocr=False))
    assert x.method == "pdf_text" and all(p.text.strip() == "" for p in x.pages)


def test_pages_with_a_text_layer_are_not_ocrd() -> None:
    x = asyncio.run(
        extract(text_pdf([["Minimum Bid Lot: 50 Equity Shares here"]]), "application/pdf")
    )
    assert x.method == "pdf_text" and x.pages[0].extraction == "text"
