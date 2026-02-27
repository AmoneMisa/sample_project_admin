import asyncio
from typing import Any, Dict, List, Optional, Tuple
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
import datetime
import json
import math

import httpx

from ..utils.redis_client import get_redis

router = APIRouter(prefix="/indices", tags=["Indices"])

TTL_SECONDS = 60 * 60 * 24 * 30  # 30 days

from pathlib import Path

CODES_PATH = Path(__file__).resolve().parents[1] / "data" / "country_codes.json"


def load_country_codes() -> Dict[str, Dict[str, str]]:
    if not CODES_PATH.exists():
        return {}
    return json.loads(CODES_PATH.read_text(encoding="utf-8"))


COUNTRY_CODES = load_country_codes()


# -------------------------------------------------
# Schemas
# -------------------------------------------------
class NormalizedDTO(BaseModel):
    income: Optional[float] = None  # 0..10
    education: Optional[float] = None  # 0..10
    qualityOfLife: Optional[float] = None  # 0..10
    safety: Optional[float] = None  # 0..10


class BundleDTO(BaseModel):
    key: str
    updatedAtISO: str
    normalized: NormalizedDTO
    raw: Dict[str, Any] = Field(default_factory=dict)


class BundlesPayload(BaseModel):
    keys: List[str] = Field(default_factory=list)
    includeRaw: bool = False


class BundlesResponse(BaseModel):
    items: List[BundleDTO]


# World Bank indicators
WB_INDICATORS: Dict[str, str] = {
    "income_gdp_per_capita_usd": "NY.GDP.PCAP.CD",
    "education_spend_pct_gdp": "SE.XPD.TOTL.GD.ZS",
    "life_expectancy_years": "SP.DYN.LE00.IN",
    # "internet_users_pct": "IT.NET.USER.ZS", # если понадобится
}


# -------------------------------------------------
# Helpers
# -------------------------------------------------
def clamp01(v: float) -> float:
    return max(0.0, min(1.0, v))


def now_iso() -> str:
    return datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def safe_float(x: Any) -> Optional[float]:
    try:
        if x is None:
            return None
        v = float(x)
        if math.isfinite(v):
            return v
        return None
    except Exception:
        return None


async def wb_fetch_indicator(client: httpx.AsyncClient, iso2: str, indicator: str, per_page: int = 60) -> Dict[
    str, Any]:
    # Official:
    # https://api.worldbank.org/v2/country/{iso2}/indicator/{indicator}?format=json&per_page=60
    url = f"https://api.worldbank.org/v2/country/{iso2}/indicator/{indicator}"
    r = await client.get(url, params={"format": "json", "per_page": per_page}, timeout=20)
    r.raise_for_status()
    return r.json()


def wb_extract_latest_value(raw: Any) -> Tuple[Optional[float], Optional[str]]:
    # raw = [meta, data[]]
    rows = raw[1] if isinstance(raw, list) and len(raw) > 1 and isinstance(raw[1], list) else []
    latest_val = None
    latest_date = None

    for row in rows:
        # WorldBank often already in descending years
        val = safe_float(row.get("value") if isinstance(row, dict) else None)
        date = str(row.get("date")) if isinstance(row, dict) and row.get("date") is not None else None
        if val is not None:
            latest_val = val
            latest_date = date
            break

    return latest_val, latest_date


def normalize_wb(latest: Dict[str, Optional[float]]) -> NormalizedDTO:
    # latest содержит реальные значения по индикаторам
    out = NormalizedDTO()

    gdp = latest.get(WB_INDICATORS["income_gdp_per_capita_usd"])
    if gdp is not None:
        out.income = clamp01(gdp / 80000.0) * 10.0

    edu = latest.get(WB_INDICATORS["education_spend_pct_gdp"])
    if edu is not None:
        out.education = clamp01(edu / 8.0) * 10.0

    le = latest.get(WB_INDICATORS["life_expectancy_years"])
    if le is not None:
        out.qualityOfLife = clamp01((le - 50.0) / (85.0 - 50.0)) * 10.0

    return out


