"""SeedLink INFO STREAMS.

기록계 SOH 와 다른 통로다. HELLO 뒤 INFO STREAMS 만 보내고 DATA 스트림은 열지 않는다.
실패는 예외가 아니라 TransportResult 다. 수집 루프를 죽이지 않는 것이 계약이다.

패킷 형식은 libslink / SeisComP 의 SLINFO 헤더(8바이트) + 512바이트 XML 조각이다.
실서버가 헤더 없이 XML 만 주면 그것도 받는다.
"""
from __future__ import annotations

import asyncio
from urllib.parse import parse_qs, urlparse
from xml.etree import ElementTree as ET

from app.adapters.transport.base import TransportResult
from app.domain.enums import PollErrorCode

from .parser import parse_timestamp

INFO_PACKET_BYTES = 512
INFO_HEADER_MORE = b"SLINFO  "
INFO_HEADER_LAST = b"SLINFO *"
DEFAULT_PORT = 18000
DEFAULT_MAX_PAYLOAD_BYTES = 4 * 1024 * 1024


def split_seedlink_uri(uri: str) -> tuple[str | None, int, str | None, str | None]:
    """host, port, network, station."""
    parsed = urlparse(uri.strip())
    host = parsed.hostname
    port = parsed.port or DEFAULT_PORT
    query = parse_qs(parsed.query)
    network = (query.get("net") or [None])[0]
    station = (query.get("sta") or [None])[0]
    path = (parsed.path or "").strip("/")
    if path:
        if "_" in path:
            network, station = path.split("_", 1)
        elif "/" in path:
            network, station = path.split("/", 1)
        elif station is None:
            station = path
    return host, port, (network or None), (station or None)


def pack_info_xml(xml: bytes) -> bytes:
    """시험·가상 서버가 쓰는 SLINFO 패킷 묶음."""
    if not xml:
        xml = b"<seedlink/>"
    chunks: list[bytes] = []
    for offset in range(0, len(xml), INFO_PACKET_BYTES):
        piece = xml[offset : offset + INFO_PACKET_BYTES]
        padded = piece + (b"\0" * (INFO_PACKET_BYTES - len(piece)))
        last = offset + INFO_PACKET_BYTES >= len(xml)
        chunks.append((INFO_HEADER_LAST if last else INFO_HEADER_MORE) + padded)
    return b"".join(chunks)


def unpack_info_payload(raw: bytes) -> bytes:
    if not raw:
        return b""
    if not raw.startswith(b"SLINFO"):
        return raw.split(b"\0", 1)[0]
    parts: list[bytes] = []
    offset = 0
    while offset + 8 <= len(raw):
        header = raw[offset : offset + 8]
        if not header.startswith(b"SLINFO"):
            rest = raw[offset:].split(b"\0", 1)[0]
            if rest:
                parts.append(rest)
            break
        payload = raw[offset + 8 : offset + 8 + INFO_PACKET_BYTES]
        parts.append(payload.rstrip(b"\0"))
        offset += 8 + INFO_PACKET_BYTES
        if header == INFO_HEADER_LAST:
            break
    return b"".join(parts)


