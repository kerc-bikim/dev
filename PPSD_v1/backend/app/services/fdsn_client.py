"""Thin wrapper around obspy.clients.fdsn.Client with helpers used by the API."""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import List, Tuple

from obspy import Inventory, Stream, UTCDateTime
from obspy.clients.fdsn import Client
from obspy.clients.fdsn.header import FDSNException, FDSNNoDataException

from ..config import settings
from ..models.schemas import ChannelInfo, NetworkInfo, StationInfo

logger = logging.getLogger(__name__)


class FDSNError(RuntimeError):
    """Raised for user-visible FDSNWS problems."""


@lru_cache(maxsize=1)
def get_client() -> Client:
    logger.info("Creating FDSN client for %s", settings.FDSNWS_URL)
    return Client(
        base_url=settings.FDSNWS_URL,
        timeout=settings.FDSN_TIMEOUT_SECONDS,
    )


def _to_utc(dt) -> UTCDateTime | None:
    if dt is None:
        return None
    return UTCDateTime(dt)


def list_networks() -> List[NetworkInfo]:
    client = get_client()
    try:
        inv: Inventory = client.get_stations(level="network")
    except FDSNException as exc:  # pragma: no cover
        raise FDSNError(f"Failed to list networks: {exc}") from exc

    out: List[NetworkInfo] = []
    for net in inv:
        out.append(
            NetworkInfo(
                code=net.code,
                description=net.description,
                start_date=net.start_date.datetime if net.start_date else None,
                end_date=net.end_date.datetime if net.end_date else None,
                total_stations=net.total_number_of_stations,
            )
        )
    return sorted(out, key=lambda n: n.code)


def list_stations(network: str) -> List[StationInfo]:
    client = get_client()
    try:
        inv = client.get_stations(network=network, level="station")
    except FDSNException as exc:
        raise FDSNError(f"Failed to list stations for {network}: {exc}") from exc

    out: List[StationInfo] = []
    for net in inv:
        for sta in net:
            out.append(
                StationInfo(
                    network=net.code,
                    code=sta.code,
                    name=sta.site.name if sta.site else None,
                    latitude=float(sta.latitude) if sta.latitude is not None else None,
                    longitude=float(sta.longitude) if sta.longitude is not None else None,
                    elevation=float(sta.elevation) if sta.elevation is not None else None,
                    start_date=sta.start_date.datetime if sta.start_date else None,
                    end_date=sta.end_date.datetime if sta.end_date else None,
                )
            )
    return sorted(out, key=lambda s: (s.network, s.code))


CHANNEL_SEARCH_LIMIT = 500


def list_channels(
    network: str,
    station: str,
    location: str | None = None,
    channel: str | None = None,
) -> List[ChannelInfo]:
    """List channels. ``location`` / ``channel`` accept FDSN wildcards ``*`` / ``?``.

    Empty location is sent as ``--``. Omit location/channel to return every
    channel for the network/station (dropdown behaviour).
    """
    client = get_client()
    kwargs: dict = {
        "network": network,
        "station": station,
        "level": "channel",
    }
    if location is not None:
        kwargs["location"] = "--" if location == "" else location
    if channel is not None:
        kwargs["channel"] = channel or "*"

    try:
        inv = client.get_stations(**kwargs)
    except FDSNNoDataException:
        return []
    except FDSNException as exc:
        status = getattr(exc, "code", None)
        if status == 204 or "204" in str(exc):
            return []
        nslc = f"{network}.{station}.{location or '*'}.{channel or '*'}"
        raise FDSNError(f"Failed to list channels for {nslc}: {exc}") from exc

    out: List[ChannelInfo] = []
    seen: set[Tuple[str, str, str, str]] = set()
    for net in inv:
        for sta in net:
            for cha in sta:
                loc = cha.location_code or ""
                key = (net.code, sta.code, loc, cha.code)
                if key in seen:
                    continue
                seen.add(key)
                out.append(
                    ChannelInfo(
                        network=net.code,
                        station=sta.code,
                        location=loc,
                        channel=cha.code,
                        sample_rate=float(cha.sample_rate)
                        if cha.sample_rate is not None
                        else None,
                        start_date=cha.start_date.datetime if cha.start_date else None,
                        end_date=cha.end_date.datetime if cha.end_date else None,
                        azimuth=float(cha.azimuth) if cha.azimuth is not None else None,
                        dip=float(cha.dip) if cha.dip is not None else None,
                    )
                )
                if len(out) >= CHANNEL_SEARCH_LIMIT:
                    return sorted(
                        out,
                        key=lambda c: (c.network, c.station, c.location, c.channel),
                    )
    return sorted(
        out,
        key=lambda c: (c.network, c.station, c.location, c.channel),
    )


def get_waveforms_with_response(
    network: str,
    station: str,
    location: str,
    channel: str,
    starttime: UTCDateTime,
    endtime: UTCDateTime,
) -> Tuple[Stream, Inventory]:
    """Fetch waveforms and matching response inventory."""
    client = get_client()
    loc = location if location else "--"
    try:
        st: Stream = client.get_waveforms(
            network=network,
            station=station,
            location=loc,
            channel=channel,
            starttime=starttime,
            endtime=endtime,
        )
    except FDSNException as exc:
        raise FDSNError(f"No waveforms available: {exc}") from exc

    if len(st) == 0:
        raise FDSNError(
            "No waveforms returned for the requested time window."
        )

    try:
        inv = client.get_stations(
            network=network,
            station=station,
            location=loc,
            channel=channel,
            starttime=starttime,
            endtime=endtime,
            level="response",
        )
    except FDSNException as exc:
        raise FDSNError(f"No response metadata available: {exc}") from exc

    return st, inv
