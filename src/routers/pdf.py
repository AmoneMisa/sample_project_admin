from __future__ import annotations

import os
import json
import time
import uuid
import shutil
import base64
from typing import Optional, Dict, Any, List

from fastapi import APIRouter, UploadFile, File, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from pypdf import PdfReader
from pypdf.generic import NameObject

from redis.asyncio import Redis
from ..utils.redis_client import get_redis

from ..processors.pdf_preview import render_pdf_page_to_png
from ..processors.pdf_ops import merge_pdfs  # (старый мердж оставляем)
from ..processors.pdf_ops_new import apply_png_overlays  # (новый рендер поверх)

try:
    import magic  # python-magic
except Exception:
    magic = None  # type: ignore


router = APIRouter(prefix="/pdf", tags=["pdf"])

# ----------------------------
# Config
# ----------------------------
STORAGE_ROOT = os.getenv("PDF_STORAGE_ROOT", "/var/app/storage/pdf")

DRAFT_TTL_SECONDS = int(os.getenv("PDF_DRAFT_TTL_SECONDS", "86400"))   # 24h
RESULT_TTL_SECONDS = int(os.getenv("PDF_RESULT_TTL_SECONDS", "3600"))  # 1h

MAX_FILE_SIZE = int(os.getenv("PDF_MAX_FILE_SIZE", str(50 * 1024 * 1024)))  # 50MB
MAX_FILES = int(os.getenv("PDF_MAX_FILES", "10"))
MAX_PAGES = int(os.getenv("PDF_MAX_PAGES", "500"))

# ----------------------------
# Helpers
# ----------------------------
def now_ts() -> int:
    return int(time.time())

def ensure_storage_root():
    os.makedirs(STORAGE_ROOT, exist_ok=True)

def doc_folder(doc_id: str) -> str:
    return os.path.join(STORAGE_ROOT, doc_id)

def source_path(doc_id: str) -> str:
    return os.path.join(doc_folder(doc_id), "source.pdf")

def result_path(doc_id: str) -> str:
    return os.path.join(doc_folder(doc_id), "result.pdf")

def preview_folder(doc_id: str) -> str:
    return os.path.join(doc_folder(doc_id), "previews")

def preview_path(doc_id: str, page: int, dpi: int) -> str:
    return os.path.join(preview_folder(doc_id), f"p{page}_dpi{dpi}.png")

def safe_filename(name: str, fallback: str) -> str:
    base = os.path.basename(name or "").strip()
    return base if base else fallback

def safe_remove_doc_folder(doc_id: str):
    try:
        shutil.rmtree(doc_folder(doc_id), ignore_errors=True)
    except Exception:
        pass

def validate_pdf_signature(path: str):
    with open(path, "rb") as f:
        head = f.read(5)
    if head != b"%PDF-":
        raise HTTPException(415, "Uploaded file is not a valid PDF (missing %PDF- header)")

def validate_pdf_mime(path: str):
    if magic is None:
        return
    mime = magic.from_file(path, mime=True)
    if mime != "application/pdf":
        raise HTTPException(415, f"Only PDF allowed (detected {mime})")

def validate_pages_limit(path: str):
    reader = PdfReader(path)
    pages = len(reader.pages)
    if pages > MAX_PAGES:
        raise HTTPException(413, f"Max pages is {MAX_PAGES}")

async def save_upload_validated(upload: UploadFile, dest_path: str, max_size: int) -> int:
    written = 0
    with open(dest_path, "wb") as out:
        while True:
            chunk = await upload.read(1024 * 1024)
            if not chunk:
                break
            written += len(chunk)
            if written > max_size:
                raise HTTPException(413, f"Max file size is {max_size} bytes")
            out.write(chunk)
    return written

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

def _safe_pdf_num_pages(path: str) -> int:
    try:
        reader = PdfReader(path)
        return len(reader.pages)
    except Exception:
        return 0

def k_doc(doc_id: str) -> str:
    return f"pdf:doc:{doc_id}"

def k_draft(doc_id: str) -> str:
    return f"pdf:draft:{doc_id}"

def k_result(doc_id: str) -> str:
    return f"pdf:result:{doc_id}"

async def ensure_doc_exists(r: Redis, doc_id: str):
    raw = await r.get(k_doc(doc_id))
    if not raw:
        raise HTTPException(404, "Document not found or expired")

# ----------------------------
# Schemas
# ----------------------------
class CreateResp(BaseModel):
    jobId: str
    expiresAtDraft: int

class DraftPutBody(BaseModel):
    draft: Dict[str, Any]

class SaveBody(BaseModel):
    overlays: Dict[int, str]  # page -> dataURL or base64
    dpi: int = Field(default=144, ge=72, le=220)

# ----------------------------
# Routes
# ----------------------------
@router.post("/create", response_model=CreateResp)
async def create(files: List[UploadFile] = File(...)):
    ensure_storage_root()

    if not files:
        raise HTTPException(400, "No files uploaded")
    if len(files) > MAX_FILES:
        raise HTTPException(413, f"Max files is {MAX_FILES}")

    doc_id = str(uuid.uuid4())
    folder = doc_folder(doc_id)
    os.makedirs(folder, exist_ok=True)

    tmp_paths: List[str] = []
    try:
        for i, f in enumerate(files):
            tmp = os.path.join(folder, safe_filename(f.filename, f"upload_{i}.pdf"))
            await save_upload_validated(f, tmp, MAX_FILE_SIZE)
            validate_pdf_signature(tmp)
            validate_pdf_mime(tmp)
            validate_pages_limit(tmp)
            tmp_paths.append(tmp)
    finally:
        for f in files:
            try:
                await f.close()
            except Exception:
                pass

    out_src = source_path(doc_id)
    if len(tmp_paths) == 1:
        shutil.copyfile(tmp_paths[0], out_src)
    else:
        merge_pdfs(tmp_paths, out_src)

    r: Redis = get_redis()
    expires_draft = now_ts() + DRAFT_TTL_SECONDS
    await r.set(
        k_doc(doc_id),
        json.dumps({"jobId": doc_id, "expiresAtDraft": expires_draft}),
        ex=DRAFT_TTL_SECONDS,
    )

    return CreateResp(jobId=doc_id, expiresAtDraft=expires_draft)

