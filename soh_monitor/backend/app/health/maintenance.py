"""유지보수 시간 판정.

유지보수 중에는 알림을 만들지 않는다. 다만 상태를 '정상' 으로 위조하지 않고
MAINTENANCE 로 기록한다. 나중에 "그 시각에 왜 데이터가 없었나" 를 설명할 수 있어야 한다.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import MaintenanceWindow


def in_maintenance(
    session: Session,
    *,
    device_id: uuid.UUID,
    station_id: uuid.UUID | None = None,
    edge_id: uuid.UUID | None = None,
    region_id: uuid.UUID | None = None,
    now: datetime,
) -> MaintenanceWindow | None:
    """해당 장비를 덮는 유지보수 구간을 찾는다.

    범위는 좁은 것부터 넓은 것까지 함께 본다. 관측소 전체 점검과 장비 하나 점검이
    각각 등록될 수 있다.
    """
    scopes: list[tuple[str, uuid.UUID | None]] = [
        ("device", device_id),
        ("station", station_id),
        ("edge", edge_id),
        ("region", region_id),
        ("global", None),
    ]

    windows = session.scalars(
        select(MaintenanceWindow).where(
            MaintenanceWindow.starts_at <= now,
            MaintenanceWindow.ends_at >= now,
        )
    ).all()

    for scope, identifier in scopes:
        for window in windows:
            if window.scope != scope:
                continue
            if scope == "global":
                return window
            if identifier is not None and window.scope_id == identifier:
                return window
    return None
