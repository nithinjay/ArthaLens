"""PDF text extraction worker. Runs ONLY inside ``sandbox.run_sandboxed``.

Reads PDF bytes on stdin, writes JSON on stdout:
    {"page_count": n, "ocr_available": bool,
     "pages": [{"page": 1, "text": "...", "extraction": "text"|"ocr", "ocr_confidence": 91.5|null}]}

Each page keeps its own number so every quote can be traced to a page. Pages with almost no
text layer (scans) are rendered and OCR'd with Tesseract when ``--ocr on`` and Tesseract is
installed. OCR confidence is the mean word confidence Tesseract reports.

Usage: python -I -m arthalens_ai.evidence.pdf_worker --ocr on|off --max-pages N
"""

import argparse
import io
import json
import sys
from typing import Any

MIN_TEXT_CHARS = 20  # fewer characters than this on a page means "probably scanned"
OCR_DPI = 200


def _ocr_page(pdf: Any, index: int) -> tuple[str, float] | None:
    import pytesseract

    image = pdf[index].render(scale=OCR_DPI / 72).to_pil()
    data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT)
    lines: dict[tuple[int, int, int], list[str]] = {}
    confidences: list[float] = []
    for word, conf, block, par, line in zip(
        data["text"],
        data["conf"],
        data["block_num"],
        data["par_num"],
        data["line_num"],
        strict=True,
    ):
        conf_value = float(conf)
        if word.strip() and conf_value >= 0:
            lines.setdefault((block, par, line), []).append(word)
            confidences.append(conf_value)
    if not confidences:
        return None
    text = "\n".join(" ".join(words) for _, words in sorted(lines.items()))
    return text, round(sum(confidences) / len(confidences), 2)


def _tesseract_available() -> bool:
    try:
        import pytesseract

        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ocr", choices=("on", "off"), default="on")
    parser.add_argument("--max-pages", type=int, default=1500)
    args = parser.parse_args()

    from pypdf import PdfReader

    content = sys.stdin.buffer.read()
    reader = PdfReader(io.BytesIO(content))
    page_count = len(reader.pages)
    if page_count > args.max_pages:
        sys.exit(f"PDF has {page_count} pages; limit is {args.max_pages}")

    ocr_available = args.ocr == "on" and _tesseract_available()
    rendered = None
    pages = []
    for index, page in enumerate(reader.pages):
        text = page.extract_text() or ""
        entry: dict[str, Any] = {"page": index + 1, "text": text, "extraction": "text"}
        entry["ocr_confidence"] = None
        if ocr_available and len(text.strip()) < MIN_TEXT_CHARS:
            if rendered is None:
                import pypdfium2

                rendered = pypdfium2.PdfDocument(content)
            result = _ocr_page(rendered, index)
            if result is not None:
                entry.update(text=result[0], extraction="ocr", ocr_confidence=result[1])
        pages.append(entry)

    json.dump(
        {"page_count": page_count, "ocr_available": ocr_available, "pages": pages}, sys.stdout
    )


if __name__ == "__main__":
    main()
