from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from sqlalchemy.orm import Session

from .errors import ValidationError
from .models import Channel, EquipmentCatalog
from .validation import sample_rates_match


def catalog_yaml_path() -> Path:
    return Path(__file__).resolve().parent.parent / "equipment_catalog.yaml"


def load_seed_yaml(path: Path | None = None) -> dict[str, list[dict[str, Any]]]:
    path = path or catalog_yaml_path()
    with path.open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    return {
        "sensors": list(data.get("sensors") or []),
        "dataloggers": list(data.get("dataloggers") or []),
    }


def seed_catalog(session: Session, path: Path | None = None) -> None:
    if session.query(EquipmentCatalog).first() is not None:
        return
    data = load_seed_yaml(path)
    for item in data["sensors"]:
        session.add(_item_to_row("sensor", item))
    for item in data["dataloggers"]:
        session.add(_item_to_row("datalogger", item))
    session.commit()


def _item_to_row(kind: str, item: dict[str, Any]) -> EquipmentCatalog:
    return EquipmentCatalog(
        kind=kind,
        code=str(item["id"]).strip(),
        manufacturer=str(item.get("manufacturer") or "").strip(),
        model=str(item.get("model") or "").strip(),
        sample_rate=item.get("sample_rate"),
        nrl_keys=(str(item["nrl_keys"]).strip() if item.get("nrl_keys") else None),
    )


def get_by_code(session: Session, kind: str, code: str | None) -> EquipmentCatalog | None:
    if not code:
        return None
    return (
        session.query(EquipmentCatalog)
        .filter(EquipmentCatalog.kind == kind, EquipmentCatalog.code == code)
        .one_or_none()
    )


def find_by_manufacturer_model(
    session: Session,
    kind: str,
    manufacturer: str | None,
    model: str | None,
    sample_rate: float | None = None,
) -> EquipmentCatalog | None:
    if not manufacturer or not model:
        return None
    rows = session.query(EquipmentCatalog).filter(EquipmentCatalog.kind == kind).all()
    matches = [
        row
        for row in rows
        if row.manufacturer.strip().lower() == manufacturer.strip().lower()
        and row.model.strip().lower() == model.strip().lower()
    ]
    if not matches:
        return None
    if sample_rate is not None:
        for row in matches:
            if sample_rates_match(sample_rate, row.sample_rate):
                return row
    return matches[0]


def catalog_map(session: Session) -> dict[str, dict[str, EquipmentCatalog]]:
    result: dict[str, dict[str, EquipmentCatalog]] = {"sensor": {}, "datalogger": {}}
    for row in session.query(EquipmentCatalog).all():
        result[row.kind][row.code] = row
    return result


def assert_equipment_ids(
    session: Session,
    sensor_id: str | None,
    datalogger_id: str | None,
    sample_rate: float,
    row: int | None = None,
) -> list[str]:
    warnings: list[str] = []
    prefix = f"{row}행: " if row is not None else ""
    if sensor_id:
        sensor = get_by_code(session, "sensor", sensor_id)
        if sensor is None:
            allowed = [r.code for r in session.query(EquipmentCatalog).filter_by(kind="sensor")]
            raise ValidationError(
                f"{prefix}알 수 없는 센서ID '{sensor_id}'. 허용: {', '.join(allowed) or '(없음)'}"
            )
    if datalogger_id:
        logger = get_by_code(session, "datalogger", datalogger_id)
        if logger is None:
            allowed = [
                r.code for r in session.query(EquipmentCatalog).filter_by(kind="datalogger")
            ]
            raise ValidationError(
                f"{prefix}알 수 없는 기록계ID '{datalogger_id}'. 허용: {', '.join(allowed) or '(없음)'}"
            )
        if not sample_rates_match(sample_rate, logger.sample_rate):
            raise ValidationError(
                f"{prefix}기록계 '{datalogger_id}'의 샘플링레이트({logger.sample_rate})와 "
                f"채널 샘플링레이트({sample_rate})가 다릅니다"
            )
    return warnings


def catalog_in_use(session: Session, kind: str, code: str) -> list[str]:
    q = session.query(Channel)
    if kind == "sensor":
        q = q.filter(Channel.sensor_id == code)
    else:
        q = q.filter(Channel.datalogger_id == code)
    used: list[str] = []
    for ch in q.all():
        net = ch.station.network.code
        loc = ch.location or "--"
        used.append(f"{net}.{ch.station.code}.{loc}.{ch.channel}")
    return used
