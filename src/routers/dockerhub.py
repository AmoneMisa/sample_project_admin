from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
import httpx
import re
import json
from ..utils.redis_client import get_redis

router = APIRouter(prefix="/dockerhub", tags=["DockerHub"])

DOCKERHUB_BASE = "https://hub.docker.com"
REGISTRY_BASE = "https://registry-1.docker.io"
AUTH_BASE = "https://auth.docker.io"


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
        # быстрый режим: пытаемся собрать aliases из DockerHub tags API (images[].digest)
        p = parse_tag(tag)
        name_filter = str(p["major"]) if p else None

        raw = await dockerhub_list_tags(repo, name_filter=name_filter, page_size=100)
        digest_to_tags: Dict[str, List[str]] = {}
        for t in raw:
            tname = t.get("name")
            for img in t.get("images", []) or []:
                d = img.get("digest")
                if d and tname:
                    digest_to_tags.setdefault(d, []).append(tname)

        aliases = sorted(set(digest_to_tags.get(digest, [])))
        await rset_json(redis, aliases_key, aliases, ttl=1800)

    return AliasesResponse(repo=repo, tag=tag, digest=digest, aliases=aliases, reason="ok")
