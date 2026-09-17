"""로그 설정. 인증키는 로그에 남기지 않는다."""

from __future__ import annotations

import logging
import sys
from typing import Any

SECRET_PARAM_NAMES = frozenset({"key", "apikey", "api_key", "servicekey"})


def configure_logging(verbose: int) -> None:
    """-v 는 조회 과정(INFO), -vv 는 요청 상세(DEBUG). 출력은 표준에러."""
    if verbose <= 0:
        level = logging.WARNING
    elif verbose == 1:
        level = logging.INFO
    else:
        level = logging.DEBUG

    logging.basicConfig(
        level=level,
        format="%(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
        force=True,
    )
    noisy = logging.DEBUG if verbose >= 2 else logging.WARNING
    logging.getLogger("urllib3").setLevel(noisy)
    logging.getLogger("requests").setLevel(noisy)


def safe_params(params: dict[str, Any]) -> dict[str, Any]:
    """요청 파라미터에서 인증키만 가린다."""
    return {
        name: "(redacted)" if name.lower() in SECRET_PARAM_NAMES else value
        for name, value in params.items()
    }


def redact(text: str, secret: str = "") -> str:
    if secret:
        return text.replace(secret, "(redacted)")
    return text
