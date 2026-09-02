from __future__ import annotations

import configparser
import copy
import os
import threading
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

import httpx
from lxml import etree

from ..config import settings
from .client import NrlError

FDSN_NS = "http://www.fdsn.org/xml/station/1"
LIBRARY_FILENAME = "full_NRL_v2.stationxml.zip"
LIBRARY_SOURCE_INSTCONFIG = "full_NRL_v2_zip"
MAX_METADATA_BYTES = 2 * 1024 * 1024
DOWNLOAD_CHUNK_BYTES = 1024 * 1024


@dataclass
class ModelEntry:
    name: str
    tree_path: str


@dataclass
class ManufacturerEntry:
    name: str
    models: dict[str, ModelEntry] = field(default_factory=dict)


@dataclass
class ElementEntry:
    name: str
    manufacturers: dict[str, ManufacturerEntry] = field(default_factory=dict)


@dataclass
class ArchiveIndex:
    root: str
    elements: dict[str, ElementEntry]
    response_paths: dict[str, str]


def library_path() -> Path:
    configured = (settings.nrl_offline_zip or "").strip()
    if configured:
        return Path(configured)
    root = Path((settings.data_dir or ".").strip() or ".")
    return root / "nrl" / LIBRARY_FILENAME


def _parser(raw: bytes, name: str) -> configparser.ConfigParser:
    if len(raw) > MAX_METADATA_BYTES:
        raise NrlError(f"NRL zip 메타데이터가 너무 큽니다: {name}", 503)
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    parser.optionxform = str.lower
    try:
        parser.read_string(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, configparser.Error) as exc:
        raise NrlError(f"NRL zip 메타데이터를 읽을 수 없습니다: {name}", 503) from exc
    return parser


def _safe_member(name: str) -> str:
    normalized = str(PurePosixPath(name))
    if normalized.startswith("/") or normalized == ".." or normalized.startswith("../"):
        raise NrlError("NRL zip에 안전하지 않은 경로가 있습니다", 503)
    return normalized


def _join_member(parent: str, child: str) -> str:
    return _safe_member(str(PurePosixPath(parent).parent / child))


def _index_sections(archive: zipfile.ZipFile, path: str) -> list[tuple[str, str]]:
    try:
        parser = _parser(archive.read(path), path)
    except KeyError as exc:
        raise NrlError(f"NRL zip 메타데이터가 없습니다: {path}", 503) from exc
    rows: list[tuple[str, str]] = []
    for section in parser.sections():
        if section.lower() == "main":
            continue
        target = parser.get(section, "path", fallback="").strip().strip('"')
        if target:
            rows.append((section, _join_member(path, target)))
    return rows


def _response_file_from_section(
    parser: configparser.ConfigParser, section: str
) -> str | None:
    for key in ("xml", "stationxml", "response"):
        value = parser.get(section, key, fallback="").strip().strip('"')
        if value.lower().endswith((".xml", ".response.xml")):
            return value
    return None


def _parameters(description: str) -> dict[str, str]:
    params: dict[str, str] = {}
    for part in description.split(";")[2:]:
        text = part.strip()
        if not text or " " not in text:
            continue
        key, value = text.split(None, 1)
        if key and value:
            params[key] = value
    return params


def _configuration_rows(
    archive: zipfile.ZipFile,
    path: str,
    *,
    element: str,
    manufacturer: str,
    seen: set[str] | None = None,
) -> list[dict]:
    visited = seen if seen is not None else set()
    if path in visited:
        raise NrlError("NRL zip 결정 트리에 순환 경로가 있습니다", 503)
    visited.add(path)
    try:
        parser = _parser(archive.read(path), path)
    except KeyError as exc:
        raise NrlError(f"NRL zip 메타데이터가 없습니다: {path}", 503) from exc
    rows: list[dict] = []
    for section in parser.sections():
        if section.lower() == "main":
            continue
        next_path = parser.get(section, "path", fallback="").strip().strip('"')
        if next_path:
            rows.extend(
                _configuration_rows(
                    archive,
                    _join_member(path, next_path),
                    element=element,
                    manufacturer=manufacturer,
                    seen=visited,
                )
            )
            continue
        response_file = _response_file_from_section(parser, section)
        if not response_file:
            continue
        response_path = _join_member(path, response_file)
        stem = PurePosixPath(response_file).name
        if stem.endswith(".response.xml"):
            stem = stem[: -len(".response.xml")]
        else:
            stem = PurePosixPath(stem).stem
        description = parser.get(section, "description", fallback="").strip().strip('"')
        rows.append(
            {
                "instconfig": f"{element}_{manufacturer}_{stem}",
                "description": description,
                "parameters": _parameters(description),
                "_response_path": response_path,
            }
        )
    visited.remove(path)
    return rows


def _find_root(names: set[str]) -> str:
    roots = sorted(
        name[: -len("/index.txt")]
        for name in names
        if name == "NRL/index.txt" or name.endswith("/NRL/index.txt")
    )
    if not roots:
        raise NrlError("NRL zip에 NRL/index.txt가 없습니다", 503)
    return roots[0]


