from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
import httpx
import re
import json
from ..utils.redis_client import get_redis
import asyncio

router = APIRouter(prefix="/dockerhub", tags=["DockerHub"])

DOCKERHUB_BASE = "https://hub.docker.com"
REGISTRY_BASE = "https://registry-1.docker.io"
AUTH_BASE = "https://auth.docker.io"

SIMPLE_RE = re.compile(
    r"^(?:(?P<major>\d+)(?:\.\d+\.\d+)?)?-?(?P<q>[a-z0-9]+)(?P<tail>.*)?$",
    re.IGNORECASE
)


def make_base_tag(tag: str, q: str) -> Optional[str]:
    # хотим только те, где q является "основной частью" варианта (alpine, slim, bullseye и т.п.)
    # Поддержка:
    #  alpine
    #  17-alpine
    #  17.0.18-alpine3.23
    #  17-alpine3.23
    #  17-alpine-jdk (если захотите — можно расширить правила)
    t = tag.lower()
    q = q.lower()

    # строго "alpine" как отдельный вариант:
    # - либо ровно alpine
    # - либо начинается с "<major>" или "<major>.<minor>.<patch>" и дальше "-alpine..."
    if t == q:
        return q

    m = re.match(rf"^(?P<major>\d+)(?:\.\d+\.\d+)?-(?P<rest>.+)$", t)
    if not m:
        return None

    major = m.group("major")
    rest = m.group("rest")

    # rest должен начинаться с q (alpine...)
    if not rest.startswith(q):
        return None

    # базовый = "<major>-<q>"
    return f"{major}-{q}"


def pick_best_for_base(base: str, tags: List[str]) -> str:
    # 1) если base реально есть — берём его
    if base in tags:
        return base

    # 2) иначе ищем самый "общий": без patch и без version-хвоста после q
    #    пример: предпочтём 17-alpine над 17.0.18-alpine3.23
    def score(t: str):
        p = parse_tag(t)  # у тебя уже есть parse_tag выше
        spec = 0
        if p:
            spec += 1 if p["minor"] is not None else 0
            spec += 1 if p["patch"] is not None else 0
            spec += 1 if p["variant_ver"] is not None else 0
        else:
            spec = 10
        return (spec, t)

    return sorted(tags, key=score)[0]


# -----------------------------
# Redis helpers
# -----------------------------
async def rget_json(redis, key: str):
    raw = await redis.get(key)
    if not raw:
        return None
    return json.loads(raw)


async def rset_json(redis, key: str, obj, ttl: int):
    await redis.set(key, json.dumps(obj, ensure_ascii=False), ex=ttl)


# -----------------------------
# Responses
# -----------------------------
class ResolveResponse(BaseModel):
    repo: str
    major: int
    variant: Optional[str] = None
    best_tag: Optional[str] = None
    fallbacks: List[str] = []
    reason: str
    total_matched: int


class AliasesResponse(BaseModel):
    repo: str
    tag: str
    digest: Optional[str] = None
    aliases: List[str] = []
    reason: str


class SimpleSearchItem(BaseModel):
    base: str  # например "17-alpine" или "alpine"
    tag: str  # реально существующий "основной" тег (лучший)
    examples: List[str] = []


# -----------------------------
# DockerHub: list tags (pagination)
# -----------------------------
async def dockerhub_list_tags(repo: str, name_filter: Optional[str], page_size: int = 100) -> List[Dict[str, Any]]:
    url = f"{DOCKERHUB_BASE}/v2/repositories/{repo}/tags"
    params = {"page_size": page_size}
    if name_filter:
        params["name"] = name_filter

    out: List[Dict[str, Any]] = []
    async with httpx.AsyncClient(timeout=20) as client:
        next_url = url
        next_params = params
        while next_url:
            r = await client.get(next_url, params=next_params)
            r.raise_for_status()
            data = r.json()
            out.extend(data.get("results", []))
            next_url = data.get("next")
            next_params = None
    return out


# -----------------------------
# Registry: token + digest
# -----------------------------
async def registry_get_token(repo: str) -> str:
    params = {
        "service": "registry.docker.io",
        "scope": f"repository:{repo}:pull",
    }
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.get(f"{AUTH_BASE}/token", params=params)
        r.raise_for_status()
        return r.json()["token"]


