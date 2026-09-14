"""작업 실행. API 프로세스와 워커가 같은 함수를 쓴다."""

from __future__ import annotations

import json
import logging
import time

from ..db import SessionLocal
from ..export import ExportError, render_export
from ..models import ExportJob, Project, utcnow
from .queue import dequeue_job, worker_heartbeat
from .store import write_artifact

log = logging.getLogger("pdcc.worker")


def process_job(job_id: str) -> None:
    db = SessionLocal()
    try:
        job = db.get(ExportJob, job_id)
        if job is None:
            log.warning("job %s missing", job_id)
            return
        if job.status == "cancelled":
            return
        job.status = "running"
        job.progress = 10
        job.message = "변환 중"
        job.started_at = utcnow()
        job.error = None
        db.commit()
        project = db.get(Project, job.project_id)
        network = project.network_code if project is not None else None
        try:
            job.progress = 40
            db.commit()
            result = render_export(
                job.xml_snapshot,
                kind=job.kind,
                network=network,
                station=job.station,
                start=job.start_time,
                nslc=job.nslc,
                accept_losses=True,
            )
            job.progress = 80
            db.commit()
            path = write_artifact(job.id, result.filename, result.data)
            job.filename = result.filename
            job.media_type = result.media_type
            job.artifact_path = str(path)
            job.warnings_json = json.dumps(result.warnings, ensure_ascii=False)
            job.losses_json = json.dumps(result.losses, ensure_ascii=False)
            job.drops_json = json.dumps(result.drops, ensure_ascii=False)
            job.status = "completed"
            job.progress = 100
            job.message = "완료"
            job.finished_at = utcnow()
            db.commit()
        except ExportError as exc:
            log.warning("job %s export failed: %s", job_id, exc)
            job.status = "failed"
            job.error = str(exc)
            job.message = "실패"
            job.progress = 100
            job.finished_at = utcnow()
            job.losses_json = json.dumps(exc.losses, ensure_ascii=False)
            job.drops_json = json.dumps(exc.drops, ensure_ascii=False)
            db.commit()
        except Exception:
            log.exception("job %s crashed", job_id)
            job.status = "failed"
            job.error = "변환 중 오류가 났습니다"
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
