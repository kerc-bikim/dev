"""수집 스케줄러.

한 Tick 에서 하는 일은 넷이다.
  1. 수집 시각이 된 장비를 고른다
  2. 장비별 Lease 를 잡는다 (중복 수집 방지)
  3. 동시 실행 수를 제한해 수집한다
  4. 결과를 시계열·이력·현재 상태에 남기고 다음 수집 시각을 잡는다

느린 장비 하나가 전체를 붙잡지 않도록, 수집은 장비별로 독립적으로 진행되고 Tick 은
진행 중인 작업이 끝나기를 기다리지 않는다.
"""
from __future__ import annotations

import asyncio
import socket
import os
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.adapters.registry import AdapterRegistry, get_registry
from app.auth.credentials import CredentialResolver
from app.collector.retry import RetryPolicy
from app.collector.runner import PollOutcome, poll_device
from app.config.settings import Settings, get_settings
from app.health.service import HealthService
from app.observability.logging import get_logger
from app.repository.influx.points import build_points
from app.repository.influx.sink import MetricSink
from app.repository.postgres import collector_repo as repo
from app.repository.postgres.collector_repo import DueDevice

logger = get_logger("app.collector.scheduler", role="collector")


def default_owner() -> str:
    """Lease 소유자 표시. 어느 인스턴스가 잡았는지 화면에서 보여야 한다."""
    return f"{socket.gethostname()}:{os.getpid()}"


@dataclass
class TickReport:
    due: int = 0
    leased: int = 0
    skipped_leased: int = 0
    succeeded: int = 0
    failed: int = 0
    points_written: int = 0
    sink_failed: bool = False
    errors: dict[str, int] = field(default_factory=dict)
    opened: int = 0
    resolved: int = 0
    escalated: int = 0
    severities: dict[str, int] = field(default_factory=dict)


