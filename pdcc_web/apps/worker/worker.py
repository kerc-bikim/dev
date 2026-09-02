"""PDCC worker. Redis 큐에서 RESP/dataless 내보내기를 실행한다."""

from __future__ import annotations

import sys
from pathlib import Path

API_ROOT = Path(__file__).resolve().parent.parent / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.jobs.runner import main  # noqa: E402


if __name__ == "__main__":
    main()
