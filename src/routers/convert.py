from __future__ import annotations

import csv
import io
import json
import subprocess
import tempfile
import zipfile
from pathlib import Path
from typing import Literal

import openpyxl
import xmltodict
from PIL import Image
from fastapi import APIRouter, UploadFile, File, Form
from fastapi.responses import StreamingResponse

router = APIRouter(prefix="/convert", tags=["Convert"])


# ---------------------------------------------------------
# Unified API error helper
# ---------------------------------------------------------
def api_error(code: str, message: str, status: int = 400, field: str | None = None):
    detail = {"code": code, "message": message}
    if field:
        detail["field"] = field
    from fastapi import HTTPException
    raise HTTPException(status_code=status, detail=detail)


# ---------------------------------------------------------
# Helpers
# ---------------------------------------------------------
IMAGE_INPUT_EXTS = {"png", "jpg", "jpeg", "webp"}
IMAGE_TARGET_EXTS = {"png", "jpg", "jpeg", "webp"}

DATA_INPUT_EXTS = {"csv", "json", "xml"}
DATA_TARGET_EXTS = {"csv", "json", "xml", "xlsx"}

DOC_INPUT_EXTS = {"docx", "pdf"}
DOC_TARGET_EXTS = {"docx", "pdf"}


def safe_ext(filename: str) -> str:
    ext = Path(filename).suffix.lower().lstrip(".")
    return ext


def base_name(filename: str) -> str:
    return Path(filename).stem


def guess_mime_for_ext(ext: str) -> str:
    ext = ext.lower()
    if ext == "pdf":
        return "application/pdf"
    if ext == "docx":
        return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    if ext == "xlsx":
        return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    if ext == "json":
        return "application/json"
    if ext == "xml":
        return "application/xml"
    if ext == "csv":
        return "text/csv"
    if ext in {"jpg", "jpeg"}:
        return "image/jpeg"
    if ext == "png":
        return "image/png"
    if ext == "webp":
        return "image/webp"
    return "application/octet-stream"


def enforce_single_file(files: list[UploadFile], field: str = "files"):
    if len(files) != 1:
        api_error(
            "ONLY_ONE_FILE",
            "Для этого типа конвертации можно загрузить только один файл.",
            status=422,
            field=field,
        )


