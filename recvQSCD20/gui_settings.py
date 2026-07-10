# -*- coding: utf-8 -*-

"""GUI 런타임 설정 — recvQSCD20_gui_settings.json (BIN_FILE_MAGIC 제외)."""

from __future__ import annotations



import json

import os

from dataclasses import asdict, dataclass, field, fields

from typing import Any, Dict, List, Optional, Tuple



SETTINGS_FILENAME = "recvQSCD20_gui_settings.json"



# field_name -> (라벨, 한글 툴팁, 타입, min, max)

SETTING_UI_SPECS: Dict[str, Tuple[str, str, str, Optional[int], Optional[int]]] = {

    "log_save_dir": (

        "로그 저장 디렉터리",

        "텍스트 로그(.QSCD.log)가 저장되는 폴더입니다. "

        "상대 경로이면 프로그램(작업) 디렉터리 기준입니다. 기본: logs",

        "path",

        None,

        None,

    ),

    "bin_save_dir": (

        "바이너리 저장 디렉터리",

        "QCDX 바이너리(.QSCD20.bin)가 저장되는 폴더입니다. "

        "상대 경로이면 프로그램(작업) 디렉터리 기준입니다. 기본: bin",

        "path",

        None,

        None,

    ),

    "default_port": (

        "UDP 기본 포트",

        "메인 화면 우측에 처음 표시되는 UDP 포트 번호입니다.",

        "int",

        1,

        65535,

    ),

    "default_time_window_sec": (

        "기본 표시 구간(초)",

        "Live·File Viewer 시간 콤보의 기본 선택값(초)입니다.",

        "int",

        30,

        7200,

    ),

    "time_window_choices": (

        "시간 콤보 목록(초)",

        "시간 선택 콤보박스에 나올 구간(초)을 쉼표로 구분해 입력합니다. 예: 60, 120, 600",

        "int_list",

        None,

        None,

    ),

    "default_panels": (

        "기본 ON 차트 패널",

        "프로그램 시작 시 체크될 차트 ID를 쉼표로 구분합니다. "

        "예: diff, max, pga (가능: wmma_ud, wmma_ns, wmma_ew, tmm_ud, tmm_ns, tmm_ew)",

        "str_list",

        None,

        None,

    ),

    "default_show_legend": (

        "범례·최근값 기본 표시",

        "시작 시 차트 범례와 상단 최근값 라벨을 표시할지 여부입니다.",

        "bool",

        None,

        None,

    ),

    "log_max_lines": (

        "로그 최대 줄 수",

        "로그 뷰어 화면에 유지할 최대 줄 수입니다. 초과 시 오래된 줄이 삭제됩니다.",

        "int",

        500,

        100000,

    ),

    "chart_refresh_ms": (

        "차트 갱신 주기(ms)",

        "패킷 배치 처리 및 차트를 다시 그리는 타이머 간격(밀리초)입니다.",

        "int",

        50,

        5000,

    ),

    "packet_drain_max": (

        "패킷 배치 처리 상한",

        "한 번의 타이머 주기에 처리할 최대 패킷 개수입니다.",

        "int",

        50,

        10000,

    ),

    "bin_flush_every": (

        "바이너리 flush 주기",

        "몇 개의 패킷을 저장할 때마다 디스크에 flush 할지 설정합니다.",

        "int",

        1,

        500,

    ),

    "live_log_verbose": (

        "Live 상세 로그",

        "켜면 패킷마다 여러 줄 상세 로그, 끄면 한 줄 요약 로그를 기록합니다.",

        "bool",

        None,

        None,

    ),

    "recv_delay_alert_sec": (

        "수신 지연 경고(초)",

        "선택 관측소 기준 이 시간(초) 이상 패킷이 없으면 최종 수신 라벨이 빨갛게 깜빡입니다.",

        "int",

        1,

        3600,

    ),

    "recv_alert_blink_ms": (

        "지연 깜빡임 주기(ms)",

        "수신 지연 경고 시 라벨이 깜빡이는 간격(밀리초)입니다.",

        "int",

        100,

        5000,

    ),

    "sock_timeout_sec": (

        "UDP 소켓 timeout(초)",

        "수신 스레드에서 recv 대기 시간(초)입니다. Stop 응답성에도 영향을 줍니다.",

        "float",

        0,

        10,

    ),

    "sock_timeout_count": (

        "UDP 무수신 경고 횟수",

        "timeout이 연속 이 횟수만큼 발생하면 경고 로그를 남깁니다. "

        "실제 경고 시간 ≈ timeout(초) × 이 값",

        "int",

        1,

        1000,

    ),

}





