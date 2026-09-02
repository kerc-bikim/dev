"""dataless SEED → StationXML 변환.

공식 converter JAR 가 있으면 그걸 쓰고, 없으면 ObsPy xseed Parser 로 읽는다.
원문 바이트는 여기서 고치지 않는다.
"""

from __future__ import annotations

import logging
import subprocess
import tempfile
import warnings
from io import BytesIO
from pathlib import Path

from lxml import etree
from obspy import read_inventory

from ..config import settings
from .xmlbuild import InventoryError, _issue
from .xmlutil import dumps, local, parse_root, qname

log = logging.getLogger("pdcc.seed_convert")

SEED_MEDIA = "application/vnd.fdsn.seed"
COMMENT_MAX = 70
FIR_NAME_MAX = 25


def classify_seed(data: bytes) -> str:
    types: set[str] = set()
    for rec_len in (4096, 512):
        for offset in range(0, min(len(data), rec_len * 64), rec_len):
            rec = data[offset : offset + 8]
            if len(rec) < 7:
                break
            marker = rec[6:7]
            if marker.isalpha():
                types.add(marker.decode("ascii", errors="ignore"))
        if types:
            break
    has_header = bool(types & {"V", "A", "S"})
    has_data = bool(types & {"D", "R", "Q", "M"})
    if has_data and not has_header:
        return "miniseed"
    if has_data and has_header:
        return "full"
    if has_header:
        return "dataless"
    return "unknown"


def looks_like_seed(raw: bytes) -> bool:
    if len(raw) < 8:
        return False
    return raw[:6].isdigit() and raw[6:7].isalpha()


def looks_like_resp(raw: bytes) -> bool:
    head = raw.lstrip()[:200].upper()
    if head.startswith(b"B050") or head.startswith(b"B010"):
        return True
    if head.startswith(b"#") and b"B050" in raw[:800].upper():
        return True
    return False


def convert_warning(
    code: str,
    message: str,
    *,
    path: str = "import",
    field: str = "xml",
    station: str | None = None,
    start: str | None = None,
    nslc: str | None = None,
) -> dict:
    return _issue(
        code,
        message,
        path,
        field,
        station,
        start,
        nslc,
        level="warning",
        source="import",
    )


def converter_jar_path() -> str | None:
    configured = (settings.seed_converter_jar or "").strip()
    if configured:
        path = Path(configured)
        return str(path) if path.is_file() else None
    bundled = Path(__file__).resolve().parents[4] / "infra" / "jars" / "stationxml-seed-converter.jar"
    return str(bundled) if bundled.is_file() else None


def convert_dataless_to_xml(raw: bytes) -> tuple[str, list[dict]]:
    kind = classify_seed(raw)
    if kind == "miniseed":
        raise InventoryError(
            "파형 MiniSEED는 열 수 없습니다. dataless SEED를 선택하세요",
            400,
            "E_IMPORT",
        )
    if kind == "full":
        raise InventoryError(
            "파형 레코드가 있는 SEED는 열 수 없습니다. dataless만 가져옵니다",
            400,
            "E_IMPORT",
        )
    if kind != "dataless" and not looks_like_seed(raw):
        raise InventoryError(
            "dataless SEED가 아닙니다. StationXML 또는 dataless SEED를 선택하세요",
            400,
            "E_IMPORT",
        )

    notes: list[dict] = []
    xml: str | None = None
    engine = "obspy"
    jar = converter_jar_path()
    if jar:
        try:
            xml = _run_converter_jar(jar, raw)
            engine = "converter"
        except InventoryError:
            raise
        except Exception as exc:
            log.warning("seed converter jar failed, falling back to ObsPy: %s", exc)
            notes.append(
                convert_warning(
                    "W_SEED_CONVERTER",
                    "공식 converter 실행에 실패해 ObsPy로 변환했습니다",
                )
            )

    if xml is None:
        xml, obspy_notes = _convert_with_obspy(raw)
        notes.extend(obspy_notes)
        engine = "obspy"

    xml, schema_notes = _ensure_schema_12(xml)
    notes.extend(schema_notes)
    notes.extend(_seed_field_warnings(raw))
    notes.insert(
        0,
        convert_warning(
            "W_SEED_CONVERT",
            f"dataless SEED를 StationXML 1.2로 변환했습니다 ({engine})",
        ),
    )
    return xml, notes


