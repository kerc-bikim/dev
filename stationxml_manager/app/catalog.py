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
        origin="seed",
        description=None,
    )


def _slug_part(value: str) -> str:
    parts: list[str] = []
    for char in value.strip():
        if char.isalnum() or char in "-_":
            parts.append(char)
        elif char.isspace():
            parts.append("_")
    slug = "".join(parts).strip("_")
    return slug or "EQ"


def suggest_custom_code(
    session: Session,
    kind: str,
    manufacturer: str,
    model: str,
    sample_rate: float | None = None,
) -> str:
    mid = f"{_slug_part(manufacturer)}_{_slug_part(model)}"
    suffix = ""
    if kind == "datalogger" and sample_rate is not None:
        rate = float(sample_rate)
        if rate.is_integer():
            suffix = f"_{int(rate)}sps"
        else:
            suffix = f"_{str(rate).replace('.', 'p')}sps"
    room = 64 - len("CUSTOM_") - len(suffix) - 3
    base = f"CUSTOM_{mid[: max(room, 1)].rstrip('_')}{suffix}"
    if get_by_code(session, kind, base) is None:
        return base
    index = 2
    while True:
        extra = f"_{index}"
        candidate = f"{base}{extra}"
        if len(candidate) > 64:
            candidate = f"{base[: 64 - len(extra)]}{extra}"
        if get_by_code(session, kind, candidate) is None:
            return candidate
        index += 1


def get_or_create_custom_equipment(
    session: Session,
    *,
    kind: str,
    manufacturer: str,
    model: str,
    sample_rate: float | None = None,
    code: str | None = None,
    description: str | None = None,
    nrl_keys: str | None = None,
) -> tuple[EquipmentCatalog, bool]:
    from .validation import validate_sample_rate

    if kind not in {"sensor", "datalogger"}:
        raise ValidationError("장비 종류는 sensor 또는 datalogger여야 합니다")
    manufacturer = (manufacturer or "").strip()
    model = (model or "").strip()
    if not manufacturer or not model:
        raise ValidationError("제조사와 모델은 필수입니다")
    if kind == "datalogger":
        if sample_rate is None:
            raise ValidationError("기록계 샘플링레이트는 필수입니다")
        validate_sample_rate(sample_rate)

    existing = find_by_manufacturer_model(
        session,
        kind,
        manufacturer,
        model,
        sample_rate if kind == "datalogger" else None,
    )
    if existing is not None:
        return existing, False

    code = (code or "").strip()
    if code:
        taken = get_by_code(session, kind, code)
        if taken is not None:
            raise ValidationError(f"이미 있는 장비 ID입니다: {code}")
    else:
        code = suggest_custom_code(session, kind, manufacturer, model, sample_rate)

    row = EquipmentCatalog(
        kind=kind,
        code=code,
        manufacturer=manufacturer,
        model=model,
        sample_rate=sample_rate if kind == "datalogger" else None,
        nrl_keys=str(nrl_keys).strip() if nrl_keys else None,
        origin="custom",
        description=(description or "").strip() or None,
    )
    session.add(row)
    session.flush()
    return row, True


def get_by_code(
    session: Session, kind: str, code: str | None
) -> EquipmentCatalog | None:
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
        return None
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
            allowed = [
                r.code for r in session.query(EquipmentCatalog).filter_by(kind="sensor")
            ]
            raise ValidationError(
                f"{prefix}알 수 없는 센서ID '{sensor_id}'. 허용: {', '.join(allowed) or '(없음)'}"
            )
    if datalogger_id:
        logger = get_by_code(session, "datalogger", datalogger_id)
        if logger is None:
            allowed = [
                r.code
                for r in session.query(EquipmentCatalog).filter_by(kind="datalogger")
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
