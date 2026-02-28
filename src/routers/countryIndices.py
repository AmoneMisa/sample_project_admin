import asyncio
from typing import Any, Dict, List, Optional, Tuple
from fastapi import APIRouter
from pydantic import BaseModel, Field
import datetime
import json
import math
from pathlib import Path

import httpx

from ..utils.redis_client import get_redis

router = APIRouter(prefix="/indices", tags=["Indices"])
TTL_SECONDS = 60 * 60 * 24 * 30  # 30 days

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
    # 0..10
    income: Optional[float] = None
    education: Optional[float] = None
    qualityOfLife: Optional[float] = None
    safety: Optional[float] = None

    # extra indices (0..10)
    internet: Optional[float] = None
    unemployment: Optional[float] = None
    air: Optional[float] = None
    inequality: Optional[float] = None
    health: Optional[float] = None


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


# -------------------------------------------------
# World Bank indicators (id -> WB code)
# -------------------------------------------------
WB_INDICATORS: Dict[str, str] = {
    # core
    "income_gdp_per_capita_usd": "NY.GDP.PCAP.CD",
    "education_spend_pct_gdp": "SE.XPD.TOTL.GD.ZS",
    "life_expectancy_years": "SP.DYN.LE00.IN",

    # safety proxy (lower is better): Intentional homicides (per 100k)
    "homicide_per_100k": "VC.IHR.PSRC.P5",

    # extra
    "internet_users_pct": "IT.NET.USER.ZS",
    "unemployment_pct": "SL.UEM.TOTL.ZS",
    "pm25_ug_m3": "EN.ATM.PM25.MC.M3",
    "gini": "SI.POV.GINI",
    "health_exp_pc_usd": "SH.XPD.CHEX.PC.CD",
}

# -------------------------------------------------
# US Census ACS (states) — works without API key
# -------------------------------------------------
US_STATE_FIPS: Dict[str, str] = {
    "al": "01", "ak": "02", "az": "04", "ar": "05", "ca": "06", "co": "08", "ct": "09",
    "de": "10", "dc": "11", "fl": "12", "ga": "13", "hi": "15", "id": "16", "il": "17",
    "in": "18", "ia": "19", "ks": "20", "ky": "21", "la": "22", "me": "23", "md": "24",
    "ma": "25", "mi": "26", "mn": "27", "ms": "28", "mo": "29", "mt": "30", "ne": "31",
    "nv": "32", "nh": "33", "nj": "34", "nm": "35", "ny": "36", "nc": "37", "nd": "38",
    "oh": "39", "ok": "40", "or": "41", "pa": "42", "ri": "44", "sc": "45", "sd": "46",
    "tn": "47", "tx": "48", "ut": "49", "vt": "50", "va": "51", "wa": "53", "wv": "54",
    "wi": "55", "wy": "56",
}

# ACS vars:
# - income: median household income (USD)
# - gini: inequality index (0..1)
# - education/internet/unemployment/poverty are in ACS profile tables (DP)
ACS_VARS: Dict[str, str] = {
    "income_median_household_usd": "B19013_001E",
    "gini": "B19083_001E",

    "education_bachelor_plus_pct": "DP02_0068PE",
    "internet_broadband_pct": "DP02_0151PE",
    "unemployment_pct": "DP03_0009PE",
    "poverty_pct": "DP03_0128PE",

    # health: percent insured — var name can vary by year; we keep it optional.
    # If it’s missing for some year, it will just be None.
    "insured_pct": "DP03_0099PE",
}


# -------------------------------------------------
# Helpers
# -------------------------------------------------
def clamp01(v: float) -> float:
    return max(0.0, min(1.0, v))


def clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


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


def round1(x: Optional[float]) -> Optional[float]:
    if x is None:
        return None
    return float(f"{x:.1f}")


def is_us_state_key(key: str) -> bool:
    # countries.usa.xx or countries.usa.xx.city
    return key.startswith("countries.usa.") and key != "countries.usa"


def parse_us_state_code(key: str) -> Optional[str]:
    parts = key.split(".")
    if len(parts) < 3:
        return None
    if parts[0] != "countries" or parts[1] != "usa":
        return None
    code = parts[2].lower()
    return code if code in US_STATE_FIPS else None


# -------------------------------------------------
# World Bank
# -------------------------------------------------
async def wb_fetch_indicator(client: httpx.AsyncClient, iso2: str, indicator: str, per_page: int = 60) -> Any:
    url = f"https://api.worldbank.org/v2/country/{iso2}/indicator/{indicator}"
    r = await client.get(url, params={"format": "json", "per_page": per_page}, timeout=25)
    r.raise_for_status()
    return r.json()