def zip_bytes(outputs: list[tuple[str, bytes]]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in outputs:
            z.writestr(name, data)
    buf.seek(0)
    return buf.read()


def streaming_download(data: bytes, filename: str, mime: str):
    return StreamingResponse(
        io.BytesIO(data),
        media_type=mime,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------------------------------------------------------
# Image conversion
# ---------------------------------------------------------
def convert_image_bytes(input_bytes: bytes, src_ext: str, target_ext: str) -> bytes:
    src_ext = src_ext.lower()
    target_ext = target_ext.lower()

    with Image.open(io.BytesIO(input_bytes)) as img:
        # Normalize mode for formats
        if target_ext in {"jpg", "jpeg"}:
            # JPEG doesn't support alpha; flatten if needed
            if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
                bg = Image.new("RGB", img.size, (255, 255, 255))
                bg.paste(img, mask=img.split()[-1] if img.mode in ("RGBA", "LA") else None)
                img = bg
            else:
                img = img.convert("RGB")

        out = io.BytesIO()
        save_format = "JPEG" if target_ext in {"jpg", "jpeg"} else target_ext.upper()

        # Some sane defaults
        save_kwargs = {}
        if save_format == "JPEG":
            save_kwargs.update({"quality": 92, "optimize": True})
        if save_format == "WEBP":
            save_kwargs.update({"quality": 90, "method": 6})

        img.save(out, format=save_format, **save_kwargs)
        return out.getvalue()


# ---------------------------------------------------------
# Data conversions
# ---------------------------------------------------------
def csv_to_json_bytes(csv_bytes: bytes) -> bytes:
    text = csv_bytes.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    rows = list(reader)
    return json.dumps(rows, ensure_ascii=False, indent=2).encode("utf-8")


def json_to_csv_bytes(json_bytes: bytes) -> bytes:
    payload = json.loads(json_bytes.decode("utf-8", errors="replace"))
    if not isinstance(payload, list):
        api_error("INVALID_JSON", "JSON для конвертации в CSV должен быть массивом объектов.", status=422)

    # gather headers (union)
    headers: list[str] = []
    seen = set()
    for row in payload:
        if isinstance(row, dict):
            for k in row.keys():
                if k not in seen:
                    seen.add(k)
                    headers.append(k)

    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=headers, extrasaction="ignore")
    writer.writeheader()
    for row in payload:
        if not isinstance(row, dict):
            continue
        writer.writerow(row)

    return out.getvalue().encode("utf-8")


def xml_to_json_bytes(xml_bytes: bytes) -> bytes:
    text = xml_bytes.decode("utf-8", errors="replace")
    obj = xmltodict.parse(text)
    return json.dumps(obj, ensure_ascii=False, indent=2).encode("utf-8")


def json_to_xml_bytes(json_bytes: bytes) -> bytes:
    obj = json.loads(json_bytes.decode("utf-8", errors="replace"))
    # Ensure one root element (простая стратегия)
    if isinstance(obj, dict) and len(obj) == 1:
        root_obj = obj
    else:
        root_obj = {"root": obj}
    xml = xmltodict.unparse(root_obj, pretty=True)
    return xml.encode("utf-8")


def csv_to_xlsx_bytes(csv_bytes: bytes) -> bytes:
    text = csv_bytes.decode("utf-8-sig", errors="replace")
    reader = csv.reader(io.StringIO(text))

    wb = openpyxl.Workbook()
    ws = wb.active
    for r_idx, row in enumerate(reader, start=1):
        for c_idx, val in enumerate(row, start=1):
            ws.cell(row=r_idx, column=c_idx, value=val)

    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def passthrough_json_bytes(data: bytes) -> bytes:
    # normalize/pretty-print
    obj = json.loads(data.decode("utf-8", errors="replace"))
    return json.dumps(obj, ensure_ascii=False, indent=2).encode("utf-8")


def passthrough_xml_bytes(data: bytes) -> bytes:
    # parse/unparse to normalize formatting a bit
    text = data.decode("utf-8", errors="replace")
    obj = xmltodict.parse(text)
    xml = xmltodict.unparse(obj, pretty=True)
    return xml.encode("utf-8")


# ---------------------------------------------------------
# Document conversions
# ---------------------------------------------------------
def docx_to_pdf_via_libreoffice(docx_bytes: bytes) -> bytes:
    # Requires `soffice` available in PATH
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        in_path = tmp_path / "input.docx"
        out_dir = tmp_path / "out"
        out_dir.mkdir(parents=True, exist_ok=True)

        in_path.write_bytes(docx_bytes)

        # LibreOffice headless conversion
        cmd = [
            "soffice",
            "--headless",
            "--nologo",
            "--nodefault",
            "--nolockcheck",
            "--norestore",
            "--convert-to",
            "pdf",
            "--outdir",
            str(out_dir),
            str(in_path),
        ]
        try:
            subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except FileNotFoundError:
            api_error(
                "LIBREOFFICE_NOT_FOUND",
                "Не найден soffice (LibreOffice). Установи LibreOffice на сервер и добавь soffice в PATH.",
                status=500,
            )
        except subprocess.CalledProcessError as e:
            api_error(
                "DOCX_TO_PDF_FAILED",
                f"Ошибка конвертации DOCX→PDF: {e.stderr.decode('utf-8', errors='replace')[:500]}",
                status=500,
            )

        pdf_path = out_dir / "input.pdf"
        if not pdf_path.exists():
            api_error("DOCX_TO_PDF_FAILED", "LibreOffice не создал PDF файл.", status=500)

        return pdf_path.read_bytes()


def pdf_to_docx_via_pdf2docx(pdf_bytes: bytes) -> bytes:
    # Best effort conversion
    from pdf2docx import Converter

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        in_path = tmp_path / "input.pdf"
        out_path = tmp_path / "output.docx"
        in_path.write_bytes(pdf_bytes)

        try:
            cv = Converter(str(in_path))
            cv.convert(str(out_path), start=0, end=None)
            cv.close()
        except Exception as e:
            api_error("PDF_TO_DOCX_FAILED", f"Ошибка конвертации PDF→DOCX: {str(e)[:400]}", status=500)

        if not out_path.exists():
            api_error("PDF_TO_DOCX_FAILED", "Конвертер не создал DOCX файл.", status=500)

        return out_path.read_bytes()


# ---------------------------------------------------------
# POST /convert/media  (batch up to 20)
# ---------------------------------------------------------
@router.post("/media")
async def convert_media(
        files: list[UploadFile] = File(...),
        target: Literal["png", "jpeg", "jpg", "webp"] = Form(...)
):
    if not files:
        api_error("NO_FILES", "Не переданы файлы.", field="files", status=422)

    if len(files) > 20:
        api_error("TOO_MANY_FILES", "Для медиа можно загрузить максимум 20 файлов.", field="files", status=422)

    target_ext = "jpg" if target == "jpeg" else target

    outputs: list[tuple[str, bytes]] = []

    for f in files:
        ext = safe_ext(f.filename or "")
        if ext not in IMAGE_INPUT_EXTS:
            api_error(
                "UNSUPPORTED_INPUT",
                f"Неподдерживаемый тип файла для media: .{ext}",
                field="files",
                status=422,
            )

        raw = await f.read()
        try:
            out_bytes = convert_image_bytes(raw, ext, target_ext)
        except Exception as e:
            api_error("CONVERT_FAILED", f"Ошибка конвертации изображения: {str(e)[:300]}", status=500)

        out_name = f"{base_name(f.filename or 'file')}.{target_ext}"
        outputs.append((out_name, out_bytes))

    if len(outputs) == 1:
        name, data = outputs[0]
        return streaming_download(data, name, guess_mime_for_ext(target_ext))

    zip_data = zip_bytes(outputs)
    return streaming_download(zip_data, "converted_media.zip", "application/zip")


# ---------------------------------------------------------
# POST /convert/data  (single file)
# ---------------------------------------------------------
@router.post("/data")
async def convert_data(
        file: UploadFile = File(...),
        target: Literal["csv", "json", "xml", "xlsx"] = Form(...)
):
    if not file:
        api_error("NO_FILE", "Не передан файл.", field="file", status=422)

    src_ext = safe_ext(file.filename or "")
    if src_ext not in DATA_INPUT_EXTS:
        api_error("UNSUPPORTED_INPUT", f"Неподдерживаемый входной формат: .{src_ext}", field="file", status=422)

    if target not in DATA_TARGET_EXTS:
        api_error("UNSUPPORTED_TARGET", f"Неподдерживаемый целевой формат: {target}", field="target", status=422)

    raw = await file.read()

    # Routes
    if src_ext == "csv" and target == "json":
        out = csv_to_json_bytes(raw)
    elif src_ext == "json" and target == "csv":
        out = json_to_csv_bytes(raw)
    elif src_ext == "xml" and target == "json":
        out = xml_to_json_bytes(raw)
    elif src_ext == "json" and target == "xml":
        out = json_to_xml_bytes(raw)
    elif src_ext == "csv" and target == "xlsx":
        out = csv_to_xlsx_bytes(raw)
    elif src_ext == "json" and target == "json":
        out = passthrough_json_bytes(raw)
    elif src_ext == "xml" and target == "xml":
        out = passthrough_xml_bytes(raw)
    elif src_ext == "csv" and target == "csv":
        out = raw
    else:
        api_error(
            "UNSUPPORTED_CONVERSION",
            f"Конвертация {src_ext} → {target} пока не поддержана этим эндпоинтом.",
            status=422,
        )

    out_name = f"{base_name(file.filename or 'file')}.{target}"
    return streaming_download(out, out_name, guess_mime_for_ext(target))


# ---------------------------------------------------------
# POST /convert/document  (single file, doc/pdf)
# ---------------------------------------------------------
@router.post("/document")
async def convert_document(
        file: UploadFile = File(...),
        target: Literal["docx", "pdf"] = Form(...)
):
    if not file:
        api_error("NO_FILE", "Не передан файл.", field="file", status=422)

    src_ext = safe_ext(file.filename or "")
    if src_ext not in DOC_INPUT_EXTS:
        api_error("UNSUPPORTED_INPUT", f"Неподдерживаемый входной формат: .{src_ext}", field="file", status=422)

    if target not in DOC_TARGET_EXTS:
        api_error("UNSUPPORTED_TARGET", f"Неподдерживаемый целевой формат: {target}", field="target", status=422)

    if src_ext == target:
        api_error("NOOP", "Входной формат уже совпадает с целевым.", status=422)

    raw = await file.read()

    if src_ext == "docx" and target == "pdf":
        out = docx_to_pdf_via_libreoffice(raw)
    elif src_ext == "pdf" and target == "docx":
        out = pdf_to_docx_via_pdf2docx(raw)
    else:
        api_error("UNSUPPORTED_CONVERSION", f"Конвертация {src_ext} → {target} не поддержана.", status=422)

    out_name = f"{base_name(file.filename or 'file')}.{target}"
    return streaming_download(out, out_name, guess_mime_for_ext(target))
