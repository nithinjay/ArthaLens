"""Split extracted page text into passages small enough to cite and to send to a model.

Splitting never drops or rewrites text: joining a page's passages with single spaces
reproduces the page with only whitespace runs collapsed at the split points.
"""

from dataclasses import dataclass

from arthalens_ai.evidence.extract import Extraction

MAX_PASSAGE_CHARS = 2000


@dataclass(frozen=True)
class Passage:
    page_number: int | None
    passage_index: int
    text: str
    extraction: str  # "text" | "ocr"
    ocr_confidence: float | None


def _split(text: str, limit: int) -> list[str]:
    """Greedy split on the strongest boundary available: paragraph, line, word, character."""
    text = text.strip()
    if len(text) <= limit:
        return [text] if text else []
    for sep in ("\n\n", "\n", " "):
        cut = text.rfind(sep, 0, limit + 1)
        if cut > 0:
            return [text[:cut].strip(), *_split(text[cut + len(sep) :], limit)]
    return [text[:limit], *_split(text[limit:], limit)]


def to_passages(extraction: Extraction, limit: int = MAX_PASSAGE_CHARS) -> list[Passage]:
    passages: list[Passage] = []
    for page in extraction.pages:
        for index, chunk in enumerate(_split(page.text, limit)):
            passages.append(
                Passage(
                    page_number=page.page_number,
                    passage_index=index,
                    text=chunk,
                    extraction=page.extraction,
                    ocr_confidence=page.ocr_confidence,
                )
            )
    return passages
