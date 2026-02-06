from __future__ import annotations

import os
import json
import time
import uuid
import shutil
from dataclasses import dataclass
from typing import Any, Literal, Optional, List, Dict

from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field
from ..processors.pdf_preview import render_pdf_page_to_png
from ..utils.redis_client import get_redis

try:
    import magic  # python-magic
except Exception:
    magic = None  # type: ignore

from pypdf import PdfReader

# ✅ operations moved to processors
from ..processors.pdf_ops import (
    merge_pdfs,
    rotate_pdf,
    watermark_text,
    watermark_image,
    draw_signature,
)

router = APIRouter(prefix="/pdf", tags=["pdf"])

# ----------------------------
# Config
# ----------------------------
STORAGE_ROOT = os.getenv("PDF_STORAGE_ROOT", "/var/app/storage/pdf")
TTL_SECONDS = int(os.getenv("PDF_TTL_SECONDS", "3600"))

MAX_FILE_SIZE = int(os.getenv("PDF_MAX_FILE_SIZE", str(50 * 1024 * 1024)))  # 50MB
MAX_FILES = int(os.getenv("PDF_MAX_FILES", "10"))
MAX_PAGES = int(os.getenv("PDF_MAX_PAGES", "500"))

MAX_VERSIONS = 5
MAX_IMAGE_SIZE = int(os.getenv("PDF_MAX_IMAGE_SIZE", str(5 * 1024 * 1024)))  # 5MB

Tool = Literal["merge", "rotate", "watermark_text", "watermark_image", "draw_signature"]

# ----------------------------
# Redis
# ----------------------------
from redis.asyncio import Redis

_redis_client: Optional[Redis] = None


def err(status: int, code: str, message: str, meta: Optional[dict] = None):
    raise HTTPException(status_code=status, detail={"code": code, "message": message, "meta": meta or {}})


def now_ts() -> int:
    return int(time.time())


def job_key(job_id: str) -> str:
    return f"pdf:job:{job_id}"


def ensure_storage_root():
    os.makedirs(STORAGE_ROOT, exist_ok=True)


def safe_filename(name: str, fallback: str) -> str:
    base = os.path.basename(name or "").strip()
    return base if base else fallback


# ----------------------------
# Schemas
# ----------------------------
class JobCreateResponse(BaseModel):
    jobId: str
    status: Literal["done"]
    cursor: int
    versions: int
    downloadUrl: str
    expiresAt: int


class JobStatusResponse(BaseModel):
    jobId: str
    status: Literal["done", "failed"]
    cursor: int
    versions: int
    activeVersion: int
    expiresAt: int
    lastTool: Optional[str] = None
    lastError: Optional[str] = None


class ApplyToolResponse(BaseModel):
    jobId: str
    status: Literal["done"]
    cursor: int
    versions: int
    activeVersion: int
    downloadUrl: str
    expiresAt: int


class UndoRedoResponse(BaseModel):
    jobId: str
    cursor: int
    versions: int
    activeVersion: int
    downloadUrl: str
    expiresAt: int


class RotateOptions(BaseModel):
    degrees: Literal[0, 90, 180, 270] = 90


class WatermarkTextOptions(BaseModel):
    text: str = Field(min_length=1, max_length=80)
    opacity: int = Field(ge=5, le=100, default=30)
    page: int = 1
    x: float = 72
    y: float = 72
    fontSize: int = Field(ge=8, le=120, default=32)

    color: str = Field(default="#ffffff")
    font: str = Field(default="Helvetica")
    bold: bool = False
    italic: bool = False
    underline: bool = False
    align: Literal["left", "center", "right"] = "left"
    maxWidth: Optional[float] = None


class WatermarkImageOptions(BaseModel):
    page: int = 1
    x: float = 72
    y: float = 72
    w: float = 220
    h: float = 80
    opacity: int = Field(ge=5, le=100, default=100)


class DrawSignatureOptions(BaseModel):
    page: int = 1
    x: float = 72
    y: float = 72
    w: float = 260
    h: float = 120
    strokes: List[List[List[float]]] = Field(min_length=1)
    strokeWidth: float = Field(ge=0.5, le=8.0, default=2.0)
    opacity: int = Field(ge=10, le=100, default=100)


