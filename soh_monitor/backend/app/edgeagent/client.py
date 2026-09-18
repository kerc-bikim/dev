"""중앙 API 클라이언트.

Edge 는 Outbound HTTPS 만 쓴다. 중앙이 꺼져 있어도 예외로 올려 수집 루프가
멈추지 않게 한다. 유실은 Spool 이 막고, 여기서는 전송만 시도한다.
"""
from __future__ import annotations

import gzip
import json
from typing import Any, Protocol

import httpx

from app.edgeagent.enroll import EnrollmentBundle
from app.observability.logging import get_logger

logger = get_logger("app.edgeagent.client", role="edge")


class CentralUnavailable(Exception):
    """중앙에 닿지 않는다. 수집은 계속하고 전송만 미룬다."""


class CentralRejected(Exception):
    """중앙이 요청을 거절했다. 같은 내용을 반복해 보내지 않는다."""

    def __init__(self, message: str, *, status_code: int) -> None:
        super().__init__(message)
        self.status_code = status_code


class CentralClient(Protocol):
    token: str | None

    async def enroll(
        self,
        edge_id: str,
        enrollment_token: str,
        *,
        agent_version: str,
        adapters: list[str],
    ) -> EnrollmentBundle: ...

    async def heartbeat(self, payload: dict[str, Any]) -> dict[str, Any]: ...

    async def fetch_config(self, current_version: int) -> dict[str, Any] | None: ...

    async def upload_batch(self, batch: dict[str, Any]) -> dict[str, Any]: ...

    async def report_task(self, task_id: str, result: dict[str, Any]) -> dict[str, Any]: ...

    async def aclose(self) -> None: ...


class HttpxCentralClient:
    """실제 중앙 FastAPI 에 붙는 구현."""

    def __init__(
        self,
        base_url: str,
        *,
        token: str | None = None,
        timeout: float = 30.0,
        http: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout
        self._owns_http = http is None
        self._http = http or httpx.AsyncClient(timeout=timeout)

    def _headers(self, *, with_auth: bool = True) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if with_auth and self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    async def aclose(self) -> None:
        if self._owns_http:
            await self._http.aclose()

    async def enroll(
        self,
        edge_id: str,
        enrollment_token: str,
        *,
        agent_version: str,
        adapters: list[str],
    ) -> EnrollmentBundle:
        body = {
            "edgeId": edge_id,
            "enrollmentToken": enrollment_token,
            "agentVersion": agent_version,
            "installedAdapters": adapters,
        }
        payload = await self._request(
            "POST",
            "/api/v1/edge/enroll",
            json_body=body,
            with_auth=False,
        )
        bundle = EnrollmentBundle(
            certificate=payload["certificate"],
            private_key=payload["privateKey"],
            ca_certificate=payload["caCertificate"],
            client_token=payload["clientToken"],
            expires_at=payload.get("expiresAt"),
        )
        self.token = bundle.client_token
        return bundle

    async def heartbeat(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._request("POST", "/api/v1/edge/heartbeat", json_body=payload)

    async def fetch_config(self, current_version: int) -> dict[str, Any] | None:
        payload = await self._request(
            "GET",
            "/api/v1/edge/config",
            params={"currentVersion": str(current_version)},
        )
        if payload.get("unchanged"):
            return None
        return payload.get("config") or payload

    async def upload_batch(self, batch: dict[str, Any]) -> dict[str, Any]:
        raw = json.dumps(batch, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        compressed = gzip.compress(raw)
        return await self._request(
            "POST",
            "/api/v1/edge/ingest/batches",
            content=compressed,
            extra_headers={"Content-Type": "application/gzip"},
        )

    async def report_task(self, task_id: str, result: dict[str, Any]) -> dict[str, Any]:
        return await self._request(
            "POST",
            f"/api/v1/edge/tasks/{task_id}/result",
            json_body=result,
        )

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        content: bytes | None = None,
        params: dict[str, str] | None = None,
        extra_headers: dict[str, str] | None = None,
        with_auth: bool = True,
    ) -> dict[str, Any]:
        headers = self._headers(with_auth=with_auth)
        if extra_headers:
            headers.update(extra_headers)
        url = f"{self.base_url}{path}"
        try:
            response = await self._http.request(
                method,
                url,
                json=json_body,
                content=content,
                params=params,
                headers=headers,
                timeout=self.timeout,
            )
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout, httpx.NetworkError) as exc:
            raise CentralUnavailable(f"중앙에 닿지 않는다: {exc}") from exc

        if response.status_code >= 500:
            raise CentralUnavailable(f"중앙이 {response.status_code} 를 돌려줬다")
        if response.status_code == 409:
            try:
                return response.json()
            except ValueError:
                return {"duplicate": True}
        if response.status_code == 204:
            return {"unchanged": True}
        if response.status_code >= 400:
            detail = _error_detail(response)
            raise CentralRejected(
                f"중앙이 요청을 거절했다 ({response.status_code}): {detail}",
                status_code=response.status_code,
            )
        if not response.content:
            return {}
        try:
            return response.json()
        except ValueError as exc:
            raise CentralUnavailable("중앙 응답이 JSON 이 아니다") from exc


def _error_detail(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.text[:200]
    if isinstance(payload, dict) and payload.get("detail") is not None:
        return str(payload["detail"])
    return str(payload)[:200]