# -------------------------------------------------
# OECD placeholder
# -------------------------------------------------
async def oecd_fetch_safety(client: httpx.AsyncClient, country_key: str) -> Optional[float]:
    """
    Берём safety из OECD SDMX dataset.
    MVP-реализация:
      - тянем structure, ищем dimension страны и dimension индикатора
      - тянем data, берём последнюю obs
      - нормализуем в 0..10

    ВАЖНО: dataset/agency сейчас берём по Data Explorer ссылке.
    """

    # 1) коды страны
    oecd_code = (COUNTRY_CODES.get(country_key) or {}).get("oecd")  # обычно ISO3: "DEU", "FRA" и т.д.
    if not oecd_code:
        return None

    agency = "OECD.CFE.EDS"
    dataset = "DSD_REG_SOC@DF_SAFETY"
    version = ""  # latest

    # 2) structure
    struct_url = f"https://sdmx.oecd.org/public/rest/datastructure/{agency},{dataset},{version}"
    try:
        r = await client.get(struct_url, params={"format": "sdmx-json"}, timeout=25)
        r.raise_for_status()
        structure = r.json()
    except Exception:
        return None

    # ---- helpers to work with SDMX-JSON structure ----
    def find_dim_id(candidates: List[str]) -> Optional[str]:
        dims = structure.get("structure", {}).get("dimensions", {})
        for scope in ("series", "observation"):
            for d in dims.get(scope, []):
                did = (d.get("id") or "").upper()
                if did in candidates:
                    return d.get("id")
        # fallback: fuzzy
        for scope in ("series", "observation"):
            for d in dims.get(scope, []):
                did = (d.get("id") or "").upper()
                if any(c in did for c in candidates):
                    return d.get("id")
        return None

    # обычно страна = REF_AREA или LOCATION
    dim_country = find_dim_id(["REF_AREA", "LOCATION", "GEO", "COUNTRY"])

    # индикатор/показатель = INDICATOR / MEASURE / SUBJECT (очень зависит от DSD)
    dim_indicator = find_dim_id(["INDICATOR", "MEASURE", "SUBJECT", "VAR", "CONCEPT"])

    if not dim_country or not dim_indicator:
        return None

    # 3) пытаемся выбрать код safety-показателя из codelist по названию
    # (ищем что-то про "HOMICIDE", "CRIME", "SAFETY")
    def get_codelist_for_dim(dim_id: str) -> List[Dict[str, Any]]:
        dims = structure.get("structure", {}).get("dimensions", {})
        for scope in ("series", "observation"):
            for d in dims.get(scope, []):
                if d.get("id") == dim_id:
                    return d.get("values") or []
        return []

    indicator_values = get_codelist_for_dim(dim_indicator)
    pick = None
    for v in indicator_values:
        name = ((v.get("name") or "") + " " + (v.get("id") or "")).upper()
        if "HOMIC" in name or "CRIME" in name or "SAFETY" in name or "SECUR" in name:
            pick = v.get("id")
            break

    if not pick:
        return None

    # 4) строим selection.
    # В SDMX порядок dims важен, поэтому берём список series-dims в правильном порядке
    series_dims = structure.get("structure", {}).get("dimensions", {}).get("series", [])
    order = [d.get("id") for d in series_dims if d.get("id")]

    # заполняем "all", кроме country/indicator
    parts = []
    for did in order:
        if did == dim_country:
            parts.append(oecd_code)
        elif did == dim_indicator:
            parts.append(pick)
        else:
            parts.append("")  # пусто => all по этому измерению

    selection = ".".join(parts) if parts else "all"

    # 5) data
    data_url = f"https://sdmx.oecd.org/public/rest/data/{agency},{dataset},{version}/{selection}"
    try:
        r = await client.get(data_url, params={"format": "jsondata"}, timeout=30)
        r.raise_for_status()
        raw = r.json()
    except Exception:
        return None

    # 6) достаём последнее observation из SDMX-JSON
    # (берём любую series, из неё max time index)
    try:
        ds = raw["dataSets"][0]
        series = ds.get("series") or {}
        if not series:
            return None

        any_series = next(iter(series.values()))
        obs = any_series.get("observations") or {}
        if not obs:
            return None

        # ключи obs: "0", "1", ... (индексы времени)
        last_k = max(int(k) for k in obs.keys())
        val = obs[str(last_k)][0]
        val = safe_float(val)
        if val is None:
            return None
    except Exception:
        return None

    # 7) нормализация safety -> 0..10
    # Тут без знания конкретной метрики делаем MVP:
    # - если это “чем больше, тем лучше” → clamp к 0..10
    # - если это “хомициды/преступления (чем меньше, тем лучше)” → инвертируем
    name_upper = ""
    for v in indicator_values:
        if v.get("id") == pick:
            name_upper = (v.get("name") or "").upper()
            break

    if "HOMIC" in name_upper or "CRIME" in name_upper:
        # условно: 0..10 на шкале 0..15 (хуже)
        safety10 = clamp01(1.0 - (val / 15.0)) * 10.0
    else:
        # если это уже score/percent -> просто зажмём в 0..10
        safety10 = max(0.0, min(10.0, float(val)))

    return float(safety10)


