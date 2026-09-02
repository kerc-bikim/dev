from __future__ import annotations

import json

QUEUE_KEY = "pdcc:jobs:queue"
HEARTBEAT_KEY = "pdcc:worker:heartbeat"


def loads_obj(raw: str | None) -> dict | None:
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None
