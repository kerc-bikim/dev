"""Edge 한 Tick.

순서: 등록 → 설정 동기 → 할당 장비 수집 → Spool 기록 → 업로드 → Heartbeat·원격 작업.

중앙이 꺼져 있어도 수집과 Spool 기록은 계속한다. 업로드와 Heartbeat 만 미룬다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.adapters.registry import AdapterRegistry
from app.auth.credentials import CredentialResolver
from app.config.settings import Settings
from app.edgeagent import AGENT_VERSION
from app.edgeagent.client import CentralClient, CentralRejected, CentralUnavailable, HttpxCentralClient
from app.edgeagent.configsync import ConfigError, ConfigStore
from app.edgeagent.enroll import EnrollmentStore
from app.edgeagent.heartbeat import build_heartbeat, clock_offset_ms, collect_health
from app.edgeagent.poller import LocalSchedule, collect_due
from app.edgeagent.spool import Spool
from app.edgeagent.tasks import execute_task
from app.edgeagent.uploader import Uploader
from app.observability.logging import get_logger

logger = get_logger("app.edgeagent.runtime", role="edge")


@dataclass
class TickStats:
    enrolled: bool = False
    config_version: int = 0
    collected: int = 0
    spooled: int = 0
    uploaded: int = 0
    central_down: bool = False
    tasks: int = 0
    errors: list[str] = field(default_factory=list)


class EdgeRuntime:
    def __init__(
        self,
        *,
        edge_id: str,
        spool_path: Path,
        spool_limit_bytes: int,
        registry: AdapterRegistry,
        client: CentralClient,
        enrollment_token: str | None = None,
        enrollment_token_file: Path | None = None,
        resolver: CredentialResolver | None = None,
        heartbeat_seconds: int = 30,
        max_concurrent: int = 10,
        upload_batch_max_polls: int = 1000,
        upload_batch_max_bytes: int = 5 * 1024 * 1024,
        sleepless: bool = False,
        allowed_adapters: set[str] | None = None,
    ) -> None:
        self.edge_id = edge_id
        self.registry = registry
        self.client = client
        self.resolver = resolver or CredentialResolver()
        self.heartbeat_seconds = heartbeat_seconds
        self.max_concurrent = max_concurrent
        self.sleepless = sleepless
        self.spool_path = Path(spool_path)
        self.spool_path.mkdir(parents=True, exist_ok=True)
        self.spool = Spool(self.spool_path, limit_bytes=spool_limit_bytes)
        self.config = ConfigStore(
            self.spool_path / "config",
            edge_id=edge_id,
            known_adapters=allowed_adapters if allowed_adapters is not None else set(registry.keys()),
        )
        self.enroll_store = EnrollmentStore(
            self.spool_path / "certs",
            token=enrollment_token,
            token_file=enrollment_token_file,
        )
        if self.enroll_store.client_token():
            self.client.token = self.enroll_store.client_token()
        self.schedule = LocalSchedule(self.spool_path / "schedule.json")
        self.uploader = Uploader(
            self.spool,
            client,
            edge_id=edge_id,
            max_polls=upload_batch_max_polls,
            max_bytes=upload_batch_max_bytes,
            max_backoff_seconds=0.0 if sleepless else 60.0,
        )
        self._pending_tasks: list[dict[str, Any]] = []
        self._clock_offset_ms: float | None = None
        self._last_heartbeat_at: datetime | None = None
        self.central_down = False

    @classmethod
    def from_settings(cls, settings: Settings, registry: AdapterRegistry) -> "EdgeRuntime":
        if not settings.edge_id:
            raise SystemExit("SOH_EDGE_ID 가 없다")
        token = settings.resolved_secret("edge_enrollment_token") or settings.edge_enrollment_token
        token_file = None
        env_file = Path("/run/secrets/edge_enrollment_token")
        if not token and env_file.exists():
            token_file = env_file
        client = HttpxCentralClient(
            settings.central_url,
            timeout=float(settings.edge_upload_timeout_seconds),
        )
        return cls(
            edge_id=settings.edge_id,
            spool_path=settings.edge_spool_path,
            spool_limit_bytes=settings.edge_spool_limit_bytes,
            registry=registry,
            client=client,
            enrollment_token=token or None,
            enrollment_token_file=token_file,
            heartbeat_seconds=settings.edge_heartbeat_seconds,
            max_concurrent=settings.max_concurrent_polls,
        )

    def close(self) -> None:
        self.spool.close()

    async def aclose(self) -> None:
        self.close()
        closer = getattr(self.client, "aclose", None)
        if closer is not None:
            await closer()

    async def tick(self) -> TickStats:
        stats = TickStats(config_version=self.config.current_version)
        await self._ensure_enrolled(stats)
        await self._sync_config(stats)
        await self._collect(stats)
        await self._upload(stats)
        await self._heartbeat_and_tasks(stats)
        return stats

    async def _ensure_enrolled(self, stats: TickStats) -> None:
        if self.enroll_store.has_certificate() and self.client.token:
            stats.enrolled = True
            return
        token = self.enroll_store.peek_token()
        if not token:
            if not self.enroll_store.has_certificate():
                stats.errors.append("등록 Token 이 없고 인증서도 없다")
            else:
                stats.enrolled = True
                self.client.token = self.enroll_store.client_token()
            return
        try:
            bundle = await self.client.enroll(
                self.edge_id,
                token,
                agent_version=AGENT_VERSION,
                adapters=list(self.registry.keys()),
            )
        except CentralUnavailable as exc:
            self.central_down = True
            stats.central_down = True
            stats.errors.append(f"등록 실패: {exc}")
            return
        except CentralRejected as exc:
            self.enroll_store.take_token()
            self.enroll_store.discard_token_file()
            stats.errors.append(f"등록이 거절됐다: {exc}")
            logger.error("등록 Token 이 거절되어 버렸다", extra={"error": str(exc)})
            return
        self.enroll_store.save(bundle)
        self.enroll_store.take_token()
        self.enroll_store.discard_token_file()
        self.client.token = bundle.client_token
        stats.enrolled = True
        logger.info("중앙에 등록했다", extra={"edge_id": self.edge_id})

    async def _sync_config(self, stats: TickStats) -> None:
        try:
            incoming = await self.client.fetch_config(self.config.current_version)
        except CentralUnavailable as exc:
            self.central_down = True
            stats.central_down = True
            stats.errors.append(f"설정 동기 실패: {exc}")
            return
        if not incoming:
            stats.config_version = self.config.current_version
            return
        try:
            self.config.apply(incoming)
        except ConfigError as exc:
            stats.errors.append(str(exc))
            logger.error("설정을 적용하지 못했다", extra={"error": str(exc)})
        stats.config_version = self.config.current_version

    async def _collect(self, stats: TickStats) -> None:
        document = self.config.load()
        if not document:
            return
        results = await collect_due(
            document,
            self.schedule,
            self.registry,
            self.resolver,
            edge_id=self.edge_id,
            max_concurrent=self.max_concurrent,
            sleepless=self.sleepless,
        )
        stats.collected = len(results)
        for result in results:
            self.spool.append(result)
            stats.spooled += 1

    async def _upload(self, stats: TickStats) -> None:
        health = collect_health(spool_path=self.spool_path, clock_offset_ms=self._clock_offset_ms)
        report = await self.uploader.flush(
            config_version=self.config.current_version,
            edge_health=health,
        )
        stats.uploaded = int(report.get("uploaded") or 0)
        if report.get("deferred"):
            self.central_down = True
            stats.central_down = True
        else:
            self.central_down = False

    async def _heartbeat_and_tasks(self, stats: TickStats) -> None:
        now = datetime.now(timezone.utc)
        if self._last_heartbeat_at is not None:
            elapsed = (now - self._last_heartbeat_at).total_seconds()
            if elapsed < self.heartbeat_seconds and not self._pending_tasks:
                await self._run_pending_tasks(stats)
                return
        health = collect_health(spool_path=self.spool_path, clock_offset_ms=self._clock_offset_ms)
        payload = build_heartbeat(
            edge_id=self.edge_id,
            config_version=self.config.current_version,
            spool=self.spool,
            health=health,
            adapters=list(self.registry.keys()),
        )
        try:
            response = await self.client.heartbeat(payload)
        except CentralUnavailable as exc:
            self.central_down = True
            stats.central_down = True
            stats.errors.append(f"Heartbeat 실패: {exc}")
            return
        self._last_heartbeat_at = now
        self.central_down = False
        self._clock_offset_ms = clock_offset_ms(response.get("serverTime"), now=now)
        for task in response.get("tasks") or []:
            self._pending_tasks.append(task)
        await self._run_pending_tasks(stats)

    async def _run_pending_tasks(self, stats: TickStats) -> None:
        remaining: list[dict[str, Any]] = []
        for task in self._pending_tasks:
            task_type = str(task.get("type") or "")
            payload = task.get("payload") or {}
            if task_type == "poll_now" and payload.get("deviceId"):
                self.schedule.force(str(payload["deviceId"]))
            result = await execute_task(task, self.registry, self.resolver)
            task_id = str(task.get("id") or "")
            if not task_id:
                stats.tasks += 1
                continue
            try:
                await self.client.report_task(task_id, result)
                stats.tasks += 1
            except CentralUnavailable:
                remaining.append(task)
                self.central_down = True
                stats.central_down = True
                break
        self._pending_tasks = remaining
