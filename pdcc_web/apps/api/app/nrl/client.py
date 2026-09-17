from __future__ import annotations

import hashlib
import json
import logging
import re
from typing import Any

import httpx

from ..cache import get_redis
from ..config import settings
from ..tls import CaBundleError, httpx_verify, is_cert_verify_failed, load_verify, tls_hint

log = logging.getLogger("pdcc.nrl")

ALLOWED_FORMATS = frozenset({"stationxml", "stationxml-resp", "resp"})
INSTCONFIG_RE = re.compile(r"^[A-Za-z0-9_.:-]+$")
CATALOG_LEVELS = frozenset({"element", "manufacturer", "model", "configuration"})


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


class NrlClient:
    def __init__(
        self,
        base_url: str | None = None,
        timeout: float | None = None,
        verify: bool | str | None = None,
    ):
        self.base_url = (base_url or settings.nrl_base_url).rstrip("/")
        self.timeout = timeout if timeout is not None else settings.nrl_timeout_sec
        if verify is None:
            try:
                self.verify: bool | str = httpx_verify()
                if self.verify is True and settings.ssl_ca_bundle:
                    self.verify = load_verify(settings.ssl_ca_bundle)
            except CaBundleError as exc:
                raise NrlError(str(exc), 500) from exc
        else:
            self.verify = verify

    def _get(self, path: str, params: dict[str, Any]) -> httpx.Response:
        url = f"{self.base_url}{path}"
        try:
            with httpx.Client(
                timeout=self.timeout,
                follow_redirects=True,
                verify=self.verify,
            ) as client:
                response = client.get(url, params=params)
        except httpx.HTTPError as exc:
            if is_cert_verify_failed(exc):
                log.warning("nrl TLS verify failed %s %s", url, exc)
                raise NrlError(
                    "NRL 인증서 검증에 실패했습니다. " + tls_hint(exc)
                ) from exc
            log.warning("nrl request failed %s %s", url, exc)
            raise NrlError("NRL 서비스에 연결할 수 없습니다") from exc
        if response.status_code == 204 or response.status_code == 404:
            raise NrlError("NRL에 해당 항목이 없습니다", 404)
        if response.status_code >= 400:
            log.warning("nrl status %s %s", response.status_code, url)
            raise NrlError("NRL 서비스가 오류를 반환했습니다", 502)
        return response

    def _cached_json(self, key: str, loader) -> Any:
        redis = get_redis()
        try:
            raw = redis.get(key)
        except Exception:
            raw = None
        if raw:
            return json.loads(raw)
        data = loader()
        try:
            redis.set(key, json.dumps(data), ex=settings.nrl_cache_ttl_sec)
        except Exception:
            log.debug("nrl cache write skipped", exc_info=True)
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
        digest = hashlib.sha256(f"{fmt}|{instconfig}".encode()).hexdigest()[:16]
        cache_key = f"pdcc:nrl:combine:{digest}"

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