@router.get("/download/{doc_id}")
async def download_source(doc_id: str):
    r: Redis = get_redis()
    await ensure_doc_exists(r, doc_id)

    path = source_path(doc_id)
    if not os.path.exists(path):
        raise HTTPException(404, "Source PDF not found")

    return FileResponse(path, media_type="application/pdf", filename=f"pdf_{doc_id}_source.pdf")

@router.get("/page-info/{doc_id}")
async def page_info(doc_id: str):
    r: Redis = get_redis()
    await ensure_doc_exists(r, doc_id)

    path = source_path(doc_id)
    if not os.path.exists(path):
        raise HTTPException(404, "Source PDF not found")

    reader = PdfReader(path)
    pages = len(reader.pages)

    w, h = (595.0, 842.0)
    if pages > 0:
        w, h = _safe_page_box(reader.pages[0])

    return JSONResponse({"pages": pages, "pageW": w, "pageH": h})

@router.get("/preview/{doc_id}/{page}")
async def preview(doc_id: str, page: int, dpi: int = 144):
    # clamp dpi
    if dpi < 72:
        dpi = 72
    if dpi > 220:
        dpi = 220

    r: Redis = get_redis()
    await ensure_doc_exists(r, doc_id)

    src = source_path(doc_id)
    if not os.path.exists(src):
        raise HTTPException(404, "Source PDF not found")

    total = _safe_pdf_num_pages(src)
    if total <= 0:
        raise HTTPException(500, "Unable to read PDF")

    if page < 1 or page > total:
        raise HTTPException(400, "Invalid page number")

    os.makedirs(preview_folder(doc_id), exist_ok=True)
    out_png = preview_path(doc_id, page, dpi)

    if os.path.exists(out_png):
        return FileResponse(out_png, media_type="image/png")

    try:
        render_pdf_page_to_png(src, out_png, page=page, dpi=dpi)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"Failed to render preview: {e}")

    return FileResponse(out_png, media_type="image/png")

@router.get("/draft/{doc_id}")
async def get_draft(doc_id: str):
    r: Redis = get_redis()
    await ensure_doc_exists(r, doc_id)

    raw = await r.get(k_draft(doc_id))
    if not raw:
        raise HTTPException(404, "Draft not found")
    return JSONResponse({"draft": json.loads(raw)})

@router.put("/draft/{doc_id}")
async def put_draft(doc_id: str, body: DraftPutBody):
    r: Redis = get_redis()
    await ensure_doc_exists(r, doc_id)

    await r.set(k_draft(doc_id), json.dumps(body.draft), ex=DRAFT_TTL_SECONDS)
    return JSONResponse({"ok": True, "expiresAtDraft": now_ts() + DRAFT_TTL_SECONDS})

@router.post("/save/{doc_id}")
async def save(doc_id: str, body: SaveBody):
    r: Redis = get_redis()
    await ensure_doc_exists(r, doc_id)

    src = source_path(doc_id)
    if not os.path.exists(src):
        raise HTTPException(404, "Source PDF not found (expired?)")

    # decode overlays (dataURL OR raw base64)
    overlays_bytes: Dict[int, bytes] = {}
    for p, data in body.overlays.items():
        if not data:
            continue
        if isinstance(data, str) and data.startswith("data:image"):
            b64 = data.split(",", 1)[1]
        else:
            b64 = data
        try:
            overlays_bytes[int(p)] = base64.b64decode(b64)
        except Exception:
            raise HTTPException(400, f"Bad base64 for page {p}")

    # apply overlays -> result.pdf
    out = result_path(doc_id)
    os.makedirs(doc_folder(doc_id), exist_ok=True)
    apply_png_overlays(src, out, overlays_bytes, dpi=body.dpi)

    # result TTL
    expires_result = now_ts() + RESULT_TTL_SECONDS
    await r.set(k_result(doc_id), json.dumps({"expiresAtResult": expires_result}), ex=RESULT_TTL_SECONDS)

    # draft больше не нужен после сохранения
    await r.delete(k_draft(doc_id))

    return JSONResponse({"downloadUrl": f"/api/pdf/download-result/{doc_id}", "expiresAtResult": expires_result})

@router.get("/download-result/{doc_id}")
async def download_result(doc_id: str):
    r: Redis = get_redis()

    # результат живёт ТОЛЬКО пока есть ключ
    raw = await r.get(k_result(doc_id))
    if not raw:
        # чистим папку, если TTL вышел
        safe_remove_doc_folder(doc_id)
        raise HTTPException(404, "Result not found or expired")

    path = result_path(doc_id)
    if not os.path.exists(path):
        raise HTTPException(404, "Result file missing")

    return FileResponse(path, media_type="application/pdf", filename=f"pdf_{doc_id}.pdf")

@router.delete("/{doc_id}")
async def delete_doc(doc_id: str):
    r: Redis = get_redis()
    await r.delete(k_draft(doc_id))
    await r.delete(k_result(doc_id))
    await r.delete(k_doc(doc_id))
    safe_remove_doc_folder(doc_id)
    return JSONResponse({"ok": True})
