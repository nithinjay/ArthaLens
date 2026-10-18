"""Extract plain text from source documents, for quote verification.

Untrusted input (threat model T-21): the declared type must match the bytes, and PDFs are
limited in size and pages. Scanned PDFs yield little or no text, so their quotes won't verify
and their fields stay "Not verified" until OCR arrives (Milestone 3/4). Parsing in a sandboxed
subprocess is also a Milestone 3 item.
"""

import io
import logging
from html.parser import HTMLParser

from pypdf import PdfReader
from pypdf.errors import PdfReadError

logger = logging.getLogger(__name__)

MAX_PDF_PAGES = 1500


class ExtractionError(ValueError):
    pass


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


def extract_text(content: bytes, mime_type: str) -> str:
    if mime_type == "application/pdf":
        return _pdf(content)
    if content.startswith(b"%PDF-"):
        raise ExtractionError(f"declared {mime_type} but the bytes are a PDF")
    text = content.decode("utf-8", errors="replace")
    if mime_type == "text/html":
        parser = _TextOnly()
        parser.feed(text)
        parser.close()
        return " ".join(" ".join(parser.parts).split())
    if mime_type == "text/plain":
        return text
    raise ExtractionError(f"unsupported type {mime_type}")


def _pdf(content: bytes) -> str:
    if not content.startswith(b"%PDF-"):
        raise ExtractionError("declared application/pdf but the bytes are not a PDF")
    try:
        reader = PdfReader(io.BytesIO(content))
        if len(reader.pages) > MAX_PDF_PAGES:
            raise ExtractionError(f"PDF has more than {MAX_PDF_PAGES} pages")
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    except PdfReadError as exc:
        raise ExtractionError(f"unreadable PDF: {type(exc).__name__}") from exc