def wb_extract_latest_value(raw: Any) -> Tuple[Optional[float], Optional[str]]:
    if not (isinstance(raw, list) and len(raw) > 1 and isinstance(raw[1], list)):
        return None, None

    for row in raw[1]:
        if not isinstance(row, dict):
            continue
        val = safe_float(row.get("value"))
        date = str(row.get("date")) if row.get("date") is not None else None
        if val is not None:
            return val, date

    return None, None


def normalize_wb(latest_by_code: Dict[str, Optional[float]]) -> NormalizedDTO:
    out = NormalizedDTO()

    gdp = latest_by_code.get(WB_INDICATORS["income_gdp_per_capita_usd"])
    if gdp is not None:
        out.income = round1(clamp01(gdp / 80000.0) * 10.0)

    edu = latest_by_code.get(WB_INDICATORS["education_spend_pct_gdp"])
    if edu is not None:
        out.education = round1(clamp01(edu / 8.0) * 10.0)

    le = latest_by_code.get(WB_INDICATORS["life_expectancy_years"])
    if le is not None:
        out.qualityOfLife = round1(clamp01((le - 50.0) / (85.0 - 50.0)) * 10.0)

    hom = latest_by_code.get(WB_INDICATORS["homicide_per_100k"])
    if hom is not None:
        out.safety = round1(clamp01(1.0 - (hom / 15.0)) * 10.0)

    inet = latest_by_code.get(WB_INDICATORS["internet_users_pct"])
    if inet is not None:
        out.internet = round1(clamp01(inet / 100.0) * 10.0)

    unemp = latest_by_code.get(WB_INDICATORS["unemployment_pct"])
    if unemp is not None:
        out.unemployment = round1(clamp01(1.0 - (unemp / 25.0)) * 10.0)

    pm25 = latest_by_code.get(WB_INDICATORS["pm25_ug_m3"])
    if pm25 is not None:
        out.air = round1(clamp01(1.0 - ((pm25 - 5.0) / (35.0 - 5.0))) * 10.0)

    gini = latest_by_code.get(WB_INDICATORS["gini"])
    if gini is not None:
        out.inequality = round1(clamp01(1.0 - ((gini - 20.0) / (60.0 - 20.0))) * 10.0)

    hx = latest_by_code.get(WB_INDICATORS["health_exp_pc_usd"])
    if hx is not None:
        out.health = round1(clamp01(hx / 8000.0) * 10.0)

    return out


# -------------------------------------------------
# US Census ACS
# -------------------------------------------------
async def census_fetch(
        client: httpx.AsyncClient,
        endpoint: str,
        year: int,
        vars_list: List[str],
        state_fips: str
) -> Any:
    url = f"https://api.census.gov/data/{year}/{endpoint}"
    params = {
        "get": ",".join(vars_list),
        "for": f"state:{state_fips}",
    }
    r = await client.get(url, params=params, timeout=25)
    r.raise_for_status()
    return r.json()


def census_extract_row(table_json: Any) -> Dict[str, Any]:
    if not isinstance(table_json, list) or len(table_json) < 2:
        return {}
    header = table_json[0]
    row = table_json[1]
    if not isinstance(header, list) or not isinstance(row, list):
        return {}
    return {str(k): row[i] if i < len(row) else None for i, k in enumerate(header)}


def normalize_us_state_from_acs(extracted: Dict[str, Optional[float]]) -> NormalizedDTO:
    out = NormalizedDTO()

    income = extracted.get(ACS_VARS["income_median_household_usd"])
    if income is not None:
        # 30k..90k => 0..10
        out.income = round1(clamp01((income - 30000.0) / (90000.0 - 30000.0)) * 10.0)

    edu = extracted.get(ACS_VARS["education_bachelor_plus_pct"])
    if edu is not None:
        # 10..60% => 0..10
        out.education = round1(clamp01((edu - 10.0) / (60.0 - 10.0)) * 10.0)

    inet = extracted.get(ACS_VARS["internet_broadband_pct"])
    if inet is not None:
        # 60..95% => 0..10
        out.internet = round1(clamp01((inet - 60.0) / (95.0 - 60.0)) * 10.0)

    unemp = extracted.get(ACS_VARS["unemployment_pct"])
    if unemp is not None:
        # 2..15% => 10..0 (lower better)
        out.unemployment = round1(clamp01(1.0 - ((unemp - 2.0) / (15.0 - 2.0))) * 10.0)

    gini = extracted.get(ACS_VARS["gini"])
    if gini is not None:
        # 0.35..0.55 => 10..0
        out.inequality = round1(clamp01(1.0 - ((gini - 0.35) / (0.55 - 0.35))) * 10.0)

    insured = extracted.get(ACS_VARS["insured_pct"])
    if insured is not None:
        # 70..98 => 0..10
        out.health = round1(clamp01((insured - 70.0) / (98.0 - 70.0)) * 10.0)

    pov = extracted.get(ACS_VARS["poverty_pct"])
    if pov is not None:
        # 5..25% => 10..0 (lower poverty is better)
        out.qualityOfLife = round1(clamp01(1.0 - ((pov - 5.0) / (25.0 - 5.0))) * 10.0)

    # safety / air — no guaranteed no-key source here => keep None
    out.safety = None
    out.air = None

    return out


