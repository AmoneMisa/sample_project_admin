import codecs
import json
from pathlib import Path
from typing import List, Union, Optional

from fastapi import APIRouter, Query, Depends, HTTPException, UploadFile, File
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.session import get_session
from ..deps.require_user import require_permission, require_editor
from ..models.models import Language, TranslationKey, TranslationValue
from ..utils.flatten_tree import flatten_tree
from ..utils.redis_client import get_redis
from ..utils.translation_tree import build_tree

router = APIRouter(prefix="/translations", tags=["Translations"])


# ---------------------------------------------------------
# Unified API error helper
# ---------------------------------------------------------
def api_error(code: str, message: str, status: int = 400, field: str | None = None):
    detail = {"code": code, "message": message}
    if field:
        detail["field"] = field
    raise HTTPException(status_code=status, detail=detail)


def normalize_value_for_db(value):
    # None → JSON null
    if value is None:
        return "null"

    # строки и числа → превращаем в JSON-строку
    if isinstance(value, (str, int, float)):
        return json.dumps(value, ensure_ascii=False)

    # объекты и массивы → сериализуем как есть
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)

    api_error(
        "INVALID_VALUE_TYPE",
        f"Неподдерживаемый тип значения: {type(value)}",
        status=422,
    )


# ---------------------------------------------------------
# PUBLIC GET /translations?lang=ru
# ---------------------------------------------------------
@router.get("")
async def get_translations(
        key: str | None = None,
        lang: str | None = None,
        session: AsyncSession = Depends(get_session),
):
    # Если указан конкретный язык → вернуть только его
    if lang:
        values = await session.execute(
            select(TranslationValue, TranslationKey)
            .join(TranslationKey, TranslationKey.id == TranslationValue.translationKeyId)
            .join(Language, Language.id == TranslationValue.languageId)
            .where(Language.code == lang)
        )

        result: dict[str, Union[str, int, float, list, dict]] = {}
        for value, key_obj in values.all():
            try:
                parsed = json.loads(value.value)
                result[key_obj.key] = parsed
            except Exception:
                result[key_obj.key] = value.value
        return result

    # Если язык НЕ указан → вернуть ВСЕ языки
    languages = await session.execute(select(Language))
    languages = [l[0].code for l in languages.all()]

    result: dict[str, dict[str, Union[str, int, float, list, dict]]] = {}

    for code in languages:
        values = await session.execute(
            select(TranslationValue, TranslationKey)
            .join(TranslationKey, TranslationKey.id == TranslationValue.translationKeyId)
            .join(Language, Language.id == TranslationValue.languageId)
            .where(Language.code == code)
        )

        lang_map: dict[str, Union[str, int, float, list, dict]] = {}
        for value, key_obj in values.all():
            try:
                parsed = json.loads(value.value)
                lang_map[key_obj.key] = parsed
            except Exception:
                lang_map[key_obj.key] = value.value

        result[code] = lang_map

    # Если указан key → вернуть только его
    if key:
        return {code: result[code].get(key, "") for code in result}

    return result


# ---------------------------------------------------------
# PUBLIC GET /translations/structured?lang=ru
# ---------------------------------------------------------
@router.get("/structured")
async def get_structured_translations(
        key: str | None = None,
        lang: str | None = None,
        session: AsyncSession = Depends(get_session),
):
    # 1. Если указан язык → вернуть дерево только для него
    if lang:
        values = await session.execute(
            select(TranslationValue, TranslationKey)
            .join(TranslationKey, TranslationKey.id == TranslationValue.translationKeyId)
            .join(Language, Language.id == TranslationValue.languageId)
            .where(Language.code == lang)
        )

        flat: dict[str, Union[str, int, float, list, dict]] = {}
        for value, key_obj in values.all():
            try:
                flat[key_obj.key] = json.loads(value.value)
            except Exception:
                flat[key_obj.key] = value.value

        tree = build_tree(flat)

        if key:
            return tree.get(key, {})

        return tree

    # 2. Если язык НЕ указан → вернуть дерево для всех языков
    languages = await session.execute(select(Language))
    languages = [l[0].code for l in languages.all()]

    result: dict[str, dict] = {}

    for code in languages:
        values = await session.execute(
            select(TranslationValue, TranslationKey)
            .join(TranslationKey, TranslationKey.id == TranslationValue.translationKeyId)
            .join(Language, Language.id == TranslationValue.languageId)
            .where(Language.code == code)
        )

        flat: dict[str, Union[str, int, float, list, dict]] = {}
        for value, key_obj in values.all():
            try:
                flat[key_obj.key] = json.loads(value.value)
            except Exception:
                flat[key_obj.key] = value.value

        tree = build_tree(flat)

        if key:
            result[code] = tree.get(key, {})
        else:
            result[code] = tree

    return result