# ----------------------------
# Job model
# ----------------------------
@dataclass
class Job:
    jobId: str
    createdAt: int
    expiresAt: int
    status: str
    cursor: int
    versions: List[Dict[str, Any]]
    lastTool: Optional[str] = None
    lastError: Optional[str] = None

    @property
    def active_version(self) -> int:
        return self.versions[self.cursor - 1]["v"]

    @property
    def active_path(self) -> str:
        return self.versions[self.cursor - 1]["path"]

    def to_json(self) -> str:
        return json.dumps(
            {
                "jobId": self.jobId,
                "createdAt": self.createdAt,
                "expiresAt": self.expiresAt,
                "status": self.status,
                "cursor": self.cursor,
                "versions": self.versions,
                "lastTool": self.lastTool,
                "lastError": self.lastError,
            }
        )

    @staticmethod
    def from_json(s: str) -> "Job":
        d = json.loads(s)
        return Job(
            jobId=d["jobId"],
            createdAt=d["createdAt"],
            expiresAt=d["expiresAt"],
            status=d["status"],
            cursor=d["cursor"],
            versions=d["versions"],
            lastTool=d.get("lastTool"),
            lastError=d.get("lastError"),
        )


async def load_job(r: Redis, job_id: str) -> Job:
    raw = await r.get(job_key(job_id))
    if not raw:
        err(404, "JOB_NOT_FOUND", "Job not found or expired")

    job = Job.from_json(raw)
    if job.expiresAt <= now_ts():
        await r.delete(job_key(job_id))
        safe_remove_job_folder(job_id)
        err(410, "JOB_EXPIRED", "Job expired")
    return job


async def save_job(r: Redis, job: Job):
    ttl = max(1, job.expiresAt - now_ts())
    await r.set(job_key(job.jobId), job.to_json(), ex=ttl)


def preview_folder(job_id: str) -> str:
    return os.path.join(job_folder(job_id), "previews")


def preview_path(job_id: str, version: int, page: int, dpi: int) -> str:
    # version включаем в ключ, чтобы превью не было “старым” после apply
    return os.path.join(preview_folder(job_id), f"v{version}_p{page}_dpi{dpi}.png")


def job_folder(job_id: str) -> str:
    return os.path.join(STORAGE_ROOT, job_id)


def version_path(job_id: str, v: int) -> str:
    return os.path.join(job_folder(job_id), f"v{v}.pdf")


def safe_remove_job_folder(job_id: str):
    try:
        shutil.rmtree(job_folder(job_id), ignore_errors=True)
    except Exception:
        pass


# ----------------------------
# Validation
# ----------------------------
async def save_upload_validated(upload: UploadFile, dest_path: str, max_size: int) -> int:
    written = 0
    with open(dest_path, "wb") as out:
        while True:
            chunk = await upload.read(1024 * 1024)
            if not chunk:
                break
            written += len(chunk)
            if written > max_size:
                err(413, "FILE_TOO_LARGE", f"Max file size is {max_size} bytes")
            out.write(chunk)
    return written


def validate_pdf_signature(path: str):
    with open(path, "rb") as f:
        head = f.read(5)
    if head != b"%PDF-":
        err(415, "UNSUPPORTED_TYPE", "Uploaded file is not a valid PDF (missing %PDF- header)")


def validate_pdf_mime(path: str):
    if magic is None:
        return
    mime = magic.from_file(path, mime=True)
    if mime != "application/pdf":
        err(415, "UNSUPPORTED_TYPE", f"Only PDF allowed (detected {mime})")


def validate_pages_limit(path: str):
    reader = PdfReader(path)
    pages = len(reader.pages)
    if pages > MAX_PAGES:
        err(413, "TOO_MANY_PAGES", f"Max pages is {MAX_PAGES}", {"pages": pages})


def copy_as_result(src: str, dst: str):
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copyfile(src, dst)


