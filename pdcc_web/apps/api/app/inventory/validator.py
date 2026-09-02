"""공식 StationXML 검증 (S5).

JAR 가 있으면 sidecar 로 위임하고, 없어도 410/412 등 핵심 규칙은 Python 으로
같은 번호를 붙인다. 즉시 검증(E_LAT 등)과 번호를 섞지 않는다.
"""

from __future__ import annotations

import logging
import re
import subprocess
import tempfile
from pathlib import Path

from lxml import etree

from ..config import settings
from .xmlbuild import (
    InventoryError,
    _float,
    _issue,
    _overlaps,
    _parse_time,
    validate_inventory,
)
from .xmlutil import child_text, parse_root, qname

log = logging.getLogger("pdcc.validator")

QUICK_SKIP_IN_FULL = {"E_EPOCH_OVERLAP"}
SOH_TYPES = {"HEALTH", "FLAG", "MAINTENANCE"}
REL_TOL = 0.01

OFFICIAL = {
    "XSD": "XML 구조가 표준과 다릅니다",
    "111": "같은 관측소의 기간이 겹칩니다",
    "112": "네트워크 시작·종료를 넓히세요",
    "211": "같은 채널의 기간이 겹칩니다",
    "305": "샘플링을 넣거나 응답을 제거하세요",
    "401": "응답 단계 번호가 1부터 연속이 아닙니다",
    "410": "감도를 재계산하세요",
    "411": "감도 주파수를 낮추세요",
    "412": "전체 감도가 단계 게인 곱과 다릅니다",
    "413": "응답 단계를 확인하세요",
    "415": "SOH/가속도 다항식 응답을 확인하세요",
    "416": "감도를 추가하세요",
    "421": "데이터로거 샘플링을 맞추세요",
    "422": "NRL 캐스케이드를 다시 적용하세요",
}

_SIDECAR_RE = re.compile(
    r"(?P<lvl>ERROR|WARNING|WARN)?[^0-9]{0,24}(?P<code>\d{3})\b",
    re.IGNORECASE,
)


def xml_filename(network: str, issues: list[dict]) -> str:
    suffix = "_unvalidated" if has_errors(issues) else ""
    return f"{network}{suffix}.xml"


def has_errors(issues: list[dict]) -> bool:
    return any(row.get("level") == "error" for row in issues)


def summarize(
    issues: list[dict],
    *,
    xml_source: str,
    mode: str,
    network: str,
) -> dict:
    errors = [row for row in issues if row.get("level") == "error"]
    warnings = [row for row in issues if row.get("level") == "warning"]
    return {
        "issues": issues,
        "source": xml_source,
        "mode": mode,
        "error_count": len(errors),
        "warning_count": len(warnings),
        "can_export_seed": len(errors) == 0,
        "filename": xml_filename(network, issues),
        "engine": _engine_name(),
    }


def validate_project(
    xml: str,
    network: str,
    project_id: int,
    *,
    mode: str = "quick",
) -> list[dict]:
    if mode not in {"quick", "full"}:
        raise InventoryError("mode는 quick 또는 full 이어야 합니다", 400, "E_MODE")
    quick = validate_inventory(xml, network, project_id)
    if mode == "quick":
        return quick
    official = official_validate(xml, network, project_id)
    sidecar = run_sidecar(xml)
    merged: list[dict] = [
        row for row in quick if row.get("code") not in QUICK_SKIP_IN_FULL
    ]
    seen = {(row.get("code"), row.get("path"), row.get("nslc")) for row in merged}
    for row in official + sidecar:
        key = (row.get("code"), row.get("path"), row.get("nslc"))
        if key in seen:
            continue
        seen.add(key)
        merged.append(row)
    return merged