def _run_converter_jar(jar: str, raw: bytes) -> str:
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "input.seed"
        dest = Path(tmp) / "output.xml"
        src.write_bytes(raw)
        attempts = (
            ["java", "-jar", jar, "--input", str(src), "--output", str(dest)],
            ["java", "-jar", jar, "-i", str(src), "-o", str(dest)],
        )
        last_err = ""
        for cmd in attempts:
            try:
                proc = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=settings.converter_timeout_sec,
                    check=False,
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                last_err = str(exc)
                continue
            if dest.is_file() and dest.stat().st_size > 0:
                return dest.read_text(encoding="utf-8")
            last_err = ((proc.stderr or "") + "\n" + (proc.stdout or "")).strip()
        suffix = f": {last_err[:200]}" if last_err else ""
        raise InventoryError(
            f"SEED converter가 StationXML을 만들지 못했습니다{suffix}",
            400,
            "E_IMPORT",
        )


def _convert_with_obspy(raw: bytes) -> tuple[str, list[dict]]:
    notes: list[dict] = []
    caught: list[warnings.WarningMessage] = []
    try:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            inv = read_inventory(BytesIO(raw), format="SEED")
    except Exception as exc:
        raise InventoryError(
            "dataless SEED를 읽지 못했습니다. 파일이 손상되었거나 형식이 아닙니다",
            400,
            "E_IMPORT",
        ) from exc
    for item in caught:
        text = str(item.message).strip()
        if not text:
            continue
        notes.append(
            convert_warning(
                "W_SEED_UNITS",
                _korean_obspy_warning(text),
            )
        )
    buf = BytesIO()
    try:
        inv.write(buf, format="STATIONXML")
    except Exception as exc:
        raise InventoryError("변환된 StationXML을 쓰지 못했습니다", 500, "E_IMPORT") from exc
    xml = buf.getvalue().decode("utf-8")
    if not xml.strip():
        raise InventoryError("변환 결과가 비어 있습니다", 400, "E_IMPORT")
    return xml, notes


def _korean_obspy_warning(text: str) -> str:
    lower = text.lower()
    if "output units" in lower:
        return "변환 중 출력 단위를 확인하지 못했습니다. 응답을 검사하세요"
    if "input units" in lower:
        return "변환 중 입력 단위를 확인하지 못했습니다. 응답을 검사하세요"
    return f"SEED 변환 경고: {text[:180]}"


def _ensure_schema_12(xml: str) -> tuple[str, list[dict]]:
    try:
        root = parse_root(xml)
    except etree.XMLSyntaxError as exc:
        raise InventoryError("변환된 XML 구조가 표준과 다릅니다", 400, "XSD") from exc
    if local(root.tag) != "FDSNStationXML":
        raise InventoryError("변환 결과가 FDSN StationXML이 아닙니다", 400, "XSD")
    version = (root.get("schemaVersion") or "").strip()
    notes: list[dict] = []
    if version != "1.2":
        root.set("schemaVersion", "1.2")
        notes.append(
            convert_warning(
                "W_SEED_SCHEMA",
                f"schemaVersion {version or '없음'}을 1.2로 맞췄습니다",
            )
        )
    return dumps(root), notes


def _seed_field_warnings(raw: bytes) -> list[dict]:
    notes: list[dict] = []
    try:
        from obspy.io.xseed import Parser

        parser = Parser(BytesIO(raw), strict=False)
    except Exception:
        return notes
    for station in getattr(parser, "stations", []) or []:
        for blkt in station:
            bid = getattr(blkt, "id", None) or getattr(blkt, "blockette_id", None)
            text = ""
            name = ""
            if bid in (51, "051", 31, "031"):
                text = str(getattr(blkt, "comment", "") or getattr(blkt, "comment_text", "") or "")
            if bid in (61, "061"):
                name = str(getattr(blkt, "response_name", "") or "")
            if len(text) >= COMMENT_MAX:
                notes.append(
                    convert_warning(
                        "W_SEED_TRUNC",
                        f"코멘트가 {COMMENT_MAX}자로 잘려 있을 수 있습니다",
                    )
                )
            if name and len(name) >= FIR_NAME_MAX:
                notes.append(
                    convert_warning(
                        "W_SEED_FIR",
                        f"FIR 이름 {name[:FIR_NAME_MAX]} 이 {FIR_NAME_MAX}자로 잘려 있습니다",
                    )
                )
    return notes


