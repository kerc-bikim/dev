"""구조화 로깅.

수집 로그에는 항상 `device_id` 와 `poll_id` 가 붙어야 한다. 수십 대를 동시에 수집하는
동안 어느 장비의 로그인지 구분되지 않으면 장애 분석이 불가능하다.
"""
from __future__ import annotations

import json
import logging
import sys
from typing import Any

_RESERVED = frozenset(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {
    "message",
    "asctime",
    "taskName",
}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging(level: str = "INFO", *, role: str = "app", json_output: bool = True) -> None:
    handler = logging.StreamHandler(stream=sys.stdout)
    if json_output:
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)-7s [%(name)s] %(message)s")
        )

    root = logging.getLogger()
    for existing in list(root.handlers):
        root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(level.upper())

    logging.getLogger("uvicorn.access").propagate = False
    logging.LoggerAdapter(logging.getLogger(role), {"role": role})


def get_logger(name: str, **context: Any) -> logging.LoggerAdapter:
    """문맥이 항상 따라붙는 로거."""
    return logging.LoggerAdapter(logging.getLogger(name), context)
