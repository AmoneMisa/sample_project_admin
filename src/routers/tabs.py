import uuid
from typing import Optional, Literal, List
from sqlalchemy.orm import selectinload

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.session import get_session
from ..deps.require_user import require_editor
from ..models.models import TabsWithBackground, TabsWithBackgroundFeature, TabsUnderbutton

router = APIRouter(prefix="/tabs", tags=["Tabs"])

TabsType = Literal["with-background", "underbutton"]


# ---------------------------------------------------------
# Unified API error helper
# ---------------------------------------------------------
def api_error(
        code: str,
        message: str,
        status: int = 400,
        field: str | None = None,
        extra: dict | None = None,
):
    detail = {"code": code, "message": message}
    if field:
        detail["field"] = field
    if extra:
        detail["extra"] = extra
    raise HTTPException(status_code=status, detail=detail)


def _normalize_type(t: Optional[str]) -> Optional[TabsType]:
    if t is None:
        return None
    if t not in ("with-background", "underbutton"):
        api_error(
            "INVALID_TYPE",
            "Некорректный параметр type. Допустимо: with-background | underbutton",
            status=422,
            field="type",
            extra={"got": t},
        )
    return t  # type: ignore


# ---------------------------------------------------------
# Schemas
# ---------------------------------------------------------
class FeatureOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    textKey: str
    order: int = 0
    isVisible: bool = True


class TabWithBackgroundOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    labelKey: str
    icon: Optional[str] = None
    titleKey: str
    textKey: str
    buttonTextKey: Optional[str] = None
    image: Optional[str] = None
    order: int = 0
    isVisible: bool = True
    list: List[FeatureOut] = Field(default_factory=list)


class TabUnderbuttonOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    labelKey: str
    titleKey: str
    descriptionKey: str
    headlineKey: Optional[str] = None
    image: Optional[str] = None
    buttonTextKey: Optional[str] = None
    order: int = 0
    isVisible: bool = True


class TabWithBackgroundCreate(BaseModel):
    id: Optional[str] = None
    labelKey: str = Field(..., min_length=1)
    icon: Optional[str] = None
    titleKey: str = Field(..., min_length=1)
    textKey: str = Field(..., min_length=1)
    buttonTextKey: Optional[str] = None
    image: Optional[str] = None
    order: int = 0
    isVisible: bool = True
    list: List[dict] = Field(default_factory=list)


class TabUnderbuttonCreate(BaseModel):
    id: Optional[str] = None
    labelKey: str = Field(..., min_length=1)
    titleKey: str = Field(..., min_length=1)
    descriptionKey: str = Field(..., min_length=1)
    headlineKey: Optional[str] = None
    image: Optional[str] = None
    buttonTextKey: Optional[str] = None
    order: int = 0
    isVisible: bool = True


class TabWithBackgroundPatchItem(BaseModel):
    id: str = Field(..., min_length=1)
    labelKey: Optional[str] = None
    icon: Optional[str] = None
    titleKey: Optional[str] = None
    textKey: Optional[str] = None
    buttonTextKey: Optional[str] = None
    image: Optional[str] = None
    order: Optional[int] = None
    isVisible: Optional[bool] = None
    list: Optional[List[dict]] = None


class TabUnderbuttonPatchItem(BaseModel):
    id: str = Field(..., min_length=1)
    labelKey: Optional[str] = None
    titleKey: Optional[str] = None
    descriptionKey: Optional[str] = None
    headlineKey: Optional[str] = None
    image: Optional[str] = None
    buttonTextKey: Optional[str] = None
    order: Optional[int] = None
    isVisible: Optional[bool] = None


class TabsMassPatch(BaseModel):
    type: TabsType
    items: List[TabWithBackgroundPatchItem | TabUnderbuttonPatchItem] = Field(..., min_length=1)


class TabsMassDelete(BaseModel):
    type: TabsType
    ids: List[str] = Field(..., min_length=1)


class TabsGetResponse(BaseModel):
    status: str
    description: str
    type: Optional[TabsType] = None
    withBackground: Optional[List[TabWithBackgroundOut]] = None
    underbutton: Optional[List[TabUnderbuttonOut]] = None


class ApiResponse(BaseModel):
    status: str
    description: str
    ids: Optional[List[str]] = None