def dataless_filename(xml: str, network: str, when=None) -> str:
    from datetime import datetime, timezone

    stamp = when or datetime.now(timezone.utc)
    date = stamp.strftime("%Y%m%d")
    net = (network or "XX").strip() or "XX"
    stations: list[str] = []
    try:
        root = parse_root(xml)
    except etree.XMLSyntaxError:
        return f"{net}.{date}.dataless"
    for node in root.findall(f".//{qname('Station')}"):
        code = (node.get("code") or "").strip()
        if code and code not in stations:
            stations.append(code)
    if len(stations) == 1:
        return f"{net}.{stations[0]}.{date}.dataless"
    return f"{net}.{date}.dataless"


def convert_xml_to_dataless(
    xml: str,
    *,
    organization: str | None = None,
    label: str | None = None,
) -> tuple[bytes, str]:
    """StationXML 원문 → dataless SEED. 원문 문자열은 바꾸지 않는다."""
    from .seed_write import SeedWriteError, inventory_to_seed_bytes, prepare_seed_inventory

    org = (organization or settings.seed_organization or "").strip() or "PDCC Web"
    lab = (label or settings.seed_label or "").strip() or "dataless"
    jar = converter_jar_path()
    if jar:
        try:
            data = _run_converter_xml_to_seed(jar, xml, organization=org, label=lab)
            if classify_seed(data) == "dataless":
                return data, "converter"
            log.warning("seed converter jar produced non-dataless output, falling back to ObsPy")
        except Exception as exc:
            log.warning("xml→seed converter jar failed, falling back to ObsPy: %s", exc)

    try:
        inv = read_inventory(BytesIO(xml.encode("utf-8")), format="STATIONXML")
    except Exception as exc:
        raise InventoryError("StationXML을 읽지 못해 SEED를 만들지 못했습니다", 422, "E_EXPORT") from exc
    prepare_seed_inventory(inv)
    try:
        data = inventory_to_seed_bytes(inv, organization=org, label=lab)
    except SeedWriteError as exc:
        raise InventoryError(str(exc), 400, "E_EXPORT") from exc
    except Exception as exc:
        raise InventoryError(f"SEED 응답 단계를 쓰지 못했습니다: {exc}", 400, "E_EXPORT") from exc
    if classify_seed(data) != "dataless":
        raise InventoryError("dataless SEED가 만들어지지 않았습니다", 500, "E_EXPORT")
    return data, "obspy"


def _run_converter_xml_to_seed(
    jar: str, xml: str, *, organization: str, label: str
) -> bytes:
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "input.xml"
        dest = Path(tmp) / "output.dataless"
        src.write_text(xml, encoding="utf-8")
        attempts = (
            [
                "java",
                "-jar",
                jar,
                "--input",
                str(src),
                "--output",
                str(dest),
                "--organization",
                organization,
                "--label",
                label,
            ],
            ["java", "-jar", jar, "-i", str(src), "-o", str(dest)],
        )
        last_err = ""
        for cmd in attempts:
            try:
                proc = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=settings.converter_timeout_sec,
                    check=False,
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                last_err = str(exc)
                continue
            if dest.is_file() and dest.stat().st_size > 0:
                return dest.read_bytes()
            last_err = ((proc.stderr or "") + "\n" + (proc.stdout or "")).strip()
        suffix = f": {last_err[:200]}" if last_err else ""
        raise InventoryError(
            f"SEED converter가 dataless를 만들지 못했습니다{suffix}",
            400,
            "E_EXPORT",
        )