async def registry_get_manifest_digest(repo: str, tag: str, token: str) -> Optional[str]:
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": ", ".join([
            "application/vnd.oci.image.manifest.v1+json",
            "application/vnd.docker.distribution.manifest.v2+json",
            "application/vnd.docker.distribution.manifest.list.v2+json",
            "application/vnd.oci.image.index.v1+json",
        ])
    }
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.head(f"{REGISTRY_BASE}/v2/{repo}/manifests/{tag}", headers=headers)
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.headers.get("Docker-Content-Digest")


# -----------------------------
# Tag parsing / scoring
# -----------------------------
TAG_RE = re.compile(
    r"^(?P<major>\d+)"
    r"(?:(?:\.(?P<minor>\d+)\.(?P<patch>\d+))?)"
    r"(?:-(?P<variant>[a-z0-9]+)(?P<variant_ver>[0-9.]+)?)?$",
    re.IGNORECASE
)


def parse_tag(tag: str):
    m = TAG_RE.match(tag)
    if not m:
        return None
    gd = m.groupdict()
    return {
        "major": int(gd["major"]),
        "minor": int(gd["minor"]) if gd["minor"] else None,
        "patch": int(gd["patch"]) if gd["patch"] else None,
        "variant": gd["variant"].lower() if gd["variant"] else None,
        "variant_ver": gd["variant_ver"] or None,
    }


def is_more_general(a: str, b: str) -> bool:
    """
    True если a "общей" чем b (меньше деталей).
    """
    pa, pb = parse_tag(a), parse_tag(b)
    if not pa or not pb:
        return False

    def spec(p):
        return sum([
            1 if p["minor"] is not None else 0,
            1 if p["patch"] is not None else 0,
            1 if p["variant_ver"] is not None else 0,
        ])

    return spec(pa) < spec(pb)


def pick_best(names: List[str], major: int, variant: Optional[str]) -> (Optional[str], List[str], str):
    variant = variant.lower() if variant else None

    # 1) Жёсткие “хотелки” (в порядке приоритета)
    preferred = []
    if variant:
        preferred.append(f"{major}-{variant}")  # 17-alpine
    preferred.append(f"{major}")  # 17

    # 2) Собираем кандидатов, которые вообще соответствуют major/variant
    candidates = []
    for t in names:
        p = parse_tag(t)
        if not p or p["major"] != major:
            continue
        if variant and p["variant"] != variant:
            continue
        candidates.append(t)

    if not candidates:
        return None, [], "no_matching_tags"

    # 3) Если идеальные алиасы существуют — берём их
    cand_set = set(candidates)
    for want in preferred:
        if want in cand_set:
            # fallbacks: сначала остальные общие, потом конкретика
            ordered = sorted(candidates, key=lambda x: (0 if is_more_general(x, want) else 1, x))
            return want, ordered[:10], "picked_preferred_alias"

    # 4) Иначе: выбираем “самый общий” среди кандидатов
    #    (то есть без patch и без variant_ver если возможно)
    def specificity(t: str):
        p = parse_tag(t)
        return sum([
            1 if p["minor"] is not None else 0,
            1 if p["patch"] is not None else 0,
            1 if p["variant_ver"] is not None else 0,
        ])

    candidates_sorted = sorted(candidates, key=lambda x: (specificity(x), x))
    best = candidates_sorted[0]
    return best, candidates_sorted[:10], "picked_most_general_available"


# -----------------------------
# Endpoints
# -----------------------------
@router.get("/tags/resolve", response_model=ResolveResponse)
async def resolve_tag(
        repo: str,
        major: int,
        variant: Optional[str] = None,
        redis=Depends(get_redis),
):
    cache_key = f"dockerhub:tags:{repo}:name={major}"
    cached = await rget_json(redis, cache_key)

    if cached is None:
        raw = await dockerhub_list_tags(repo, name_filter=str(major), page_size=100)
        cached = [{"name": t.get("name"), "images": t.get("images", [])} for t in raw]
        await rset_json(redis, cache_key, cached, ttl=900)  # 15 минут

    names = [t["name"] for t in cached if t.get("name")]
    best, fallbacks, reason = pick_best(names, major, variant)

    return ResolveResponse(
        repo=repo,
        major=major,
        variant=variant,
        best_tag=best,
        fallbacks=fallbacks,
        reason=reason,
        total_matched=len(names),
    )


