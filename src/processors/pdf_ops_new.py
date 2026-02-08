from __future__ import annotations

import io
from typing import Dict

from pypdf import PdfReader, PdfWriter
from pypdf.generic import NameObject
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas


def _safe_page_wh(page) -> tuple[float, float]:
    """
    Safely read page size in PDF points. Falls back to A4-like defaults.
    """
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
        return 595.0, 842.0  # ~A4 in points

    try:
        arr = list(box)
        if len(arr) != 4:
            return 595.0, 842.0
        x0, y0, x1, y1 = [float(v) for v in arr]
        w = abs(x1 - x0)
        h = abs(y1 - y0)
        if w <= 0 or h <= 0:
            return 595.0, 842.0
        return w, h
    except Exception:
        return 595.0, 842.0


def _make_overlay_pdf(page_w: float, page_h: float, png_bytes: bytes) -> bytes:
    """
    Creates a single-page PDF (same size as target page) with the PNG drawn full-bleed.
    """
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(page_w, page_h))

    # PNG keeps alpha; mask="auto" makes ReportLab respect transparency.
    img = ImageReader(io.BytesIO(png_bytes))
    c.drawImage(img, 0, 0, width=page_w, height=page_h, mask="auto")

    c.showPage()
    c.save()
    buf.seek(0)
    return buf.read()


def apply_png_overlays(src_pdf: str, out_pdf: str, overlays: Dict[int, bytes], dpi: int = 144) -> None:
    """
    Applies per-page PNG overlays (1-based page numbers) over src_pdf and writes out_pdf.
    Each overlay PNG is expected to represent the FULL page (transparent background where empty).
    `dpi` is kept for API symmetry; overlay placement does not depend on it (only on page size).
    """
    base = PdfReader(src_pdf)
    writer = PdfWriter()

    for i, page in enumerate(base.pages):
        page_no = i + 1

        png = overlays.get(page_no)
        if png:
            w, h = _safe_page_wh(page)
            overlay_pdf = _make_overlay_pdf(w, h, png)
            overlay_reader = PdfReader(io.BytesIO(overlay_pdf))

            # merge overlay on top of original page
            page.merge_page(overlay_reader.pages[0])

        writer.add_page(page)

    with open(out_pdf, "wb") as f:
        writer.write(f)
