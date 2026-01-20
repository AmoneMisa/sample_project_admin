import json
import os
from pathlib import Path
from fastapi import APIRouter, Query, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.models.models import Language, TranslationKey, TranslationValue
from app.utils.translation_tree import build_tree
from app.utils.flatten_tree import flatten_tree

router = APIRouter(prefix="/translations", tags=["Translations"])

NUXT_LOCALES_PATH = Path("C:/Users/kubai/IdeaProjects/sample_project/i18n/locales")


# ---------------------------------------------------------
# GET /translations?lang=ru
# ---------------------------------------------------------
@router.get("/")
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
        result[key.key] = value.value

    return result


# ---------------------------------------------------------
# GET /translations/structured?lang=ru
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
# POST /translations/export
# ---------------------------------------------------------
@router.post("/export")
async def export_translations(session: AsyncSession = Depends(get_session)):
    languages = await session.scalars(
        select(Language).where(Language.isEnabled == True)
    )
    languages = languages.all()

    for lang in languages:
        values = await session.execute(
            select(TranslationValue, TranslationKey)
            .join(TranslationKey, TranslationKey.id == TranslationValue.translationKeyId)
            .where(TranslationValue.languageId == lang.id)
        )

        flat = {key.key: value.value for value, key in values.all()}
        tree = build_tree(flat)

        output_path = NUXT_LOCALES_PATH / f"{lang.code}.json"
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(tree, f, ensure_ascii=False, indent=2)

    return {"status": "ok", "languages": [l.code for l in languages]}


# ---------------------------------------------------------
# GET /translations/import
# ---------------------------------------------------------
def decode_unicode(value):
    """Рекурсивно декодирует строки вида '\\u0411\\u0430...' внутри любых структур."""
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


@router.get("/import")
async def import_translations(session: AsyncSession = Depends(get_session)):
    files = os.listdir(NUXT_LOCALES_PATH)

    for file in files:
        if not file.endswith(".json"):
            continue

        lang_code = file.replace(".json", "")

        # find language
        lang = await session.scalar(
            select(Language).where(Language.code == lang_code)
        )
        if not lang:
            continue

        # load JSON
        with open(os.path.join(NUXT_LOCALES_PATH, file), "r", encoding="utf-8") as f:
            tree = json.load(f)

        flat = flatten_tree(tree)

        for key_str, value in flat.items():

            # decode unicode inside strings, arrays, objects
            value = decode_unicode(value)

            # find or create key
            key = await session.scalar(
                select(TranslationKey).where(TranslationKey.key == key_str)
            )
            if not key:
                key = TranslationKey(key=key_str)
                session.add(key)
                await session.flush()

            # check if value exists
            existing_value = await session.scalar(
                select(TranslationValue).where(
                    TranslationValue.translationKeyId == key.id,
                    TranslationValue.languageId == lang.id
                )
            )
            if existing_value:
                continue

            # create value
            session.add(
                TranslationValue(
                    translationKeyId=key.id,
                    languageId=lang.id,
                    value=value
                )
            )

    await session.commit()
    return {"status": "imported"}