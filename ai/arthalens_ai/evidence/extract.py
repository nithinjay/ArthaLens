"""Turn source bytes into page-anchored text (replaces Milestone 2's ingestion/text.py).

Plain text and HTML are parsed in-process with the standard library. PDFs, the riskiest input,
are parsed in a sandboxed worker process (see ``sandbox``), with OCR for scanned pages.
"""

import json
import logging
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Literal

from arthalens_ai.evidence.sandbox import (
    DEFAULT_LIMITS,
    SandboxError,
    SandboxLimits,
    python_module,
    run_sandboxed,
)

logger = logging.getLogger(__name__)

EXTRACTOR_VERSION = "m3.1"
MAX_PDF_PAGES = 1500

ExtractionMethod = Literal["plain_text", "html", "pdf_text", "pdf_text_ocr"]


class ExtractionError(ValueError):
    pass


@dataclass(frozen=True)
class PageText:
    page_number: int | None  # None for formats without pages
    text: str
    extraction: Literal["text", "ocr"] = "text"
    ocr_confidence: float | None = None


@dataclass(frozen=True)
class Extraction:
    method: ExtractionMethod
    page_count: int | None
    pages: tuple[PageText, ...]
    ocr_available: bool = False

    @property
    def text(self) -> str:
        return "\n".join(p.text for p in self.pages)

    def page_texts(self) -> tuple[tuple[int | None, str], ...]:
        return tuple((p.page_number, p.text) for p in self.pages)


class _TextOnly(HTMLParser):
    _SKIP = frozenset({"script", "style", "noscript", "template"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skipping = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self._SKIP:
            self._skipping += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP and self._skipping:
            self._skipping -= 1

    def handle_data(self, data: str) -> None:
        if not self._skipping:
            self.parts.append(data)


def _html(content: bytes) -> str:
    parser = _TextOnly()
    parser.feed(content.decode("utf-8", errors="replace"))
    parser.close()
    return " ".join(" ".join(parser.parts).split())


async def extract(
    content: bytes,
    mime_type: str,
    *,
    ocr: bool = True,
    limits: SandboxLimits = DEFAULT_LIMITS,
) -> Extraction:
    is_pdf = content.startswith(b"%PDF-")
    if mime_type == "application/pdf":
        if not is_pdf:
            raise ExtractionError("declared application/pdf but the bytes are not a PDF")
        return await _pdf(content, ocr, limits)
    if is_pdf:
        raise ExtractionError(f"declared {mime_type} but the bytes are a PDF")
    if mime_type == "text/plain":
        text = content.decode("utf-8", errors="replace")
        return Extraction("plain_text", None, (PageText(None, text),))
    if mime_type == "text/html":
        return Extraction("html", None, (PageText(None, _html(content)),))
    raise ExtractionError(f"unsupported type {mime_type}")


async def _pdf(content: bytes, ocr: bool, limits: SandboxLimits) -> Extraction:
    command = python_module(
        "arthalens_ai.evidence.pdf_worker",
        "--ocr",
        "on" if ocr else "off",
        "--max-pages",
        str(MAX_PDF_PAGES),
    )
    try:
        raw = await run_sandboxed(command, content, limits)
        data = json.loads(raw)
        pages = tuple(
            PageText(
                page_number=int(p["page"]),
                text=str(p["text"]),
                extraction="ocr" if p["extraction"] == "ocr" else "text",
                ocr_confidence=None if p["ocr_confidence"] is None else float(p["ocr_confidence"]),
            )
            for p in data["pages"]
        )
        page_count = int(data["page_count"])
    except SandboxError as exc:
        raise ExtractionError(f"PDF could not be parsed ({exc.code})") from exc
    except (ValueError, KeyError, TypeError) as exc:
        raise ExtractionError("PDF worker returned malformed output") from exc
    if len(pages) != page_count or [p.page_number for p in pages] != list(range(1, page_count + 1)):
        raise ExtractionError("PDF worker returned inconsistent page numbering")
    used_ocr = any(p.extraction == "ocr" for p in pages)
    if ocr and not data.get("ocr_available") and any(len(p.text.strip()) < 20 for p in pages):
        logger.warning("PDF has pages without a text layer but OCR is unavailable")
    return Extraction(
        method="pdf_text_ocr" if used_ocr else "pdf_text",
        page_count=page_count,
        pages=pages,
        ocr_available=bool(data.get("ocr_available")),
    )