def work_directory() -> str:

    """프로그램(스크립트) 디렉터리 — 상대 경로 설정의 기준."""

    return os.path.dirname(os.path.abspath(__file__))





def resolve_data_dir(path: str) -> str:

    p = (path or "").strip()

    if not p:

        raise ValueError("저장 디렉터리 경로가 비어 있습니다.")

    if not os.path.isabs(p):

        p = os.path.join(work_directory(), p)

    return os.path.normpath(p)





@dataclass

class GuiSettings:

    log_save_dir: str = "logs"

    bin_save_dir: str = "bin"

    default_port: int = 9908

    default_time_window_sec: int = 600

    time_window_choices: List[int] = field(default_factory=lambda: [60, 120, 600, 1200, 1800])

    default_panels: List[str] = field(default_factory=lambda: ["diff", "max", "pga"])

    default_show_legend: bool = True

    log_max_lines: int = 5000

    chart_refresh_ms: int = 200

    packet_drain_max: int = 800

    bin_flush_every: int = 32

    live_log_verbose: bool = False

    recv_delay_alert_sec: int = 10

    recv_alert_blink_ms: int = 500

    sock_timeout_sec: float = 0.5

    sock_timeout_count: int = 120



    def resolved_log_dir(self) -> str:

        return resolve_data_dir(self.log_save_dir)



    def resolved_bin_dir(self) -> str:

        return resolve_data_dir(self.bin_save_dir)



    def default_panels_frozen(self) -> frozenset:

        return frozenset(self.default_panels)



    def time_window_choices_tuple(self) -> Tuple[int, ...]:

        return tuple(self.time_window_choices)





def settings_file_path() -> str:

    return os.path.join(work_directory(), SETTINGS_FILENAME)





def default_settings() -> GuiSettings:

    return GuiSettings()





def parse_int_list(text: str) -> List[int]:

    parts = [p.strip() for p in text.replace("，", ",").split(",") if p.strip()]

    if not parts:

        raise ValueError("숫자 목록이 비어 있습니다.")

    out: List[int] = []

    for p in parts:

        out.append(int(p))

    return out





def parse_str_list(text: str) -> List[str]:

    parts = [p.strip() for p in text.replace("，", ",").split(",") if p.strip()]

    if not parts:

        raise ValueError("목록이 비어 있습니다.")

    return parts





def validate_settings(s: GuiSettings, valid_panel_ids: Optional[List[str]] = None) -> None:

    try:

        resolve_data_dir(s.log_save_dir)

        resolve_data_dir(s.bin_save_dir)

    except ValueError as e:

        raise ValueError(str(e)) from e

    if s.default_port < 1 or s.default_port > 65535:

        raise ValueError("UDP 기본 포트는 1~65535 이어야 합니다.")

    if not s.time_window_choices:

        raise ValueError("시간 콤보 목록이 비어 있습니다.")

    if s.default_time_window_sec not in s.time_window_choices:

        raise ValueError("기본 표시 구간은 시간 콤보 목록에 포함되어야 합니다.")

    if valid_panel_ids is not None:

        for pid in s.default_panels:

            if pid not in valid_panel_ids:

                raise ValueError(f"알 수 없는 패널 ID: {pid}")

    if s.sock_timeout_sec < 0:

        raise ValueError("UDP 소켓 timeout은 0 이상이어야 합니다.")





def settings_to_dict(s: GuiSettings) -> Dict[str, Any]:

    return asdict(s)





def settings_from_dict(data: Dict[str, Any]) -> GuiSettings:

    base = default_settings()

    names = {f.name for f in fields(base)}

    kwargs: Dict[str, Any] = {}

    for key in names:

        if key in data:

            kwargs[key] = data[key]

    s = GuiSettings(**kwargs)

    s.time_window_choices = [int(x) for x in s.time_window_choices]

    s.default_panels = [str(x).strip() for x in s.default_panels]

    s.log_save_dir = str(s.log_save_dir).strip() or "logs"

    s.bin_save_dir = str(s.bin_save_dir).strip() or "bin"

    return s





def load_settings() -> GuiSettings:

    path = settings_file_path()

    if not os.path.isfile(path):

        return default_settings()

    try:

        with open(path, encoding="utf-8") as f:

            data = json.load(f)

        if not isinstance(data, dict):

            return default_settings()

        return settings_from_dict(data)

    except (OSError, json.JSONDecodeError, TypeError, ValueError):

        return default_settings()





def save_settings(s: GuiSettings) -> None:

    path = settings_file_path()

    with open(path, "w", encoding="utf-8") as f:

        json.dump(settings_to_dict(s), f, ensure_ascii=False, indent=2)

        f.write("\n")

