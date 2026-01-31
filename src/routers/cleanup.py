from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.session import get_session
from ..deps.require_user import require_editor

router = APIRouter(prefix="/cleanup", tags=["Maintenance"])


@router.post("")
async def cleanup_translations(
        translations: bool = False,
        mode: str | None = None,
        session: AsyncSession = Depends(get_session),
        user=Depends(require_editor),
):
    """
    Чистит битые ключи переводов.
    Значения могут быть пустыми — это нормально.
    """

    if not translations:
        raise HTTPException(400, "Use /cleanup?translations=1")

    # Базовые условия (всегда чистим)
    base_conditions = """
        `key` = '' 
        OR `key` IS NULL
        OR `key` LIKE '%undefined%'
        OR (value LIKE '%{%' AND value NOT LIKE '%}%')
        OR (value LIKE '%}%' AND value NOT LIKE '%{%')
        OR value = '{}'
    """

    extra_condition = ""

    # mode=headerMenu → проверяем UUID в headerMenu.<uuid>.*
    if mode == "headerMenu":
        extra_condition = """
            OR (
                `key` LIKE 'headerMenu.%'
                AND `key` NOT REGEXP '^headerMenu\\.[0-9a-fA-F-]{36}\\.'
            )
        """

    # mode=contacts → проверяем UUID в contacts.<type>.<uuid>.label
    if mode == "contacts":
        extra_condition = """
            OR (
                `key` LIKE 'contacts.%'
                AND `key` NOT REGEXP '^contacts\\.[^.]+\\.[0-9a-fA-F-]{36}\\.label$'
            )
        """

    # mode=featureCard → проверяем UUID в featureCard.<uuid>.title/description
    if mode == "featureCard":
        extra_condition = """
            OR (
                `key` LIKE 'featureCard.%'
                AND `key` NOT REGEXP '^featureCard\\.[0-9a-fA-F-]{36}\\.(title|description)$'
            )
        """

    # Финальный SQL
    query = f"""
        SELECT id, `key`, value
        FROM translations
        WHERE {base_conditions}
        {extra_condition}
    """

    result = await session.execute(text(query))
    rows = result.fetchall()

    if not rows:
        return {"removed": 0, "message": "Нет битых ключей"}

    ids = [r.id for r in rows]

    # Удаляем найденные строки
    delete_query = f"""
        DELETE FROM translations
        WHERE id IN ({','.join([':id'+str(i) for i in range(len(ids))])})
    """

    await session.execute(
        text(delete_query),
        {f"id{i}": ids[i] for i in range(len(ids))}
    )

    await session.commit()

    return {
        "removed": len(ids),
        "ids": ids,
        "mode": mode,
        "message": "Некорректные ключи удалены"
    }