# ---------------------------------------------------------
# Helpers
# ---------------------------------------------------------
def _validate_feature_list(raw_list: List[dict]) -> List[str]:
    # ожидаем [{ "textKey": "..." }, ...]
    out: List[str] = []
    for i, item in enumerate(raw_list):
        text_key = (item or {}).get("textKey")
        if not isinstance(text_key, str) or not text_key.strip():
            api_error(
                "INVALID_FEATURE",
                "Каждая фича в list должна содержать непустой textKey",
                status=422,
                field="list",
                extra={"index": i, "got": item},
            )
        out.append(text_key.strip())
    return out


async def _get_with_bg(session: AsyncSession, all_: bool) -> list[TabsWithBackground]:
    q = (
        select(TabsWithBackground)
        .options(selectinload(TabsWithBackground.features))
        .order_by(TabsWithBackground.order.asc(), TabsWithBackground.id.asc())
    )

    if not all_:
        q = q.where(TabsWithBackground.isVisible == True)

    rows = await session.execute(q)
    return rows.scalars().unique().all()


async def _get_underbutton(session: AsyncSession, all_: bool) -> List[TabsUnderbutton]:
    q = select(TabsUnderbutton).order_by(TabsUnderbutton.order.asc(), TabsUnderbutton.id.asc())
    if not all_:
        q = q.where(TabsUnderbutton.isVisible == True)  # noqa: E712
    rows = await session.execute(q)
    return rows.scalars().all()


def _map_with_bg(tab: TabsWithBackground) -> dict:
    return {
        "id": tab.id,
        "labelKey": tab.labelKey,
        "icon": tab.icon,
        "titleKey": tab.titleKey,
        "textKey": tab.textKey,
        "image": tab.image,
        "order": tab.order,
        "isVisible": tab.isVisible,
        "buttonTextKey": tab.buttonTextKey,
        "list": [
            {"id": f.id, "textKey": f.textKey, "order": f.order, "isVisible": f.isVisible}
            for f in (tab.features or [])
        ],
    }


def _map_underbutton(tab: TabsUnderbutton) -> dict:
    return {
        "id": tab.id,
        "labelKey": tab.labelKey,
        "titleKey": tab.titleKey,
        "descriptionKey": tab.descriptionKey,
        "headlineKey": tab.headlineKey,
        "image": tab.image,
        "buttonTextKey": tab.buttonTextKey,
        "order": tab.order,
        "isVisible": tab.isVisible,
    }


# ---------------------------------------------------------
# GET /tabs
#  - без type: возвращаем оба массива
#  - с type: возвращаем только нужный
# ---------------------------------------------------------
@router.get("", response_model=TabsGetResponse)
async def get_tabs(
        type: Optional[str] = Query(None, description="with-background | underbutton"),
        all: bool = False,
        session: AsyncSession = Depends(get_session),
):
    t = _normalize_type(type)

    if t is None:
        with_bg = await _get_with_bg(session, all)
        under = await _get_underbutton(session, all)
        return {
            "status": "ok",
            "description": "Списки табов",
            "withBackground": [_map_with_bg(x) for x in with_bg],
            "underbutton": [_map_underbutton(x) for x in under],
        }

    if t == "with-background":
        with_bg = await _get_with_bg(session, all)
        return {
            "status": "ok",
            "description": "Список табов (with-background)",
            "type": t,
            "withBackground": [_map_with_bg(x) for x in with_bg],
        }

    under = await _get_underbutton(session, all)
    return {
        "status": "ok",
        "description": "Список табов (underbutton)",
        "type": t,
        "underbutton": [_map_underbutton(x) for x in under],
    }


# ---------------------------------------------------------
# POST /tabs  (создание одного таба)
# ---------------------------------------------------------
class TabsCreate(BaseModel):
    type: TabsType
    tab: dict


