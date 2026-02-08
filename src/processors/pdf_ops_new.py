import io
from typing import Dict
from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
from pypdf.generic import NameObject


def _safe_page_wh(page) -> tuple[float, float]:
    box = None
    try:
        box = page.get(NameObject("/CropBox"))
    except Exception:
        box = None
    if box is None:
        try:
            box = page.get(NameObject("/MediaBox"))
        except Exception:
            box = None
    if box is None:
        return 595.0, 842.0
    try:
        x0, y0, x1, y1 = [float(v) for v in list(box)]
        w = abs(x1 - x0)
        h = abs(y1 - y0)
        return (w, h) if w > 0 and h > 0 else (595.0, 842.0)
    except Exception:
        return 595.0, 842.0


def _overlay_pdf_with_png(page_w: float, page_h: float, png_bytes: bytes) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(page_w, page_h))

    img = ImageReader(io.BytesIO(png_bytes))

    # ✅ рисуем на весь лист (в PDF-пойнтах)
    c.drawImage(img, 0, 0, width=page_w, height=page_h, mask="auto")

    c.showPage()
    c.save()
    buf.seek(0)
    return buf.read()


def apply_png_overlays(src_pdf: str, out_pdf: str, overlays: Dict[int, bytes], dpi: int = 144) -> None:
    base = PdfReader(src_pdf)
    writer = PdfWriter()

    for i, page in enumerate(base.pages):
        p1 = i + 1
        if p1 in overlays:
            w, h = _safe_page_wh(page)
            overlay_bytes = _overlay_pdf_with_png(w, h, overlays[p1])
            overlay_reader = PdfReader(io.BytesIO(overlay_bytes))
            page.merge_page(overlay_reader.pages[0])

        writer.add_page(page)

    with open(out_pdf, "wb") as f:
        writer.write(f)