# -------------------------------------------------
# Core builder with Redis cache
# -------------------------------------------------
async def build_bundle(key: str, include_raw: bool) -> BundleDTO:
    redis = get_redis()
    cache_key = f"indices:bundle:{key}:raw={1 if include_raw else 0}"

    cached = await redis.get(cache_key)
    if cached:
        return BundleDTO.model_validate_json(cached)

    iso2 = (COUNTRY_CODES.get(key) or {}).get("wb")

    normalized = NormalizedDTO()
    raw_out: Dict[str, Any] = {}

    async with httpx.AsyncClient() as client:
        # ---- WorldBank ----
        if iso2:
            latest_vals: Dict[str, Optional[float]] = {}
            wb_raw: Dict[str, Any] = {}

            indicator_ids = list(WB_INDICATORS.values())

            raw_list = await asyncio.gather(
                *(wb_fetch_indicator(client, iso2, ind) for ind in indicator_ids),
                return_exceptions=True
            )

            for ind, raw in zip(indicator_ids, raw_list):
                if isinstance(raw, Exception) or raw is None:
                    val, date = None, None
                else:
                    val, date = wb_extract_latest_value(raw)

                latest_vals[ind] = val

                if include_raw:
                    wb_raw[ind] = {"latestValue": val, "latestDate": date}

            normalized = normalize_wb(latest_vals)

            if include_raw:
                raw_out["worldbank"] = wb_raw

        # ---- OECD safety (считаем всегда) ----
        safety = await oecd_fetch_safety(client, key)
        if safety is not None:
            normalized.safety = safety
            if include_raw:
                raw_out["oecd"] = {"safety": safety}

    bundle = BundleDTO(
        key=key,
        updatedAtISO=now_iso(),
        normalized=normalized,
        raw=raw_out if include_raw else {}
    )

    await redis.set(cache_key, bundle.model_dump_json(), ex=TTL_SECONDS)
    return bundle


# -------------------------------------------------
# Endpoints
# -------------------------------------------------
@router.get("/bundle", response_model=BundleDTO)
async def get_bundle(key: str, includeRaw: bool = False):
    return await build_bundle(key, includeRaw)


@router.post("/bundles", response_model=BundlesResponse)
async def get_bundles(payload: BundlesPayload):
    # важно: ключи уникализируем, чтобы не считать дважды
    uniq = []
    seen = set()
    for k in payload.keys:
        if k and k not in seen:
            uniq.append(k)
            seen.add(k)

    items: List[BundleDTO] = []
    for k in uniq:
        items.append(await build_bundle(k, payload.includeRaw))

    return BundlesResponse(items=items)
