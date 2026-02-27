import httpx
import json
from fastapi import APIRouter, HTTPException

from ..utils.redis_client import get_redis

router = APIRouter(prefix="/wb", tags=["WorldBank"])
TTL = 60 * 60 * 24 * 30  # 30 days


@router.get("/indicator")
async def wb_indicator(country: str, indicator: str, per_page: int = 60):
    if not country or not indicator:
        raise HTTPException(400, "country and indicator are required")

    redis = get_redis()
    cache_key = f"wb:indicator:{country}:{indicator}:{per_page}"

    cached = await redis.get(cache_key)
    if cached:
        return json.loads(cached)

    url = f"https://api.worldbank.org/v2/country/{country}/indicator/{indicator}"
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(url, params={"format": "json", "per_page": per_page})
        r.raise_for_status()
        raw = r.json()

    await redis.set(cache_key, json.dumps(raw), ex=TTL)
    return raw