def _build_index(path: Path) -> ArchiveIndex:
    try:
        archive = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile) as exc:
        raise NrlError("NRL 오프라인 zip을 열 수 없습니다", 503) from exc
    with archive:
        names = {_safe_member(info.filename) for info in archive.infolist()}
        root = _find_root(names)
        elements: dict[str, ElementEntry] = {}
        responses: dict[str, str] = {}
        for element_name, element_index in _index_sections(archive, f"{root}/index.txt"):
            element = ElementEntry(element_name.lower())
            for manufacturer_name, manufacturer_index in _index_sections(
                archive, element_index
            ):
                manufacturer = ManufacturerEntry(manufacturer_name)
                for model_name, model_tree in _index_sections(archive, manufacturer_index):
                    manufacturer.models[model_name] = ModelEntry(model_name, model_tree)
                    for row in _configuration_rows(
                        archive,
                        model_tree,
                        element=element.name,
                        manufacturer=manufacturer.name,
                    ):
                        responses[row["instconfig"]] = row["_response_path"]
                element.manufacturers[manufacturer.name] = manufacturer
            elements[element.name] = element
        if not elements or not responses:
            raise NrlError("NRL zip에 탐색 가능한 응답이 없습니다", 503)
        return ArchiveIndex(root=root, elements=elements, response_paths=responses)


class OfflineNrlLibrary:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path is not None else library_path()
        self._lock = threading.RLock()
        self._stamp: tuple[int, int] | None = None
        self._index: ArchiveIndex | None = None

    def _load(self) -> ArchiveIndex:
        try:
            stat = self.path.stat()
        except OSError as exc:
            raise NrlError(f"NRL 오프라인 zip이 없습니다: {self.path}", 503) from exc
        stamp = (stat.st_mtime_ns, stat.st_size)
        with self._lock:
            if self._index is None or self._stamp != stamp:
                self._index = _build_index(self.path)
                self._stamp = stamp
            return self._index

    def status(self) -> dict:
        try:
            stat = self.path.stat()
            index = self._load()
        except (OSError, NrlError) as exc:
            return {
                "available": False,
                "path": str(self.path),
                "bytes": 0,
                "responses": 0,
                "error": str(exc),
            }
        return {
            "available": True,
            "path": str(self.path),
            "bytes": int(stat.st_size),
            "responses": len(index.response_paths),
            "error": None,
        }

    def _element(self, name: str | None) -> ElementEntry:
        key = (name or "").strip().lower()
        element = self._load().elements.get(key)
        if element is None:
            raise NrlError("NRL zip에 해당 장비 유형이 없습니다", 404)
        return element

    def catalog(
        self,
        *,
        level: str,
        element: str | None = None,
        manufacturer: str | None = None,
        model: str | None = None,
    ) -> dict:
        index = self._load()
        if level == "element":
            nodes = [{"name": row.name, "detail": ""} for row in index.elements.values()]
            return {"NRLCatalog": {"formatversion": 1.0, "element": nodes}}
        selected = self._element(element)
        if level == "manufacturer":
            manufacturers = [
                {"name": row.name, "detail": ""} for row in selected.manufacturers.values()
            ]
            return {
                "NRLCatalog": {
                    "formatversion": 1.0,
                    "element": [{"name": selected.name, "manufacturer": manufacturers}],
                }
            }
        manufacturer_rows = selected.manufacturers.values()
        if manufacturer:
            chosen = selected.manufacturers.get(manufacturer)
            if chosen is None:
                raise NrlError("NRL zip에 해당 제조사가 없습니다", 404)
            manufacturer_rows = [chosen]
        if level == "model":
            nodes = []
            for maker in manufacturer_rows:
                nodes.append(
                    {
                        "name": maker.name,
                        "detail": "",
                        "model": [
                            {"name": row.name, "detail": ""}
                            for row in maker.models.values()
                        ],
                    }
                )
            return {
                "NRLCatalog": {
                    "formatversion": 1.0,
                    "element": [{"name": selected.name, "manufacturer": nodes}],
                }
            }
        if level != "configuration" or not manufacturer or not model:
            raise NrlError("configuration 탐색에는 제조사와 모델이 필요합니다", 400)
        maker = selected.manufacturers.get(manufacturer)
        model_entry = maker.models.get(model) if maker else None
        if model_entry is None:
            raise NrlError("NRL zip에 해당 모델이 없습니다", 404)
        with zipfile.ZipFile(self.path) as archive:
            configs = _configuration_rows(
                archive,
                model_entry.tree_path,
                element=selected.name,
                manufacturer=maker.name,
            )
        for row in configs:
            row.pop("_response_path", None)
        return {
            "NRLCatalog": {
                "formatversion": 1.0,
                "element": [
                    {
                        "name": selected.name,
                        "manufacturer": [
                            {
                                "name": maker.name,
                                "model": [
                                    {"name": model_entry.name, "configuration": configs}
                                ],
                            }
                        ],
                    }
                ],
            }
        }

    def prefix_lookup(self) -> list[dict]:
        return []

    def combine(self, instconfig: str, fmt: str) -> tuple[bytes, str]:
        if fmt not in {"stationxml", "stationxml-resp"}:
            raise NrlError("오프라인 zip 미리보기는 StationXML 형식만 지원합니다", 400)
        index = self._load()
        names = instconfig.split(":")
        paths: list[str] = []
        for name in names:
            response_path = index.response_paths.get(name)
            if response_path is None:
                raise NrlError(f"NRL zip에 해당 응답이 없습니다: {name}", 404)
            paths.append(response_path)
        try:
            with zipfile.ZipFile(self.path) as archive:
                payloads = [archive.read(path) for path in paths]
        except (OSError, KeyError, zipfile.BadZipFile) as exc:
            raise NrlError("NRL zip 응답을 읽을 수 없습니다", 503) from exc
        if len(payloads) == 1:
            return payloads[0], "application/xml"
        return _cascade_stationxml(payloads), "application/xml"


