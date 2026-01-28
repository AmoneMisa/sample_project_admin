import codecs
import json
from pathlib import Path
from typing import List, Union

from fastapi import APIRouter, Query, Depends, HTTPException, UploadFile, File
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.session import get_session
from ..deps.require_user import require_permission
from ..models.models import Language, TranslationKey, TranslationValue
from ..utils.flatten_tree import flatten_tree
from ..utils.redis_client import get_redis
from ..utils.translation_tree import build_tree

router = APIRouter(prefix="/translations", tags=["Translations"])

# ---------------------------------------------------------
# PUBLIC GET /translations?lang=ru
# ---------------------------------------------------------
@router.get("")
async def get_translations(
        lang: str = Query(...),
        session: AsyncSession = Depends(get_session)
):
    values = await session.execute(
        select(TranslationValue, TranslationKey)
        .join(TranslationKey, TranslationKey.id == TranslationValue.translationKeyId)
        .join(Language, Language.id == TranslationValue.languageId)
        .where(Language.code == lang)
    )

    result = {}
    for value, key in values.all():
        try:
            parsed = json.loads(value.value)
            result[key.key] = parsed
        except:
            result[key.key] = value.value
    return result


# ---------------------------------------------------------
# PUBLIC GET /translations/structured?lang=ru
# ---------------------------------------------------------
@router.get("/structured")
async def get_structured_translations(
        lang: str = Query(...),
        session: AsyncSession = Depends(get_session)
):
    values = await session.execute(
        select(TranslationValue, TranslationKey)
        .join(TranslationKey, TranslationKey.id == TranslationValue.translationKeyId)
        .join(Language, Language.id == TranslationValue.languageId)
        .where(Language.code == lang)
    )

    flat = {key.key: value.value for value, key in values.all()}
    return build_tree(flat)


# ---------------------------------------------------------
# IMPORT (оставляем как есть)
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
        session: AsyncSession = Depends(get_session),
        user=Depends(require_permission("translations", "update")),
):
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

            key = await session.scalar(select(TranslationKey).where(TranslationKey.key == key_str))
            if not key:
                key = TranslationKey(key=key_str)
                session.add(key)
                await session.flush()

            existing_value = await session.scalar(
                select(TranslationValue).where(
                    TranslationValue.translationKeyId == key.id,
                    TranslationValue.languageId == lang.id
                )
            )
            if existing_value:
                continue

            session.add(
                TranslationValue(
                    translationKeyId=key.id,
                    languageId=lang.id,
                    value=value
                )
            )

    await session.commit()

    redis = get_redis()
    await redis.delete(f"translations:{lang_code}")

    return {"status": "imported"}


# ---------------------------------------------------------
# CREATE /translations (создать новый ключ)
# ---------------------------------------------------------
class CreateTranslationPayload(BaseModel):
    key: str
    values: dict[str, Union[str, list, dict, None]] = {}


@router.post("")
async def create_translation(
        payload: CreateTranslationPayload,
        session: AsyncSession = Depends(get_session),
        user=Depends(require_permission("translations", "create")),
):
    key_row = await session.scalar(
        select(TranslationKey).where(TranslationKey.key == payload.key)
    )
    if not key_row:
        key_row = TranslationKey(key=payload.key)
        session.add(key_row)
        await session.flush()

    languages = {
        lang.code: lang
        for lang in (await session.execute(select(Language))).scalars().all()
    }

    for lang_code, lang in languages.items():
        existing_value = await session.scalar(
            select(TranslationValue).where(
                TranslationValue.translationKeyId == key_row.id,
                TranslationValue.languageId == lang.id
            )
        )
        if not existing_value:
            session.add(
                TranslationValue(
                    translationKeyId=key_row.id,
                    languageId=lang.id,
                    value=payload.values.get(lang_code, "")
                )
            )

    await session.commit()

    redis = get_redis()
    for lang_code in payload.values.keys():
        await redis.delete(f"translations:{lang_code}")

    return {"status": "created", "key": payload.key}


# ---------------------------------------------------------
# UPDATE /translations (массовое обновление)
# ---------------------------------------------------------
class UpdateItem(BaseModel):
    key: str
    lang: str
    value: Union[str, dict, list, None]


class UpdatePayload(BaseModel):
    items: List[UpdateItem]


@router.patch("")
async def update_translations(
        payload: UpdatePayload,
        session: AsyncSession = Depends(get_session),
        user=Depends(require_permission("translations", "update")),
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

    updated_langs = set()

    for item in payload.items:
        lang = languages.get(item.lang)
        if not lang:
            raise HTTPException(404, f"Language '{item.lang}' not found")

        key_row = existing_keys.get(item.key)
        if not key_row:
            key_row = TranslationKey(key=item.key)
            session.add(key_row)
            await session.flush()
            existing_keys[item.key] = key_row

        value_key = (key_row.id, lang.id)
        value_row = existing_values.get(value_key)

        value_to_save = (
            json.dumps(item.value, ensure_ascii=False)
            if isinstance(item.value, (list, dict))
            else item.value
        )

        if value_row:
            value_row.value = value_to_save
        else:
            value_row = TranslationValue(
                translationKeyId=key_row.id,
                languageId=lang.id,
                value=value_to_save
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
        user=Depends(require_permission("translations", "delete")),
):
    key_rows = (
        await session.execute(
            select(TranslationKey).where(TranslationKey.key.in_(payload.keys))
        )
    ).scalars().all()

    if not key_rows:
        return {"status": "ok", "deleted": 0}

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
