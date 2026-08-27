from __future__ import annotations

import json
from pathlib import Path

from ..config import settings
from ..models import ExportJob

QUEUE_KEY = "pdcc:jobs:queue"
HEARTBEAT_KEY = "pdcc:worker:heartbeat"


def job_dir(job_id: str) -> Path:
    path = Path(settings.export_dir) / job_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_artifact(job_id: str, filename: str, data: bytes) -> Path:
    path = job_dir(job_id) / filename
    path.write_bytes(data)
    return path


def artifact_bytes(job: ExportJob) -> bytes:
    if not job.artifact_path:
        raise FileNotFoundError(job.id)
    return Path(job.artifact_path).read_bytes()


def loads_list(raw: str | None) -> list:
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []
