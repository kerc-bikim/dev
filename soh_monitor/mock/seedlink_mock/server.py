"""가상 SeedLink.

실서버의 DATA 스트림은 열지 않는다. HELLO 와 INFO STREAMS 만 받아
채널 시작·끝 시각을 SLINFO 패킷으로 돌려준다. 시험이 파형 연속성 검사만
보면 되므로 이 표면으로 충분하다.
"""
from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Iterable

INFO_PACKET_BYTES = 512
INFO_HEADER_MORE = b"SLINFO  "
INFO_HEADER_LAST = b"SLINFO *"


def pack_info_xml(xml: bytes) -> bytes:
    if not xml:
        xml = b"<seedlink/>"
    chunks: list[bytes] = []
    for offset in range(0, len(xml), INFO_PACKET_BYTES):
        piece = xml[offset : offset + INFO_PACKET_BYTES]
        padded = piece + (b"\0" * (INFO_PACKET_BYTES - len(piece)))
        last = offset + INFO_PACKET_BYTES >= len(xml)
        chunks.append((INFO_HEADER_LAST if last else INFO_HEADER_MORE) + padded)
    return b"".join(chunks)


@dataclass(frozen=True)
class MockStream:
    channel: str
    begin: datetime
    end: datetime
    location: str = ""
    network: str = "KS"
    station: str = "A01"


@dataclass
class SeedLinkMock:
    streams: list[MockStream] = field(default_factory=list)
    host: str = "127.0.0.1"
    banner_software: str = "SeedLink v3.3 (soh-mock)"
    banner_org: str = "SOH Monitor mock"
    _server: asyncio.AbstractServer | None = None
    port: int = 0

    async def __aenter__(self) -> SeedLinkMock:
        self._server = await asyncio.start_server(self._handle, self.host, 0)
        sockets = self._server.sockets or []
        self.port = sockets[0].getsockname()[1]
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        del exc_type, exc, tb
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

    @property
    def uri(self) -> str:
        return f"seedlink://{self.host}:{self.port}"

    def xml_bytes(self) -> bytes:
        by_station: dict[tuple[str, str], list[MockStream]] = {}
        for stream in self.streams:
            by_station.setdefault((stream.network, stream.station), []).append(stream)
        lines = ['<?xml version="1.0"?>', "<seedlink>"]
        for (network, station), items in by_station.items():
            lines.append(f' <station name="{station}" network="{network}">')
            for item in items:
                loc = item.location
                begin = _fmt(item.begin)
                end = _fmt(item.end)
                lines.append(
                    f'  <stream location="{loc}" seedname="{item.channel}" type="D"'
                    f' begin_time="{begin}" end_time="{end}"/>'
                )
            lines.append(" </station>")
        lines.append("</seedlink>")
        return "\n".join(lines).encode("utf-8")

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            while True:
                raw = await asyncio.wait_for(reader.readuntil(b"\r"), timeout=5)
                command = raw.decode("ascii", errors="replace").strip().upper()
                if command.endswith("\n"):
                    command = command.strip()
                if command == "HELLO":
                    writer.write(f"{self.banner_software}\r\n{self.banner_org}\r\n".encode("ascii"))
                elif command.startswith("INFO"):
                    writer.write(pack_info_xml(self.xml_bytes()))
                elif command in {"BYE", "END"}:
                    break
                await writer.drain()
        except (asyncio.IncompleteReadError, asyncio.TimeoutError, ConnectionError):
            pass
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:  # noqa: BLE001
                pass


def fresh_streams(
    *,
    now: datetime | None = None,
    station: str = "A01",
    stale_minutes: int = 0,
    gap: bool = False,
) -> list[MockStream]:
    moment = now or datetime.now(timezone.utc)
    end = moment - timedelta(minutes=stale_minutes)
    if gap:
        return [
            MockStream(
                channel="HHZ",
                begin=end - timedelta(hours=6),
                end=end - timedelta(hours=3),
                station=station,
            ),
            MockStream(
                channel="HHZ",
                begin=end - timedelta(hours=2),
                end=end,
                station=station,
            ),
            MockStream(channel="HHN", begin=end - timedelta(hours=6), end=end, station=station),
            MockStream(channel="HHE", begin=end - timedelta(hours=6), end=end, station=station),
        ]
    return [
        MockStream(channel=axis, begin=end - timedelta(hours=6), end=end, station=station)
        for axis in ("HHZ", "HHN", "HHE")
    ]


async def serve_seedlink(streams: Iterable[MockStream] | None = None) -> SeedLinkMock:
    mock = SeedLinkMock(streams=list(streams) if streams is not None else fresh_streams())
    await mock.__aenter__()
    return mock


def _fmt(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


async def _main() -> None:
    port = int(os.environ.get("SEEDLINK_MOCK_PORT", "18000"))
    mock = SeedLinkMock(streams=fresh_streams())
    server = await asyncio.start_server(mock._handle, "0.0.0.0", port)
    mock._server = server
    mock.port = port
    print(f"가상 SeedLink  {mock.uri}")
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(_main())