# ----------------------------
# Routes
# ----------------------------
@router.post("/create", response_model=JobCreateResponse)
async def create_job(files: List[UploadFile] = File(...)):
    ensure_storage_root()

    if not files:
        err(400, "NO_FILES", "No files uploaded")
    if len(files) > MAX_FILES:
        err(413, "TOO_MANY_FILES", f"Max files is {MAX_FILES}")

    job_id = str(uuid.uuid4())
    folder = job_folder(job_id)
    os.makedirs(folder, exist_ok=True)

    saved_paths: List[str] = []
    try:
        for i, f in enumerate(files):
            tmp_path = os.path.join(folder, safe_filename(f.filename, f"upload_{i}.pdf"))
            await save_upload_validated(f, tmp_path, MAX_FILE_SIZE)
            validate_pdf_signature(tmp_path)
            validate_pdf_mime(tmp_path)
            validate_pages_limit(tmp_path)
            saved_paths.append(tmp_path)
    finally:
        for f in files:
            try:
                await f.close()
            except Exception:
                pass

    v1 = version_path(job_id, 1)
    if len(saved_paths) == 1:
        copy_as_result(saved_paths[0], v1)
    else:
        merge_pdfs(saved_paths, v1)

    expires_at = now_ts() + TTL_SECONDS
    job = Job(
        jobId=job_id,
        createdAt=now_ts(),
        expiresAt=expires_at,
        status="done",
        cursor=1,
        versions=[{"v": 1, "path": v1}],
        lastTool="create",
        lastError=None,
    )

    r = get_redis()
    await save_job(r, job)

    return JobCreateResponse(
        jobId=job_id,
        status="done",
        cursor=job.cursor,
        versions=len(job.versions),
        downloadUrl=f"/api/pdf/download/{job_id}",
        expiresAt=job.expiresAt,
    )


@router.get("/status/{job_id}", response_model=JobStatusResponse)
async def status(job_id: str):
    r = get_redis()
    job = await load_job(r, job_id)
    return JobStatusResponse(
        jobId=job.jobId,
        status=job.status,
        cursor=job.cursor,
        versions=len(job.versions),
        activeVersion=job.active_version,
        expiresAt=job.expiresAt,
        lastTool=job.lastTool,
        lastError=job.lastError,
    )


@router.get("/download/{job_id}")
async def download(job_id: str):
    r = get_redis()
    job = await load_job(r, job_id)

    path = job.active_path
    if not os.path.exists(path):
        err(404, "RESULT_MISSING", "Result file missing on server")

    filename = f"pdf_{job_id}_v{job.active_version}.pdf"
    return FileResponse(path, media_type="application/pdf", filename=filename)


@router.post("/apply/{job_id}", response_model=ApplyToolResponse)
async def apply_tool(
        job_id: str,
        tool: Tool = Form(...),
        options: str = Form("{}"),
        image: Optional[UploadFile] = File(None),
):
    r = get_redis()
    job = await load_job(r, job_id)

    try:
        opts_raw = json.loads(options or "{}")
    except Exception:
        err(400, "BAD_OPTIONS", "Options must be valid JSON")

    # if undo was used then apply new action => truncate redo tail
    if job.cursor < len(job.versions):
        job.versions = job.versions[: job.cursor]

    if len(job.versions) >= MAX_VERSIONS:
        err(409, "VERSION_LIMIT", f"Max versions is {MAX_VERSIONS}")

    src = job.active_path
    new_v = job.versions[-1]["v"] + 1
    dst = version_path(job_id, new_v)

    try:
        if tool == "merge":
            err(400, "BAD_OPTIONS", "Use /create with multiple files for merge")

        elif tool == "rotate":
            opt = RotateOptions(**opts_raw)
            rotate_pdf(src, dst, opt.degrees)

        elif tool == "watermark_text":
            opt = WatermarkTextOptions(**opts_raw)
            watermark_text(
                src,
                dst,
                page=opt.page,
                x=opt.x,
                y=opt.y,
                text=opt.text,
                opacity=opt.opacity,
                font_size=opt.fontSize,
                color=opt.color,
                font=opt.font,
                bold=opt.bold,
                italic=opt.italic,
                underline=opt.underline,
                align=opt.align,
                max_width=opt.maxWidth,
            );

        elif tool == "watermark_image":
            if not image:
                err(400, "NO_IMAGE", "Image file is required for watermark_image")

            folder = job_folder(job_id)
            img_path = os.path.join(folder, f"wm_{uuid.uuid4().hex}_{safe_filename(image.filename, 'image')}")
            try:
                await save_upload_validated(image, img_path, MAX_IMAGE_SIZE)
            finally:
                try:
                    await image.close()
                except Exception:
                    pass

            opt = WatermarkImageOptions(**opts_raw)
            watermark_image(
                src,
                dst,
                page=opt.page,
                x=opt.x,
                y=opt.y,
                w=opt.w,
                h=opt.h,
                image_path=img_path,
                opacity=opt.opacity,
            )

        elif tool == "draw_signature":
            opt = DrawSignatureOptions(**opts_raw)
            draw_signature(
                src,
                dst,
                page=opt.page,
                x=opt.x,
                y=opt.y,
                w=opt.w,
                h=opt.h,
                strokes=opt.strokes,
                stroke_width=opt.strokeWidth,
                opacity=opt.opacity,
            )

        else:
            err(400, "BAD_OPTIONS", "Unknown tool")

        job.versions.append({"v": new_v, "path": dst})
        job.cursor = len(job.versions)
        job.lastTool = tool
        job.lastError = None
        await save_job(r, job)

        return ApplyToolResponse(
            jobId=job.jobId,
            status="done",
            cursor=job.cursor,
            versions=len(job.versions),
            activeVersion=job.active_version,
            downloadUrl=f"/api/pdf/download/{job.jobId}",
            expiresAt=job.expiresAt,
        )

    except ValueError as e:
        # processors raise ValueError for invalid page etc.
        err(400, "BAD_OPTIONS", str(e))
    except HTTPException:
        raise
    except Exception as e:
        job.status = "failed"
        job.lastTool = tool
        job.lastError = str(e)
        await save_job(r, job)
        err(500, "PROCESSING_FAILED", "PDF processing failed", {"tool": tool})


