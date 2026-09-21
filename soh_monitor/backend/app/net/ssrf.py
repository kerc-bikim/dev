"""기록계 연결 시험 SSRF 차단.

관리 API 의 연결 시험·Probe·미리보기는 운영자가 넣은 호스트로 HTTP 를 나간다.
화이트리스트가 없으면 이 통로가 클라우드 메타데이터나 내부 관리 포트로 열린다.

규칙
  * 허용 대역에 들어 있는 주소만 나간다. 기본값은 RFC1918.
  * 링크 로컬·메타데이터·멀티캐스트·미지정 주소는 허용 대역에 넣어도 거부한다.
  * 호스트명은 모든 해석 결과가 허용돼야 한다. 하나라도 바깥이면 거부한다.
  * 해석에 실패하면 거부한다. 모르는 이름을 통과시키면 DNS 재바인딩 자리가 된다.
"""
from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass

# 허용 목록에 넣어도 나가지 않는 대역. 클라우드 메타데이터와 비유니캐스트.
ALWAYS_DENIED_NETWORKS = (
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("224.0.0.0/4"),
    ipaddress.ip_network("255.255.255.255/32"),
    ipaddress.ip_network("::/128"),
    ipaddress.ip_network("fe80::/10"),
    ipaddress.ip_network("ff00::/8"),
)


class SsrfError(ValueError):
    """연결 대상이 안전하지 않아 요청을 거부한다."""


@dataclass(frozen=True)
class ResolvedTarget:
    hostname: str
    addresses: tuple[str, ...]


def parse_networks(raw: list[str]) -> list[ipaddress._BaseNetwork]:
    networks: list[ipaddress._BaseNetwork] = []
    for item in raw:
        try:
            networks.append(ipaddress.ip_network(item, strict=False))
        except ValueError as exc:
            raise SsrfError(f"허용 대역 형식이 잘못됐다: {item}") from exc
    return networks


def _canonical(address: ipaddress.IPv4Address | ipaddress.IPv6Address):
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        return address.ipv4_mapped
    return address


def _always_denied(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    canonical = _canonical(address)
    return any(canonical in network for network in ALWAYS_DENIED_NETWORKS)


def is_allowed_host(hostname: str, allowed_networks: list[str]) -> bool:
    """호스트가 이미 IP 문자열일 때의 보조 판정.

    호스트명이 IP 가 아니면 False 다. 이름 해석은 `resolve_safe_host` 가 한다.
    """
    try:
        address = _canonical(ipaddress.ip_address(hostname.strip()))
    except ValueError:
        return False
    if _always_denied(address):
        return False
    networks = parse_networks(allowed_networks)
    return any(address in network for network in networks)


def _looks_like_url(hostname: str) -> bool:
    lowered = hostname.lower()
    return "://" in lowered or "/" in hostname or "@" in hostname or "?" in hostname


def resolve_addresses(hostname: str) -> tuple[str, ...]:
    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        pass
    else:
        return (hostname,)

    try:
        results = socket.getaddrinfo(hostname, None, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise SsrfError(f"호스트 이름을 해석할 수 없다: {hostname}") from exc

    addresses: list[str] = []
    seen: set[str] = set()
    for item in results:
        sockaddr = item[4]
        if not sockaddr:
            continue
        ip = sockaddr[0]
        if ip not in seen:
            seen.add(ip)
            addresses.append(ip)
    if not addresses:
        raise SsrfError(f"호스트 이름을 해석할 수 없다: {hostname}")
    return tuple(addresses)


def resolve_safe_host(hostname: str, allowed_networks: list[str]) -> ResolvedTarget:
    """연결 시험 전에 호스트를 검사한다. 통과한 주소 목록을 돌려준다."""
    host = (hostname or "").strip().rstrip(".")
    if not host:
        raise SsrfError("호스트명이 비어 있다")
    if _looks_like_url(host):
        raise SsrfError("호스트명에 URL 문자가 들어 있다")
    if host.lower() in {"localhost"}:
        # localhost 는 루프백으로 해석된다. 허용 대역에 루프백이 있을 때만 통과한다.
        pass

    try:
        networks = parse_networks(allowed_networks)
    except SsrfError:
        raise
    if not networks:
        raise SsrfError("허용된 기록계 대역이 비어 있다")

    addresses = resolve_addresses(host)
    accepted: list[str] = []
    for raw in addresses:
        try:
            address = _canonical(ipaddress.ip_address(raw))
        except ValueError as exc:
            raise SsrfError(f"해석 결과가 주소가 아니다: {raw}") from exc
        if _always_denied(address):
            raise SsrfError(f"메타데이터·링크 로컬 주소로는 나갈 수 없다: {address}")
        if not any(address in network for network in networks):
            raise SsrfError(f"허용 대역 밖의 주소다: {address}")
        accepted.append(str(address))
    return ResolvedTarget(hostname=host, addresses=tuple(accepted))