def info_xml_to_bands(
    xml_text: str,
    *,
    network: str | None = None,
    station: str | None = None,
) -> dict:
    """SeedLink INFO XML → 공통 availability 봉투."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise ValueError(f"SeedLink INFO XML 을 해석할 수 없다: {exc}") from exc

    want_net = (network or "").strip().upper() or None
    want_sta = (station or "").strip().upper() or None
    bands: list[dict] = []

    stations = list(root.findall(".//station"))
    if not stations and root.tag.endswith("station"):
        stations = [root]

    for item in stations:
        net = (item.get("network") or item.get("net") or "").strip().upper()
        sta = (item.get("name") or item.get("station") or "").strip().upper()
        if want_net and net and net != want_net:
            continue
        if want_sta and sta and sta != want_sta:
            continue
        for stream in item.findall("stream"):
            seedname = (stream.get("seedname") or stream.get("channel") or "").strip()
            if not seedname:
                continue
            location = (stream.get("location") or "").strip()
            channel = f"{location}.{seedname}" if location and location not in {"--", ""} else seedname
            start = stream.get("begin_time") or stream.get("start") or stream.get("begin")
            end = stream.get("end_time") or stream.get("end")
            if parse_timestamp(end) is None and parse_timestamp(start) is None:
                bands.append({"channel": channel, "ranges": []})
                continue
            bands.append(
                {
                    "channel": channel,
                    "ranges": [{"start": start or end, "end": end or start}],
                }
            )

    if not bands:
        raise ValueError("SeedLink INFO STREAMS 에서 채널을 하나도 찾지 못했다")
    return {"bands": bands}


class SeedLinkTransport:
    """HELLO + INFO STREAMS. 채널 마지막 시각만 가져온다."""

    def __init__(self, *, max_payload_bytes: int = DEFAULT_MAX_PAYLOAD_BYTES) -> None:
        self.max_payload_bytes = max_payload_bytes

    async def fetch(
        self,
        uri: str,
        *,
        connect_timeout_ms: int,
        request_timeout_ms: int,
        station_code: str | None = None,
    ) -> TransportResult:
        host, port, network, station = split_seedlink_uri(uri)
        station = station or station_code
        if not host:
            return TransportResult(
                success=False,
                error_code=PollErrorCode.ADAPTER_ERROR,
                error_message="SeedLink 호스트가 없다",
            )
        loop = asyncio.get_running_loop()
        started = loop.time()
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port),
                timeout=connect_timeout_ms / 1000,
            )
        except Exception as exc:  # noqa: BLE001
            return TransportResult(
                success=False,
                error_code=PollErrorCode.CONNECTION_REFUSED,
                error_message=str(exc),
            )

        try:
            await _command(writer, "HELLO")
            banner = await _read_hello(reader, request_timeout_ms / 1000)
            if not banner.strip():
                return TransportResult(
                    success=False,
                    error_code=PollErrorCode.INVALID_PAYLOAD,
                    error_message="SeedLink HELLO 응답이 비어 있다",
                )
            await _command(writer, "INFO STREAMS")
            raw = await _read_info(reader, request_timeout_ms / 1000, self.max_payload_bytes)
        except TimeoutError:
            return TransportResult(
                success=False,
                error_code=PollErrorCode.REQUEST_TIMEOUT,
                error_message="SeedLink INFO STREAMS 응답이 없다",
            )
        except Exception as exc:  # noqa: BLE001
            return TransportResult(
                success=False,
                error_code=PollErrorCode.ADAPTER_ERROR,
                error_message=str(exc),
            )
        finally:
            await _close(writer)

        xml = unpack_info_payload(raw)
        if len(xml) > self.max_payload_bytes:
            return TransportResult(
                success=False,
                error_code=PollErrorCode.INVALID_PAYLOAD,
                error_message="SeedLink INFO 응답이 너무 크다",
            )
        try:
            payload = info_xml_to_bands(xml.decode("utf-8", errors="replace"), network=network, station=station)
        except ValueError as exc:
            return TransportResult(
                success=False,
                payload_bytes=len(xml),
                error_code=PollErrorCode.INVALID_PAYLOAD,
                error_message=str(exc),
            )
        latency_ms = (loop.time() - started) * 1000
        return TransportResult(
            success=True,
            payload=payload,
            latency_ms=latency_ms,
            payload_bytes=len(xml),
        )


# 예전 이름. 호출부는 TransportResult 계약만 본다.
SeedLinkStubTransport = SeedLinkTransport


async def _command(writer: asyncio.StreamWriter, command: str) -> None:
    writer.write(f"{command}\r".encode("ascii"))
    await writer.drain()


async def _read_cr_line(reader: asyncio.StreamReader, timeout: float) -> bytes:
    """SeedLink 줄 끝은 \\r 또는 \\r\\n 이다. readline() 은 \\n 만 보면 멈춘다."""
    data = bytearray()
    while True:
        chunk = await asyncio.wait_for(reader.readexactly(1), timeout=timeout)
        if chunk in {b"\n", b"\r"}:
            return bytes(data)
        data.extend(chunk)


async def _read_hello(reader: asyncio.StreamReader, timeout: float) -> bytes:
    """HELLO 응답은 소프트웨어·기관 두 줄이다. 빈 줄(남은 LF)은 건너뛴다."""
    lines: list[bytes] = []
    while len(lines) < 2:
        line = await _read_cr_line(reader, timeout)
        if line.strip():
            lines.append(line)
    return b"\n".join(lines)


async def _read_info(reader: asyncio.StreamReader, timeout: float, limit: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    deadline = asyncio.get_running_loop().time() + timeout
    first = b""
    while True:
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            raise TimeoutError
        byte = await asyncio.wait_for(reader.readexactly(1), timeout=remaining)
        if byte in b"\r\n" and not first:
            continue
        first = byte
        break
    while True:
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            raise TimeoutError
        header = first + await asyncio.wait_for(reader.readexactly(8 - len(first)), timeout=remaining)
        first = b""
        if header.startswith(b"SLINFO"):
            remaining = deadline - asyncio.get_running_loop().time()
            payload = await asyncio.wait_for(reader.readexactly(INFO_PACKET_BYTES), timeout=max(remaining, 0.01))
            chunks.append(header + payload)
            total += 8 + INFO_PACKET_BYTES
            if total > limit:
                break
            if header == INFO_HEADER_LAST:
                break
            continue
        rest = header + await asyncio.wait_for(reader.read(limit), timeout=max(remaining, 0.01))
        chunks.append(rest)
        break
    return b"".join(chunks)


async def _close(writer: asyncio.StreamWriter) -> None:
    try:
        writer.write(b"BYE\r")
        await writer.drain()
    except Exception:  # noqa: BLE001
        pass
    writer.close()
    try:
        await writer.wait_closed()
    except Exception:  # noqa: BLE001
        pass
