from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class PreviewResult:
    png_path: str
    dpi: int


def render_pdf_page_to_png(
        input_pdf: str,
        out_png: str,
        *,
        page: int,
        dpi: int = 144,
        timeout_sec: int = 25,
) -> PreviewResult:
    """
    Renders a single PDF page to PNG using Ghostscript.

    Requires `gs` available in PATH inside container.
    """
    if page < 1:
        raise ValueError("Invalid page number")

    os.makedirs(os.path.dirname(out_png), exist_ok=True)

    # Ghostscript:
    # -dSAFER: safer file ops
    # -sDEVICE=pngalpha: RGBA png
    # -r{dpi}: raster resolution
    # -dFirstPage / -dLastPage: single page
    # -o out.png: output
    cmd = [
        "gs",
        "-dSAFER",
        "-dBATCH",
        "-dNOPAUSE",
        "-sDEVICE=pngalpha",
        f"-r{dpi}",
        f"-dFirstPage={page}",
        f"-dLastPage={page}",
        "-o",
        out_png,
        input_pdf,
    ]

    try:
        subprocess.run(
            cmd,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=timeout_sec,
        )
    except subprocess.TimeoutExpired as e:
        raise RuntimeError("Preview render timed out") from e
    except subprocess.CalledProcessError as e:
        # e.stderr is bytes
        msg = (e.stderr or b"").decode("utf-8", errors="ignore")[:1200]
        raise RuntimeError(f"Ghostscript failed: {msg}") from e

    if not os.path.exists(out_png):
        raise RuntimeError("Preview render failed: output file not created")

    return PreviewResult(png_path=out_png, dpi=dpi)