# ---------------------------------------------------------
# IMPORT
# ---------------------------------------------------------
def decode_unicode(value):
    if isinstance(value, str):
        if "\\u" in value:
            try:
                return codecs.decode(value, "unicode_escape")
            except Exception:
                return value
        return value

    if isinstance(value, list):
        return [decode_unicode(v) for v in value]

    if isinstance(value, dict):
        return {k: decode_unicode(v) for k, v in value.items()}

    return value


@router.post("/import")
async def import_translations(
        files: list[UploadFile] = File(...),
        rewrite: bool = Query(False),
        session: AsyncSession = Depends(get_session),
        user=Depends(require_permission("translations", "update")),
):
    updated_langs: set[str] = set()

    for file in files:
        content = await file.read()
        tree = json.loads(content)

        flat = flatten_tree(tree)

        lang_code = Path(file.filename).stem
        lang = await session.scalar(select(Language).where(Language.code == lang_code))
        if not lang:
            continue

        for key_str, value in flat.items():
            value = decode_unicode(value)
            value = normalize_value_for_db(value)

            key = await session.scalar(select(TranslationKey).where(TranslationKey.key == key_str))
            if not key:
                key = TranslationKey(key=key_str)
                session.add(key)
                await session.flush()

            existing_value = await session.scalar(
                select(TranslationValue).where(
                    TranslationValue.translationKeyId == key.id,
                    TranslationValue.languageId == lang.id,
                    )
            )

            if existing_value:
                # режим по умолчанию: НЕ перезаписываем существующий перевод,
                # но можем заполнить пустой (None / "")

                if rewrite:
                    existing_value.value = value
                else:
                    is_empty = existing_value.value is None or existing_value.value == ""
                    if is_empty:
                        existing_value.value = value
                    # иначе — пропускаем
            else:
                session.add(
                    TranslationValue(
                        translationKeyId=key.id,
                        languageId=lang.id,
                        value=value,
                    )
                )

        updated_langs.add(lang_code)

    await session.commit()

    redis = get_redis()
    for lang_code in updated_langs:
        await redis.delete(f"translations:{lang_code}")

    return {"status": "imported", "languages": list(updated_langs), "rewrite": rewrite}


# ---------------------------------------------------------
# CREATE /translations (создать новый ключ)
# ---------------------------------------------------------
class CreateTranslationPayload(BaseModel):
    key: str = Field(..., min_length=1)
    values: dict[str, Union[str, int, float, None]] = {}


