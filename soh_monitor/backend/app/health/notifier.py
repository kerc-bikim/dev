"""알림 발신.

중복 억제를 여기서 하지 않는다. 알림은 **Incident 상태 전이에서만** 나오고, 전이는
DB 에 한 번만 기록되므로 구조적으로 중복이 없다. 억제 로직을 따로 두면 그 로직이
또 다른 버그의 자리가 된다.
"""
from __future__ import annotations

import abc
from dataclasses import dataclass
from datetime import datetime

from app.domain.enums import Severity
from app.observability.logging import get_logger

logger = get_logger("app.health.notifier")


@dataclass(frozen=True)
class Notification:
    kind: str  # OPENED | ESCALATED | RESOLVED | ACKNOWLEDGED
    incident_id: str
    device_id: str
    station_code: str
    category: str
    metric_key: str | None
    dimension_value: str
    severity: Severity
    title: str
    occurred_at: datetime
    detail: dict | None = None


class Notifier(abc.ABC):
    @abc.abstractmethod
    def send(self, notification: Notification) -> None: ...


class LoggingNotifier(Notifier):
    """MVP 기본. 이메일·Slack 연동은 Grafana Alerting 으로 처리한다."""

    def send(self, notification: Notification) -> None:
        level = logger.warning if notification.kind != "RESOLVED" else logger.info
        level(
            f"장애 {notification.kind}: {notification.title}",
            extra={
                "kind": notification.kind,
                "incident_id": notification.incident_id,
                "device_id": notification.device_id,
                "station_code": notification.station_code,
                "category": notification.category,
                "metric_key": notification.metric_key,
                "severity": notification.severity.value,
            },
        )


class CollectingNotifier(Notifier):
    """시험용. 발신된 알림을 모아 둔다."""

    def __init__(self) -> None:
        self.sent: list[Notification] = []

    def send(self, notification: Notification) -> None:
        self.sent.append(notification)

    def kinds(self) -> list[str]:
        return [notification.kind for notification in self.sent]
