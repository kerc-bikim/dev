"""api 프로세스 실행점.

관리 API, 계약 조회, Edge Ingest 를 담당한다.
"""
from __future__ import annotations

import uvicorn

from app.api.app import app  # noqa: F401  (uvicorn 이 문자열 경로로도 참조한다)
from app.config.settings import get_settings


def main() -> None:
    settings = get_settings()
    uvicorn.run(
        "app.api.app:app",
        host="0.0.0.0",
        port=settings.http_port,
        log_config=None,
        reload=False,
    )


if __name__ == "__main__":
    main()
