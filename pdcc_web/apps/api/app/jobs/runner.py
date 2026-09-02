"""작업 실행. API 테스트와 워커가 같은 함수를 쓴다."""

from __future__ import annotations

import json
import logging
import time

from ..db import SessionLocal
from ..models import Job, Project, utcnow
from .queue import dequeue_job, worker_heartbeat
from .service import run_validate_snapshot

log = logging.getLogger("pdcc.worker")


def process_job(job_id: str) -> None:
    db = SessionLocal()
    try:
        job = db.get(Job, job_id)
        if job is None:
            log.warning("job %s missing", job_id)
            return
        if job.status == "cancelled":
            return
        job.status = "running"
        job.progress = 10
        job.message = "검증 중"
        job.started_at = utcnow()
        job.error = None
        db.commit()
        project = db.get(Project, job.project_id)
        if project is None:
            job.status = "failed"
            job.error = "프로젝트가 없습니다"
            job.message = "실패"
            job.progress = 100
            job.finished_at = utcnow()
            db.commit()
            return
        try:
            job.progress = 40
            db.commit()
            if job.kind != "validate":
                raise RuntimeError(f"지원하지 않는 작업: {job.kind}")
            result = run_validate_snapshot(db, job, project)
            job.progress = 80
            db.commit()
            job.result_json = json.dumps(result, ensure_ascii=False)
            job.status = "succeeded"
            job.progress = 100
            job.message = "완료"
            job.finished_at = utcnow()
            db.commit()
        except Exception:
            log.exception("job %s crashed", job_id)
            job.status = "failed"
            job.error = "검증 중 오류가 났습니다"
            job.message = "실패"
            job.progress = 100
            job.finished_at = utcnow()
            db.commit()
    finally:
        db.close()


def run_worker_loop() -> None:
    log.info("pdcc worker started")
    while True:
        worker_heartbeat()
        job_id = dequeue_job(timeout=5)
        if not job_id:
            continue
        log.info("job %s", job_id)
        process_job(job_id)
        time.sleep(0)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    from ..db import Base, configure_engine, get_engine

    configure_engine()
    Base.metadata.create_all(bind=get_engine())
    run_worker_loop()


if __name__ == "__main__":
    main()