def _first(root: etree._Element, name: str) -> etree._Element | None:
    return root.find(f".//{{{FDSN_NS}}}{name}")


def _cascade_stationxml(payloads: list[bytes]) -> bytes:
    try:
        roots = [etree.fromstring(payload) for payload in payloads]
    except etree.XMLSyntaxError as exc:
        raise NrlError("NRL zip StationXML이 올바르지 않습니다", 503) from exc
    output = copy.deepcopy(roots[0])
    output_response = _first(output, "Response")
    if output_response is None:
        raise NrlError("NRL zip StationXML에 Response가 없습니다", 503)
    stages = output_response.findall(f"{{{FDSN_NS}}}Stage")
    next_stage = len(stages) + 1
    sensitivities: list[etree._Element] = []
    for root in roots:
        response = _first(root, "Response")
        sensitivity = _first(response, "InstrumentSensitivity") if response is not None else None
        if sensitivity is not None:
            sensitivities.append(sensitivity)
    for root in roots[1:]:
        response = _first(root, "Response")
        if response is None:
            raise NrlError("NRL zip StationXML에 Response가 없습니다", 503)
        for stage in response.findall(f"{{{FDSN_NS}}}Stage"):
            cloned = copy.deepcopy(stage)
            cloned.set("number", str(next_stage))
            output_response.append(cloned)
            next_stage += 1
    output_sensitivity = _first(output_response, "InstrumentSensitivity")
    if output_sensitivity is not None and sensitivities:
        product = 1.0
        for sensitivity in sensitivities:
            value = _first(sensitivity, "Value")
            try:
                product *= float(value.text) if value is not None and value.text else 1.0
            except ValueError:
                pass
        value = _first(output_sensitivity, "Value")
        if value is not None:
            value.text = f"{product:.12g}"
        last_output = _first(sensitivities[-1], "OutputUnits")
        current_output = _first(output_sensitivity, "OutputUnits")
        if last_output is not None and current_output is not None:
            output_sensitivity.replace(current_output, copy.deepcopy(last_output))
    output_channel = _first(output, "Channel")
    last_channel = _first(roots[-1], "Channel")
    if output_channel is not None and last_channel is not None:
        last_rate = last_channel.find(f"{{{FDSN_NS}}}SampleRate")
        current_rate = output_channel.find(f"{{{FDSN_NS}}}SampleRate")
        if last_rate is not None:
            if current_rate is not None:
                output_channel.replace(current_rate, copy.deepcopy(last_rate))
            else:
                response_position = list(output_channel).index(output_response)
                output_channel.insert(response_position, copy.deepcopy(last_rate))
    return etree.tostring(
        output, xml_declaration=True, encoding="UTF-8", pretty_print=True
    )


_library: OfflineNrlLibrary | None = None
_library_lock = threading.Lock()


def get_offline_library() -> OfflineNrlLibrary:
    global _library
    path = library_path()
    with _library_lock:
        if _library is None or _library.path != path:
            _library = OfflineNrlLibrary(path)
        return _library


def reset_offline_library() -> None:
    global _library
    with _library_lock:
        _library = None


def download_library() -> dict:
    target = library_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.part")
    url = f"{settings.nrl_base_url.rstrip('/')}/combine"
    params = {
        "nodata": "404",
        "instconfig": LIBRARY_SOURCE_INSTCONFIG,
        "format": "stationxml.zip",
    }
    try:
        with httpx.stream(
            "GET",
            url,
            params=params,
            timeout=settings.nrl_library_timeout_sec,
            follow_redirects=True,
        ) as response:
            if response.status_code >= 400:
                raise NrlError("EarthScope NRL 전체 zip 다운로드에 실패했습니다", 502)
            with temporary.open("wb") as handle:
                for chunk in response.iter_bytes(DOWNLOAD_CHUNK_BYTES):
                    handle.write(chunk)
                handle.flush()
                os.fsync(handle.fileno())
        _build_index(temporary)
        os.replace(temporary, target)
    except NrlError:
        temporary.unlink(missing_ok=True)
        raise
    except (OSError, httpx.HTTPError) as exc:
        temporary.unlink(missing_ok=True)
        raise NrlError("EarthScope NRL 전체 zip 다운로드에 실패했습니다", 502) from exc
    settings.nrl_offline_zip = str(target)
    reset_offline_library()
    return get_offline_library().status()
