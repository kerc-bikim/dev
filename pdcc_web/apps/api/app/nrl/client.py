from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import datetime, timezone
from typing import Any

import httpx

from ..cache import get_redis
from ..config import settings

log = logging.getLogger("pdcc.nrl")

ALLOWED_FORMATS = frozenset({"stationxml", "stationxml-resp", "resp"})
INSTCONFIG_RE = re.compile(r"^[A-Za-z0-9_.:-]+$")
CATALOG_LEVELS = frozenset({"element", "manufacturer", "model", "configuration"})
STALE_TTL_SEC = 30 * 24 * 3600
PROBE_CACHE_TTL_SEC = 30
CACHE_MISS_DETAIL = "캐시에 없는 항목입니다. NRL이 복구된 뒤에 다시 시도하세요"
META_LAST_OK = "pdcc:nrl:last_ok"
META_LAST_OK_AT = "pdcc:nrl:last_ok_at"
META_SOURCE = "pdcc:nrl:source"
META_PROBE = "pdcc:nrl:probe_ok"
CACHE_KEY_PREFIXES = (
    "pdcc:nrl:catalog:",
    "pdcc:nrl:combine:",
    "pdcc:nrl:prefix",
    "pdcc:nrl:index:",
)


class NrlError(Exception):
    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


def validate_instconfig(value: str) -> str:
    text = value.strip()
    if not text or not INSTCONFIG_RE.match(text):
        raise NrlError("instconfig 형식이 올바르지 않습니다", 400)
    if "," in text or "full_NRL" in text:
        raise NrlError("전체 NRL 다운로드와 다중 instconfig는 허용하지 않습니다", 400)
    return text


def validate_format(value: str) -> str:
    fmt = value.strip()
    if fmt not in ALLOWED_FORMATS:
        raise NrlError(f"지원하지 않는 형식입니다: {fmt}", 400)
    return fmt


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def combine_cache_key(instconfig: str, fmt: str) -> str:
    digest = hashlib.sha256(f"{fmt}|{instconfig}".encode()).hexdigest()[:16]
    return f"pdcc:nrl:combine:{digest}"


def nrl_cache_count(redis) -> int:
    seen: set[str] = set()
    keys: list = []
    try:
        keys = list(redis.scan_iter(match="pdcc:nrl:*"))
    except Exception:
        try:
            keys = list(redis.keys("pdcc:nrl:*"))
        except Exception:
            return 0
    for key in keys:
        text = key.decode() if isinstance(key, bytes) else str(key)
        if text.endswith(":stale"):
            text = text[: -len(":stale")]
        if any(text.startswith(prefix) for prefix in CACHE_KEY_PREFIXES):
            seen.add(text)
    return len(seen)


def nrl_cache_bytes(redis) -> int:
    total = 0
    keys: list = []
    try:
        keys = list(redis.scan_iter(match="pdcc:nrl:*"))
    except Exception:
        try:
            keys = list(redis.keys("pdcc:nrl:*"))
        except Exception:
            return 0
    for key in keys:
        text = key.decode() if isinstance(key, bytes) else str(key)
        if not any(text.startswith(prefix) for prefix in CACHE_KEY_PREFIXES):
            continue
        try:
            total += int(redis.strlen(key) or 0)
        except Exception:
            try:
                raw = redis.get(key)
            except Exception:
                raw = None
            if raw:
                total += len(raw) if isinstance(raw, (bytes, str)) else 0
    return total


def nrl_snapshot_from_redis(redis) -> dict:
    cache_count = 0
    cache_bytes = 0
    last_ok_at = None
    source = None
    try:
        cache_count = nrl_cache_count(redis)
        cache_bytes = nrl_cache_bytes(redis)
        last_ok_at = redis.get(META_LAST_OK_AT)
        source = redis.get(META_SOURCE)
    except Exception:
        cache_count = 0
        cache_bytes = 0
    mode = nrl_mode()
    library = None
    if mode == "offline":
        from .offline import get_offline_library

        library = get_offline_library().status()
        source = "zip" if library["available"] else "offline"
    elif source not in {"online", "cache", "offline", "zip"}:
        if cache_count > 0:
            source = "cache"
        elif last_ok_at:
            source = "online"
        else:
            source = None
    return {
        "mode": mode,
        "source": source,
        "badge": nrl_badge(source) if source else None,
        "base_url": settings.nrl_base_url,
        "last_ok": bool(last_ok_at),
        "last_ok_at": last_ok_at,
        "cache_count": cache_count,
        "cache_bytes": cache_bytes,
        "library": library,
    }


def _redis_set(redis, key: str, value: str, ex: int | None = None) -> None:
    try:
        if ex is None:
            redis.set(key, value)
        else:
            redis.set(key, value, ex=ex)
    except Exception:
        log.debug("nrl cache write skipped", exc_info=True)


def mark_nrl_live_ok(redis) -> None:
    now = utc_now_iso()
    _redis_set(redis, META_LAST_OK, "1")
    _redis_set(redis, META_LAST_OK_AT, now)
    _redis_set(redis, META_SOURCE, "online")
    _redis_set(redis, META_PROBE, "1", ex=PROBE_CACHE_TTL_SEC)


def mark_nrl_live_failed(redis, *, has_cache: bool) -> None:
    _redis_set(redis, META_PROBE, "0", ex=PROBE_CACHE_TTL_SEC)
    _redis_set(redis, META_SOURCE, "cache" if has_cache else "offline")


def mark_nrl_using_cache(redis) -> None:
    mark_nrl_live_failed(redis, has_cache=True)


def nrl_mode() -> str:
    mode = (settings.nrl_mode or "online").strip().lower()
    return mode if mode in {"online", "cache-first", "offline"} else "online"


def nrl_badge(source: str) -> str:
    return {
        "online": "온라인",
        "cache": "캐시 사용",
        "offline": "NRL 장애",
        "zip": "오프라인 zip",
    }.get(source, source)


