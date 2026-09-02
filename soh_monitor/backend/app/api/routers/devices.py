"""기록계 운영 엔드포인트.

전체 CRUD 는 M5 에서 붙는다. 여기는 M3 의 수동 수집과 최근 수집 이력만 다룬다.

수동 수집은 API 가 직접 장비를 부르지 않는다. `next_poll_at` 을 현재로 당겨 두고
collector 프로세스가 다음 Tick 에 집어 간다. 이유가 둘 있다.
  * API 프로세스가 관측소망으로 직접 나가지 않는다. 나갈 수 있는 경로를 하나로 묶어
    두는 편이 방화벽·감사 관점에서 낫다.
  * 같은 장비를 API 와 수집기가 동시에 부르는 상황을 만들지 않는다.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Response, status
from sqlalchemy import desc, select

from app.db.models import Device, DeviceRuntimeState, PollRun
from app.db.session import session_scope
from app.repository.postgres import collector_repo as repo

router = APIRouter(prefix="/api/v1", tags=["devices"])


def _parse_uuid(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="장비 식별자 형식이 잘못됐다") from exc


@router.post(
    "/devices/{device_id}/poll-now",
    status_code=status.HTTP_202_ACCEPTED,
    summary="수동 수집 요청",
)
def poll_now(device_id: str, response: Response) -> dict[str, object]:
    identifier = _parse_uuid(device_id)
    with session_scope() as session:
        device = session.get(Device, identifier)
        if device is None:
            raise HTTPException(status_code=404, detail="등록되지 않은 장비다")
        if not device.enabled:
            raise HTTPException(status_code=409, detail="수집이 비활성된 장비다")

        repo.request_immediate_poll(session, identifier)

    response.headers["Retry-After"] = "10"
    return {
        "deviceId": device_id,
        "accepted": True,
        "detail": "다음 수집 Tick 에서 곧바로 수집한다",
    }


@router.get("/devices/{device_id}/poll-runs", summary="최근 수집 이력")
def poll_runs(device_id: str, limit: int = 20) -> dict[str, object]:
    identifier = _parse_uuid(device_id)
    limit = max(1, min(limit, 200))

    with session_scope() as session:
        if session.get(Device, identifier) is None:
            raise HTTPException(status_code=404, detail="등록되지 않은 장비다")

        runs = session.scalars(
            select(PollRun)
            .where(PollRun.device_id == identifier)
            .order_by(desc(PollRun.observed_at))
            .limit(limit)
        ).all()

        state = session.get(DeviceRuntimeState, identifier)

        return {
            "deviceId": device_id,
            "runtime": {
                "lastPollAt": repo.as_utc(state.last_poll_at) if state else None,
                "lastSuccessAt": repo.as_utc(state.last_success_at) if state else None,
                "lastObservedAt": repo.as_utc(state.last_observed_at) if state else None,
                "consecutiveFailures": state.consecutive_failures if state else 0,
                "severity": state.overall_severity.value if state else "UNKNOWN",
                "lastErrorCode": (
                    state.last_error_code.value if state and state.last_error_code else None
                ),
                "leaseOwner": state.poll_lease_owner if state else None,
            },
            "runs": [
                {
                    "pollId": run.poll_id,
                    "observedAt": repo.as_utc(run.observed_at),
                    "receivedAt": repo.as_utc(run.received_at),
                    "success": run.success,
                    "latencyMs": run.latency_ms,
                    "httpStatus": run.http_status,
                    "sampleCount": run.sample_count,
                    "errorCode": run.error_code.value if run.error_code else None,
                    "errorMessage": run.error_message,
                    "unmappedValues": run.unmapped_values or {},
                }
                for run in runs
            ],
        }
