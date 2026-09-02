"""편집자 알림. 잠금 강제 해제 등. 초안은 지우지 않는다."""

from __future__ import annotations

import json
import uuid
from typing import Any

from .cache import get_redis
from .nrl.client import utc_now_iso

NOTIFY_PREFIX = "pdcc:notify:"
NOTIFY_TTL_SEC = 7 * 24 * 3600
NOTIFY_MAX = 20


def _key(user_id: int) -> str:
    return f"{NOTIFY_PREFIX}{user_id}"


def push_notice(user_id: int, message: str, *, kind: str = "unlock") -> dict[str, Any]:
    notice = {
        "id": uuid.uuid4().hex,
        "kind": kind,
        "message": message,
        "created_at": utc_now_iso(),
    }
    redis = get_redis()
    key = _key(user_id)
    try:
        redis.lpush(key, json.dumps(notice, ensure_ascii=False))
        redis.ltrim(key, 0, NOTIFY_MAX - 1)
        redis.expire(key, NOTIFY_TTL_SEC)
    except Exception:
        pass
    return notice


def list_notices(user_id: int) -> list[dict[str, Any]]:
    redis = get_redis()
    try:
        raw_items = redis.lrange(_key(user_id), 0, NOTIFY_MAX - 1) or []
    except Exception:
        return []
    out: list[dict[str, Any]] = []
    for raw in raw_items:
        try:
            item = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            continue
        if isinstance(item, dict) and item.get("id") and item.get("message"):
            out.append(item)
    return out


def ack_notice(user_id: int, notice_id: str) -> bool:
    notices = [row for row in list_notices(user_id) if row.get("id") != notice_id]
    redis = get_redis()
    key = _key(user_id)
    try:
        redis.delete(key)
        if notices:
            redis.rpush(key, *[json.dumps(row, ensure_ascii=False) for row in reversed(notices)])
            redis.expire(key, NOTIFY_TTL_SEC)
    except Exception:
        return False
    return True
