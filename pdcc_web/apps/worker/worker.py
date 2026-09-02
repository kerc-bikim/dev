"""M0 worker stub. M3에서 작업 큐를 붙인다."""

from __future__ import annotations

import os
import time

import redis


def main() -> None:
    url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    client = redis.Redis.from_url(url, decode_responses=True)
    while True:
        client.set("pdcc:worker:heartbeat", "ok", ex=30)
        time.sleep(10)


if __name__ == "__main__":
    main()
