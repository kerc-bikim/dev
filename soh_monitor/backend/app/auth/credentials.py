"""기록계 접속 인증정보 해석.

DB 에는 참조만 있고 값은 없다. 이 모듈이 참조를 실제 값으로 바꾼다.

지원하는 참조 형식
    env:SOH_DEVICE_PW_A01          환경변수
    file:/run/secrets/device_a01   파일 (Docker Secret)

해석한 값은 절대 로그·응답·예외 메시지에 담지 않는다. 실패해도 '참조를 해석할 수 없다'
까지만 알린다. 참조 이름 자체는 비밀이 아니므로 남긴다.
"""
from __future__ import annotations

import os
from pathlib import Path

from app.observability.logging import get_logger

logger = get_logger("app.auth.credentials")


class CredentialResolver:
    def __init__(self, *, overrides: dict[str, str] | None = None) -> None:
        # 시험에서 실제 Secret 저장소 없이 값을 넣기 위한 통로다.
        self._overrides = overrides or {}

    def resolve(self, reference: str | None) -> dict[str, str] | None:
        if not reference:
            return None

        if reference in self._overrides:
            return {"password": self._overrides[reference]}

        scheme, _, target = reference.partition(":")
        if not target:
            logger.warning("인증정보 참조 형식이 잘못됐다", extra={"reference": reference})
            return None

        if scheme == "env":
            value = os.environ.get(target)
        elif scheme == "file":
            path = Path(target)
            value = path.read_text(encoding="utf-8").strip() if path.exists() else None
        else:
            logger.warning(
                "지원하지 않는 인증정보 참조 방식",
                extra={"reference": reference, "scheme": scheme},
            )
            return None

        if not value:
            logger.warning("인증정보 참조를 해석하지 못했다", extra={"reference": reference})
            return None

        return {"password": value}