def official_validate(xml: str, network: str, project_id: int) -> list[dict]:
    issues: list[dict] = []
    try:
        root = parse_root(xml)
    except etree.XMLSyntaxError:
        return [
            _off(
                "XSD",
                "XML 구조가 표준과 다릅니다",
                network,
                "xml",
                None,
                None,
                None,
            )
        ]
    version = root.get("schemaVersion") or ""
    if version and version != "1.2":
        issues.append(
            _off("XSD", "schemaVersion 은 1.2 여야 합니다", network, "xml", None, None, None)
        )
    net = None
    for node in root.findall(qname("Network")):
        if node.get("code") == network:
            net = node
            break
    if net is None:
        return issues
    net_start = net.get("startDate") or ""
    net_end = net.get("endDate")
    stations = list(net.findall(qname("Station")))
    for i, sta in enumerate(stations):
        code = sta.get("code") or ""
        start = sta.get("startDate") or ""
        prefix = f"{code}#{start}"
        if net_start:
            try:
                if _outside(start, sta.get("endDate"), net_start, net_end):
                    issues.append(
                        _off("112", OFFICIAL["112"], prefix, "start", code, start, None)
                    )
            except InventoryError:
                pass
        for other in stations[i + 1 :]:
            if other.get("code") != code:
                continue
            try:
                overlap = _overlaps(
                    start, sta.get("endDate"), other.get("startDate", ""), other.get("endDate")
                )
            except InventoryError:
                overlap = False
            if overlap:
                issues.append(
                    _off("111", OFFICIAL["111"], prefix, "start", code, start, None)
                )
        channels = list(sta.findall(qname("Channel")))
        for j, cha in enumerate(channels):
            issues.extend(_channel_official(sta, cha, code, start, prefix))
            loc = cha.get("locationCode") or ""
            cha_code = cha.get("code") or ""
            nslc = f"{loc}.{cha_code}" if loc else cha_code
            cha_prefix = f"{prefix}/{nslc}"
            for other in channels[j + 1 :]:
                if (other.get("locationCode") or "") != loc or (other.get("code") or "") != cha_code:
                    continue
                try:
                    overlap = _overlaps(
                        cha.get("startDate") or start,
                        cha.get("endDate"),
                        other.get("startDate") or start,
                        other.get("endDate"),
                    )
                except InventoryError:
                    overlap = False
                if overlap:
                    issues.append(
                        _off("211", OFFICIAL["211"], cha_prefix, "start", code, start, nslc)
                    )
    return issues


def run_sidecar(xml: str) -> list[dict]:
    jar = _jar_path()
    if not jar:
        return []
    try:
        with tempfile.NamedTemporaryFile(suffix=".xml", delete=True) as handle:
            handle.write(xml.encode("utf-8"))
            handle.flush()
            proc = subprocess.run(
                ["java", "-jar", jar, handle.name],
                capture_output=True,
                text=True,
                timeout=settings.validator_timeout_sec,
                check=False,
            )
        text = (proc.stdout or "") + "\n" + (proc.stderr or "")
        parsed = parse_sidecar_output(text)
        if parsed:
            return parsed
        if proc.returncode not in (0, 1):
            log.warning("validator jar exit %s", proc.returncode)
            return [
                _off(
                    "XSD",
                    "공식 validator sidecar 실행에 실패했습니다",
                    "sidecar",
                    "xml",
                    None,
                    None,
                    None,
                    level="warning",
                    source="sidecar",
                )
            ]
        return []
    except (OSError, subprocess.TimeoutExpired) as exc:
        log.warning("validator jar skipped: %s", exc)
        return []


def parse_sidecar_output(text: str) -> list[dict]:
    issues: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for line in text.splitlines():
        match = _SIDECAR_RE.search(line)
        if not match:
            continue
        code = match.group("code")
        if code not in OFFICIAL and code != "XSD":
            continue
        raw_lvl = (match.group("lvl") or "ERROR").upper()
        level = "warning" if raw_lvl.startswith("WARN") else "error"
        if code == "411":
            level = "warning"
        if code == "305" and "warn" in line.lower():
            level = "warning"
        key = (code, line.strip())
        if key in seen:
            continue
        seen.add(key)
        nslc = _nslc_from_line(line)
        issues.append(
            _off(
                code,
                OFFICIAL.get(code, line.strip()),
                nslc or "sidecar",
                _field_for(code),
                None,
                None,
                nslc,
                level=level,
                source="sidecar",
            )
        )
    return issues