class NrlClient:
    def __init__(self, base_url: str | None = None, timeout: float | None = None):
        self.base_url = (base_url or settings.nrl_base_url).rstrip("/")
        self.timeout = timeout if timeout is not None else settings.nrl_timeout_sec

    def _get(self, path: str, params: dict[str, Any]) -> httpx.Response:
        url = f"{self.base_url}{path}"
        try:
            with httpx.Client(timeout=self.timeout, follow_redirects=True) as client:
                response = client.get(url, params=params)
        except httpx.HTTPError as exc:
            log.warning("nrl request failed %s %s", url, exc)
            raise NrlError("NRL 서비스에 연결할 수 없습니다") from exc
        if response.status_code == 204 or response.status_code == 404:
            raise NrlError("NRL에 해당 항목이 없습니다", 404)
        if response.status_code >= 400:
            log.warning("nrl status %s %s", response.status_code, url)
            raise NrlError("NRL 서비스가 오류를 반환했습니다", 502)
        return response

    def probe(self, timeout: float | None = None) -> dict:
        import time

        url = f"{self.base_url}/catalog"
        params = {"format": "json", "nodata": "404", "level": "element"}
        started = time.perf_counter()
        wait = timeout if timeout is not None else self.timeout
        try:
            with httpx.Client(timeout=wait, follow_redirects=True) as client:
                response = client.get(url, params=params)
        except httpx.HTTPError as exc:
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            return {
                "ok": False,
                "url": url,
                "status_code": 0,
                "elapsed_ms": elapsed_ms,
                "elements": [],
                "error": "NRL 서비스에 연결할 수 없습니다",
            }
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        elements: list[str] = []
        if response.status_code < 400:
            try:
                data = response.json()
                from .questions import as_list

                for node in as_list(data.get("NRLCatalog", {}).get("element")):
                    name = node.get("name") if isinstance(node, dict) else None
                    if name:
                        elements.append(str(name))
            except Exception:
                pass
        return {
            "ok": 200 <= response.status_code < 400,
            "url": url,
            "status_code": response.status_code,
            "elapsed_ms": elapsed_ms,
            "elements": elements,
            "error": None if 200 <= response.status_code < 400 else "NRL 서비스가 오류를 반환했습니다",
        }

    def _read_cached(self, redis, key: str) -> tuple[Any | None, Any | None]:
        fresh = None
        stale = None
        try:
            raw = redis.get(key)
            if raw:
                fresh = json.loads(raw)
            raw_stale = redis.get(f"{key}:stale")
            if raw_stale:
                stale = json.loads(raw_stale)
        except Exception:
            log.debug("nrl cache read skipped", exc_info=True)
        return fresh, stale

    def _write_cached(self, redis, key: str, data: Any) -> None:
        blob = json.dumps(data)
        _redis_set(redis, key, blob, ex=settings.nrl_cache_ttl_sec)
        _redis_set(redis, f"{key}:stale", blob, ex=STALE_TTL_SEC)

    def _cached_json(self, key: str, loader) -> Any:
        redis = get_redis()
        fresh, stale = self._read_cached(redis, key)
        mode = (settings.nrl_mode or "online").strip().lower()

        if mode == "offline":
            cached = fresh if fresh is not None else stale
            if cached is not None:
                mark_nrl_using_cache(redis)
                return cached
            raise NrlError(CACHE_MISS_DETAIL, 503)

        if fresh is not None:
            return fresh

        try:
            data = loader()
        except NrlError as exc:
            cached = stale
            has_cache = cached is not None or nrl_cache_count(redis) > 0
            if cached is not None:
                log.warning("nrl fallback to cache for %s", key)
                mark_nrl_using_cache(redis)
                return cached
            if exc.status_code in (400, 404):
                raise
            mark_nrl_live_failed(redis, has_cache=has_cache)
            raise NrlError(CACHE_MISS_DETAIL, 503) from exc

        self._write_cached(redis, key, data)
        mark_nrl_live_ok(redis)
        return data

    def catalog(
        self,
        *,
        level: str,
        element: str | None = None,
        manufacturer: str | None = None,
        model: str | None = None,
    ) -> dict:
        if level not in CATALOG_LEVELS:
            raise NrlError(f"알 수 없는 catalog level: {level}", 400)
        if nrl_mode() == "offline":
            from .offline import get_offline_library

            return get_offline_library().catalog(
                level=level,
                element=element,
                manufacturer=manufacturer,
                model=model,
            )
        params: dict[str, Any] = {
            "format": "json",
            "nodata": "404",
            "level": level,
        }
        if element:
            params["element"] = element
        if manufacturer:
            params["manufacturer"] = manufacturer
        if model:
            params["model"] = model
        digest = hashlib.sha256(json.dumps(params, sort_keys=True).encode()).hexdigest()[:16]
        cache_key = f"pdcc:nrl:catalog:{digest}"

        def load() -> dict:
            return self._get("/catalog", params).json()

        return self._cached_json(cache_key, load)

    def prefix_lookup(self) -> list[dict]:
        if nrl_mode() == "offline":
            from .offline import get_offline_library

            return get_offline_library().prefix_lookup()

        def load() -> list[dict]:
            data = self._get("/prefix-lookup", {"format": "json"}).json()
            if isinstance(data, list):
                return data
            return []

        return self._cached_json("pdcc:nrl:prefix", load)

    def catalog_fingerprint(self) -> str:
        try:
            data = self.catalog(level="element")
        except NrlError:
            return "nrl-offline"
        blob = json.dumps(data, sort_keys=True, default=str)
        return hashlib.sha256(blob.encode()).hexdigest()[:16]

    def combine(self, instconfig: str, fmt: str) -> tuple[bytes, str]:
        instconfig = validate_instconfig(instconfig)
        fmt = validate_format(fmt)
        if nrl_mode() == "offline":
            from .offline import get_offline_library

            return get_offline_library().combine(instconfig, fmt)
        cache_key = combine_cache_key(instconfig, fmt)

        def load() -> dict:
            response = self._get(
                "/combine",
                {"nodata": "404", "format": fmt, "instconfig": instconfig},
            )
            return {
                "body": response.content.decode("utf-8"),
                "content_type": response.headers.get(
                    "content-type", "application/octet-stream"
                ),
            }

        data = self._cached_json(cache_key, load)
        return data["body"].encode("utf-8"), data["content_type"]


_client: NrlClient | None = None


def get_nrl_client() -> NrlClient:
    global _client
    if _client is None:
        _client = NrlClient()
    return _client


def set_nrl_client(client: NrlClient | None) -> None:
    global _client
    _client = client
