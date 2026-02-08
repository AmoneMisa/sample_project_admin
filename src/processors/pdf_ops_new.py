from __future__ import annotations

import io
from typing import Dict, Tuple

from pypdf import PdfReader, PdfWriter
from pypdf.generic import NameObject
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas


def _safe_box_xywh(page, prefer_crop: bool) -> Tuple[float, float, float, float]:
    """
    Returns (x0, y0, w, h) for CropBox or MediaBox.
    If prefer_crop=True -> try CropBox first, else MediaBox first.
    """
    def _get(name: str):
        try:
            return page.get(NameObject(name))
        except Exception:
            return None

    box = None
    if prefer_crop:
        box = _get("/CropBox") or _get("/MediaBox")
    else:
        box = _get("/MediaBox") or _get("/CropBox")

    if box is None:
        return 0.0, 0.0, 595.0, 842.0

    try:
        arr = list(box)
        if len(arr) != 4:
            return 0.0, 0.0, 595.0, 842.0
        x0, y0, x1, y1 = [float(v) for v in arr]
        w = abs(x1 - x0)
        h = abs(y1 - y0)
        if w <= 0 or h <= 0:
            return 0.0, 0.0, 595.0, 842.0
        return min(x0, x1), min(y0, y1), w, h
    except Exception:
        return 0.0, 0.0, 595.0, 842.0


def _overlay_pdf_with_png(
        *,
        media_w: float,
        media_h: float,
        png_bytes: bytes,
        draw_x: float,
        draw_y: float,
        draw_w: float,
        draw_h: float,
) -> bytes:
    """
    Creates 1-page PDF of size MediaBox and draws PNG into CropBox area (with offsets).
    """
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(media_w, media_h))

    img = ImageReader(io.BytesIO(png_bytes))
    c.drawImage(img, draw_x, draw_y, width=draw_w, height=draw_h, mask="auto")

    c.showPage()
    c.save()
    buf.seek(0)
    return buf.read()


def apply_png_overlays(src_pdf: str, out_pdf: str, overlays: Dict[int, bytes], dpi: int = 144) -> None:
    """
    overlays: {page_number_1based: png_bytes}
    PNG должен соответствовать ПРЕВЬЮ (а превью почти всегда рендерится по CropBox).
    Поэтому:
      - overlay PDF делаем по MediaBox
      - PNG кладём в область CropBox (с учётом смещения относительно MediaBox)
    """
    base = PdfReader(src_pdf)
    writer = PdfWriter()

    for i, page in enumerate(base.pages):
        p1 = i + 1
        png = overlays.get(p1)

        if png:
            # Координатная система страницы = MediaBox
            media_x0, media_y0, media_w, media_h = _safe_box_xywh(page, prefer_crop=False)

            # То, что видит пользователь на превью = CropBox (обычно)
            crop_x0, crop_y0, crop_w, crop_h = _safe_box_xywh(page, prefer_crop=True)

            # Смещение CropBox внутри MediaBox
            draw_x = crop_x0 - media_x0
            draw_y = crop_y0 - media_y0

            overlay_bytes = _overlay_pdf_with_png(
                media_w=media_w,
                media_h=media_h,
                png_bytes=png,
                draw_x=draw_x,
                draw_y=draw_y,
                draw_w=crop_w,
                draw_h=crop_h,
            )

            overlay_reader = PdfReader(io.BytesIO(overlay_bytes))
            page.merge_page(overlay_reader.pages[0])

        writer.add_page(page)

    with open(out_pdf, "wb") as f:
        writer.write(f)
