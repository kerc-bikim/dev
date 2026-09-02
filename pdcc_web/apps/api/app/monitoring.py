"""운영 대시보드에 노출할 경량 런타임 모니터링 상태."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone

from fastapi import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .cache import get_redis

log = logging.getLogger("pdcc.monitoring")

API_5XX_EVENTS_KEY = "pdcc:monitoring:api_5xx"
API_5XX_MAX_EVENTS = 200
NRL_FAILURE_COUNT_KEY = "pdcc:monitoring:nrl:consecutive_failures"
NRL_LAST_FAILURE_KEY = "pdcc:monitoring:nrl:last_failure_at"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _text(value) -> str | None:
    if value is None:
        return None
    return value.decode() if isinstance(value, bytes) else str(value)


def record_api_5xx(redis, *, method: str, path: str, status_code: int) -> None:
    event = json.dumps(
        {
            "at": _iso(_utc_now()),
            "method": method,
            "path": path,
            "status_code": status_code,
        },
        separators=(",", ":"),
    )
    try:
        redis.lpush(API_5XX_EVENTS_KEY, event)
        redis.ltrim(API_5XX_EVENTS_KEY, 0, API_5XX_MAX_EVENTS - 1)
    except Exception:
        log.warning("API 5xx monitoring write failed", exc_info=True)


def api_5xx_snapshot(redis, *, window_sec: int) -> dict:
    cutoff = _utc_now() - timedelta(seconds=max(1, window_sec))
    events: list[dict] = []
    try:
        rows = redis.lrange(API_5XX_EVENTS_KEY, 0, API_5XX_MAX_EVENTS - 1)
    except Exception:
        rows = []
    for raw in rows:
        try:
            event = json.loads(_text(raw) or "")
            at = datetime.fromisoformat(str(event["at"]).replace("Z", "+00:00"))
            if at >= cutoff:
                events.append(event)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            continue
    latest = events[0] if events else {}
    return {
        "window_sec": window_sec,
        "count": len(events),
        "last_at": latest.get("at"),
        "last_method": latest.get("method"),
        "last_path": latest.get("path"),
        "last_status": latest.get("status_code"),
    }


def record_nrl_failure(redis) -> int:
    try:
        count = int(redis.incr(NRL_FAILURE_COUNT_KEY))
        redis.set(NRL_LAST_FAILURE_KEY, _iso(_utc_now()))
        return count
    except Exception:
        log.warning("NRL failure monitoring write failed", exc_info=True)
        return 0


def reset_nrl_failures(redis) -> None:
    try:
        redis.delete(NRL_FAILURE_COUNT_KEY)
    except Exception:
        log.warning("NRL failure monitoring reset failed", exc_info=True)


def nrl_failure_snapshot(redis, *, threshold: int) -> dict:
    try:
        count = int(_text(redis.get(NRL_FAILURE_COUNT_KEY)) or 0)
        last_at = _text(redis.get(NRL_LAST_FAILURE_KEY))
    except Exception:
        count = 0
        last_at = None
    return {
        "consecutive_failures": count,
        "threshold": threshold,
        "last_failed_at": last_at,
    }


class Api5xxMonitoringMiddleware:
    """응답 본문을 건드리지 않고 API 5xx 응답 메타데이터만 Redis에 기록한다."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope)
        recorded = False

        async def send_with_monitoring(message: Message) -> None:
            nonlocal recorded
            if message["type"] == "http.response.start":
                status_code = int(message["status"])
                if status_code >= 500 and not recorded:
                    recorded = True
                    record_api_5xx(
                        get_redis(),
                        method=request.method,
                        path=request.url.path,
                        status_code=status_code,
                    )
            await send(message)

        try:
            await self.app(scope, receive, send_with_monitoring)
        except Exception:
            if not recorded:
                record_api_5xx(
                    get_redis(),
                    method=request.method,
                    path=request.url.path,
                    status_code=500,
                )
            raise
