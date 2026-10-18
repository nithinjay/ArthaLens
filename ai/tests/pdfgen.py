"""Build small PDFs for tests, without extra dependencies.

``text_pdf`` writes a real text layer (Helvetica, one line per string). ``scanned_pdf`` writes
pages that are only images, like a scan: there is no text layer, so only OCR can read them.
All content is SYNTHETIC.
"""

import io


def text_pdf(pages: list[list[str]]) -> bytes:
    objects: dict[int, bytes] = {
        1: b"<< /Type /Catalog /Pages 2 0 R >>",
        3: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    }
    page_ids = [4 + 2 * i for i in range(len(pages))]
    kids = b" ".join(b"%d 0 R" % p for p in page_ids)
    objects[2] = b"<< /Type /Pages /Kids [" + kids + b"] /Count %d >>" % len(pages)
    for i, lines in enumerate(pages):
        ops = ["BT", "/F1 12 Tf", "72 720 Td", "16 TL"]
        for line in lines:
            escaped = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            ops.append(f"({escaped}) Tj T*")
        ops.append("ET")
        stream = "\n".join(ops).encode("latin-1")
        content_id = page_ids[i] + 1
        objects[content_id] = b"<< /Length %d >>\nstream\n%s\nendstream" % (len(stream), stream)
        objects[page_ids[i]] = (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 3 0 R >> >> /Contents %d 0 R >>" % content_id
        )
    out = bytearray(b"%PDF-1.4\n")
    offsets: dict[int, int] = {}
    for oid in sorted(objects):
        offsets[oid] = len(out)
        out += b"%d 0 obj\n%s\nendobj\n" % (oid, objects[oid])
    xref = len(out)
    size = max(objects) + 1
    out += b"xref\n0 %d\n0000000000 65535 f \n" % size
    for oid in range(1, size):
        out += b"%010d 00000 n \n" % offsets[oid]
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (size, xref)
    return bytes(out)


def scanned_pdf(pages: list[list[str]]) -> bytes:
    from PIL import Image, ImageDraw, ImageFont

    font = ImageFont.load_default(size=44)
    images = []
    for lines in pages:
        image = Image.new("L", (1700, 2200), 255)
        draw = ImageDraw.Draw(image)
        for n, line in enumerate(lines):
            draw.text((150, 200 + n * 90), line, fill=0, font=font)
        images.append(image)
    buf = io.BytesIO()
    images[0].save(buf, "PDF", resolution=200, save_all=True, append_images=images[1:])
    return buf.getvalue()
