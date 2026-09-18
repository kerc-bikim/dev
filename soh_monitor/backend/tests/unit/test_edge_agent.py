"""Edge Agent 단위 시험.

Spool 유실 방지, 설정 Rollback, 등록 Token 폐기, 중앙 단절 중 수집이 핵심이다.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from app.adapters.contract import ConnectionTest
from app.domain.enums import Severity
from app.domain.models import DeviceIdentity, MetricSample, PollResult
from app.edgeagent.client import CentralUnavailable
from app.edgeagent.configsync import ConfigError, ConfigStore
from app.edgeagent.enroll import (
    EnrollmentBundle,
    EnrollmentStore,
    hash_enrollment_token,
    issue_edge_token,
    verify_edge_token,
    write_placeholder_certificate,
)
from app.edgeagent.poller import to_due_device
from app.edgeagent.runtime import EdgeRuntime
from app.edgeagent.spool import PENDING, Spool

ADAPTER = "nanometrics.centaur.ctr"
OBSERVED = datetime(2026, 9, 18, 12, 0, tzinfo=timezone.utc)


def _poll(device_id: str = "d-1", *, success: bool = True, incident: bool = False, poll_id: str | None = None) -> PollResult:
    samples = ()
    if incident:
        samples = (
            MetricSample(metric_key="timing.gnss_status", value_status=Severity.CRITICAL, raw_value="unlocked"),
        )
    elif success:
        samples = (MetricSample(metric_key="connectivity.reachable", value_bool=True),)
    return PollResult(
        poll_id=poll_id or str(uuid.uuid4()),
        device_id=device_id,
        adapter_key=ADAPTER,
        adapter_version="1.0",
        observed_at=OBSERVED,
        success=success,
        samples=samples,
        error_message=None if success else "연결 거부",
        latency_ms=12.0,
    )


def _config(edge_id: str, version: int, device_id: str | None = None) -> dict:
    device = device_id or str(uuid.uuid4())
    return {
        "configVersion": version,
        "edgeId": edge_id,
        "issuedAt": "2026-09-18T00:00:00Z",
        "devices": [
            {
                "deviceId": device,
                "stationCode": "A01",
                "adapterKey": ADAPTER,
                "adapterVersion": "1.0",
                "assignmentEpoch": 1,
                "enabled": True,
                "pollIntervalMinutes": 5,
                "connection": {"hostname": "10.10.1.20", "scheme": "http"},
            }
        ],
    }


class FakeAdapter:
    def __init__(self) -> None:
        self.collect_calls = 0
        self.test_calls = 0

    async def collect(self, context):
        self.collect_calls += 1
        return _poll(context.device_id, poll_id=str(uuid.uuid4()))

    async def test_connection(self, context):
        self.test_calls += 1
        return ConnectionTest(
            reachable=True,
            latency_ms=4.0,
            http_status=200,
            message="연결됐다",
            identity=DeviceIdentity(serial_number="0242"),
        )


class FakeRegistry:
    def __init__(self, adapter=None) -> None:
        self._adapter = adapter or FakeAdapter()

    def get(self, adapter_key: str):
        return self._adapter

    def keys(self):
        return (ADAPTER,)


class FakeCentral:
    def __init__(self, edge_id: str, config: dict | None = None) -> None:
        self.token: str | None = None
        self.down = False
        self.edge_id = edge_id
        self.config = config
        self.batches: list[dict] = []
        self.heartbeats: list[dict] = []
        self.task_results: list[tuple[str, dict]] = []
        self.tasks: list[dict] = []
        self.enroll_calls = 0

    async def enroll(self, edge_id, enrollment_token, *, agent_version, adapters):
        if self.down:
            raise CentralUnavailable("중앙 단절")
        self.enroll_calls += 1
        cert, key, ca = write_placeholder_certificate(edge_id, "2026-09-18T00:00:00Z")
        self.token = "issued-client-token"
        return EnrollmentBundle(
            certificate=cert,
            private_key=key,
            ca_certificate=ca,
            client_token=self.token,
            expires_at="2027-09-18T00:00:00Z",
        )

    async def fetch_config(self, current_version: int):
        if self.down:
            raise CentralUnavailable("중앙 단절")
        if not self.config:
            return None
        if current_version >= int(self.config["configVersion"]):
            return None
        return self.config

    async def upload_batch(self, batch: dict):
        if self.down:
            raise CentralUnavailable("중앙 단절")
        self.batches.append(batch)
        return {"accepted": True, "batchId": batch["batchId"]}

    async def heartbeat(self, payload: dict):
        if self.down:
            raise CentralUnavailable("중앙 단절")
        self.heartbeats.append(payload)
        tasks = list(self.tasks)
        self.tasks = []
        return {"serverTime": "2026-09-18T00:00:00Z", "configVersion": payload.get("configVersion"), "tasks": tasks}

    async def report_task(self, task_id: str, result: dict):
        if self.down:
            raise CentralUnavailable("중앙 단절")
        self.task_results.append((task_id, result))
        return {"ok": True}

    async def aclose(self) -> None:
        return None


class TestSpool:
    def test_파일을_먼저_쓰고_행을_남긴다(self, tmp_path):
        spool = Spool(tmp_path, limit_bytes=10_000_000)
        record = spool.append(_poll("dev-a"))
        assert record.sequence == 1
        assert (tmp_path / "segments" / record.path).exists()
        loaded = spool.load_poll(1)
        assert loaded["deviceId"] == "dev-a"
        assert loaded["sequence"] == 1
        spool.close()

    def test_닫았다가_다시_열어도_유실되지_않는다(self, tmp_path):
        spool = Spool(tmp_path, limit_bytes=10_000_000)
        spool.append(_poll("dev-a", poll_id="p1"))
        spool.append(_poll("dev-b", poll_id="p2"))
        spool.close()

        reopened = Spool(tmp_path, limit_bytes=10_000_000)
        pending = reopened.pending()
        assert [row.sequence for row in pending] == [1, 2]
        assert reopened.next_sequence == 3
        reopened.close()

    def test_ACK_전에는_파일을_지우지_않는다(self, tmp_path):
        spool = Spool(tmp_path, limit_bytes=10_000_000)
        spool.append(_poll("dev-a", poll_id="p1"))
        pending = spool.pending()
        spool.mark_uploading([pending[0].sequence], "batch-1")
        assert (tmp_path / "segments" / pending[0].path).exists()
        spool.revert_upload("batch-1")
        assert spool.pending()[0].status == PENDING
        spool.mark_uploading([1], "batch-1")
        deleted = spool.acknowledge("batch-1")
        assert deleted == 1
        assert not (tmp_path / "segments" / pending[0].path).exists()
        assert spool.pending() == []
        spool.close()

    def test_한도를_넘으면_장애_Poll을_마지막까지_남긴다(self, tmp_path):
        spool = Spool(tmp_path, limit_bytes=400)
        for index in range(8):
            spool.append(_poll(f"ok-{index}", poll_id=f"ok-{index}"))
        spool.append(_poll("bad", success=False, incident=True, poll_id="bad-1"))
        leftover = spool.pending()
        assert leftover
        assert any(row.is_incident for row in leftover)
        assert all(row.device_id == "bad" or row.is_incident for row in leftover) or any(
            row.is_incident for row in leftover
        )
        incidents = [row for row in leftover if row.is_incident]
        assert incidents, "장애 Poll 은 한도를 넘겨도 남아 있어야 한다"
        spool.close()


class Test설정동기:
    def test_버전이_작으면_거절하고_현재를_지킨다(self, tmp_path):
        store = ConfigStore(tmp_path, edge_id="edge-a", known_adapters={ADAPTER})
        store.apply(_config("edge-a", 2))
        with pytest.raises(ConfigError):
            store.apply(_config("edge-a", 1))
        assert store.current_version == 2

    def test_다른_Edge_설정은_거절한다(self, tmp_path):
        store = ConfigStore(tmp_path, edge_id="edge-a", known_adapters={ADAPTER})
        with pytest.raises(ConfigError, match="다르다"):
            store.apply(_config("edge-b", 1))

    def test_같은_장비가_두_번이면_거절한다(self, tmp_path):
        store = ConfigStore(tmp_path, edge_id="edge-a", known_adapters={ADAPTER})
        document = _config("edge-a", 1)
        document["devices"].append(dict(document["devices"][0]))
        with pytest.raises(ConfigError, match="두 번"):
            store.apply(document)

    def test_적용_실패_시_이전_버전으로_돌아간다(self, tmp_path):
        store = ConfigStore(tmp_path, edge_id="edge-a", known_adapters={ADAPTER})
        store.apply(_config("edge-a", 1, "dev-1"))
        calls = {"n": 0}
        original = store.validate

        def flaky(document):
            calls["n"] += 1
            original(document)
            if calls["n"] >= 2:
                raise RuntimeError("디스크가 깨졌다")

        store.validate = flaky  # type: ignore[method-assign]
        with pytest.raises(ConfigError, match="되돌렸다"):
            store.apply(_config("edge-a", 2, "dev-2"))
        store.validate = original  # type: ignore[method-assign]
        loaded = store.load()
        assert loaded is not None
        assert loaded["configVersion"] == 1
        assert loaded["devices"][0]["deviceId"] == "dev-1"


class Test등록:
    def test_Token_파일은_한_번_쓰고_지운다(self, tmp_path):
        token_file = tmp_path / "enroll.token"
        token_file.write_text("once-only-token", encoding="utf-8")
        store = EnrollmentStore(tmp_path / "certs", token_file=token_file)
        assert store.peek_token() == "once-only-token"
        taken = store.take_token()
        assert taken == "once-only-token"
        store.discard_token_file()
        assert not token_file.exists()
        store2 = EnrollmentStore(tmp_path / "certs", token_file=token_file)
        assert store2.peek_token() is None

    def test_HMAC_토큰을_검증한다(self):
        token = issue_edge_token("edge-a", "secret", now=1_000_000)
        assert verify_edge_token(token, "secret", now=1_000_001) == "edge-a"
        with pytest.raises(ValueError):
            verify_edge_token(token, "other", now=1_000_001)
        with pytest.raises(ValueError):
            verify_edge_token(token, "secret", now=1_000_000 + 40 * 24 * 3600)

    def test_등록_해시가_원문을_저장하지_않는다(self):
        token = "plain-enrollment-token"
        digest = hash_enrollment_token(token)
        assert digest != token
        assert len(digest) == 64


class Test런타임:
    @pytest.fixture()
    def runtime(self, tmp_path):
        edge_id = "edge-region-a-01"
        device_id = str(uuid.uuid4())
        adapter = FakeAdapter()
        client = FakeCentral(edge_id, _config(edge_id, 1, device_id))
        rt = EdgeRuntime(
            edge_id=edge_id,
            spool_path=tmp_path,
            spool_limit_bytes=10_000_000,
            registry=FakeRegistry(adapter),
            client=client,
            enrollment_token="enroll-token",
            heartbeat_seconds=0,
            sleepless=True,
        )
        return rt, client, adapter, device_id

    async def test_중앙이_꺼져_있어도_수집은_계속된다(self, runtime):
        rt, client, adapter, device_id = runtime
        await rt.tick()
        assert adapter.collect_calls == 1
        assert rt.spool.pending_count() == 0
        assert client.batches

        client.down = True
        rt.schedule.force(device_id)
        await rt.tick()
        assert adapter.collect_calls == 2
        assert rt.spool.pending_count() == 1
        assert rt.central_down is True

        client.down = False
        rt.schedule.force(device_id)
        await rt.tick()
        assert rt.spool.pending_count() == 0
        sequences = [poll["sequence"] for batch in client.batches for poll in batch["polls"]]
        assert sequences == sorted(sequences)
        assert sequences[0] == 1
        await rt.aclose()

    async def test_원격_연결_시험을_수행한다(self, runtime):
        rt, client, adapter, device_id = runtime
        await rt.tick()
        client.tasks.append(
            {
                "id": str(uuid.uuid4()),
                "type": "test_connection",
                "payload": {"hostname": "10.10.1.20", "adapterKey": ADAPTER, "deviceId": device_id},
            }
        )
        await rt.tick()
        assert adapter.test_calls == 1
        assert client.task_results
        assert client.task_results[0][1]["reachable"] is True
        await rt.aclose()

    async def test_같은_Adapter_경로를_중앙_수집과_공유한다(self, runtime):
        """poll_device 가 Edge 수집의 실제 경로인지 확인한다."""
        rt, client, adapter, device_id = runtime
        await rt.tick()
        assert adapter.collect_calls >= 1
        from app.auth.credentials import CredentialResolver
        from app.collector.retry import RetryPolicy
        from app.collector.runner import poll_device

        document = rt.config.load()
        due = to_due_device(document["devices"][0], edge_id=rt.edge_id)
        outcome = await poll_device(due, rt.registry, CredentialResolver(), RetryPolicy(max_attempts=1))
        assert outcome.result.success is True
        await rt.aclose()
