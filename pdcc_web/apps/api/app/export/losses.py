"""SEED 변환 손실. 70자 코멘트, 25자 FIR, 비 ASCII 사이트명, 확장 필드."""

from __future__ import annotations

from .slice import iter_channels
from ..inventory.xmlutil import child_text, local, parse_root

COMMENT_MAX = 70
SITE_MAX = 60
FIR_NAME_MAX = 25
SEED_NETWORK_LEN = 2
SEED_STATION_MAX = 5
SEED_CHANNEL_LEN = 3
SEED_LOCATION_MAX = 2


def _ascii_ok(value: str | None) -> bool:
    if not value:
        return True
    return all(ord(ch) < 128 for ch in value)


def _nslc(net: str, sta: str, loc: str, cha: str) -> str:
    loc_disp = loc or "--"
    return f"{net}.{sta}.{loc_disp}.{cha}"


def collect_export_issues(xml: str, *, kind: str) -> tuple[list[dict], list[dict], list[dict]]:
    """errors (차단), losses (확인 필요), drops (안내)."""
    errors: list[dict] = []
    losses: list[dict] = []
    drops: list[dict] = []
    root = parse_root(xml)
    for net in root.iter():
        if local(net.tag) != "Network":
            continue
        net_code = net.get("code") or ""
        if kind == "dataless" and len(net_code) != SEED_NETWORK_LEN:
            errors.append(
                {
                    "nslc": net_code or "?",
                    "field": "network",
                    "kind": "error",
                    "reason": f"{net_code or '?'}: 네트워크 코드는 SEED에서 2자여야 합니다",
                }
            )
        for sta in net:
            if local(sta.tag) != "Station":
                continue
            sta_code = sta.get("code") or ""
            if len(sta_code) > SEED_STATION_MAX:
                errors.append(
                    {
                        "nslc": f"{net_code}.{sta_code}",
                        "field": "station",
                        "kind": "error",
                        "reason": f"{net_code}.{sta_code}: 관측소 코드는 5자 이하여야 합니다",
                    }
                )
            site = sta.find("{*}Site")
            site_name = child_text(site, "Name") if site is not None else None
            if site_name and not _ascii_ok(site_name):
                losses.append(
                    {
                        "nslc": f"{net_code}.{sta_code}",
                        "field": "site_name",
                        "kind": "replace",
                        "original": site_name,
                        "result": sta_code,
                        "reason": f"{net_code}.{sta_code}: 한글 사이트명을 관측소 코드로 대체합니다",
                    }
                )
            elif site_name and len(site_name) > SITE_MAX:
                losses.append(
                    {
                        "nslc": f"{net_code}.{sta_code}",
                        "field": "site_name",
                        "kind": "truncate",
                        "original": site_name,
                        "result": site_name[:SITE_MAX],
                        "reason": f"{net_code}.{sta_code}: 사이트명이 {SITE_MAX}자로 잘립니다",
                    }
                )
            if sta.find("{*}Operator") is not None:
                drops.append(
                    {
                        "nslc": f"{net_code}.{sta_code}",
                        "field": "operator",
                        "kind": "drop",
                        "reason": f"{net_code}.{sta_code}: Operator는 dataless SEED에 없습니다",
                    }
                )
            for cha in sta:
                if local(cha.tag) != "Channel":
                    continue
                loc = cha.get("locationCode") or ""
                code = cha.get("code") or ""
                nslc = _nslc(net_code, sta_code, loc, code)
                if len(code) != SEED_CHANNEL_LEN:
                    errors.append(
                        {
                            "nslc": nslc,
                            "field": "channel",
                            "kind": "error",
                            "reason": f"{nslc}: 채널 코드는 3자여야 합니다",
                        }
                    )
                if len(loc) > SEED_LOCATION_MAX:
                    errors.append(
                        {
                            "nslc": nslc,
                            "field": "location",
                            "kind": "error",
                            "reason": f"{nslc}: 위치코드는 2자 이하여야 합니다",
                        }
                    )
                has_response = cha.find("{*}Response") is not None
                if not has_response:
                    errors.append(
                        {
                            "nslc": nslc,
                            "field": "response",
                            "kind": "error",
                            "reason": f"{nslc}: 계측기 응답이 없습니다",
                        }
                    )
                for comment in cha.findall("{*}Comment"):
                    value = child_text(comment, "Value") or ""
                    if len(value) > COMMENT_MAX:
                        losses.append(
                            {
                                "nslc": nslc,
                                "field": "comment",
                                "kind": "truncate",
                                "original": value,
                                "result": value[:COMMENT_MAX],
                                "reason": f"{nslc}: 코멘트가 {COMMENT_MAX}자로 잘립니다",
                            }
                        )
                    elif value:
                        drops.append(
                            {
                                "nslc": nslc,
                                "field": "comment",
                                "kind": "drop",
                                "reason": f"{nslc}: 채널 코멘트는 dataless SEED 약어로만 남습니다",
                            }
                        )
                for fir in cha.findall(".//{*}FIR"):
                    name = child_text(fir, "Name") or ""
                    if len(name) > FIR_NAME_MAX:
                        losses.append(
                            {
                                "nslc": nslc,
                                "field": "fir_name",
                                "kind": "truncate",
                                "original": name,
                                "result": name[:FIR_NAME_MAX],
                                "reason": f"{nslc}: FIR 이름이 {FIR_NAME_MAX}자로 잘립니다",
                            }
                        )
    return errors, losses, drops


def has_channels(xml: str) -> bool:
    return bool(iter_channels(xml))