class CollectorScheduler:
    def __init__(
        self,
        session_factory,
        sink: MetricSink,
        *,
        settings: Settings | None = None,
        registry: AdapterRegistry | None = None,
        resolver: CredentialResolver | None = None,
        owner: str | None = None,
        sleep=asyncio.sleep,
        health: HealthService | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.sink = sink
        self.settings = settings or get_settings()
        self.registry = registry or get_registry()
        self.resolver = resolver or CredentialResolver()
        self.owner = owner or default_owner()
        self.sleep = sleep
        # 판정 엔진. 수집만 시험하고 싶을 때는 None 으로 둔다.
        self.health = health
        self._semaphore = asyncio.Semaphore(self.settings.max_concurrent_polls)
        # 진행 중인 장비를 다시 집지 않기 위한 표시. Lease 는 DB, 이것은 프로세스 안이다.
        self._in_flight: set[str] = set()

    # ------------------------------------------------------------------ 선택

    def _claim(self, session: Session, devices: list[DueDevice], report: TickReport) -> list[DueDevice]:
        claimed: list[DueDevice] = []
        for device in devices:
            key = str(device.device_id)
            if key in self._in_flight:
                # 이전 Tick 의 수집이 아직 끝나지 않았다. 겹쳐 부르지 않는다.
                report.skipped_leased += 1
                continue
            if not repo.acquire_lease(
                session,
                device.device_id,
                self.owner,
                ttl_seconds=max(60, device.request_timeout_ms // 1000 * 4),
            ):
                report.skipped_leased += 1
                continue
            self._in_flight.add(key)
            claimed.append(device)
        session.commit()
        report.leased = len(claimed)
        return claimed

    # ------------------------------------------------------------------ 기록

    def _persist(self, outcome: PollOutcome, report: TickReport) -> None:
        device = outcome.device
        result = outcome.result
        health_points: list = []

        with self.session_factory() as session:
            try:
                # 낡은 값 판정은 이번 수집이 상태를 갱신하기 **전**의 마지막 성공 시각을
                # 근거로 한다. 갱신 후 값을 보면 방금 성공했으니 항상 최신으로 보인다.
                previous_success_at = self._last_success_at(session, device.device_id)

                repo.record_poll_run(session, device, result)
                state = repo.update_runtime_state(
                    session,
                    device,
                    result,
                    warning_threshold=self.settings.failure_warning_threshold,
                    critical_threshold=self.settings.failure_critical_threshold,
                )
                if result.success and result.capabilities.states:
                    repo.upsert_capabilities(
                        session, device.device_id, result.capabilities.states
                    )
                consecutive_failures = state.consecutive_failures or 0

                if self.health is not None:
                    health_points = self._evaluate_health(
                        session,
                        device,
                        result,
                        consecutive_failures,
                        report,
                        last_success_at=previous_success_at,
                    )

                repo.schedule_next_poll(
                    session,
                    device.device_id,
                    interval_minutes=device.poll_interval_minutes,
                    jitter_percent=self.settings.poll_jitter_percent,
                )
                repo.release_lease(session, device.device_id, self.owner)
                session.commit()
            except Exception:  # noqa: BLE001 - 한 장비의 기록 실패로 Tick 을 죽이지 않는다
                session.rollback()
                logger.exception(
                    "수집 결과 기록 실패", extra={"device_id": str(device.device_id)}
                )
                consecutive_failures = device.consecutive_failures

        points = build_points(
            result, device.tags, consecutive_failures=consecutive_failures
        )
        points.extend(health_points)
        if not self.sink.write(points):
            # 적재 실패는 수집 실패와 다르다. 장비는 정상인데 우리 저장소가 문제다.
            report.sink_failed = True
        else:
            report.points_written += len(points)

        if result.success:
            report.succeeded += 1
        else:
            report.failed += 1
            code = result.error_code.value if result.error_code else "UNKNOWN"
            report.errors[code] = report.errors.get(code, 0) + 1

    @staticmethod
    def _last_success_at(session, device_id):
        from app.db.models import DeviceRuntimeState

        runtime = session.get(DeviceRuntimeState, device_id)
        return repo.as_utc(runtime.last_success_at) if runtime else None

    def _evaluate_health(
        self,
        session,
        device: DueDevice,
        result,
        consecutive_failures: int,
        report: TickReport,
        *,
        last_success_at,
    ) -> list:
        """상태 판정. 판정에 필요한 장비·관측소 행이 없으면 건너뛴다."""
        from app.db.models import Device as DeviceRow
        from app.db.models import Station as StationRow

        device_row = session.get(DeviceRow, device.device_id)
        station_row = session.get(StationRow, device.station_id)
        if device_row is None or station_row is None:
            return []

        health_report = self.health.evaluate(
            session,
            device_row,
            station_row,
            result,
            consecutive_failures=consecutive_failures,
            tags=device.tags,
            poll_interval_minutes=device.poll_interval_minutes,
            last_success_at=last_success_at,
        )

        report.opened += len(health_report.opened)
        report.resolved += len(health_report.resolved)
        report.escalated += len(health_report.escalated)
        key = health_report.overall.value
        report.severities[key] = report.severities.get(key, 0) + 1
        return health_report.points

    # ------------------------------------------------------------------ 실행

    async def _run_one(self, device: DueDevice, report: TickReport) -> None:
        policy = RetryPolicy(
            max_attempts=max(1, device.retry_count + 1),
            delay_seconds=float(device.retry_delay_seconds),
        )
        try:
            async with self._semaphore:
                outcome = await poll_device(
                    device, self.registry, self.resolver, policy, sleep=self.sleep
                )
            self._persist(outcome, report)
        finally:
            self._in_flight.discard(str(device.device_id))

    def _publish_ops_health(self, report: TickReport) -> None:
        """Edge·수집기 자체 상태를 Grafana 가 감시할 수 있게 적재한다.

        장비가 없어 Tick 이 비어도 이 점은 남긴다. Influx 가 죽으면 점이 끊기고
        Grafana `Influx Write Failure` 가 noData 로 울린다.
        """
        from datetime import datetime, timezone

        from app.health.ops_points import write_ops_health

        now = datetime.now(timezone.utc)
        failed_writes = getattr(self.sink, "failed_writes", 0)
        dropped_points = getattr(self.sink, "dropped_points", 0)
        try:
            with self.session_factory() as session:
                written = write_ops_health(
                    session,
                    self.sink,
                    now,
                    write_success=not report.sink_failed,
                    failed_writes=failed_writes,
                    dropped_points=dropped_points,
                )
                session.commit()
            if written and not report.sink_failed:
                report.points_written += len(written)
        except Exception:  # noqa: BLE001 - 운영 지표 실패로 수집 Tick 을 죽이지 않는다
            logger.exception("운영 상태 적재 실패")

    async def tick(self) -> TickReport:
        report = TickReport()

        with self.session_factory() as session:
            devices = repo.due_devices(
                session,
                default_interval_minutes=self.settings.default_poll_interval_minutes,
            )
            report.due = len(devices)
            claimed = self._claim(session, devices, report)

        if claimed:
            await asyncio.gather(*(self._run_one(device, report) for device in claimed))

        self._publish_ops_health(report)

        logger.info(
            "Tick 완료",
            extra={
                "due": report.due,
                "leased": report.leased,
                "skipped": report.skipped_leased,
                "succeeded": report.succeeded,
                "failed": report.failed,
                "points": report.points_written,
                "sink_failed": report.sink_failed,
                "errors": report.errors,
                "opened": report.opened,
                "resolved": report.resolved,
                "escalated": report.escalated,
                "severities": report.severities,
            },
        )
        return report
