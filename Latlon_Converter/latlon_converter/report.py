"""결과 출력(표/CSV/JSON)."""

from __future__ import annotations

import csv
import json
from dataclasses import asdict
from typing import Iterable, TextIO

from .models import OUTPUT_COLUMNS, OWNER_NAME_NOTICE, LookupResult

# 한 화면에 보여 줄 항목과 표시 순서.
_DETAIL_FIELDS: tuple[str, ...] = (
    "지번주소",
    "도로명주소",
    "PNU",
    "법정동코드",
    "법정동명",
    "대장구분",
    "지목",
    "면적(㎡)",
    "소유구분",
    "공유인수",
    "소유권변동원인",
    "소유권변동일자",
    "개별공시지가(원/㎡)",
    "공시기준연도",
    "용도지역1",
    "용도지역2",
    "토지이용상황",
)


def _display_width(text: str) -> int:
    """한글을 두 칸으로 세어 표 정렬을 맞춘다."""
    return sum(2 if ord(char) > 0x1100 else 1 for char in text)


def _pad(text: str, width: int) -> str:
    return text + " " * max(width - _display_width(text), 0)


def render_table(result: LookupResult) -> str:
    """사람이 읽는 세로 표."""
    row = result.to_row()
    lines: list[str] = []

    header = f"좌표 {row['입력위도']}, {row['입력경도']}" if row["입력위도"] else f"PNU {row['PNU']}"
    lines.append(header)
    lines.append("-" * 56)

    if not result.found:
        lines.append("필지를 찾지 못했습니다.")
        for warning in result.warnings:
            lines.append(f"  · {warning}")
        return "\n".join(lines)

    label_width = max(_display_width(name) for name in _DETAIL_FIELDS)
    for name in _DETAIL_FIELDS:
        value = row.get(name, "")
        if value:
            lines.append(f"{_pad(name, label_width)}  {value}")

    lines.append("-" * 56)
    lines.append(f"소유자 성명  {OWNER_NAME_NOTICE}")
    lines.append(f"등기 열람    {row['등기열람URL']}")
    for warning in result.warnings:
        lines.append(f"[알림] {warning}")
    return "\n".join(lines)


def _mask_key(api_key: str) -> str:
    if not api_key:
        return "없음"
    return f"설정됨 ({api_key[:4]}…, {len(api_key)}자)"


def render_connection_check(settings, check) -> str:
    """`check` 명령의 점검 결과를 사람이 읽는 형태로 만든다."""
    bundle = check.ca_bundle if isinstance(check.ca_bundle, str) else "(기본 신뢰 저장소)"
    rows = [
        ("provider", settings.provider),
        ("VWORLD_API_KEY", _mask_key(settings.api_key)),
        ("VWORLD_DOMAIN", settings.domain or "(설정 없음)"),
        ("LATLON_CA_BUNDLE", bundle),
    ]
    verified = {True: "성공", False: "실패", None: "확인 못 함 (연결 실패)"}[check.tls_verified]
    results: list[tuple[str, str]] = [("TLS 인증서 검증", verified)]
    if check.http_status is not None:
        results.append(("HTTP 상태", str(check.http_status)))
    results.append(("점검 단계", check.status))

    label_width = max(_display_width(name) for name, _ in [*rows, *results])

    lines = ["설정", "-" * 56]
    lines.extend(f"{_pad(name, label_width)}  {value}" for name, value in rows)
    lines.extend(["", "점검 결과", "-" * 56])
    lines.extend(f"{_pad(name, label_width)}  {value}" for name, value in results)
    if check.detail:
        lines.extend(["", check.detail])
    if check.hint:
        lines.extend(["", check.hint])
    return "\n".join(lines)


def render_json(results: LookupResult | list[LookupResult]) -> str:
    items = results if isinstance(results, list) else [results]
    payload = [
        {
            "lat": item.lat,
            "lon": item.lon,
            "found": item.found,
            "parcel": asdict(item.parcel) if item.parcel else None,
            "ledger": asdict(item.ledger) if item.ledger else None,
            "characteristics": asdict(item.characteristics) if item.characteristics else None,
            "owner_name_notice": OWNER_NAME_NOTICE,
            "registry_url": item.registry_url,
            "warnings": item.warnings,
        }
        for item in items
    ]
    if not isinstance(results, list):
        return json.dumps(payload[0], ensure_ascii=False, indent=2)
    return json.dumps(payload, ensure_ascii=False, indent=2)


def write_csv(stream: TextIO, rows: Iterable[tuple[dict[str, str], LookupResult]]) -> int:
    """조회 결과를 CSV로 쓴다.

    각 항목은 (입력에서 그대로 넘길 컬럼, 결과) 쌍이며, 넘겨받은 컬럼이
    결과 컬럼 앞에 붙는다. 쓴 행 수를 돌려준다.
    """
    items = list(rows)
    leading: list[str] = []
    for passthrough, _ in items:
        for name in passthrough:
            if name not in leading and name not in OUTPUT_COLUMNS:
                leading.append(name)

    writer = csv.DictWriter(stream, fieldnames=[*leading, *OUTPUT_COLUMNS], extrasaction="ignore")
    writer.writeheader()
    for passthrough, result in items:
        row = {name: "" for name in leading}
        row.update(passthrough)
        row.update(result.to_row())
        writer.writerow(row)
    return len(items)