@router.post("", response_model=ApiResponse)
async def create_tab(
        payload: TabsCreate,
        session: AsyncSession = Depends(get_session),
        user=Depends(require_editor),
):
    if payload.type == "with-background":
        data = TabWithBackgroundCreate(**payload.tab)
        new_id = data.id or str(uuid.uuid4())

        exists = await session.get(TabsWithBackground, new_id)
        if exists:
            api_error(
                "TAB_ID_EXISTS",
                "Таб с таким id уже существует",
                status=409,
                field="id",
                extra={"id": new_id},
            )

        tab = TabsWithBackground(
            id=new_id,
            labelKey=data.labelKey,
            icon=data.icon,
            titleKey=data.titleKey,
            textKey=data.textKey,
            buttonTextKey=data.buttonTextKey,
            image=data.image,
            order=data.order,
            isVisible=data.isVisible,
        )

        session.add(tab)

        feature_keys = _validate_feature_list(data.list)
        for i, text_key in enumerate(feature_keys):
            session.add(
                TabsWithBackgroundFeature(
                    tabId=new_id,
                    textKey=text_key,
                    order=i,
                    isVisible=True,
                )
            )

        await session.commit()
        return {"status": "created", "description": "Таб создан", "ids": [new_id]}

    # underbutton
    data = TabUnderbuttonCreate(**payload.tab)
    new_id = data.id or str(uuid.uuid4())

    exists = await session.get(TabsUnderbutton, new_id)
    if exists:
        api_error(
            "TAB_ID_EXISTS",
            "Таб с таким id уже существует",
            status=409,
            field="id",
            extra={"id": new_id},
        )

    tab = TabsUnderbutton(
        id=new_id,
        labelKey=data.labelKey,
        titleKey=data.titleKey,
        descriptionKey=data.descriptionKey,
        headlineKey=data.headlineKey,
        image=data.image,
        buttonTextKey=data.buttonTextKey,
        order=data.order,
        isVisible=data.isVisible,
    )
    session.add(tab)
    await session.commit()

    return {"status": "created", "description": "Таб создан", "ids": [new_id]}


# ---------------------------------------------------------
# PATCH /tabs (массовое обновление)
#  - для with-background: если пришло поле list → полностью заменяем фичи
# ---------------------------------------------------------
@router.patch("", response_model=ApiResponse)
async def patch_tabs_mass(
        payload: TabsMassPatch,
        session: AsyncSession = Depends(get_session),
        user=Depends(require_editor),
):
    updated_ids: List[str] = []

    if payload.type == "with-background":
        for raw in payload.items:
            item = TabWithBackgroundPatchItem(**raw.model_dump())  # type: ignore

            tab = await session.get(TabsWithBackground, item.id)
            if not tab:
                api_error("TAB_NOT_FOUND", "Таб не найден", status=404, extra={"id": item.id, "type": payload.type})

            # обычные поля
            for k, v in item.model_dump(exclude_unset=True, exclude={"id", "list"}).items():
                setattr(tab, k, v)

            # list -> replace features
            if item.list is not None:
                keys = _validate_feature_list(item.list)

                # удалить старые фичи
                q = select(TabsWithBackgroundFeature).where(TabsWithBackgroundFeature.tabId == tab.id)
                rows = await session.execute(q)
                for f in rows.scalars().all():
                    await session.delete(f)

                # вставить новые
                for i, text_key in enumerate(keys):
                    session.add(TabsWithBackgroundFeature(tabId=tab.id, textKey=text_key, order=i, isVisible=True))

            updated_ids.append(tab.id)

        await session.commit()
        return {"status": "updated", "description": "Табы обновлены", "ids": updated_ids}

    # underbutton
    for raw in payload.items:
        item = TabUnderbuttonPatchItem(**raw.model_dump())  # type: ignore

        tab = await session.get(TabsUnderbutton, item.id)
        if not tab:
            api_error("TAB_NOT_FOUND", "Таб не найден", status=404, extra={"id": item.id, "type": payload.type})

        for k, v in item.model_dump(exclude_unset=True, exclude={"id"}).items():
            setattr(tab, k, v)

        updated_ids.append(tab.id)

    await session.commit()
    return {"status": "updated", "description": "Табы обновлены", "ids": updated_ids}


# ---------------------------------------------------------
# DELETE /tabs  (массовое удаление)
# ---------------------------------------------------------
@router.delete("", response_model=ApiResponse)
async def delete_tabs_mass(
        payload: TabsMassDelete,
        session: AsyncSession = Depends(get_session),
        user=Depends(require_editor),
):
    if payload.type == "with-background":
        deleted: List[str] = []
        for id_ in payload.ids:
            tab = await session.get(TabsWithBackground, id_)
            if not tab:
                continue
            await session.delete(tab)  # каскадом удалит features
            deleted.append(id_)
        await session.commit()
        return {"status": "deleted", "description": "Табы удалены", "ids": deleted}

    deleted: List[str] = []
    for id_ in payload.ids:
        tab = await session.get(TabsUnderbutton, id_)
        if not tab:
            continue
        await session.delete(tab)
        deleted.append(id_)
    await session.commit()
    return {"status": "deleted", "description": "Табы удалены", "ids": deleted}