@router.post("/undo/{job_id}", response_model=UndoRedoResponse)
async def undo(job_id: str):
    r = get_redis()
    job = await load_job(r, job_id)

    if job.cursor > 1:
        job.cursor -= 1
        await save_job(r, job)

    return UndoRedoResponse(
        jobId=job.jobId,
        cursor=job.cursor,
        versions=len(job.versions),
        activeVersion=job.active_version,
        downloadUrl=f"/api/pdf/download/{job.jobId}",
        expiresAt=job.expiresAt,
    )


@router.post("/redo/{job_id}", response_model=UndoRedoResponse)
async def redo(job_id: str):
    r = get_redis()
    job = await load_job(r, job_id)

    if job.cursor < len(job.versions):
        job.cursor += 1
        await save_job(r, job)

    return UndoRedoResponse(
        jobId=job.jobId,
        cursor=job.cursor,
        versions=len(job.versions),
        activeVersion=job.active_version,
        downloadUrl=f"/api/pdf/download/{job.jobId}",
        expiresAt=job.expiresAt,
    )


@router.delete("/{job_id}")
async def delete_job(job_id: str):
    r = get_redis()
    raw = await r.get(job_key(job_id))
    await r.delete(job_key(job_id))
    safe_remove_job_folder(job_id)
    if not raw:
        return JSONResponse({"ok": True, "message": "Already deleted"})
    return JSONResponse({"ok": True})


@router.get("/preview/{job_id}/{page}")
async def preview(job_id: str, page: int, dpi: int = 144):
    """
    Returns PNG preview of a page for the CURRENT active version.
    dpi is clamped for sanity.
    """
    # sanity dpi
    if dpi < 72:
        dpi = 72
    if dpi > 220:
        dpi = 220

    r = get_redis()
    job = await load_job(r, job_id)

    src_pdf = job.active_path
    if not os.path.exists(src_pdf):
        err(404, "RESULT_MISSING", "Result file missing on server")

    # also validate page range quickly
    try:
        reader = PdfReader(src_pdf)
        total = len(reader.pages)
    except Exception:
        err(500, "PDF_READ_FAILED", "Unable to read PDF")

    if page < 1 or page > total:
        err(400, "BAD_OPTIONS", "Invalid page number", {"page": page, "totalPages": total})

    out_png = preview_path(job_id, job.active_version, page, dpi)

    # cache: if exists, return immediately
    if os.path.exists(out_png):
        return FileResponse(out_png, media_type="image/png")

    try:
        render_pdf_page_to_png(src_pdf, out_png, page=page, dpi=dpi)
    except ValueError as e:
        err(400, "BAD_OPTIONS", str(e))
    except Exception as e:
        err(500, "PREVIEW_FAILED", "Failed to render preview", {"error": str(e)})

    return FileResponse(out_png, media_type="image/png")


from pypdf.generic import NameObject


def _safe_page_box(page):
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


@router.get("/page-info/{job_id}")
async def page_info(job_id: str):
    r = get_redis()
    job = await load_job(r, job_id)

    path = job.active_path
    if not os.path.exists(path):
        err(404, "RESULT_MISSING", "Result file missing on server")

    reader = PdfReader(path)
    pages = len(reader.pages)

    w, h = (595.0, 842.0)
    if pages > 0:
        w, h = _safe_page_box(reader.pages[0])

    return JSONResponse({
        "pages": pages,
        "pageW": w,
        "pageH": h,
        "activeVersion": job.active_version
    })