@router.post("")
async def create_translation(
        payload: list[CreateTranslationPayload],
        session: AsyncSession = Depends(get_session),
        user=Depends(require_editor),
):
    languages = {
        lang.code: lang
        for lang in (await session.execute(select(Language))).scalars().all()
    }

    if not languages:
        api_error("NO_LANGUAGES", "В системе не настроены языки", status=400)

    existing_keys = {
        k.key: k
        for k in (await session.execute(select(TranslationKey))).scalars().all()
    }

    updated_langs: set[str] = set()

    for item in payload:
        if not item.key.strip():
            api_error("INVALID_KEY", "Ключ перевода не может быть пустым", field="key", status=422)

        key_row = existing_keys.get(item.key)
        if not key_row:
            key_row = TranslationKey(key=item.key)
            session.add(key_row)
            await session.flush()
            existing_keys[item.key] = key_row

        for lang_code, lang in languages.items():
            raw_value = item.values.get(lang_code, "")
            value = normalize_value_for_db(raw_value)

            existing_value = await session.scalar(
                select(TranslationValue).where(
                    TranslationValue.translationKeyId == key_row.id,
                    TranslationValue.languageId == lang.id,
                    )
            )

            if existing_value:
                existing_value.value = value
            else:
                session.add(
                    TranslationValue(
                        translationKeyId=key_row.id,
                        languageId=lang.id,
                        value=value,
                    )
                )

            updated_langs.add(lang_code)

    await session.commit()

    redis = get_redis()
    for lang in updated_langs:
        await redis.delete(f"translations:{lang}")

    return {"status": "created", "count": len(payload)}


# ---------------------------------------------------------
# UPDATE /translations (массовое обновление)
# ---------------------------------------------------------
class UpdateItem(BaseModel):
    key: str = Field(..., min_length=1)
    lang: str = Field(..., min_length=1)
    value: Union[str, int, float, None]


class UpdatePayload(BaseModel):
    items: List[UpdateItem]


@router.patch("")
async def update_translations(
        payload: UpdatePayload,
        session: AsyncSession = Depends(get_session),
        user=Depends(require_editor),
):
    languages = {
        lang.code: lang
        for lang in (await session.execute(select(Language))).scalars().all()
    }

    existing_keys = {
        k.key: k
        for k in (await session.execute(select(TranslationKey))).scalars().all()
    }

    existing_values = {
        (v.translationKeyId, v.languageId): v
        for v in (await session.execute(select(TranslationValue))).scalars().all()
    }

    updated_langs: set[str] = set()

    for item in payload.items:
        lang = languages.get(item.lang)
        if not lang:
            api_error("LANGUAGE_NOT_FOUND", f"Язык '{item.lang}' не найден", field="lang", status=404)

        if not item.key.strip():
            api_error("INVALID_KEY", "Ключ перевода не может быть пустым", field="key", status=422)

        key_row = existing_keys.get(item.key)
        if not key_row:
            key_row = TranslationKey(key=item.key)
            session.add(key_row)
            await session.flush()
            existing_keys[item.key] = key_row

        value_to_save = normalize_value_for_db(item.value)

        value_key = (key_row.id, lang.id)
        value_row = existing_values.get(value_key)

        if value_row:
            value_row.value = value_to_save
        else:
            value_row = TranslationValue(
                translationKeyId=key_row.id,
                languageId=lang.id,
                value=value_to_save,
            )
            session.add(value_row)
            existing_values[value_key] = value_row

        updated_langs.add(item.lang)

    await session.commit()

    redis = get_redis()
    for lang in updated_langs:
        await redis.delete(f"translations:{lang}")

    return {"status": "updated", "count": len(payload.items)}


# ---------------------------------------------------------
# DELETE /translations (массовое удаление)
# ---------------------------------------------------------
class DeletePayload(BaseModel):
    keys: List[str]


@router.delete("")
async def delete_translations(
        payload: DeletePayload,
        session: AsyncSession = Depends(get_session),
        user=Depends(require_editor),
):
    if not payload.keys:
        return {"status": "deleted", "count": 0}

    key_rows = (
        await session.execute(
            select(TranslationKey).where(TranslationKey.key.in_(payload.keys))
        )
    ).scalars().all()

    if not key_rows:
        return {"status": "deleted", "count": 0}

    key_ids = [k.id for k in key_rows]

    await session.execute(
        TranslationValue.__table__.delete().where(
            TranslationValue.translationKeyId.in_(key_ids)
        )
    )

    for k in key_rows:
        await session.delete(k)

    await session.commit()

    redis = get_redis()
    langs = await session.execute(select(Language.code))
    for lang in langs.scalars().all():
        await redis.delete(f"translations:{lang}")

    return {"status": "deleted", "count": len(payload.keys)}
