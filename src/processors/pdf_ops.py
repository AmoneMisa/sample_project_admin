from __future__ import annotations
from typing import Dict
import io
from typing import List, Callable, Optional

from pypdf import PdfReader, PdfWriter
from pypdf.generic import NameObject

from reportlab.lib.colors import Color
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfgen import canvas


# ----------------------------
# Core ops
# ----------------------------
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


# ----------------------------
# Helpers
# ----------------------------
def _parse_hex_color(s: str) -> Color:
    val = (s or "").strip()
    if not val:
        return Color(1, 1, 1)
    if val.startswith("#"):
        val = val[1:]
    if len(val) == 3:
        val = "".join([ch * 2 for ch in val])
    if len(val) != 6:
        return Color(1, 1, 1)
    try:
        r = int(val[0:2], 16) / 255.0
        g = int(val[2:4], 16) / 255.0
        b = int(val[4:6], 16) / 255.0
        return Color(r, g, b)
    except Exception:
        return Color(1, 1, 1)


def _safe_page_wh(page) -> tuple[float, float]:
    # Some PDFs have invalid MediaBox/CropBox (pypdf may assert).
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


def _font_ascent(font_name: str, font_size: float) -> float:
    # pdfmetrics.getAscent returns in 1/1000 em
    try:
        asc = pdfmetrics.getAscent(font_name)
        if asc:
            return (asc / 1000.0) * float(font_size)
    except Exception:
        pass
    return 0.8 * float(font_size)


def _pick_font(base: str, bold: bool, italic: bool) -> str:
    b = (base or "Helvetica").strip().lower()

    if b in ("helvetica", "arial"):
        if bold and italic:
            return "Helvetica-BoldOblique"
        if bold:
            return "Helvetica-Bold"
        if italic:
            return "Helvetica-Oblique"
        return "Helvetica"

    if b in ("times", "times-roman", "timesroman", "times new roman"):
        if bold and italic:
            return "Times-BoldItalic"
        if bold:
            return "Times-Bold"
        if italic:
            return "Times-Italic"
        return "Times-Roman"

    if b in ("courier", "monospace", "mono"):
        if bold and italic:
            return "Courier-BoldOblique"
        if bold:
            return "Courier-Bold"
        if italic:
            return "Courier-Oblique"
        return "Courier"

    return "Helvetica-Bold" if bold else "Helvetica"


def _clamp(n: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, n))


# ----------------------------
# Text watermark (UI top-left -> PDF baseline)
# ----------------------------
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
        color: str = "#ffffff",
        font: str = "Helvetica",
        bold: bool = False,
        italic: bool = False,
        underline: bool = False,
        align: str = "left",
        max_width: Optional[float] = None,
) -> None:
    reader = PdfReader(input_pdf)
    idx = page - 1
    if idx < 0 or idx >= len(reader.pages):
        raise ValueError("Invalid page number")

    # ✅ SAFE page size (avoid pypdf asserts on broken boxes)
    w, h = _safe_page_wh(reader.pages[idx])

    fnt = _pick_font(font, bold, italic)
    col = _parse_hex_color(color)
    a = (align or "left").strip().lower()

    # UI gives Y as "top" position (because it's from CSS top),
    # but reportlab uses baseline. Convert top->baseline.
    ascent = _font_ascent(fnt, font_size)
    y_baseline = y - ascent

    def draw(c: canvas.Canvas, _w: float, _h: float) -> None:
        c.saveState()
        try:
            c.setFillAlpha(_clamp(opacity, 0, 100) / 100.0)
        except Exception:
            pass

        c.setFont(fnt, font_size)
        c.setFillColor(col)

        s = text or ""
        if not s:
            c.restoreState()
            return

        # For simple single-line rendering:
        draw_x = x
        text_w = pdfmetrics.stringWidth(s, fnt, font_size)

        if max_width and max_width > 0:
            if a == "center":
                draw_x = x + (max_width - text_w) / 2.0
            elif a == "right":
                draw_x = x + (max_width - text_w)
            elif a == "justify":
                spaces = s.count(" ")
                if spaces > 0:
                    extra = max_width - text_w
                    if extra > 0:
                        t = c.beginText()
                        t.setTextOrigin(x, y_baseline)
                        try:
                            t.setWordSpace(extra / spaces)
                        except Exception:
                            pass
                        t.textOut(s)
                        c.drawText(t)

                        if underline:
                            ul_y = y_baseline - max(1.0, font_size * 0.12)
                            c.setLineWidth(max(0.8, font_size * 0.06))
                            c.setStrokeColor(col)
                            c.line(x, ul_y, x + max_width, ul_y)

                        c.restoreState()
                        return

        c.drawString(draw_x, y_baseline, s)

        if underline:
            ul_y = y_baseline - max(1.0, font_size * 0.12)
            c.setLineWidth(max(0.8, font_size * 0.06))
            c.setStrokeColor(col)
            c.line(draw_x, ul_y, draw_x + text_w, ul_y)

        c.restoreState()

    overlay = _make_overlay_pdf(w, h, draw)
    _overlay_single_page(input_pdf, out_path, idx, overlay)


# ----------------------------
# Image watermark
# ----------------------------
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

    page_w, page_h = _safe_page_wh(reader.pages[idx])

    def draw(c: canvas.Canvas, _pw: float, _ph: float) -> None:
        c.saveState()
        try:
            c.setFillAlpha(_clamp(opacity, 0, 100) / 100.0)
        except Exception:
            pass
        img = ImageReader(image_path)
        c.drawImage(img, x, y, width=w, height=h, mask="auto")
        c.restoreState()

    overlay = _make_overlay_pdf(page_w, page_h, draw)
    _overlay_single_page(input_pdf, out_path, idx, overlay)


# ----------------------------
# Signature (strokes in box)
# ----------------------------
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
        color: str = "#ffffff",  # ✅ new
) -> None:
    reader = PdfReader(input_pdf)
    idx = page - 1
    if idx < 0 or idx >= len(reader.pages):
        raise ValueError("Invalid page number")

    page_w, page_h = _safe_page_wh(reader.pages[idx])
    col = _parse_hex_color(color)

    def draw(c: canvas.Canvas, _pw: float, _ph: float) -> None:
        c.saveState()
        try:
            c.setStrokeAlpha(_clamp(opacity, 0, 100) / 100.0)
        except Exception:
            pass

        c.setLineWidth(_clamp(float(stroke_width), 0.1, 50.0))
        c.setStrokeColor(col)

        path = c.beginPath()
        for stroke in strokes:
            if not stroke or len(stroke) < 2:
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


# ----------------------------
# Overlay composition
# ----------------------------
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