def _channel_official(
    sta: etree._Element,
    cha: etree._Element,
    station: str,
    start: str,
    prefix: str,
) -> list[dict]:
    loc = cha.get("locationCode") or ""
    cha_code = cha.get("code") or ""
    nslc = f"{loc}.{cha_code}" if loc else cha_code
    path = f"{prefix}/{nslc}"
    issues: list[dict] = []
    resp = cha.find(qname("Response"))
    rate = _float(child_text(cha, "SampleRate"))
    soh = _is_soh(cha)
    if resp is None:
        return issues

    if rate is None:
        issues.append(
            _off("305", OFFICIAL["305"], path, "sample_rate", station, start, nslc, level="warning")
        )
    elif rate <= 0:
        issues.append(_off("305", OFFICIAL["305"], path, "sample_rate", station, start, nslc))

    stages = list(resp.findall(qname("Stage")))
    numbers: list[int] = []
    for stage in stages:
        raw = stage.get("number")
        try:
            numbers.append(int(raw)) if raw is not None else numbers.append(-1)
        except ValueError:
            numbers.append(-1)
    if stages and numbers != list(range(1, len(stages) + 1)):
        issues.append(_off("401", OFFICIAL["401"], path, "sensitivity", station, start, nslc))

    poly = _is_polynomial(resp)
    if _has_polynomial_stage(resp) and resp.find(qname("InstrumentPolynomial")) is None:
        issues.append(_off("415", OFFICIAL["415"], path, "sensitivity", station, start, nslc))

    ins = resp.find(qname("InstrumentSensitivity"))
    sens = _float(child_text(ins, "Value")) if ins is not None else None
    freq = _float(child_text(ins, "Frequency")) if ins is not None else None

    if not soh and not poly:
        if ins is None:
            issues.append(_off("416", OFFICIAL["416"], path, "sensitivity", station, start, nslc))
        elif sens is None or sens == 0:
            issues.append(_off("410", OFFICIAL["410"], path, "sensitivity", station, start, nslc))

    if not soh and stages:
        product = 1.0
        missing_gain = False
        for stage in stages:
            gain_el = stage.find(qname("StageGain"))
            gain = _float(child_text(gain_el, "Value")) if gain_el is not None else None
            if gain is None or gain == 0:
                missing_gain = True
                issues.append(
                    _off("413", OFFICIAL["413"], path, "sensitivity", station, start, nslc)
                )
                break
            product *= gain
        if (
            not missing_gain
            and sens is not None
            and sens != 0
            and _differs(sens, product)
        ):
            issues.append(_off("412", OFFICIAL["412"], path, "sensitivity", station, start, nslc))

    if freq is not None and rate is not None and rate > 0 and freq >= (rate / 2):
        issues.append(
            _off("411", OFFICIAL["411"], path, "sensitivity", station, start, nslc, level="warning")
        )

    decimations = _decimations(stages)
    if decimations:
        last_in, last_factor = decimations[-1]
        out_rate = last_in / last_factor if last_factor else last_in
        if rate is not None and rate > 0 and _differs(out_rate, rate):
            issues.append(_off("421", OFFICIAL["421"], path, "sample_rate", station, start, nslc))
        for idx in range(len(decimations) - 1):
            inp, factor = decimations[idx]
            nxt, _ = decimations[idx + 1]
            expected = inp / factor if factor else inp
            if _differs(expected, nxt):
                issues.append(_off("422", OFFICIAL["422"], path, "sample_rate", station, start, nslc))
                break
    return issues


def _decimations(stages: list[etree._Element]) -> list[tuple[float, float]]:
    rows: list[tuple[float, float]] = []
    for stage in stages:
        dec = stage.find(qname("Decimation"))
        if dec is None:
            continue
        inp = _float(child_text(dec, "InputSampleRate"))
        factor = _float(child_text(dec, "Factor")) or 1.0
        if inp is not None:
            rows.append((inp, factor))
    return rows


def _is_soh(cha: etree._Element) -> bool:
    types = {
        (node.text or "").strip().upper()
        for node in cha.findall(qname("Type"))
        if node.text
    }
    return bool(types & SOH_TYPES)


def _is_polynomial(resp: etree._Element) -> bool:
    return resp.find(qname("InstrumentPolynomial")) is not None or _has_polynomial_stage(resp)


def _has_polynomial_stage(resp: etree._Element) -> bool:
    for stage in resp.findall(qname("Stage")):
        if stage.find(qname("Polynomial")) is not None:
            return True
    return False


def _outside(sta_start: str, sta_end: str | None, net_start: str, net_end: str | None) -> bool:
    start_a = _parse_time(sta_start)
    start_n = _parse_time(net_start)
    if start_a is None or start_n is None:
        return False
    if start_a < start_n:
        return True
    if net_end:
        end_a = _parse_time(sta_end) if sta_end else None
        end_n = _parse_time(net_end)
        if end_n is None:
            return False
        if end_a is None or end_a > end_n:
            return True
    return False


def _differs(left: float, right: float) -> bool:
    scale = max(abs(left), abs(right), 1e-12)
    return abs(left - right) / scale > REL_TOL


def _off(
    code: str,
    message: str,
    path: str,
    field: str,
    station: str | None,
    start: str | None,
    nslc: str | None,
    *,
    level: str = "error",
    source: str = "validator",
) -> dict:
    return _issue(
        code,
        message,
        path,
        field,
        station,
        start,
        nslc,
        level=level,
        source=source,
        official=code,
    )


def _field_for(code: str) -> str:
    if code in {"305", "421", "422"}:
        return "sample_rate"
    if code in {"111", "112", "211"}:
        return "start"
    if code == "XSD":
        return "xml"
    return "sensitivity"


def _nslc_from_line(line: str) -> str | None:
    match = re.search(r"\b([A-Z0-9]{0,2})\.([A-Z0-9]{3})\b", line)
    if match:
        loc, code = match.group(1), match.group(2)
        return f"{loc}.{code}" if loc else code
    return None


def _jar_path() -> str | None:
    configured = (settings.validator_jar or "").strip()
    if configured:
        path = Path(configured)
        return str(path) if path.is_file() else None
    bundled = Path(__file__).resolve().parents[4] / "infra" / "jars" / "stationxml-validator.jar"
    return str(bundled) if bundled.is_file() else None


def _engine_name() -> str:
    return "sidecar" if _jar_path() else "python"
