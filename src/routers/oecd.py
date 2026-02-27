from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional, Any, Dict
import httpx, json

from ..utils.redis_client import get_redis

router = APIRouter(prefix="/oecd", tags=["OECD"])
TTL = 60 * 60 * 24 * 30  # 30 days

@router.get("/data")
async def oecd_data(
        agency: str,
        dataset: str,
        selection: str = "all",
        version: str = "",
        startPeriod: Optional[str] = None,
        endPeriod: Optional[str] = None,
        format: str = "jsondata",
):
    """
    Пример внешнего:
    https://sdmx.oecd.org/public/rest/data/{agency},{dataset},{version}/{selection}?format=jsondata
    В v2 базовый урл может быть /public/rest/v2/...
    """
    if not agency or not dataset:
        raise HTTPException(400, "agency and dataset are required")

    redis = get_redis()
    cache_key = f"oecd:data:{agency}:{dataset}:{version or 'latest'}:{selection}:{startPeriod or ''}:{endPeriod or ''}:{format}"

    cached = await redis.get(cache_key)
    if cached:
        # формат может быть CSV, тогда кешить как строку и отдавать как text/plain;
        # для простоты сейчас считаем json.
        return json.loads(cached)

    base = "https://sdmx.oecd.org/public/rest/data"
    # если хочешь v2 — просто base = "https://sdmx.oecd.org/public/rest/v2/data"
    url = f"{base}/{agency},{dataset},{version}/{selection}"

    params: Dict[str, str] = {"format": format}
    if startPeriod: params["startPeriod"] = startPeriod
    if endPeriod: params["endPeriod"] = endPeriod

    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(url, params=params)
        r.raise_for_status()

        # jsondata → json
        raw = r.json()

    await redis.set(cache_key, json.dumps(raw), ex=TTL)
    return raw