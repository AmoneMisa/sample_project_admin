from __future__ import annotations

import io
from typing import List, Callable

from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader


def merge_pdfs(inputs: List[str], out_path: str) -> None:
    writer = PdfWriter()
    for p in inputs:
        reader = PdfReader(p)
        for page in reader.pages:
            writer.add_page(page)
    with open(out_path, "wb") as f:
        writer.write(f)


def rotate_pdf(input_pdf: str, out_path: str, degrees: int) -> None:
    reader = PdfReader(input_pdf)
    writer = PdfWriter()
    for page in reader.pages:
        if degrees:
            page.rotate(degrees)
        writer.add_page(page)
    with open(out_path, "wb") as f:
        writer.write(f)


def watermark_text(
        input_pdf: str,
        out_path: str,
        *,
        page: int,
        x: float,
        y: float,
        text: str,
        opacity: int = 30,
        font_size: int = 32,
) -> None:
    reader = PdfReader(input_pdf)
    idx = page - 1
    if idx < 0 or idx >= len(reader.pages):
        raise ValueError("Invalid page number")

    mb = reader.pages[idx].mediabox
    w, h = float(mb.width), float(mb.height)

    def draw(c: canvas.Canvas, _w: float, _h: float) -> None:
        c.saveState()
        try:
            c.setFillAlpha(opacity / 100.0)
        except Exception:
            pass
        c.setFont("Helvetica-Bold", font_size)
        c.setFillColorRGB(1, 1, 1)
        c.drawString(x, y, text)
        c.restoreState()

    overlay = _make_overlay_pdf(w, h, draw)
    _overlay_single_page(input_pdf, out_path, idx, overlay)


def watermark_image(
        input_pdf: str,
        out_path: str,
        *,
        page: int,
        x: float,
        y: float,
        w: float,
        h: float,
        image_path: str,
        opacity: int = 100,
) -> None:
    reader = PdfReader(input_pdf)
    idx = page - 1
    if idx < 0 or idx >= len(reader.pages):
        raise ValueError("Invalid page number")

    mb = reader.pages[idx].mediabox
    page_w, page_h = float(mb.width), float(mb.height)

    def draw(c: canvas.Canvas, _pw: float, _ph: float) -> None:
        c.saveState()
        try:
            c.setFillAlpha(opacity / 100.0)
        except Exception:
            pass
        img = ImageReader(image_path)
        c.drawImage(img, x, y, width=w, height=h, mask="auto")
        c.restoreState()

    overlay = _make_overlay_pdf(page_w, page_h, draw)
    _overlay_single_page(input_pdf, out_path, idx, overlay)


def draw_signature(
        input_pdf: str,
        out_path: str,
        *,
        page: int,
        x: float,
        y: float,
        w: float,
        h: float,
        strokes: list[list[list[float]]],
        stroke_width: float = 2.0,
        opacity: int = 100,
) -> None:
    reader = PdfReader(input_pdf)
    idx = page - 1
    if idx < 0 or idx >= len(reader.pages):
        raise ValueError("Invalid page number")

    mb = reader.pages[idx].mediabox
    page_w, page_h = float(mb.width), float(mb.height)

    def draw(c: canvas.Canvas, _pw: float, _ph: float) -> None:
        c.saveState()
        try:
            c.setStrokeAlpha(opacity / 100.0)
        except Exception:
            pass
        c.setLineWidth(stroke_width)
        c.setStrokeColorRGB(1, 1, 1)

        path = c.beginPath()
        for stroke in strokes:
            if len(stroke) < 2:
                continue
            x0 = x + stroke[0][0] * w
            y0 = y + stroke[0][1] * h
            path.moveTo(x0, y0)
            for pt in stroke[1:]:
                px = x + pt[0] * w
                py = y + pt[1] * h
                path.lineTo(px, py)

        c.drawPath(path, stroke=1, fill=0)
        c.restoreState()

    overlay = _make_overlay_pdf(page_w, page_h, draw)
    _overlay_single_page(input_pdf, out_path, idx, overlay)


def _make_overlay_pdf(
        page_w: float,
        page_h: float,
        draw_fn: Callable[[canvas.Canvas, float, float], None],
) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(page_w, page_h))
    draw_fn(c, page_w, page_h)
    c.showPage()
    c.save()
    buf.seek(0)
    return buf.read()


def _overlay_single_page(input_pdf: str, out_path: str, page_index0: int, overlay_pdf_bytes: bytes) -> None:
    base = PdfReader(input_pdf)
    overlay = PdfReader(io.BytesIO(overlay_pdf_bytes))

    writer = PdfWriter()
    for i, page in enumerate(base.pages):
        if i == page_index0:
            page.merge_page(overlay.pages[0])
        writer.add_page(page)

    with open(out_path, "wb") as f:
        writer.write(f)
