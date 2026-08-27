"""시계열 적재 경로.

InfluxDB 가 잠시 멈춰도 수집은 계속돼야 하고, 그동안의 데이터를 잃지 않아야 한다.
그래서 쓰기 실패분을 한도 있는 버퍼에 담아 다음 시도에 함께 보낸다.

한도를 두는 이유는 분명하다. InfluxDB 가 장시간 죽어 있을 때 버퍼가 무한히 자라면
수집기가 메모리로 죽는다. 그러면 데이터를 더 크게 잃는다. 오래된 것부터 버리고,
버린 사실을 로그와 지표로 남긴다.
"""
from __future__ import annotations

import abc
from collections import deque

from app.observability.logging import get_logger

from .points import PointSpec

logger = get_logger("app.influx", role="collector")


class MetricSink(abc.ABC):
    """적재 대상. 시험에서는 메모리 구현으로 바꿔 끼운다."""

    @abc.abstractmethod
    def write(self, points: list[PointSpec]) -> bool:
        """성공하면 True. 실패는 예외가 아니라 False 로 알린다."""

    def close(self) -> None:  # pragma: no cover - 기본 구현은 할 일이 없다
        return None


class InMemoryMetricSink(MetricSink):
    """시험·개발용. 적재된 Point 를 그대로 들고 있는다."""

    def __init__(self, *, fail: bool = False) -> None:
        self.points: list[PointSpec] = []
        self.fail = fail
        self.write_calls = 0

    def write(self, points: list[PointSpec]) -> bool:
        self.write_calls += 1
        if self.fail:
            return False
        self.points.extend(points)
        return True

    def fields_of(self, measurement: str) -> list[dict]:
        return [point.fields for point in self.points if point.measurement == measurement]

    def measurements(self) -> set[str]:
        return {point.measurement for point in self.points}


class BufferedMetricSink(MetricSink):
    """쓰기 실패분을 모아 다음에 다시 시도하는 감싸기.

    수집 루프는 이 객체만 보고, InfluxDB 가 살았는지 죽었는지 신경 쓰지 않는다.
    """

    def __init__(self, inner: MetricSink, *, max_buffered_points: int = 200_000) -> None:
        self.inner = inner
        self.max_buffered_points = max_buffered_points
        self._buffer: deque[PointSpec] = deque()
        self.dropped_points = 0
        self.failed_writes = 0

    @property
    def buffered_points(self) -> int:
        return len(self._buffer)

    def write(self, points: list[PointSpec]) -> bool:
        pending = list(self._buffer) + list(points)
        if not pending:
            return True

        if self.inner.write(pending):
            self._buffer.clear()
            return True

        self.failed_writes += 1
        self._buffer.clear()
        self._buffer.extend(pending)
        self._trim()
        logger.warning(
            "시계열 적재 실패. 버퍼에 보관한다",
            extra={
                "buffered_points": self.buffered_points,
                "dropped_points": self.dropped_points,
            },
        )
        return False

    def flush(self) -> bool:
        return self.write([])

    def _trim(self) -> None:
        overflow = len(self._buffer) - self.max_buffered_points
        if overflow <= 0:
            return
        for _ in range(overflow):
            self._buffer.popleft()
        self.dropped_points += overflow
        # 버린 사실을 숨기지 않는다. 데이터가 비어 있는 이유를 나중에 설명할 수 있어야 한다.
        logger.error(
            "버퍼 한도를 넘어 오래된 지점을 버렸다",
            extra={"dropped_points": self.dropped_points, "overflow": overflow},
        )

    def close(self) -> None:
        self.inner.close()


class InfluxMetricSink(MetricSink):
    """InfluxDB 2.x 적재.

    influxdb-client 를 이 클래스 안에서만 import 한다. 나머지 코드가 특정 클라이언트에
    묶이지 않게 하려는 것이다.
    """

    def __init__(self, url: str, token: str, org: str, bucket: str, *, timeout_ms: int = 10_000) -> None:
        from influxdb_client import InfluxDBClient
        from influxdb_client.client.write_api import SYNCHRONOUS

        self.bucket = bucket
        self.org = org
        self._client = InfluxDBClient(url=url, token=token, org=org, timeout=timeout_ms)
        self._write_api = self._client.write_api(write_options=SYNCHRONOUS)

    def write(self, points: list[PointSpec]) -> bool:
        if not points:
            return True

        from influxdb_client import Point, WritePrecision

        payload = []
        for spec in points:
            point = Point(spec.measurement)
            for key, value in spec.tags.items():
                point = point.tag(key, value)
            for key, value in spec.fields.items():
                point = point.field(key, value)
            if spec.timestamp is not None:
                point = point.time(spec.timestamp, WritePrecision.NS)
            payload.append(point)

        try:
            self._write_api.write(bucket=self.bucket, org=self.org, record=payload)
            return True
        except Exception as exc:  # noqa: BLE001 - 적재 실패로 수집을 멈추지 않는다
            logger.error("InfluxDB 쓰기 실패", extra={"error": str(exc), "points": len(payload)})
            return False

    def close(self) -> None:
        self._client.close()