# -------------------------------------------------
# Core builder with Redis cache
# -------------------------------------------------
async def build_bundle(key: str, include_raw: bool) -> BundleDTO:
    redis = get_redis()
    cache_key = f"indices:bundle:{key}:raw={1 if include_raw else 0}"

    cached = await redis.get(cache_key)
    if cached:
        return BundleDTO.model_validate_json(cached)

    normalized = NormalizedDTO()
    raw_out: Dict[str, Any] = {}

    async with httpx.AsyncClient() as client:
        # ---- US STATE ----
        if is_us_state_key(key):
            code = parse_us_state_code(key)
            fips = US_STATE_FIPS.get(code or "")
            # ACS latest часто с лагом => берем (текущий год - 2)
            year = datetime.datetime.utcnow().year - 2

            if code and fips:
                # DP vars live in acs/acs1/profile, B vars in acs/acs1
                dp_vars = [ACS_VARS["education_bachelor_plus_pct"], ACS_VARS["internet_broadband_pct"], ACS_VARS["unemployment_pct"], ACS_VARS["poverty_pct"], ACS_VARS["insured_pct"]]
                b_vars = [ACS_VARS["income_median_household_usd"], ACS_VARS["gini"]]

                extracted: Dict[str, Optional[float]] = {}

                try:
                    # profile
                    prof = await census_fetch(client, "acs/acs1/profile", year, dp_vars, fips)
                    row = census_extract_row(prof)
                    for v in dp_vars:
                        extracted[v] = safe_float(row.get(v))

                except Exception as e:
                    if include_raw:
                        raw_out.setdefault("us", {})["profile_error"] = str(e)

                try:
                    # base
                    base = await census_fetch(client, "acs/acs1", year, b_vars, fips)
                    row = census_extract_row(base)
                    for v in b_vars:
                        extracted[v] = safe_float(row.get(v))

                except Exception as e:
                    if include_raw:
                        raw_out.setdefault("us", {})["base_error"] = str(e)

                normalized = normalize_us_state_from_acs(extracted)

                if include_raw:
                    raw_out["us"] = {
                        **raw_out.get("us", {}),
                        "stateCode": code,
                        "stateFips": fips,
                        "acsYear": year,
                        "acsExtracted": extracted,
                    }

            bundle = BundleDTO(
                key=key,
                updatedAtISO=now_iso(),
                normalized=normalized,
                raw=raw_out if include_raw else {}
            )

            await redis.set(cache_key, bundle.model_dump_json(), ex=TTL_SECONDS)
            return bundle

        # ---- WORLD BANK (countries) ----
        iso2 = (COUNTRY_CODES.get(key) or {}).get("wb")

        if iso2:
            indicator_codes = list(WB_INDICATORS.values())

            raw_list = await asyncio.gather(
                *(wb_fetch_indicator(client, iso2, code) for code in indicator_codes),
                return_exceptions=True
            )

            latest_by_code: Dict[str, Optional[float]] = {}
            wb_raw: Dict[str, Any] = {}

            for code, raw in zip(indicator_codes, raw_list):
                if isinstance(raw, Exception) or raw is None:
                    val, date = None, None
                else:
                    val, date = wb_extract_latest_value(raw)

                latest_by_code[code] = val

                if include_raw:
                    wb_raw[code] = {"latestValue": val, "latestDate": date}

            normalized = normalize_wb(latest_by_code)

            if include_raw:
                raw_out["worldbank"] = wb_raw

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
    uniq: List[str] = []
    seen = set()
    for k in payload.keys:
        if k and k not in seen:
            uniq.append(k)
            seen.add(k)

    items = await asyncio.gather(*(build_bundle(k, payload.includeRaw) for k in uniq))
    return BundlesResponse(items=list(items))