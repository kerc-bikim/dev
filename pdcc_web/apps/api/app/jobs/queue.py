from __future__ import annotations

from ..cache import get_redis
from .store import HEARTBEAT_KEY, QUEUE_KEY


def enqueue_job(job_id: str) -> None:
    get_redis().lpush(QUEUE_KEY, job_id)


def dequeue_job(timeout: int = 5) -> str | None:
    item = get_redis().brpop(QUEUE_KEY, timeout=timeout)
    if not item:
        return None
    return item[1]


def worker_heartbeat() -> None:
    get_redis().set(HEARTBEAT_KEY, "ok", ex=30)


def cancel_queued(job_id: str) -> int:
    return int(get_redis().lrem(QUEUE_KEY, 0, job_id) or 0)