async def registry_digest_map_for_tags(repo: str, tags: List[str], token: str, concurrency: int = 10) -> Dict[
    str, List[str]]:
    sem = asyncio.Semaphore(concurrency)
    digest_to_tags: Dict[str, List[str]] = {}

    async def one(t: str):
        async with sem:
            d = await registry_get_manifest_digest(repo, t, token)
            return t, d

    results = await asyncio.gather(*(one(t) for t in tags), return_exceptions=True)

    for r in results:
        if isinstance(r, Exception):
            continue
        t, d = r
        if d:
            digest_to_tags.setdefault(d, []).append(t)

    # нормализуем
    for d in list(digest_to_tags.keys()):
        digest_to_tags[d] = sorted(set(digest_to_tags[d]))

    return digest_to_tags


@router.get("/tags/aliases", response_model=AliasesResponse)
async def tag_aliases(
        repo: str,
        tag: str,
        redis=Depends(get_redis),
):
    # digest cache
    digest_key = f"dockerhub:digest:{repo}:{tag}"
    digest = await rget_json(redis, digest_key)

    if digest is None:
        token_key = f"dockerhub:registry_token:{repo}"
        token = await rget_json(redis, token_key)
        if token is None:
            token = await registry_get_token(repo)
            await rset_json(redis, token_key, token, ttl=1800)  # 30 мин

        digest = await registry_get_manifest_digest(repo, tag, token)
        await rset_json(redis, digest_key, digest, ttl=6 * 3600)

    if not digest:
        return AliasesResponse(repo=repo, tag=tag, digest=None, aliases=[], reason="digest_not_found")

    # aliases cache
    aliases_key = f"dockerhub:aliases:{repo}:{digest}"
    aliases = await rget_json(redis, aliases_key)

    if aliases is None:
        p = parse_tag(tag)
        name_filter = str(p["major"]) if p else None

        raw = await dockerhub_list_tags(repo, name_filter=name_filter, page_size=100)
        tag_names = [t.get("name") for t in raw if t.get("name")]

        # токен
        token_key = f"dockerhub:registry_token:{repo}"
        token = await rget_json(redis, token_key)
        if token is None:
            token = await registry_get_token(repo)
            await rset_json(redis, token_key, token, ttl=1800)

        digest_map_key = f"dockerhub:digest_map:{repo}:filter={name_filter or 'all'}"
        digest_to_tags = await rget_json(redis, digest_map_key)

        if digest_to_tags is None:
            digest_to_tags = await registry_digest_map_for_tags(repo, tag_names, token, concurrency=10)
            await rset_json(redis, digest_map_key, digest_to_tags, ttl=1800)  # 30 мин

        aliases = sorted(set(digest_to_tags.get(digest, [])))
        await rset_json(redis, aliases_key, aliases, ttl=1800)

    return AliasesResponse(repo=repo, tag=tag, digest=digest, aliases=aliases, reason="ok")


@router.get("/tags/search", response_model=List[SimpleSearchItem])
async def simple_search_tags(
        repo: str,
        q: str,
        redis=Depends(get_redis),
):
    q = (q or "").strip().lower()
    if not q:
        return []

    # кешируем список тегов по q
    cache_key = f"dockerhub:simple_search:{repo}:q={q}"
    cached = await rget_json(redis, cache_key)
    if cached is None:
        raw = await dockerhub_list_tags(repo, name_filter=q, page_size=100)
        names = [t.get("name") for t in raw if t.get("name")]
        await rset_json(redis, cache_key, names, ttl=600)  # 10 минут
    else:
        names = cached

    # группировка в base
    groups: Dict[str, List[str]] = {}
    for name in names:
        base = make_base_tag(name, q)
        if not base:
            continue
        groups.setdefault(base, []).append(name)

    out: List[SimpleSearchItem] = []
    for base, tags in groups.items():
        tags_unique = sorted(set(tags))
        best = pick_best_for_base(base, tags_unique)
        out.append(SimpleSearchItem(
            base=base,
            tag=best,
            examples=tags_unique[:6]
        ))

    # сортировка: "alpine" первым, потом по major
    def sort_key(item: SimpleSearchItem):
        if item.base == q:
            return (-1, 0, item.base)
        m = re.match(r"^(\d+)-", item.base)
        return (0, int(m.group(1)) if m else 10 ** 9, item.base)

    out.sort(key=sort_key)
    return out
