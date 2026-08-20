#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
QSCD20 UDP 수신 GUI (PyQt5 + pyqtgraph) — 설정: recvQSCD20_gui_settings.json

실행:
    pip install -r requirements.txt
    python recvQSCD20_gui.py

메뉴: 기본 설정. 로그 뷰어는 Live 탭 상단 아이콘. 수신(UDP·Start/Stop)은 메인 우측 패널.
"""
from __future__ import annotations

import datetime
import logging
import os
import queue
import socket
import struct
import sys
import time
import zlib
from typing import Any, Dict, List, NamedTuple, Optional, Tuple

import numpy as np
import pyqtgraph as pg
from PyQt5 import QtCore, QtGui, QtWidgets

try:
    from PyQt5.QtWebEngineWidgets import QWebEnginePage, QWebEngineView

    _HAS_WEBENGINE = True
except ImportError:
    QWebEnginePage = None  # type: ignore[misc, assignment]
    QWebEngineView = None  # type: ignore[misc, assignment]
    _HAS_WEBENGINE = False

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
from copy import deepcopy

from gui_settings import (
    GuiSettings,
    MIN_SOCK_TIMEOUT_SEC,
    SETTING_UI_SPECS,
    default_settings,
    load_settings,
    parse_int_list,
    parse_str_list,
    path_for_settings_storage,
    pending_apply_notes,
    sanitize_file_prefix,
    save_settings,
    settings_file_path,
    validate_settings,
    work_directory,
)

FALLBACK_VERSION = "3.10"


def _load_gui_version() -> str:
    try:
        vpath = os.path.join(os.path.dirname(os.path.abspath(__file__)), "VERSION")
        with open(vpath, encoding="utf-8") as f:
            return f.read().strip() or FALLBACK_VERSION
    except OSError:
        return FALLBACK_VERSION


GUI_VERSION = _load_gui_version()

HOST = "0.0.0.0"
QSCD_LEN = 120
QSCD20_FMT = ">Lccc2s3sIfffffffffffffffffffffffffcc2s"
# GUI 바이너리: 매직 + (120B 패킷 + 8B recv−data TimeDiff) — 설정 파일에서 변경 불가
BIN_FILE_MAGIC = b"QCDX\x01"
QSCD_BIN_REC_LEN = QSCD_LEN + 8
DIFF_PACK_FMT = ">d"
REPLAY_SUFFIX = ".QSCD20.replay"

KST_OFFSET = 9 * 3600

# 아래 값은 recvQSCD20_gui_settings.json 에서 로드 (_apply_gui_settings)
DEFAULT_SHOW_LEGEND = True
DEFAULT_PORT = 9908
TIME_WINDOW_CHOICES = (60, 120, 600, 1200, 1800)
DEFAULT_TIME_WINDOW_SEC = 600
LOG_MAX_LINES = 5000
CHART_REFRESH_MS = 200
PACKET_DRAIN_MAX = 800
PACKET_QUEUE_MAX = 20000
BIN_FLUSH_EVERY = 32
LIVE_LOG_VERBOSE = False
GUI_LOG_VERBOSE = False
RECV_DELAY_ALERT_SEC = 10
RECV_ALERT_BLINK_MS = 500
SockTimeOut = 0.5
SockTimeOutCount = 120
_runtime_settings: GuiSettings = default_settings()

APP_STYLESHEET = """
QMainWindow { background: #dde3ea; }
QGroupBox {
    font-weight: 600;
    border: 1px solid #b8c4d4;
    border-radius: 6px;
    margin-top: 10px;
    padding: 8px 6px 6px 6px;
    background: #eef2f7;
}
QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 6px; }
QTabWidget::pane {
    border: 2px solid #94a3b8;
    border-radius: 8px;
    background: #f1f5f9;
    top: -1px;
}
QTabBar::tab {
    background: #cbd5e1;
    color: #334155;
    font-weight: 600;
    min-width: 140px;
    padding: 10px 32px;
    margin-right: 4px;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
}
QTabBar::tab:selected {
    background: #ffffff;
    color: #0f172a;
    font-weight: 600;
}
QToolButton#BtnLogViewer {
    background: #ffffff;
    border: 1px solid #94a3b8;
    border-radius: 6px;
    padding: 3px;
}
QToolButton#BtnLogViewer:hover {
    background: #e0f2fe;
    border-color: #0284c7;
}
QToolButton#BtnLogViewer:pressed {
    background: #bae6fd;
}
QFrame#MetaBar, QFrame#FileMetaBar {
    background: #ffffff;
    border: 1px solid #cbd5e1;
    border-radius: 6px;
    padding: 4px;
}
QFrame#ChartArea {
    background: #ffffff;
    border: 2px solid #64748b;
    border-radius: 8px;
}
QFrame#ChartPanel {
    background: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 6px;
    margin: 2px 4px;
}
QScrollArea#ChartScroll {
    background: #f8fafc;
    border: none;
}
QPlainTextEdit#LogView {
    background: #1e293b;
    color: #e2e8f0;
    font-family: Consolas, monospace;
    font-size: 11px;
    border: 1px solid #475569;
    border-radius: 6px;
}
QLabel#LastRecvLabel {
    padding: 4px 10px;
    border-radius: 4px;
    font-weight: 600;
}
QPushButton#BtnStart {
    background: #16a34a;
    color: white;
    font-weight: bold;
    padding: 6px 14px;
    border-radius: 4px;
}
QPushButton#BtnStop {
    background: #dc2626;
    color: white;
    font-weight: bold;
    padding: 6px 14px;
    border-radius: 4px;
}
"""

Y_LABEL_DIFF = "시간(초)"
Y_LABEL_GAL = "gal(cm/sec2)"

# panel_id -> (title, [(curve_id, legend, rgba), ...])
PANEL_DEFS: Dict[str, Tuple[str, List[Tuple[str, str, Tuple[int, int, int, int]]]]] = {
    "diff": (
        "Time Diff (recv − data)",
        [("diff", "Diff", (220, 50, 50, 255))],
    ),
    "max": (
        "Maximum (Z, N, E)",
        [
            ("max_Z", "Z", (160, 0, 160, 255)),
            ("max_N", "N", (0, 140, 140, 255)),
            ("max_E", "E", (140, 100, 0, 255)),
        ],
    ),
    "pga": (
        "PGA (H, T)",
        [
            ("pga_H", "H", (120, 120, 0, 255)),
            ("pga_T", "T", (0, 120, 120, 255)),
        ],
    ),
    "wmma_ud": (
        "U-D WMMA",
        [
            ("wmma_ud_m", "m", (200, 80, 80, 255)),
            ("wmma_ud_M", "M", (80, 80, 200, 255)),
            ("wmma_ud_A", "A", (80, 160, 80, 255)),
        ],
    ),
    "wmma_ns": (
        "N-S WMMA",
        [
            ("wmma_ns_m", "m", (200, 80, 80, 255)),
            ("wmma_ns_M", "M", (80, 80, 200, 255)),
            ("wmma_ns_A", "A", (80, 160, 80, 255)),
        ],
    ),
    "wmma_ew": (
        "E-W WMMA",
        [
            ("wmma_ew_m", "m", (200, 80, 80, 255)),
            ("wmma_ew_M", "M", (80, 80, 200, 255)),
            ("wmma_ew_A", "A", (80, 160, 80, 255)),
        ],
    ),
    "tmm_ud": (
        "U-D TMM",
        [
            ("tmm_ud_m", "m", (180, 100, 40, 255)),
            ("tmm_ud_M", "M", (40, 100, 180, 255)),
        ],
    ),
    "tmm_ns": (
        "N-S TMM",
        [
            ("tmm_ns_m", "m", (180, 100, 40, 255)),
            ("tmm_ns_M", "M", (40, 100, 180, 255)),
        ],
    ),
    "tmm_ew": (
        "E-W TMM",
        [
            ("tmm_ew_m", "m", (180, 100, 40, 255)),
            ("tmm_ew_M", "M", (40, 100, 180, 255)),
        ],
    ),
}

SERIES_IDX: Dict[str, int] = {
    "wmma_ud_m": 7,
    "wmma_ud_M": 8,
    "wmma_ud_A": 9,
    "wmma_ns_m": 10,
    "wmma_ns_M": 11,
    "wmma_ns_A": 12,
    "wmma_ew_m": 13,
    "wmma_ew_M": 14,
    "wmma_ew_A": 15,
    "tmm_ud_m": 16,
    "tmm_ud_M": 17,
    "tmm_ns_m": 18,
    "tmm_ns_M": 19,
    "tmm_ew_m": 20,
    "tmm_ew_M": 21,
    "max_Z": 22,
    "max_N": 23,
    "max_E": 24,
    "pga_H": 25,
    "pga_T": 26,
}

DEFAULT_PANELS = frozenset({"diff", "max", "pga"})


def _apply_gui_settings(s: Optional[GuiSettings] = None, *, fallback: bool = False) -> GuiSettings:
    """설정 파일 값을 모듈 전역 및 _runtime_settings에 반영."""
    global _runtime_settings
    global DEFAULT_PORT, DEFAULT_TIME_WINDOW_SEC, TIME_WINDOW_CHOICES
    global DEFAULT_PANELS, DEFAULT_SHOW_LEGEND, LOG_MAX_LINES, CHART_REFRESH_MS
    global PACKET_DRAIN_MAX, PACKET_QUEUE_MAX, BIN_FLUSH_EVERY, LIVE_LOG_VERBOSE
    global RECV_DELAY_ALERT_SEC, RECV_ALERT_BLINK_MS, SockTimeOut, SockTimeOutCount

    cfg = s if s is not None else load_settings()
    try:
        validate_settings(cfg, list(PANEL_DEFS.keys()))
    except (ValueError, TypeError):
        if not fallback:
            raise
        cfg = default_settings()
        validate_settings(cfg, list(PANEL_DEFS.keys()))
    _runtime_settings = cfg

    DEFAULT_PORT = int(cfg.default_port)
    DEFAULT_TIME_WINDOW_SEC = int(cfg.default_time_window_sec)
    TIME_WINDOW_CHOICES = cfg.time_window_choices_tuple()
    DEFAULT_PANELS = cfg.default_panels_frozen()
    DEFAULT_SHOW_LEGEND = bool(cfg.default_show_legend)
    LOG_MAX_LINES = int(cfg.log_max_lines)
    CHART_REFRESH_MS = int(cfg.chart_refresh_ms)
    PACKET_DRAIN_MAX = int(cfg.packet_drain_max)
    PACKET_QUEUE_MAX = int(cfg.packet_queue_max)
    BIN_FLUSH_EVERY = int(cfg.bin_flush_every)
    LIVE_LOG_VERBOSE = bool(cfg.live_log_verbose)
    RECV_DELAY_ALERT_SEC = int(cfg.recv_delay_alert_sec)
    RECV_ALERT_BLINK_MS = int(cfg.recv_alert_blink_ms)
    SockTimeOut = float(cfg.sock_timeout_sec)
    SockTimeOutCount = int(cfg.sock_timeout_count)
    return cfg


_apply_gui_settings(load_settings(), fallback=True)

pg.setConfigOptions(
    antialias=False,
    background="#ffffff",
    foreground="#1e293b",
    useOpenGL=False,
)


# ---------------------------------------------------------------------------
# KST axis
# ---------------------------------------------------------------------------
class ChartViewBox(pg.ViewBox):
    """왼쪽 드래그: 영역 줌인(RectMode), 더블클릭: 줌아웃(자동 범위)."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.setMouseMode(pg.ViewBox.RectMode)
        self.user_zoomed: bool = False

    def mouseDragEvent(self, ev: Any, axis: Any = None) -> None:
        if ev.button() == QtCore.Qt.LeftButton:
            self.user_zoomed = True
        super().mouseDragEvent(ev, axis)

    def mouseDoubleClickEvent(self, ev: Any) -> None:
        if ev.button() == QtCore.Qt.LeftButton:
            self.user_zoomed = False
            self.autoRange(padding=0.02)
            ev.accept()
        else:
            super().mouseDoubleClickEvent(ev)


class KSTTimeAxisItem(pg.AxisItem):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.enableAutoSIPrefix(False)
        self.setLabel(text="시각 (KST)", units=None)

    def tickStrings(self, values: List[float], scale: float, spacing: float) -> List[str]:
        out: List[str] = []
        for v in values:
            try:
                t = datetime.datetime.utcfromtimestamp(v + KST_OFFSET)
                out.append(t.strftime("%H:%M:%S"))
            except (OSError, ValueError, OverflowError):
                out.append("")
        return out


class PlainGalAxisItem(pg.AxisItem):
    """gal 축: SI 접두(k/M) 없이 데이터 값 그대로 표시."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.enableAutoSIPrefix(False)

    def tickStrings(self, values: List[float], scale: float, spacing: float) -> List[str]:
        out: List[str] = []
        for v in values:
            val = float(v) * float(scale)
            if not np.isfinite(val):
                out.append("")
            elif abs(val) >= 1000 or (0 < abs(val) < 0.0001):
                out.append(f"{val:.6g}")
            else:
                s = f"{val:.6f}".rstrip("0").rstrip(".")
                out.append(s if s else "0")
        return out


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _decode_bytes(b: bytes) -> str:
    return b.decode("utf-8", errors="replace").strip("\x00").strip()


def byte_to_u8(value: Any) -> int:
    if isinstance(value, bytes):
        return value[0] & 0xFF
    if isinstance(value, int):
        return value & 0xFF
    if isinstance(value, str):
        return ord(value) & 0xFF
    return int(value) & 0xFF


def describe_quality_flag(q: int) -> str:
    q &= 0xFF
    if q == 0x00:
        return "Good data"
    if q == 0x01:
        return "GPS Unlock"
    if q == 0x02:
        return "REBOOT"
    return "Reserved for Future Use"


def station_code_bytes(myqscd: Tuple[Any, ...]) -> bytes:
    p4, p5 = myqscd[4], myqscd[5]
    b4 = p4 if isinstance(p4, (bytes, bytearray)) else bytes(p4)
    b5 = p5 if isinstance(p5, (bytes, bytearray)) else bytes(p5)
    return bytes(b4) + bytes(b5)


def station_code_str(myqscd: Tuple[Any, ...]) -> str:
    raw = station_code_bytes(myqscd)
    return _decode_bytes(raw).strip() or raw.decode("latin-1", errors="replace").strip()


def location_str(myqscd: Tuple[Any, ...]) -> str:
    loc = myqscd[34]
    b = loc if isinstance(loc, (bytes, bytearray)) else bytes(loc)
    return _decode_bytes(b).strip()


def format_station_code_line(myqscd: Tuple[Any, ...]) -> str:
    """로그용: Station + Location (hex 없음)."""
    code = station_code_str(myqscd)
    loc = location_str(myqscd)
    if code and loc:
        return f"{code}  Location: {loc}"
    if loc:
        return f"Location: {loc}"
    return code or "—"


def format_quality_flag_line(myqscd: Tuple[Any, ...]) -> str:
    q = byte_to_u8(myqscd[1])
    return f"0x{q:02X} — {describe_quality_flag(q)}"


def format_kst_dt(epoch_sec: float) -> str:
    t = datetime.datetime.utcfromtimestamp(epoch_sec) + datetime.timedelta(hours=9)
    return t.strftime("%Y-%m-%d %H:%M:%S KST")


def make_log_viewer_icon(px: int = 22) -> QtGui.QIcon:
    """로그 뷰어용 아이콘 — 문서·줄 목록 + 돋보기."""
    dpr = 2
    size = px * dpr
    img = QtGui.QImage(size, size, QtGui.QImage.Format_ARGB32)
    img.fill(QtCore.Qt.transparent)
    p = QtGui.QPainter(img)
    p.setRenderHint(QtGui.QPainter.Antialiasing, True)
    p.scale(dpr, dpr)

    # 종이
    paper = QtCore.QRectF(1.5, 1.8, 13.2, 17.6)
    p.setPen(QtGui.QPen(QtGui.QColor("#0369a1"), 1.15))
    p.setBrush(QtGui.QColor("#f8fafc"))
    p.drawRoundedRect(paper, 2.2, 2.2)
    p.setPen(QtGui.QPen(QtGui.QColor("#bae6fd"), 0.9))
    p.drawLine(QtCore.QPointF(3.4, 5.4), QtCore.QPointF(12.6, 5.4))
    p.setPen(QtGui.QPen(QtGui.QColor("#0ea5e9"), 1.15))
    for y in (8.2, 10.8, 13.4, 16.0):
        p.drawLine(QtCore.QPointF(3.6, y), QtCore.QPointF(12.4, y))

    # 돋보기
    lens = QtCore.QRectF(11.2, 11.0, 7.4, 7.4)
    p.setPen(QtGui.QPen(QtGui.QColor("#0f766e"), 1.6))
    p.setBrush(QtGui.QColor(224, 242, 254, 210))
    p.drawEllipse(lens)
    p.setPen(QtGui.QPen(QtGui.QColor("#0f766e"), 2.1, QtCore.Qt.SolidLine, QtCore.Qt.RoundCap))
    p.drawLine(QtCore.QPointF(16.8, 17.0), QtCore.QPointF(20.2, 20.4))
    p.end()

    pix = QtGui.QPixmap.fromImage(img)
    pix.setDevicePixelRatio(dpr)
    return QtGui.QIcon(pix)


def build_second_grid(
    buckets: Dict[int, Dict[str, float]],
    field: str,
    window_sec: int = DEFAULT_TIME_WINDOW_SEC,
) -> Tuple[np.ndarray, np.ndarray]:
    """1초 격자 x(UTC epoch), y(NaN=공백)."""
    if not buckets:
        return np.array([], dtype=np.float64), np.array([], dtype=np.float64)

    max_sec = max(buckets.keys())
    min_sec = max(min(buckets.keys()), max_sec - window_sec + 1)
    secs = np.arange(min_sec, max_sec + 1, dtype=np.float64)
    ys = np.full(secs.shape, np.nan, dtype=np.float64)
    for i, si in enumerate(secs.astype(np.int64)):
        row = buckets.get(int(si))
        if row is not None:
            val = row.get(field)
            if val is not None:
                ys[i] = val
    return secs, ys


def pack_qscd20_bin_record(pmyqscd: bytes, recv_diff_sec: float) -> bytes:
    """QSCD20 120B + Live TimeDiff(초, float64)."""
    return pmyqscd + struct.pack(DIFF_PACK_FMT, float(recv_diff_sec))


def compute_recv_time_diff(recv_wall: float, myqscd: Tuple[Any, ...]) -> float:
    """UDP 수신 시각 − data time. recv_wall 은 커널/수신 직후 캡처 값."""
    return float(recv_wall) - float(myqscd[6])


def capture_recv_wall() -> float:
    """프로세스 시각(초). GUI 부하와 무관하게 ns 해상도로 찍는다."""
    return time.time_ns() / 1e9


def _cmsg_buf_size() -> int:
    if not hasattr(socket, "CMSG_SPACE"):
        return 256
    try:
        return max(256, int(socket.CMSG_SPACE(16)), int(socket.CMSG_SPACE(32)))
    except (OSError, OverflowError, TypeError, ValueError):
        return 256


def enable_kernel_recv_timestamp(sock: socket.socket) -> bool:
    """Linux 등 POSIX: 커널 수신 시각. Windows는 False (recvfrom + capture_recv_wall)."""
    if os.name == "nt" or not hasattr(sock, "recvmsg"):
        return False
    for opt in (
        getattr(socket, "SO_TIMESTAMPNS", None),
        getattr(socket, "SO_TIMESTAMP", None),
    ):
        if opt is None:
            continue
        try:
            sock.setsockopt(socket.SOL_SOCKET, int(opt), 1)
            return True
        except OSError:
            continue
    return False


def _parse_kernel_timestamp(ancdata: Any) -> Optional[float]:
    ns_types = {
        getattr(socket, "SCM_TIMESTAMPNS", None),
        getattr(socket, "SO_TIMESTAMPNS", None),
    }
    us_types = {
        getattr(socket, "SCM_TIMESTAMP", None),
        getattr(socket, "SO_TIMESTAMP", None),
    }
    ns_types.discard(None)
    us_types.discard(None)
    for level, typ, data in ancdata or ():
        if level != socket.SOL_SOCKET or not data:
            continue
        raw = bytes(data)
        if typ in ns_types and len(raw) >= 8:
            try:
                if len(raw) >= 16:
                    sec, nsec = struct.unpack_from("@ll", raw)
                else:
                    sec, nsec = struct.unpack_from("@ii", raw)
                return float(sec) + float(nsec) * 1e-9
            except struct.error:
                continue
        if typ in us_types and len(raw) >= 8:
            try:
                if len(raw) >= 16:
                    sec, usec = struct.unpack_from("@ll", raw)
                else:
                    sec, usec = struct.unpack_from("@ii", raw)
                return float(sec) + float(usec) * 1e-6
            except struct.error:
                continue
    return None


def recv_udp_datagram(
    sock: socket.socket, kernel_ts: bool
) -> Tuple[bytes, Any, float]:
    """데이터그램 + 수신 시각. kernel_ts면 커널 타임스탬프를 우선한다."""
    if kernel_ts:
        data, ancdata, _flags, addr = sock.recvmsg(QSCD_LEN, _cmsg_buf_size())
        wall = _parse_kernel_timestamp(ancdata)
        if wall is None:
            wall = capture_recv_wall()
        return data, addr, wall
    data, addr = sock.recvfrom(QSCD_LEN)
    return data, addr, capture_recv_wall()


def _boost_os_timer() -> Any:
    """Windows 기본 ~15ms 타이머를 1ms로. Linux는 손대지 않음."""
    if sys.platform != "win32":
        return None
    try:
        import ctypes

        winmm = ctypes.windll.winmm
        winmm.timeBeginPeriod(1)
        return winmm
    except Exception:
        return None


def _restore_os_timer(token: Any) -> None:
    if token is None:
        return
    try:
        token.timeEndPeriod(1)
    except Exception:
        pass


def write_qscd20_bin_header(fp: Any) -> None:
    fp.write(BIN_FILE_MAGIC)


def records_to_buckets(
    records: List[Tuple[Any, ...]],
    recv_diffs: Optional[List[float]] = None,
    recv_ts: Optional[float] = None,
) -> Dict[int, Dict[str, float]]:
    """파일/정적 데이터 → 초 단위 버킷 (동일 초는 마지막 값).

    recv_diffs가 있으면 Live 수신 시 저장한 TimeDiff를 그대로 사용.
    없으면 recv_ts 기준으로 근사(구형 120B 전용 파일).
    """
    buckets: Dict[int, Dict[str, float]] = {}
    fallback_recv = recv_ts if recv_ts is not None else time.time()
    for i, r in enumerate(records):
        sec = int(float(r[6]))
        if recv_diffs is not None and i < len(recv_diffs):
            diff = float(recv_diffs[i])
        else:
            diff = fallback_recv - float(r[6])
        row: Dict[str, float] = {"diff": diff}
        for name, idx in SERIES_IDX.items():
            row[name] = float(r[idx])
        buckets[sec] = row
    return buckets


class QscdBinLoadResult(NamedTuple):
    records: List[Tuple[Any, ...]]
    recv_diffs: Optional[List[float]]
    has_stored_diff: bool


def unique_station_codes(records: List[Tuple[Any, ...]]) -> List[str]:
    """바이너리 레코드에서 관측소 코드 목록(정렬, 중복 제거)."""
    seen: set = set()
    out: List[str] = []
    for r in records:
        st = station_code_str(r)
        if st not in seen:
            seen.add(st)
            out.append(st)
    return sorted(out)


def filter_records_by_station(
    records: List[Tuple[Any, ...]],
    station: str,
    recv_diffs: Optional[List[float]] = None,
) -> Tuple[List[Tuple[Any, ...]], Optional[List[float]]]:
    """선택 관측소 레코드만 추출 (recv_diffs 인덱스 유지)."""
    filtered: List[Tuple[Any, ...]] = []
    diffs_out: Optional[List[float]] = [] if recv_diffs is not None else None
    for i, r in enumerate(records):
        if station_code_str(r) != station:
            continue
        filtered.append(r)
        if diffs_out is not None and recv_diffs is not None and i < len(recv_diffs):
            diffs_out.append(recv_diffs[i])
    return filtered, diffs_out


def _packet_recv_times(
    myqscd: Tuple[Any, ...],
    recv_wall: Optional[float],
    recv_diff: Optional[float],
) -> Tuple[datetime.datetime, datetime.datetime, float]:
    if recv_wall is not None:
        rtime = datetime.datetime.utcfromtimestamp(recv_wall)
    else:
        rtime = datetime.datetime.utcnow()
    dtime = datetime.datetime.utcfromtimestamp(myqscd[6])
    if recv_diff is not None:
        diff = float(recv_diff)
    elif recv_wall is not None:
        diff = compute_recv_time_diff(recv_wall, myqscd)
    else:
        diff = rtime.timestamp() - float(myqscd[6])
    return rtime, dtime, diff


def format_qscd_packet_summary_line(
    myqscd: Tuple[Any, ...],
    station: str,
    *,
    recv_wall: Optional[float] = None,
    recv_diff: Optional[float] = None,
) -> str:
    _rtime, _dtime, diff = _packet_recv_times(myqscd, recv_wall, recv_diff)
    return (
        "[{}] Q={} st={} loc={} | data={} diff={:.3f}s | Zmax={:.6g} Hpga={:.6g}".format(
            station,
            describe_quality_flag(byte_to_u8(myqscd[1])),
            station_code_str(myqscd),
            location_str(myqscd) or "—",
            format_kst_dt(float(myqscd[6])),
            diff,
            float(myqscd[22]),
            float(myqscd[25]),
        )
    )


def format_qscd_packet_detail_lines(
    pmyqscd: bytes,
    myqscd: Tuple[Any, ...],
    *,
    recv_wall: Optional[float] = None,
    recv_diff: Optional[float] = None,
) -> List[str]:
    rtime, dtime, diff = _packet_recv_times(myqscd, recv_wall, recv_diff)
    buf_4_crc = pmyqscd[4:]
    mycrc = zlib.crc32(buf_4_crc) & 0xFFFFFFFF
    crc_recv = myqscd[0] & 0xFFFFFFFF
    if mycrc != crc_recv:
        crc_line = "     CRC : received {} calculated {} :::: Un-matched ".format(crc_recv, mycrc)
    else:
        crc_line = "     CRC : received {} calculated {}".format(crc_recv, mycrc)
    return [
        "#########################################################################",
        "Quality Flag: {}".format(format_quality_flag_line(myqscd)),
        "Station Code (5B): {}".format(format_station_code_line(myqscd)),
        "{:2s}/{:3s}/{} Recv : {} : Now : {} : Diff : {:.4f} s".format(
            _decode_bytes(myqscd[4]),
            _decode_bytes(myqscd[5]),
            _decode_bytes(myqscd[34]),
            dtime,
            rtime,
            diff,
        ),
        crc_line,
        "Data Type / Reserved: {} / {}".format(myqscd[2], myqscd[3]),
        "U-D WMMA : m {:.10f} M {:10f} A {:10f}".format(myqscd[7], myqscd[8], myqscd[9]),
        "N-S WMMA : m {:.10f} M {:10f} A {:10f}".format(myqscd[10], myqscd[11], myqscd[12]),
        "E-W WMMA : m {:.10f} M {:10f} A {:10f}".format(myqscd[13], myqscd[14], myqscd[15]),
        "U-D TMM  : m {:.10f} M {:10f}".format(myqscd[16], myqscd[17]),
        "N-S TMM  : m {:.10f} M {:10f}".format(myqscd[18], myqscd[19]),
        "E-W TMM  : m {:.10f} M {:10f}".format(myqscd[20], myqscd[21]),
        "Maximum  : Z {:.10f} N {:10f} E {:10f}".format(myqscd[22], myqscd[23], myqscd[24]),
        "    PGA  : H {:.10f} T {:10f}".format(myqscd[25], myqscd[26]),
        " Each SI : Z {:.10f} N {:10f} E {:10f} H {}".format(
            myqscd[27], myqscd[28], myqscd[29], myqscd[30]
        ),
        "Correlate: C {:.10f} Ch1 {} Ch2 {}".format(myqscd[31], myqscd[32], myqscd[33]),
    ]


def log_qscd_packet(
    logger: logging.Logger,
    pmyqscd: bytes,
    myqscd: Tuple[Any, ...],
    station: str,
    *,
    recv_wall: Optional[float] = None,
    recv_diff: Optional[float] = None,
) -> None:
    """파일 로그는 항상 상세."""
    extra = {"station": station, "log_kind": "detail"}
    for line in format_qscd_packet_detail_lines(
        pmyqscd, myqscd, recv_wall=recv_wall, recv_diff=recv_diff
    ):
        logger.info(line, extra=extra)


class PacketLogKindFilter(logging.Filter):
    """파일: 요약 패킷 로그는 버리고 상세만 남긴다."""

    def filter(self, record: logging.LogRecord) -> bool:
        return getattr(record, "log_kind", "") != "summary"


class StationGuiLogFilter(logging.Filter):
    """화면 로그: 시스템 메시지는 항상, 패킷 로그는 선택 관측소만.

    패킷(summary/detail)은 화면에서 _gui_log_packet 이 그리므로 여기서 제외한다.
    """

    def __init__(self, window: "MainWindow") -> None:
        super().__init__()
        self._window = window

    def filter(self, record: logging.LogRecord) -> bool:
        if getattr(record, "log_kind", "") in ("summary", "detail"):
            return False
        rec_st = getattr(record, "station", "")
        if not rec_st:
            return True
        sel = self._window._selected_station
        if not sel:
            return False
        return rec_st == sel


class QtLogHandler(QtCore.QObject, logging.Handler):
    log_signal = QtCore.pyqtSignal(str)

    def __init__(self) -> None:
        QtCore.QObject.__init__(self)
        logging.Handler.__init__(self)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
        except Exception:
            self.handleError(record)
            return
        self.log_signal.emit(msg)


# ---------------------------------------------------------------------------
# UDP thread
# ---------------------------------------------------------------------------
class UdpReceiver(QtCore.QThread):
    timeout_warning = QtCore.pyqtSignal(str)
    error_occurred = QtCore.pyqtSignal(str)
    recv_issue = QtCore.pyqtSignal(str)

    def __init__(self, host: str, port: int, parent: Optional[QtCore.QObject] = None) -> None:
        super().__init__(parent)
        self._host = host
        self._port = int(port)
        self._stop = False
        self._sock: Optional[socket.socket] = None
        self._packets: queue.Queue = queue.Queue(maxsize=max(200, PACKET_QUEUE_MAX))
        self._sock_timeout = max(MIN_SOCK_TIMEOUT_SEC, float(SockTimeOut))
        self._sock_timeout_count = int(SockTimeOutCount)
        # GUI 스레드가 쓰고 수신 스레드가 읽는다. 소켓 자체는 수신 스레드만 만진다.
        self._pending_timeout: Optional[float] = None
        self._drop_count = 0
        self._error_count = 0
        self._unpack_error_count = 0

    def stop(self) -> None:
        self._stop = True
        s = self._sock
        if s is not None:
            try:
                s.close()
            except OSError:
                pass

    def set_sock_params(self, timeout_sec: float, timeout_count: int) -> None:
        """수신 스레드가 다음 루프에서 적용하도록 예약만 한다."""
        self._sock_timeout_count = int(timeout_count)
        self._pending_timeout = max(MIN_SOCK_TIMEOUT_SEC, float(timeout_sec))

    def _report_loop_error(self, msg: str) -> None:
        """반복되는 수신 오류로 로그가 폭주하지 않도록 제한하고, 바쁜 루프를 막는다."""
        self._error_count += 1
        if self._error_count <= 3 or self._error_count % 200 == 0:
            self.recv_issue.emit(f"{msg} (누적 {self._error_count}건)")
        QtCore.QThread.msleep(50)

    def _apply_pending_timeout(self, sock: socket.socket) -> None:
        pending = self._pending_timeout
        if pending is None or pending == self._sock_timeout:
            self._pending_timeout = None
            return
        self._pending_timeout = None
        self._sock_timeout = pending
        try:
            sock.settimeout(pending)
        except OSError:
            pass

    def drain_packets(
        self, max_n: Optional[int] = None
    ) -> List[Tuple[bytes, Tuple[Any, ...], float, float]]:
        out: List[Tuple[bytes, Tuple[Any, ...], float, float]] = []
        if max_n is None:
            while True:
                try:
                    out.append(self._packets.get_nowait())
                except queue.Empty:
                    break
            return out
        limit = max(1, int(max_n))
        for _ in range(limit):
            try:
                out.append(self._packets.get_nowait())
            except queue.Empty:
                break
        return out

    def _enqueue(self, item: Tuple[bytes, Tuple[Any, ...], float, float]) -> None:
        """큐가 가득 차면 이미 받은 기록을 지키기 위해 새 패킷을 버린다."""
        try:
            self._packets.put_nowait(item)
            return
        except queue.Full:
            pass
        self._drop_count += 1
        if self._drop_count == 1 or self._drop_count % 100 == 0:
            self.recv_issue.emit(
                f"수신 큐 포화: 새 패킷 {self._drop_count}개 폐기(먼저 받은 기록 유지)"
            )

    def _apply_recv_thread_priority(self) -> None:
        """Windows에서는 실제로 오르고, Linux CFS는 root 없이 무시될 수 있다."""
        for prio in (
            QtCore.QThread.TimeCriticalPriority,
            QtCore.QThread.HighestPriority,
            QtCore.QThread.HighPriority,
        ):
            try:
                self.setPriority(prio)
            except Exception:
                continue
            if self.priority() >= QtCore.QThread.HighPriority:
                return

    def run(self) -> None:
        self._stop = False
        timeout_cnt = 0
        self._apply_recv_thread_priority()
        timer_token = _boost_os_timer()
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._sock = sock
            try:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            except OSError:
                pass
            sock.bind((self._host, self._port))
            sock.settimeout(self._sock_timeout)
        except OSError as e:
            self.error_occurred.emit(f"UDP bind 실패 ({self._host}:{self._port}): {e}")
            self._sock = None
            _restore_os_timer(timer_token)
            return

        kernel_ts = enable_kernel_recv_timestamp(sock)

        try:
            while not self._stop:
                try:
                    if self._pending_timeout is not None:
                        self._apply_pending_timeout(sock)
                    pmyqscd, _addr, recv_wall = recv_udp_datagram(sock, kernel_ts)
                    timeout_cnt = 0
                    if len(pmyqscd) != QSCD_LEN:
                        continue
                    try:
                        myqscd = struct.unpack(QSCD20_FMT, pmyqscd)
                    except struct.error as e:
                        self._unpack_error_count += 1
                        if self._unpack_error_count <= 3 or self._unpack_error_count % 100 == 0:
                            self.recv_issue.emit(
                                f"struct unpack 오류: {e} (누적 {self._unpack_error_count}건)"
                            )
                        continue
                    recv_diff = compute_recv_time_diff(recv_wall, myqscd)
                    self._enqueue((pmyqscd, myqscd, recv_wall, recv_diff))
                except socket.timeout:
                    if self._stop:
                        break
                    timeout_cnt += 1
                    if timeout_cnt >= self._sock_timeout_count:
                        self.timeout_warning.emit(
                            "Could not receive data for last "
                            + str(int(self._sock_timeout * self._sock_timeout_count))
                            + " secs."
                        )
                        timeout_cnt = 0
                except OSError as e:
                    if self._stop:
                        break
                    self._report_loop_error(f"UDP 소켓 오류: {e}")
                except Exception as e:
                    self._report_loop_error(f"UDP 수신 오류: {e}")
        finally:
            try:
                sock.close()
            except OSError:
                pass
            self._sock = None
            _restore_os_timer(timer_token)


# ---------------------------------------------------------------------------
# Station buffer (초 단위, NaN 공백)
# ---------------------------------------------------------------------------
class StationBuffer:
    def __init__(self, window_sec: int = DEFAULT_TIME_WINDOW_SEC) -> None:
        self.buckets: Dict[int, Dict[str, float]] = {}
        self.last_recv_wall: Optional[float] = None
        self.window_sec = int(window_sec)
        self.version: int = 0

    def set_window_sec(self, window_sec: int) -> None:
        self.window_sec = int(window_sec)
        self.version += 1
        self._prune()

    def append(
        self,
        myqscd: Tuple[Any, ...],
        recv_wall: Optional[float] = None,
        recv_diff: Optional[float] = None,
    ) -> None:
        recv_wall = recv_wall if recv_wall is not None else capture_recv_wall()
        self.last_recv_wall = recv_wall
        sec = int(float(myqscd[6]))
        if recv_diff is None:
            recv_diff = compute_recv_time_diff(recv_wall, myqscd)
        row: Dict[str, float] = {"diff": float(recv_diff)}
        for name, idx in SERIES_IDX.items():
            row[name] = float(myqscd[idx])
        self.buckets[sec] = row
        self.version += 1
        self._prune()

    def _prune(self) -> None:
        if not self.buckets:
            return
        limit = self.window_sec + 30
        if len(self.buckets) <= limit:
            return
        max_sec = max(self.buckets.keys())
        cutoff = max_sec - self.window_sec - 10
        for s in list(self.buckets.keys()):
            if s < cutoff:
                del self.buckets[s]

    def max_data_sec(self) -> Optional[int]:
        if not self.buckets:
            return None
        return max(self.buckets.keys())

    def clear(self) -> None:
        self.buckets.clear()
        self.last_recv_wall = None
        self.version += 1


# ---------------------------------------------------------------------------
# Chart hover tooltip
# ---------------------------------------------------------------------------
class ChartHoverTooltip(QtCore.QObject):
    """마우스 위치 근처 시계열 값 팝업."""

    _LEAVE_EVENTS = frozenset(
        {
            QtCore.QEvent.Leave,
            QtCore.QEvent.HoverLeave,
            QtCore.QEvent.Hide,
            QtCore.QEvent.WindowDeactivate,
        }
    )
    _ENTER_EVENTS = frozenset(
        {
            QtCore.QEvent.Enter,
            QtCore.QEvent.HoverEnter,
            QtCore.QEvent.HoverMove,
            QtCore.QEvent.MouseMove,
        }
    )

    def __init__(
        self,
        plot: pg.PlotItem,
        field_to_curve: Dict[str, pg.PlotDataItem],
        field_labels: Optional[Dict[str, str]] = None,
        hover_target: Optional[QtWidgets.QWidget] = None,
    ) -> None:
        super().__init__(plot)
        self._plot = plot
        self._fields = list(field_to_curve.keys())
        self._curves = field_to_curve
        self._labels = field_labels or {f: f for f in self._fields}
        self._text = pg.TextItem(
            anchor=(0, 1),
            border=pg.mkPen((20, 20, 20), width=2),
            fill=pg.mkBrush(255, 255, 255, 255),
            color=(0, 0, 0),
        )
        tip_font = QtGui.QFont()
        tip_font.setPointSize(10)
        tip_font.setBold(True)
        self._text.setFont(tip_font)
        self._text.setZValue(1000)
        self._text.hide()
        plot.addItem(self._text, ignoreBounds=True)
        self._pointer_over = False
        self._proxy = pg.SignalProxy(
            plot.scene().sigMouseMoved,
            rateLimit=30,
            slot=self._on_mouse,
        )
        self._grid_x: np.ndarray = np.array([])
        self._grid_ys: Dict[str, np.ndarray] = {}
        self._install_leave_handlers(hover_target)
        app = QtWidgets.QApplication.instance()
        if app is not None:
            app.applicationStateChanged.connect(self._on_app_state)

    def _install_leave_handlers(self, hover_target: Optional[QtWidgets.QWidget]) -> None:
        """차트 밖으로 나가면 sigMouseMoved가 멈추므로 Leave로 툴팁 숨김."""
        widgets: List[QtWidgets.QWidget] = []
        if hover_target is not None:
            widgets.append(hover_target)
        scene = self._plot.scene()
        if scene is not None:
            for view in scene.views():
                widgets.append(view)
                vp = view.viewport()
                if vp is not None:
                    widgets.append(vp)
        seen: set = set()
        for w in widgets:
            if id(w) in seen:
                continue
            seen.add(id(w))
            w.setAttribute(QtCore.Qt.WA_Hover, True)
            w.setMouseTracking(True)
            w.installEventFilter(self)

    def eventFilter(self, watched: QtCore.QObject, event: QtCore.QEvent) -> bool:
        et = event.type()
        if et in self._LEAVE_EVENTS:
            self._hide_tip()
            QtCore.QTimer.singleShot(50, self._hide_if_cursor_gone)
        elif et in self._ENTER_EVENTS:
            self._pointer_over = True
        return False

    def _on_app_state(self, state: QtCore.Qt.ApplicationState) -> None:
        if state != QtCore.Qt.ApplicationActive:
            self._hide_tip()

    def _hide_tip(self) -> None:
        self._pointer_over = False
        self._text.hide()

    def _hide_if_cursor_gone(self) -> None:
        if not self._cursor_over_plot():
            self._hide_tip()

    def hide(self) -> None:
        self._hide_tip()

    def _cursor_over_plot(self) -> bool:
        """이벤트 좌표가 아니라 실제 커서 위치로 차트 위 여부를 본다."""
        scene = self._plot.scene()
        if scene is None:
            return False
        global_pos = QtGui.QCursor.pos()
        for view in scene.views():
            vp = view.viewport()
            if vp is None or not vp.isVisible():
                continue
            local = vp.mapFromGlobal(global_pos)
            if not vp.rect().contains(local):
                continue
            scene_pt = view.mapToScene(local)
            if self._plot.sceneBoundingRect().contains(scene_pt):
                return True
        return False

    def set_grid_data(self, grid_x: np.ndarray, grid_ys: Dict[str, np.ndarray]) -> None:
        self._grid_x = grid_x
        self._grid_ys = grid_ys

    def _on_mouse(self, evt: Tuple[Any, ...]) -> None:
        pos = evt[0]
        # Leave 이후에도 SignalProxy가 옛 좌표로 show 할 수 있어, 현재 커서로 재확인
        if not self._cursor_over_plot():
            self._text.hide()
            return
        if not self._plot.sceneBoundingRect().contains(pos):
            self._text.hide()
            return
        mouse_point = self._plot.vb.mapSceneToView(pos)
        x = float(mouse_point.x())
        if self._grid_x.size == 0:
            self._text.hide()
            return
        idx = int(np.argmin(np.abs(self._grid_x - x)))
        if idx < 0 or idx >= self._grid_x.size:
            self._text.hide()
            return
        ts = self._grid_x[idx]
        try:
            kst = datetime.datetime.utcfromtimestamp(ts + KST_OFFSET).strftime("%H:%M:%S")
        except (OSError, ValueError, OverflowError):
            kst = "?"
        lines = [f"시각(KST) {kst}"]
        for f in self._fields:
            ys = self._grid_ys.get(f)
            if ys is None or idx >= len(ys):
                continue
            val = ys[idx]
            if np.isfinite(val):
                lines.append(f"{self._labels[f]}: {val:.6f}")
        if len(lines) <= 1:
            self._text.hide()
            return
        self._text.setText("\n".join(lines))
        self._place_tooltip(ts, float(mouse_point.y()), len(lines))
        self._text.show()

    def _place_tooltip(self, ts: float, mouse_y: float, line_count: int) -> None:
        """뷰 상·하단에 따라 팝업 앵커·Y를 조절해 잘리지 않게 배치."""
        vb = self._plot.getViewBox()
        yr = vb.viewRange()[1]
        y0, y1 = float(yr[0]), float(yr[1])
        y_span = max(y1 - y0, 1e-9)
        tip_frac = min(0.42, 0.055 * line_count + 0.12)
        margin = y_span * 0.04

        if mouse_y > y0 + y_span * (1.0 - tip_frac):
            self._text.setAnchor((0, 0))
            y_pos = mouse_y - margin
            y_pos = max(y0 + margin, min(y_pos, y1 - margin))
        else:
            self._text.setAnchor((0, 1))
            y_pos = mouse_y + margin
            y_pos = max(y0 + margin, min(y_pos, y1 - margin))

        self._text.setPos(ts, y_pos)


# ---------------------------------------------------------------------------
# Chart dashboard
# ---------------------------------------------------------------------------
class QscdChartDashboard(QtWidgets.QWidget):
    def __init__(
        self,
        parent: Optional[QtWidgets.QWidget] = None,
        *,
        live_mode: bool = False,
        window_sec: int = DEFAULT_TIME_WINDOW_SEC,
        scroll_object_name: str = "ChartScroll",
    ) -> None:
        super().__init__(parent)
        self._live_mode = live_mode
        self._window_sec = int(window_sec)
        self._scroll = QtWidgets.QScrollArea()
        self._scroll.setObjectName(scroll_object_name)
        self._scroll.setWidgetResizable(True)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._scroll)

        self._container = QtWidgets.QWidget()
        self._cont_layout = QtWidgets.QVBoxLayout(self._container)
        self._cont_layout.setContentsMargins(0, 0, 0, 0)
        self._cont_layout.setSpacing(2)
        self._scroll.setWidget(self._container)

        self._panels: Dict[str, Tuple[pg.GraphicsLayoutWidget, Dict[str, pg.PlotDataItem]]] = {}
        self._hovers: Dict[str, ChartHoverTooltip] = {}
        self._plot_items: List[pg.PlotItem] = []
        self._active_panels: List[str] = []
        self._cache_key: Optional[Tuple[int, int]] = None
        self._grid_cache: Dict[str, Tuple[np.ndarray, np.ndarray]] = {}
        self._last_buckets: Dict[int, Dict[str, float]] = {}
        self._panel_meta: Dict[str, Dict[str, Any]] = {}
        self._show_legend: bool = DEFAULT_SHOW_LEGEND
        self._scroll.viewport().setMouseTracking(True)
        self._scroll.viewport().setAttribute(QtCore.Qt.WA_Hover, True)
        self._scroll.viewport().installEventFilter(self)

    def eventFilter(self, watched: QtCore.QObject, event: QtCore.QEvent) -> bool:
        if watched is self._scroll.viewport() and event.type() in (
            QtCore.QEvent.Leave,
            QtCore.QEvent.HoverLeave,
        ):
            self._hide_all_hovers()
        return super().eventFilter(watched, event)

    def leaveEvent(self, event: QtGui.QEvent) -> None:
        self._hide_all_hovers()
        super().leaveEvent(event)

    def _hide_all_hovers(self) -> None:
        for h in self._hovers.values():
            h.hide()

    def set_show_legend(self, show: bool) -> None:
        self._show_legend = bool(show)
        for pid in list(self._panel_meta.keys()):
            self._apply_legend_visibility(pid)
        if show and self._last_buckets:
            for pid, (_gl, curves) in self._panels.items():
                grid_ys: Dict[str, np.ndarray] = {}
                for cid in curves:
                    field = "diff" if cid == "diff" else cid
                    _x, y = self._grid_cache.get(field, (np.array([]), np.array([])))
                    grid_ys[field] = y
                self._update_latest_labels(pid, grid_ys)

    def set_window_sec(self, window_sec: int) -> None:
        self._window_sec = int(window_sec)
        self._cache_key = None
        self._grid_cache.clear()

    def set_live_mode(self, live: bool) -> None:
        self._live_mode = live

    def _reset_plot_zoom(self, plot: pg.PlotItem) -> None:
        vb = plot.getViewBox()
        if isinstance(vb, ChartViewBox):
            vb.user_zoomed = False
        if self._last_buckets:
            max_sec = max(self._last_buckets.keys())
            x0 = float(max_sec - self._window_sec + 1)
            x1 = float(max_sec + 1)
            if self._live_mode:
                plot.setXRange(x0, x1, padding=0.02)
                plot.enableAutoRange(axis=pg.ViewBox.YAxis, enable=True)
            else:
                plot.enableAutoRange(enable=True)
        else:
            plot.enableAutoRange(enable=True)

    def _make_plot(
        self,
        gl: pg.GraphicsLayoutWidget,
        curves_def: List[Tuple[str, str, Tuple[int, int, int, int]]],
        y_label: str,
        row: int,
    ) -> Tuple[Dict[str, pg.PlotDataItem], ChartHoverTooltip, pg.PlotItem, Any]:
        axis = KSTTimeAxisItem(orientation="bottom")
        if y_label == Y_LABEL_DIFF:
            left_axis: pg.AxisItem = pg.AxisItem(orientation="left")
            left_axis.enableAutoSIPrefix(False)
        else:
            left_axis = PlainGalAxisItem(orientation="left")
        vb = ChartViewBox()
        plot = gl.addPlot(
            row=row,
            col=0,
            title="",
            viewBox=vb,
            axisItems={"bottom": axis, "left": left_axis},
        )
        plot.setLabel("left", y_label)
        plot.showGrid(x=True, y=True, alpha=0.35)
        plot.getViewBox().setBackgroundColor("#ffffff")
        legend = plot.addLegend(offset=(10, 10))
        legend.setVisible(self._show_legend)
        plot.setClipToView(True)
        plot.setDownsampling(auto=True, mode="peak")
        self._plot_items.append(plot)
        curves: Dict[str, pg.PlotDataItem] = {}
        labels_map: Dict[str, str] = {}
        for cid, label, rgba in curves_def:
            pen = pg.mkPen(color=rgba, width=1.5)
            curves[cid] = plot.plot(
                [], [], pen=pen, name=label, connect="finite", skipFiniteCheck=True
            )
            labels_map[cid] = label
        hover = ChartHoverTooltip(plot, curves, labels_map, hover_target=gl)
        return curves, hover, plot, legend

    def _apply_legend_visibility(self, pid: str) -> None:
        meta = self._panel_meta.get(pid)
        if meta is None:
            return
        vis = self._show_legend
        leg = meta.get("legend")
        if leg is not None:
            leg.setVisible(vis)
        bar = meta.get("latest_bar")
        if bar is not None:
            bar.setVisible(vis)

    def _last_finite_value(self, y: np.ndarray) -> Optional[float]:
        if y.size == 0:
            return None
        for i in range(y.size - 1, -1, -1):
            v = float(y[i])
            if np.isfinite(v):
                return v
        return None

    def _update_latest_labels(self, pid: str, grid_ys: Dict[str, np.ndarray]) -> None:
        meta = self._panel_meta.get(pid)
        if meta is None or not self._show_legend:
            return
        curves_def = meta["curves_def"]
        latest_labels: Dict[str, QtWidgets.QLabel] = meta["latest_labels"]
        for cid, label, rgba in curves_def:
            lbl = latest_labels.get(cid)
            if lbl is None:
                continue
            field = "diff" if cid == "diff" else cid
            val = self._last_finite_value(grid_ys.get(field, np.array([])))
            if val is not None:
                lbl.setText(f"— {label} : {val:.6f}")
            else:
                lbl.setText(f"— {label} : —")
            lbl.setStyleSheet(
                f"color: rgb({rgba[0]},{rgba[1]},{rgba[2]}); "
                "font-size: 11px; font-weight: bold;"
            )

    def set_active_panels(self, panel_ids: List[str]) -> None:
        if panel_ids == self._active_panels:
            return
        self._active_panels = list(panel_ids)
        self._rebuild()

    def _rebuild(self) -> None:
        while self._cont_layout.count():
            item = self._cont_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        self._panels.clear()
        self._hovers.clear()
        self._plot_items.clear()
        self._panel_meta.clear()
        self._grid_cache.clear()
        self._cache_key = None

        for pid in self._active_panels:
            title, curves_def = PANEL_DEFS[pid]
            y_label = Y_LABEL_DIFF if pid == "diff" else Y_LABEL_GAL
            gl = pg.GraphicsLayoutWidget()
            gl.setMinimumHeight(150)
            gl.setSizePolicy(
                QtWidgets.QSizePolicy.Expanding,
                QtWidgets.QSizePolicy.Minimum,
            )
            curves, hover, plot, legend = self._make_plot(gl, curves_def, y_label, 0)
            self._panels[pid] = (gl, curves)
            self._hovers[pid] = hover

            latest_bar = QtWidgets.QWidget()
            latest_layout = QtWidgets.QHBoxLayout(latest_bar)
            latest_layout.setContentsMargins(0, 0, 0, 0)
            latest_layout.setSpacing(10)
            latest_labels: Dict[str, QtWidgets.QLabel] = {}
            for cid, label, rgba in curves_def:
                lbl = QtWidgets.QLabel(f"— {label} : —")
                lbl.setStyleSheet(
                    f"color: rgb({rgba[0]},{rgba[1]},{rgba[2]}); "
                    "font-size: 11px; font-weight: bold;"
                )
                latest_labels[cid] = lbl
                latest_layout.addWidget(lbl)
            latest_bar.setVisible(self._show_legend)

            panel_wrap = QtWidgets.QFrame()
            panel_wrap.setObjectName("ChartPanel")
            panel_wrap.setFrameShape(QtWidgets.QFrame.StyledPanel)
            panel_layout = QtWidgets.QVBoxLayout(panel_wrap)
            panel_layout.setContentsMargins(0, 0, 0, 0)
            panel_layout.setSpacing(2)
            hdr = QtWidgets.QHBoxLayout()
            hdr.setContentsMargins(4, 2, 4, 0)
            title_lbl = QtWidgets.QLabel(title)
            title_lbl.setStyleSheet("font-weight: bold;")
            hdr.addWidget(title_lbl)
            hdr.addWidget(latest_bar, stretch=1)
            self._panel_meta[pid] = {
                "legend": legend,
                "latest_bar": latest_bar,
                "latest_labels": latest_labels,
                "curves_def": curves_def,
            }
            btn_reset = QtWidgets.QToolButton()
            btn_reset.setToolTip("줌 초기화")
            btn_reset.setAutoRaise(True)
            btn_reset.setFixedSize(26, 26)
            btn_reset.setIcon(
                panel_wrap.style().standardIcon(QtWidgets.QStyle.SP_BrowserReload)
            )
            btn_reset.clicked.connect(lambda _checked=False, p=plot: self._reset_plot_zoom(p))
            hdr.addWidget(btn_reset)
            panel_layout.addLayout(hdr)
            panel_layout.addWidget(gl)
            self._cont_layout.addWidget(panel_wrap)
        self._cont_layout.addStretch()

    def _grid_fields_for_active_panels(self) -> List[str]:
        fields: List[str] = []
        seen: set = set()
        for pid in self._active_panels:
            for cid, _, _ in PANEL_DEFS[pid][1]:
                f = "diff" if cid == "diff" else cid
                if f not in seen:
                    seen.add(f)
                    fields.append(f)
        return fields

    def _rebuild_grid_cache(self, buckets: Dict[int, Dict[str, float]], version: int) -> None:
        self._cache_key = (version, self._window_sec)
        self._grid_cache.clear()
        for f in self._grid_fields_for_active_panels():
            self._grid_cache[f] = build_second_grid(buckets, f, self._window_sec)

    def _apply_plot_ranges(self, buckets: Dict[int, Dict[str, float]]) -> None:
        if not buckets or not self._plot_items:
            return
        max_sec = max(buckets.keys())
        x0 = float(max_sec - self._window_sec + 1)
        x1 = float(max_sec + 1)
        for plot in self._plot_items:
            vb = plot.getViewBox()
            if not isinstance(vb, ChartViewBox):
                continue
            if self._live_mode and not vb.user_zoomed:
                plot.setXRange(x0, x1, padding=0.02)
                plot.enableAutoRange(axis=pg.ViewBox.YAxis, enable=True)
            elif not self._live_mode and not vb.user_zoomed:
                plot.enableAutoRange(enable=True)

    def update_from_buckets(self, buckets: Dict[int, Dict[str, float]], version: int = 0) -> None:
        if not self._active_panels:
            return
        if not buckets:
            self._last_buckets = {}
            for _gl, curves in self._panels.values():
                for c in curves.values():
                    c.setData([], [])
            for pid in self._panels:
                self._update_latest_labels(pid, {})
            return

        self._last_buckets = buckets
        cache_key = (version, self._window_sec)
        if cache_key != self._cache_key:
            self._rebuild_grid_cache(buckets, version)

        for pid, (_gl, curves) in self._panels.items():
            grid_ys: Dict[str, np.ndarray] = {}
            ref_x = np.array([])
            for cid, curve in curves.items():
                field = "diff" if cid == "diff" else cid
                x, y = self._grid_cache.get(field, (np.array([]), np.array([])))
                if x.size:
                    ref_x = x
                grid_ys[field] = y
                curve.setData(x, y, skipFiniteCheck=True)
            if pid in self._hovers:
                self._hovers[pid].set_grid_data(ref_x, grid_ys)
            self._update_latest_labels(pid, grid_ys)

        self._apply_plot_ranges(buckets)

    def update_from_buffer(self, buf: StationBuffer) -> None:
        self.update_from_buckets(buf.buckets, buf.version)

    def set_static_from_records(
        self,
        records: List[Tuple[Any, ...]],
        recv_diffs: Optional[List[float]] = None,
    ) -> None:
        buckets = records_to_buckets(records, recv_diffs=recv_diffs)
        self._cache_key = None
        self._grid_cache.clear()
        for plot in self._plot_items:
            vb = plot.getViewBox()
            if isinstance(vb, ChartViewBox):
                vb.user_zoomed = False
        self.update_from_buckets(buckets, version=1)


def read_qscd20_bin(path: str) -> QscdBinLoadResult:
    """QCDX 확장(120+8B/레코드) 또는 구형 120B 연속 파일 읽기."""
    with open(path, "rb") as f:
        data = f.read()

    records: List[Tuple[Any, ...]] = []
    recv_diffs: Optional[List[float]] = None
    offset = 0
    rec_stride = QSCD_LEN

    if data.startswith(BIN_FILE_MAGIC):
        offset = len(BIN_FILE_MAGIC)
        rec_stride = QSCD_BIN_REC_LEN
        recv_diffs = []

    while offset + QSCD_LEN <= len(data):
        chunk = data[offset : offset + QSCD_LEN]
        if len(chunk) != QSCD_LEN:
            break
        try:
            records.append(struct.unpack(QSCD20_FMT, chunk))
        except struct.error:
            break
        if recv_diffs is not None:
            if offset + QSCD_BIN_REC_LEN > len(data):
                records.pop()
                break
            (diff_val,) = struct.unpack(
                DIFF_PACK_FMT, data[offset + QSCD_LEN : offset + QSCD_BIN_REC_LEN]
            )
            recv_diffs.append(float(diff_val))
        offset += rec_stride

    has_stored = recv_diffs is not None and len(recv_diffs) == len(records) and len(records) > 0
    if recv_diffs is not None and len(recv_diffs) != len(records):
        recv_diffs = None
        has_stored = False

    return QscdBinLoadResult(records, recv_diffs, has_stored)


def readme_html_path() -> str:
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "README.html")


# ---------------------------------------------------------------------------
# Popup dialogs (메뉴에서 열기)
# ---------------------------------------------------------------------------
if _HAS_WEBENGINE:

    class _HelpWebPage(QWebEnginePage):
        """http(s) 링크는 시스템 브라우저로 연다."""

        def acceptNavigationRequest(
            self, url: QtCore.QUrl, nav_type: Any, is_main_frame: bool
        ) -> bool:
            if url.scheme() in ("http", "https") and is_main_frame:
                QtGui.QDesktopServices.openUrl(url)
                return False
            return super().acceptNavigationRequest(url, nav_type, is_main_frame)


class HelpManualDialog(QtWidgets.QDialog):
    """README.html 매뉴얼 — QWebEngineView HTML 렌더링."""

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"도움말 — QSCD20 {GUI_VERSION}")
        self.setMinimumSize(720, 520)
        self.resize(960, 720)
        layout = QtWidgets.QVBoxLayout(self)
        path = readme_html_path()
        missing_html = (
            f"<h2>README.html 없음</h2>"
            f"<p>다음 경로에 파일이 있어야 합니다:</p>"
            f"<p><code>{path}</code></p>"
        )

        if _HAS_WEBENGINE and QWebEngineView is not None:
            page = _HelpWebPage(self)  # type: ignore[possibly-undefined]
            browser: QtWidgets.QWidget = QWebEngineView()
            browser.setPage(page)  # type: ignore[attr-defined]
            if os.path.isfile(path):
                browser.load(QtCore.QUrl.fromLocalFile(os.path.abspath(path)))  # type: ignore[attr-defined]
            else:
                browser.setHtml(missing_html)  # type: ignore[attr-defined]
        else:
            fallback = QtWidgets.QTextBrowser()
            fallback.setOpenExternalLinks(True)
            if os.path.isfile(path):
                fallback.setSource(QtCore.QUrl.fromLocalFile(os.path.abspath(path)))
            else:
                fallback.setHtml(missing_html)
            browser = fallback
            warn = QtWidgets.QLabel(
                "PyQtWebEngine 미설치 — 기본 뷰어로 표시합니다. "
                "pip install PyQtWebEngine"
            )
            warn.setStyleSheet("color: #b45309; font-size: 11px; padding: 2px;")
            layout.addWidget(warn)

        layout.addWidget(browser, stretch=1)
        foot = QtWidgets.QLabel(f"QSCD20 UDP Receiver {GUI_VERSION}")
        foot.setStyleSheet("color: #64748b; padding: 4px;")
        foot.setAlignment(QtCore.Qt.AlignRight)
        layout.addWidget(foot)


class BasicSettingsDialog(QtWidgets.QDialog):
    """recvQSCD20_gui_settings.json 편집 (BIN_FILE_MAGIC 제외)."""

    def __init__(self, main: "MainWindow") -> None:
        super().__init__(main)
        self._main = main
        self.setWindowTitle(f"기본 설정 — QSCD20 {GUI_VERSION}")
        self.setMinimumSize(480, 520)
        self.resize(540, 640)
        root = QtWidgets.QVBoxLayout(self)

        info = QtWidgets.QLabel(
            f"설정 파일: {settings_file_path()}\n"
            "항목에 마우스를 올리면 설명이 표시됩니다. BIN_FILE_MAGIC 은 변경할 수 없습니다."
        )
        info.setWordWrap(True)
        info.setStyleSheet("color: #475569; font-size: 11px; padding: 4px;")
        root.addWidget(info)

        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        form_host = QtWidgets.QWidget()
        form = QtWidgets.QFormLayout(form_host)
        form.setFieldGrowthPolicy(QtWidgets.QFormLayout.ExpandingFieldsGrow)

        self._editors: Dict[str, QtWidgets.QWidget] = {}
        s = deepcopy(_runtime_settings)
        for key, spec in SETTING_UI_SPECS.items():
            label_text, tooltip, kind, vmin, vmax = spec
            if kind == "int":
                w: QtWidgets.QWidget = QtWidgets.QSpinBox()
                if vmin is not None:
                    w.setMinimum(int(vmin))  # type: ignore[union-attr]
                if vmax is not None:
                    w.setMaximum(int(vmax))  # type: ignore[union-attr]
                w.setValue(int(getattr(s, key)))  # type: ignore[union-attr]
            elif kind == "float":
                w = QtWidgets.QDoubleSpinBox()
                w.setDecimals(2)
                w.setSingleStep(0.1)
                if vmin is not None:
                    w.setMinimum(float(vmin))
                if vmax is not None:
                    w.setMaximum(float(vmax))
                w.setValue(float(getattr(s, key)))
            elif kind == "bool":
                w = QtWidgets.QCheckBox()
                w.setChecked(bool(getattr(s, key)))
            elif kind == "int_list":
                w = QtWidgets.QLineEdit()
                w.setText(", ".join(str(x) for x in getattr(s, key)))
            elif kind == "str_list":
                w = QtWidgets.QLineEdit()
                w.setText(", ".join(str(x) for x in getattr(s, key)))
            elif kind == "path":
                le = QtWidgets.QLineEdit()
                le.setText(str(getattr(s, key)))
                row = QtWidgets.QWidget()
                row_h = QtWidgets.QHBoxLayout(row)
                row_h.setContentsMargins(0, 0, 0, 0)
                btn_browse = QtWidgets.QPushButton("…")
                btn_browse.setFixedWidth(32)
                btn_browse.setToolTip("폴더 선택")
                btn_browse.clicked.connect(lambda _=False, e=le: self._browse_path_dir(e))
                row_h.addWidget(le, stretch=1)
                row_h.addWidget(btn_browse)
                le.setToolTip(tooltip)
                w = row
                self._editors[key] = le
            else:
                continue
            if kind != "path":
                w.setToolTip(tooltip)
            lbl = QtWidgets.QLabel(label_text)
            lbl.setToolTip(tooltip)
            form.addRow(lbl, w)
            if kind != "path":
                self._editors[key] = w

        scroll.setWidget(form_host)
        root.addWidget(scroll, stretch=1)

        btn_row = QtWidgets.QHBoxLayout()
        btn_save = QtWidgets.QPushButton("저장")
        btn_save.setDefault(True)
        btn_save.clicked.connect(self._on_save)
        btn_reset = QtWidgets.QPushButton("기본값 복원")
        btn_reset.clicked.connect(self._on_reset_defaults)
        btn_cancel = QtWidgets.QPushButton("취소")
        btn_cancel.clicked.connect(self.reject)
        btn_row.addStretch()
        btn_row.addWidget(btn_reset)
        btn_row.addWidget(btn_cancel)
        btn_row.addWidget(btn_save)
        root.addLayout(btn_row)

    def _read_form(self) -> GuiSettings:
        s = default_settings()
        for key, w in self._editors.items():
            spec = SETTING_UI_SPECS[key]
            kind = spec[2]
            if kind == "int":
                setattr(s, key, int(w.value()))  # type: ignore[union-attr]
            elif kind == "float":
                setattr(s, key, float(w.value()))  # type: ignore[union-attr]
            elif kind == "bool":
                setattr(s, key, bool(w.isChecked()))  # type: ignore[union-attr]
            elif kind == "int_list":
                setattr(s, key, parse_int_list(w.text()))  # type: ignore[union-attr]
            elif kind == "str_list":
                setattr(s, key, parse_str_list(w.text()))  # type: ignore[union-attr]
            elif kind == "path":
                raw = w.text().strip()  # type: ignore[union-attr]
                if raw:
                    try:
                        raw = path_for_settings_storage(raw)
                    except ValueError:
                        pass
                setattr(s, key, raw)
        return s

    def _browse_path_dir(self, edit: QtWidgets.QLineEdit) -> None:
        start = edit.text().strip()
        if start and not os.path.isabs(start):
            start = os.path.join(work_directory(), start)
        if not start or not os.path.isdir(start):
            start = work_directory()
        d = QtWidgets.QFileDialog.getExistingDirectory(self, "디렉터리 선택", start)
        if d:
            try:
                edit.setText(path_for_settings_storage(d))
            except ValueError:
                edit.setText(d)

    def _load_into_form(self, s: GuiSettings) -> None:
        for key, w in self._editors.items():
            spec = SETTING_UI_SPECS[key]
            kind = spec[2]
            val = getattr(s, key)
            if kind == "int":
                w.setValue(int(val))  # type: ignore[union-attr]
            elif kind == "float":
                w.setValue(float(val))  # type: ignore[union-attr]
            elif kind == "bool":
                w.setChecked(bool(val))  # type: ignore[union-attr]
            elif kind == "int_list":
                w.setText(", ".join(str(x) for x in val))  # type: ignore[union-attr]
            elif kind == "str_list":
                w.setText(", ".join(str(x) for x in val))  # type: ignore[union-attr]
            elif kind == "path":
                w.setText(str(val))  # type: ignore[union-attr]

    def _on_reset_defaults(self) -> None:
        self._load_into_form(default_settings())

    def _on_save(self) -> None:
        try:
            s = self._read_form()
            validate_settings(s, list(PANEL_DEFS.keys()))
        except ValueError as e:
            QtWidgets.QMessageBox.warning(self, "설정 오류", str(e))
            return
        notes = pending_apply_notes(_runtime_settings, s)
        try:
            save_settings(s)
        except OSError as e:
            QtWidgets.QMessageBox.critical(self, "저장 오류", str(e))
            return
        self._main.apply_runtime_settings(s)
        msg = "설정을 저장했습니다."
        if notes:
            msg += "\n\n아래 항목은 지금 바로 반영되지 않습니다.\n· " + "\n· ".join(notes)
        else:
            msg += " 변경 내용이 바로 반영되었습니다."
        QtWidgets.QMessageBox.information(self, "저장 완료", msg)
        self.accept()


class LogViewerDialog(QtWidgets.QDialog):
    """화면 로그 (선택 관측소 필터 적용)."""

    def __init__(self, main: "MainWindow") -> None:
        super().__init__(main)
        self.setWindowTitle(f"로그 뷰어 — QSCD20 {GUI_VERSION}")
        self.setMinimumSize(880, 480)
        self.resize(960, 520)
        self.setWindowFlag(QtCore.Qt.Window, True)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.addWidget(main._log_view, stretch=1)
        btn_row = QtWidgets.QHBoxLayout()
        hint = QtWidgets.QLabel("선택 관측소 패킷 로그 · Start/Stop 등 시스템 메시지 포함")
        hint.setStyleSheet("color: #64748b; font-size: 11px;")
        btn_row.addWidget(hint)
        btn_row.addStretch()
        self._chk_verbose = QtWidgets.QCheckBox("상세 로그 표시")
        self._chk_verbose.setChecked(GUI_LOG_VERBOSE)
        self._chk_verbose.setToolTip(
            "켜면 패킷마다 여러 줄 상세 로그, 끄면 한 줄 요약을 표시합니다.\n"
            "체크를 바꾸면 화면에 있는 로그를 바로 다시 그립니다.\n"
            "파일(.QSCD.log)은 항상 상세로 저장되며, 이 체크는 저장되지 않습니다."
        )
        self._chk_verbose.toggled.connect(main._on_gui_log_verbose_toggled)
        btn_row.addWidget(self._chk_verbose)
        btn_clear = QtWidgets.QPushButton("로그 지우기")
        btn_clear.clicked.connect(main._clear_gui_log)
        btn_row.addWidget(btn_clear)
        layout.addLayout(btn_row)


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------
class MainWindow(QtWidgets.QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"QSCD20 UDP Receiver {GUI_VERSION}")
        self.resize(1400, 960)

        self._logger = logging.getLogger("mylogger")
        self._logger.setLevel(logging.DEBUG)
        self._logger.handlers.clear()
        self._formatter = logging.Formatter("[%(levelname)s] %(asctime)s > %(message)s")
        self._qt_handler = QtLogHandler()
        self._qt_handler.setFormatter(self._formatter)
        self._logger.addHandler(self._qt_handler)

        self._file_handler: Optional[logging.FileHandler] = None
        self._data_fp: Optional[Any] = None
        self._receiver: Optional[UdpReceiver] = None
        self._outputs_open = False

        self._station_bufs: Dict[str, StationBuffer] = {}
        self._selected_station: str = ""
        self._chart_window_sec: int = DEFAULT_TIME_WINDOW_SEC
        self._file_records: List[Tuple[Any, ...]] = []
        self._file_recv_diffs: Optional[List[float]] = None
        self._packet_source: Optional[UdpReceiver] = None
        self._bin_flush_pending = 0
        self._live_chart_dirty = False

        self._chart_timer = QtCore.QTimer(self)
        self._chart_timer.setInterval(CHART_REFRESH_MS)
        self._chart_timer.timeout.connect(self._on_chart_timer)
        self._chart_timer.start()

        self._recv_alert_blink = False
        self._recv_alert_timer = QtCore.QTimer(self)
        self._recv_alert_timer.setInterval(RECV_ALERT_BLINK_MS)
        self._recv_alert_timer.timeout.connect(self._tick_recv_delay_alert)

        self._log_view = QtWidgets.QPlainTextEdit()
        self._log_view.setObjectName("LogView")
        self._log_view.setReadOnly(True)
        self._log_view.setMaximumBlockCount(LOG_MAX_LINES)
        self._gui_log_items: List[Any] = []

        self._dlg_log: Optional[LogViewerDialog] = None
        self._dlg_help: Optional[HelpManualDialog] = None
        self._dlg_basic_settings: Optional[BasicSettingsDialog] = None

        self._build_ui()
        self._build_menubar()
        self.setStyleSheet(APP_STYLESHEET)
        self._set_status("대기 중")
        self._gui_log_filter = StationGuiLogFilter(self)
        self._qt_handler.addFilter(self._gui_log_filter)
        self._qt_handler.log_signal.connect(self._append_log_line)

    def _build_receive_sidebar(self) -> QtWidgets.QWidget:
        """Live·File Viewer 탭 우측 — 수신 제어 패널."""
        panel = QtWidgets.QWidget()
        panel.setObjectName("ReceiveSidebar")
        panel.setMinimumWidth(228)
        panel.setMaximumWidth(320)
        outer = QtWidgets.QVBoxLayout(panel)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(6)

        box = QtWidgets.QGroupBox("수신")
        vbox = QtWidgets.QVBoxLayout(box)
        vbox.setSpacing(8)

        vbox.addWidget(QtWidgets.QLabel("로그 파일명 (prefix)"))
        self._edit_prefix = QtWidgets.QLineEdit(datetime.datetime.now().strftime("%Y%m%d_%H%M%S"))
        self._edit_prefix.setToolTip("저장 파일 이름 앞부분입니다. 예: 20260519_120000")
        vbox.addWidget(self._edit_prefix)

        self._lbl_paths = QtWidgets.QLabel("")
        self._lbl_paths.setWordWrap(True)
        self._lbl_paths.setStyleSheet("color: #475569; font-size: 10px;")
        self._update_path_labels()
        self._edit_prefix.textChanged.connect(lambda _: self._update_path_labels())
        vbox.addWidget(self._lbl_paths)

        vbox.addWidget(QtWidgets.QLabel("UDP Port"))
        self._spin_port = QtWidgets.QSpinBox()
        self._spin_port.setRange(1, 65535)
        self._spin_port.setValue(DEFAULT_PORT)
        vbox.addWidget(self._spin_port)

        self._btn_start = QtWidgets.QPushButton("▶ Start")
        self._btn_start.setObjectName("BtnStart")
        self._btn_stop = QtWidgets.QPushButton("■ Stop")
        self._btn_stop.setObjectName("BtnStop")
        self._btn_stop.setEnabled(False)
        self._btn_start.clicked.connect(self._on_start)
        self._btn_stop.clicked.connect(self._on_stop)
        vbox.addWidget(self._btn_start)
        vbox.addWidget(self._btn_stop)

        vbox.addWidget(QtWidgets.QLabel("상태"))
        self._lbl_status = QtWidgets.QLabel("대기 중")
        self._lbl_status.setWordWrap(True)
        self._lbl_status.setStyleSheet(
            "background: #e2e8f0; padding: 6px; border-radius: 4px; font-weight: 600;"
        )
        vbox.addWidget(self._lbl_status)

        outer.addWidget(box)
        outer.addStretch()
        return panel

    def _build_menubar(self) -> None:
        menu = self.menuBar().addMenu("메뉴(&M)")
        act_prefs = menu.addAction("기본 설정(&P)…")
        act_prefs.setShortcut(QtGui.QKeySequence("Ctrl+P"))
        act_prefs.triggered.connect(self._show_basic_settings)
        menu.addSeparator()
        act_quit = menu.addAction("종료(&X)")
        act_quit.setShortcut(QtGui.QKeySequence.Quit)
        act_quit.triggered.connect(self.close)

        help_menu = self.menuBar().addMenu("도움말(&H)")
        act_manual = help_menu.addAction("도움말(&H)…")
        act_manual.setShortcut(QtGui.QKeySequence.HelpContents)
        act_manual.triggered.connect(self._show_help_manual)

        sb = self.statusBar()
        sb.showMessage("우측 패널에서 UDP 수신을 시작하세요. 저장 경로는 메뉴 → 기본 설정.")

        act_log = QtWidgets.QAction("로그 뷰어", self)
        act_log.setShortcut(QtGui.QKeySequence("Ctrl+L"))
        act_log.setShortcutContext(QtCore.Qt.WindowShortcut)
        act_log.triggered.connect(self._show_log_viewer)
        self.addAction(act_log)
        self._act_log_viewer = act_log

    def _set_status(self, text: str) -> None:
        self._lbl_status.setText(text)
        self.statusBar().showMessage(f"상태: {text}")

    def _show_basic_settings(self) -> None:
        if self._dlg_basic_settings is None:
            self._dlg_basic_settings = BasicSettingsDialog(self)
        self._dlg_basic_settings._load_into_form(deepcopy(_runtime_settings))
        self._dlg_basic_settings.show()
        self._dlg_basic_settings.raise_()
        self._dlg_basic_settings.activateWindow()

    def apply_runtime_settings(self, s: GuiSettings) -> None:
        _apply_gui_settings(s)
        self._chart_timer.setInterval(CHART_REFRESH_MS)
        self._recv_alert_timer.setInterval(RECV_ALERT_BLINK_MS)
        self._log_view.setMaximumBlockCount(LOG_MAX_LINES)
        if self._receiver is None:
            self._spin_port.setValue(DEFAULT_PORT)
        else:
            self._receiver.set_sock_params(SockTimeOut, SockTimeOutCount)
        self._rebuild_time_window_combos()
        for buf in self._station_bufs.values():
            buf.set_window_sec(self._chart_window_sec)
        self._live_charts.set_window_sec(self._chart_window_sec)
        self._file_charts.set_window_sec(int(self._combo_file_time_window.currentData()))
        self._update_path_labels()

    def _rebuild_time_window_combos(self) -> None:
        live_sec = self._combo_time_window.currentData()
        file_sec = self._combo_file_time_window.currentData()

        def fill(combo: QtWidgets.QComboBox, prefer: Any) -> None:
            combo.blockSignals(True)
            combo.clear()
            for sec in TIME_WINDOW_CHOICES:
                combo.addItem(f"{sec}초", sec)
            idx = combo.findData(prefer)
            if idx < 0:
                idx = combo.findData(DEFAULT_TIME_WINDOW_SEC)
            if idx < 0:
                idx = 0
            combo.setCurrentIndex(max(0, idx))
            combo.blockSignals(False)

        fill(self._combo_time_window, live_sec if live_sec is not None else DEFAULT_TIME_WINDOW_SEC)
        fill(self._combo_file_time_window, file_sec if file_sec is not None else DEFAULT_TIME_WINDOW_SEC)
        self._chart_window_sec = int(self._combo_time_window.currentData())

    def _show_log_viewer(self) -> None:
        if self._dlg_log is None:
            self._dlg_log = LogViewerDialog(self)
        self._dlg_log._chk_verbose.blockSignals(True)
        self._dlg_log._chk_verbose.setChecked(GUI_LOG_VERBOSE)
        self._dlg_log._chk_verbose.blockSignals(False)
        self._dlg_log.show()
        self._dlg_log.raise_()
        self._dlg_log.activateWindow()

    def _on_gui_log_verbose_toggled(self, checked: bool) -> None:
        global GUI_LOG_VERBOSE
        GUI_LOG_VERBOSE = bool(checked)
        self._rebuild_gui_log_view()

    def _show_help_manual(self) -> None:
        if self._dlg_help is None:
            self._dlg_help = HelpManualDialog(self)
        self._dlg_help.show()
        self._dlg_help.raise_()
        self._dlg_help.activateWindow()

    def _on_legend_toggled(self, _state: int = 0) -> None:
        show = self._chk_show_legend.isChecked()
        self._live_charts.set_show_legend(show)
        self._file_charts.set_show_legend(show)
        if self._chk_file_show_legend.isChecked() != show:
            self._chk_file_show_legend.blockSignals(True)
            self._chk_file_show_legend.setChecked(show)
            self._chk_file_show_legend.blockSignals(False)

    def _on_file_legend_toggled(self, _state: int = 0) -> None:
        show = self._chk_file_show_legend.isChecked()
        self._live_charts.set_show_legend(show)
        self._file_charts.set_show_legend(show)
        if self._chk_show_legend.isChecked() != show:
            self._chk_show_legend.blockSignals(True)
            self._chk_show_legend.setChecked(show)
            self._chk_show_legend.blockSignals(False)

    def _build_ui(self) -> None:
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        root_layout = QtWidgets.QVBoxLayout(central)
        root_layout.setContentsMargins(4, 4, 4, 4)

        content_row = QtWidgets.QHBoxLayout()
        content_row.setSpacing(8)

        tabs = QtWidgets.QTabWidget()
        tabs.setElideMode(QtCore.Qt.ElideNone)
        tabs.tabBar().setExpanding(False)
        tabs.tabBar().setUsesScrollButtons(False)
        content_row.addWidget(tabs, stretch=1)
        content_row.addWidget(self._build_receive_sidebar())
        root_layout.addLayout(content_row, stretch=1)

        # Live
        live_widget = QtWidgets.QWidget()
        live_vbox = QtWidgets.QVBoxLayout(live_widget)

        meta = QtWidgets.QFrame()
        meta.setObjectName("MetaBar")
        meta_layout = QtWidgets.QHBoxLayout(meta)
        meta_layout.setContentsMargins(8, 6, 8, 6)
        meta_layout.addWidget(QtWidgets.QLabel("수신 관측소:"))
        self._combo_station = QtWidgets.QComboBox()
        self._combo_station.setMinimumWidth(140)
        self._combo_station.addItem("(관측소 선택)")
        self._combo_station.currentTextChanged.connect(self._on_station_selected)
        meta_layout.addWidget(self._combo_station)
        self._lbl_last_recv = QtWidgets.QLabel("최종 수신: —")
        self._lbl_last_recv.setObjectName("LastRecvLabel")
        self._lbl_last_recv.setMinimumWidth(240)
        meta_layout.addWidget(self._lbl_last_recv)
        meta_layout.addWidget(QtWidgets.QLabel("Quality:"))
        self._lbl_live_quality = QtWidgets.QLabel("—")
        self._lbl_live_quality.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        meta_layout.addWidget(self._lbl_live_quality)
        meta_layout.addWidget(QtWidgets.QLabel("Station:"))
        self._lbl_live_station = QtWidgets.QLabel("—")
        self._lbl_live_station.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        meta_layout.addWidget(self._lbl_live_station)
        meta_layout.addWidget(QtWidgets.QLabel("Location:"))
        self._lbl_live_location = QtWidgets.QLabel("—")
        self._lbl_live_location.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        meta_layout.addWidget(self._lbl_live_location, stretch=1)
        self._btn_log_viewer = QtWidgets.QToolButton()
        self._btn_log_viewer.setObjectName("BtnLogViewer")
        self._btn_log_viewer.setIcon(make_log_viewer_icon(22))
        self._btn_log_viewer.setIconSize(QtCore.QSize(22, 22))
        self._btn_log_viewer.setFixedSize(32, 32)
        self._btn_log_viewer.setAutoRaise(False)
        self._btn_log_viewer.setCursor(QtCore.Qt.PointingHandCursor)
        self._btn_log_viewer.setToolTip("로그 뷰어 열기 (Ctrl+L)")
        self._btn_log_viewer.setAccessibleName("로그 뷰어")
        self._btn_log_viewer.clicked.connect(self._show_log_viewer)
        meta_layout.addWidget(self._btn_log_viewer)
        live_vbox.addWidget(meta)

        tw_row = QtWidgets.QHBoxLayout()
        tw_row.addWidget(QtWidgets.QLabel("시간 선택:"))
        self._combo_time_window = QtWidgets.QComboBox()
        for sec in TIME_WINDOW_CHOICES:
            self._combo_time_window.addItem(f"{sec}초", sec)
        idx = TIME_WINDOW_CHOICES.index(DEFAULT_TIME_WINDOW_SEC) if DEFAULT_TIME_WINDOW_SEC in TIME_WINDOW_CHOICES else 0
        self._combo_time_window.setCurrentIndex(idx)
        self._combo_time_window.currentIndexChanged.connect(self._on_time_window_changed)
        tw_row.addWidget(self._combo_time_window)
        tw_row.addWidget(
            QtWidgets.QLabel(
                "  · 드래그: 줌인  · 더블클릭/⟲: 줌아웃  · 마우스 오버: 값 팝업"
            )
        )
        self._chk_show_legend = QtWidgets.QCheckBox("범례·최근값 표시")
        self._chk_show_legend.setChecked(DEFAULT_SHOW_LEGEND)
        self._chk_show_legend.stateChanged.connect(self._on_legend_toggled)
        tw_row.addWidget(self._chk_show_legend)
        tw_row.addStretch()
        live_vbox.addLayout(tw_row)

        chk_box = QtWidgets.QGroupBox("표시 차트 선택")
        chk_layout = QtWidgets.QHBoxLayout(chk_box)
        self._panel_checks: Dict[str, QtWidgets.QCheckBox] = {}
        for pid in PANEL_DEFS:
            chk = QtWidgets.QCheckBox(PANEL_DEFS[pid][0])
            chk.setChecked(pid in DEFAULT_PANELS)
            chk.stateChanged.connect(self._on_panel_check_changed)
            self._panel_checks[pid] = chk
            chk_layout.addWidget(chk)
        chk_layout.addStretch()
        live_vbox.addWidget(chk_box)

        chart_area = QtWidgets.QFrame()
        chart_area.setObjectName("ChartArea")
        chart_area_layout = QtWidgets.QVBoxLayout(chart_area)
        chart_area_layout.setContentsMargins(6, 6, 6, 6)
        self._live_charts = QscdChartDashboard(
            live_mode=True,
            window_sec=self._chart_window_sec,
            scroll_object_name="ChartScroll",
        )
        self._live_charts.set_show_legend(DEFAULT_SHOW_LEGEND)
        self._live_charts.set_active_panels(self._get_checked_panels())
        chart_area_layout.addWidget(self._live_charts)
        live_vbox.addWidget(chart_area, stretch=1)
        self._recv_alert_timer.start()
        tabs.addTab(live_widget, "Live")

        # File viewer
        file_widget = QtWidgets.QWidget()
        file_vbox = QtWidgets.QVBoxLayout(file_widget)
        file_top = QtWidgets.QHBoxLayout()
        self._btn_open_bin = QtWidgets.QPushButton("QSCD20.replay 열기…")
        self._btn_open_bin.clicked.connect(self._open_bin_file)
        self._lbl_file_info = QtWidgets.QLabel("파일을 선택하세요.")
        self._lbl_file_info.setWordWrap(True)
        file_top.addWidget(self._btn_open_bin)
        file_top.addWidget(self._lbl_file_info, stretch=1)
        file_vbox.addLayout(file_top)

        ftw_layout = QtWidgets.QHBoxLayout()
        ftw_layout.addWidget(QtWidgets.QLabel("시간 선택:"))
        self._combo_file_time_window = QtWidgets.QComboBox()
        for sec in TIME_WINDOW_CHOICES:
            self._combo_file_time_window.addItem(f"{sec}초", sec)
        self._combo_file_time_window.setCurrentIndex(idx)
        self._combo_file_time_window.currentIndexChanged.connect(self._on_file_time_window_changed)
        ftw_layout.addWidget(self._combo_file_time_window)
        ftw_layout.addSpacing(16)
        ftw_layout.addWidget(QtWidgets.QLabel("관측소:"))
        self._combo_file_station = QtWidgets.QComboBox()
        self._combo_file_station.setMinimumWidth(160)
        self._combo_file_station.addItem("(관측소 선택)")
        self._combo_file_station.setEnabled(False)
        self._combo_file_station.currentIndexChanged.connect(self._on_file_station_changed)
        ftw_layout.addWidget(self._combo_file_station)
        self._chk_file_show_legend = QtWidgets.QCheckBox("범례·최근값 표시")
        self._chk_file_show_legend.setChecked(DEFAULT_SHOW_LEGEND)
        self._chk_file_show_legend.stateChanged.connect(self._on_file_legend_toggled)
        ftw_layout.addWidget(self._chk_file_show_legend)
        ftw_layout.addStretch()
        file_vbox.addLayout(ftw_layout)

        fchk_box = QtWidgets.QGroupBox("표시 차트 선택")
        fchk_layout = QtWidgets.QHBoxLayout(fchk_box)
        self._file_panel_checks: Dict[str, QtWidgets.QCheckBox] = {}
        for pid in PANEL_DEFS:
            chk = QtWidgets.QCheckBox(PANEL_DEFS[pid][0])
            chk.setChecked(pid in DEFAULT_PANELS)
            chk.stateChanged.connect(self._on_file_panel_check_changed)
            self._file_panel_checks[pid] = chk
            fchk_layout.addWidget(chk)
        fchk_layout.addStretch()
        file_vbox.addWidget(fchk_box)

        file_chart_area = QtWidgets.QFrame()
        file_chart_area.setObjectName("ChartArea")
        file_chart_layout = QtWidgets.QVBoxLayout(file_chart_area)
        file_chart_layout.setContentsMargins(6, 6, 6, 6)
        self._file_charts = QscdChartDashboard(
            live_mode=False,
            window_sec=self._chart_window_sec,
            scroll_object_name="ChartScroll",
        )
        self._file_charts.set_show_legend(DEFAULT_SHOW_LEGEND)
        self._file_charts.set_active_panels(self._get_file_checked_panels())
        file_chart_layout.addWidget(self._file_charts)
        file_vbox.addWidget(file_chart_area, stretch=1)
        tabs.addTab(file_widget, "File Viewer")

    def _get_checked_panels(self) -> List[str]:
        return [pid for pid in PANEL_DEFS if self._panel_checks[pid].isChecked()]

    def _get_file_checked_panels(self) -> List[str]:
        return [pid for pid in PANEL_DEFS if self._file_panel_checks[pid].isChecked()]

    def _on_panel_check_changed(self) -> None:
        self._live_charts.set_active_panels(self._get_checked_panels())
        self._refresh_live_charts_now()

    def _on_file_panel_check_changed(self) -> None:
        self._file_charts.set_active_panels(self._get_file_checked_panels())
        self._refresh_file_charts()

    def _on_time_window_changed(self, _index: int = 0) -> None:
        self._chart_window_sec = int(self._combo_time_window.currentData())
        self._live_charts.set_window_sec(self._chart_window_sec)
        for buf in self._station_bufs.values():
            buf.set_window_sec(self._chart_window_sec)
        self._refresh_live_charts_now()

    def _on_file_time_window_changed(self, _index: int = 0) -> None:
        sec = int(self._combo_file_time_window.currentData())
        self._file_charts.set_window_sec(sec)
        self._refresh_file_charts()

    def _populate_file_station_combo(self, records: List[Tuple[Any, ...]]) -> None:
        self._combo_file_station.blockSignals(True)
        self._combo_file_station.clear()
        stations = unique_station_codes(records)
        if not stations:
            self._combo_file_station.addItem("(관측소 선택)")
            self._combo_file_station.setEnabled(False)
        else:
            for st in stations:
                self._combo_file_station.addItem(st)
            self._combo_file_station.setCurrentIndex(0)
            self._combo_file_station.setEnabled(len(stations) > 1)
        self._combo_file_station.blockSignals(False)

    def _selected_file_station(self) -> str:
        text = self._combo_file_station.currentText().strip()
        if not text or text == "(관측소 선택)":
            return ""
        return text

    def _refresh_file_charts(self) -> None:
        if not self._file_records:
            self._file_charts.set_static_from_records([])
            return
        st = self._selected_file_station()
        if not st:
            self._file_charts.set_static_from_records([])
            return
        recs, diffs = filter_records_by_station(
            self._file_records, st, recv_diffs=self._file_recv_diffs
        )
        self._file_charts.set_static_from_records(recs, recv_diffs=diffs)

    def _on_file_station_changed(self, _index: int = 0) -> None:
        self._refresh_file_charts()

    def _on_station_selected(self, text: str) -> None:
        self._selected_station = text if text != "(관측소 선택)" else ""
        self._clear_gui_log()
        self._update_last_recv_label()
        for plot in self._live_charts._plot_items:
            vb = plot.getViewBox()
            if isinstance(vb, ChartViewBox):
                vb.user_zoomed = False
        self._refresh_live_charts_now()

    def _recv_delay_seconds(self) -> Optional[float]:
        if self._receiver is None or not self._selected_station:
            return None
        buf = self._station_bufs.get(self._selected_station)
        if buf is None or buf.last_recv_wall is None:
            return None
        return time.time() - buf.last_recv_wall

    def _is_recv_delayed(self) -> bool:
        delay = self._recv_delay_seconds()
        return delay is not None and delay > RECV_DELAY_ALERT_SEC

    def _apply_last_recv_normal_style(self) -> None:
        self._lbl_last_recv.setStyleSheet(
            "QLabel#LastRecvLabel { background: #e0f2fe; color: #0c4a6e; "
            "padding: 4px 10px; border-radius: 4px; font-weight: 600; }"
        )

    def _tick_recv_delay_alert(self) -> None:
        if not self._is_recv_delayed():
            self._recv_alert_blink = False
            self._apply_last_recv_normal_style()
            return
        delay = self._recv_delay_seconds()
        delay_s = int(delay) if delay is not None else 0
        st = self._selected_station
        buf = self._station_bufs.get(st) if st else None
        if buf and buf.last_recv_wall is not None:
            self._lbl_last_recv.setText(
                f"최종 수신: {format_kst_dt(buf.last_recv_wall)}  "
                f"(⚠ {delay_s}초 지연)"
            )
        self._recv_alert_blink = not self._recv_alert_blink
        if self._recv_alert_blink:
            self._lbl_last_recv.setStyleSheet(
                "QLabel#LastRecvLabel { background: #dc2626; color: #ffffff; "
                "padding: 4px 10px; border-radius: 4px; font-weight: bold; }"
            )
        else:
            self._lbl_last_recv.setStyleSheet(
                "QLabel#LastRecvLabel { background: #fef2f2; color: #b91c1c; "
                "padding: 4px 10px; border-radius: 4px; font-weight: bold; }"
            )

    def _update_last_recv_label(self) -> None:
        st = self._selected_station
        if not st or st not in self._station_bufs:
            self._lbl_last_recv.setText("최종 수신: —")
            self._apply_last_recv_normal_style()
            return
        buf = self._station_bufs[st]
        if buf.last_recv_wall is None:
            self._lbl_last_recv.setText("최종 수신: —")
            self._apply_last_recv_normal_style()
            return
        self._lbl_last_recv.setText(f"최종 수신: {format_kst_dt(buf.last_recv_wall)}")
        if self._is_recv_delayed():
            self._tick_recv_delay_alert()
        else:
            self._apply_last_recv_normal_style()

    def _refresh_live_charts_now(self) -> None:
        self._drain_packet_queue()
        st = self._selected_station
        if not st or st not in self._station_bufs:
            return
        self._live_charts.update_from_buffer(self._station_bufs[st])

    def _on_chart_timer(self) -> None:
        self._drain_packet_queue()
        if self._live_chart_dirty:
            self._live_chart_dirty = False
            self._refresh_live_charts_now()

    def _flush_bin_if_needed(self, force: bool = False, n_packets: int = 0) -> None:
        if self._data_fp is None:
            return
        if n_packets:
            self._bin_flush_pending += int(n_packets)
        if force or self._bin_flush_pending >= BIN_FLUSH_EVERY:
            try:
                self._data_fp.flush()
            except OSError:
                pass
            self._bin_flush_pending = 0

    def _drain_packet_queue(self, drain_all: bool = False) -> None:
        # 큐는 수신 스레드가 들고 있다. 스레드를 놓아준 뒤에도 남은 패킷을 기록해야
        # 하므로 _receiver 가 아니라 별도 참조(_packet_source)를 통해 꺼낸다.
        source = self._packet_source
        if source is None:
            return
        batch = source.drain_packets(None if drain_all else PACKET_DRAIN_MAX)
        if not batch:
            return
        last_selected: Optional[Tuple[Any, ...]] = None
        for pmyqscd, myqscd, recv_wall, recv_diff in batch:
            st = station_code_str(myqscd)

            if st not in self._station_bufs:
                self._station_bufs[st] = StationBuffer(window_sec=self._chart_window_sec)
                self._combo_station.addItem(st)

            self._station_bufs[st].append(myqscd, recv_wall, recv_diff)

            if self._data_fp is not None:
                try:
                    self._data_fp.write(pack_qscd20_bin_record(pmyqscd, recv_diff))
                except OSError as e:
                    self._logger.error(f"바이너리 쓰기 오류: {e}", extra={"station": st})

            log_qscd_packet(
                self._logger,
                pmyqscd,
                myqscd,
                st,
                recv_wall=recv_wall,
                recv_diff=recv_diff,
            )
            self._gui_log_packet(pmyqscd, myqscd, st, recv_wall, recv_diff)

            if self._selected_station == st:
                last_selected = myqscd
                self._live_chart_dirty = True

        self._flush_bin_if_needed(n_packets=len(batch))

        if last_selected is not None:
            self._lbl_live_quality.setText(format_quality_flag_line(last_selected))
            self._set_live_station_labels(last_selected)
            self._update_last_recv_label()

    def _gui_log_stamp(self, ts: float) -> str:
        t = datetime.datetime.fromtimestamp(ts)
        return t.strftime("%Y-%m-%d %H:%M:%S,") + f"{int(t.microsecond / 1000):03d}"

    def _gui_packet_body_lines(
        self,
        pmyqscd: bytes,
        myqscd: Tuple[Any, ...],
        station: str,
        recv_wall: float,
        recv_diff: float,
    ) -> List[str]:
        if GUI_LOG_VERBOSE:
            return format_qscd_packet_detail_lines(
                pmyqscd, myqscd, recv_wall=recv_wall, recv_diff=recv_diff
            )
        return [
            format_qscd_packet_summary_line(
                myqscd, station, recv_wall=recv_wall, recv_diff=recv_diff
            )
        ]

    def _format_gui_packet_lines(
        self,
        pmyqscd: bytes,
        myqscd: Tuple[Any, ...],
        station: str,
        recv_wall: float,
        recv_diff: float,
        log_time: float,
    ) -> List[str]:
        stamp = self._gui_log_stamp(log_time)
        return [
            f"[INFO] {stamp} > {line}"
            for line in self._gui_packet_body_lines(
                pmyqscd, myqscd, station, recv_wall, recv_diff
            )
        ]

    def _trim_gui_log_items(self) -> None:
        cap = max(200, int(LOG_MAX_LINES))
        extra = len(self._gui_log_items) - cap
        if extra > 0:
            del self._gui_log_items[:extra]

    def _gui_log_packet(
        self,
        pmyqscd: bytes,
        myqscd: Tuple[Any, ...],
        station: str,
        recv_wall: float,
        recv_diff: float,
    ) -> None:
        sel = self._selected_station
        if not sel or station != sel:
            return
        item = ("pkt", pmyqscd, myqscd, station, recv_wall, recv_diff, time.time())
        self._gui_log_items.append(item)
        self._trim_gui_log_items()
        for line in self._format_gui_packet_lines(
            pmyqscd, myqscd, station, recv_wall, recv_diff, item[6]
        ):
            self._log_view.appendPlainText(line)

    def _append_log_line(self, line: str) -> None:
        self._gui_log_items.append(("sys", line))
        self._trim_gui_log_items()
        self._log_view.appendPlainText(line)

    def _clear_gui_log(self) -> None:
        self._gui_log_items.clear()
        self._log_view.clear()

    def _rebuild_gui_log_view(self) -> None:
        lines: List[str] = []
        for item in self._gui_log_items:
            if item[0] == "sys":
                lines.append(item[1])
                continue
            _kind, pmyqscd, myqscd, station, recv_wall, recv_diff, log_time = item
            lines.extend(
                self._format_gui_packet_lines(
                    pmyqscd, myqscd, station, recv_wall, recv_diff, log_time
                )
            )
        self._log_view.setUpdatesEnabled(False)
        try:
            self._log_view.setPlainText("\n".join(lines))
            self._log_view.moveCursor(QtGui.QTextCursor.End)
        finally:
            self._log_view.setUpdatesEnabled(True)

    def _update_path_labels(self) -> None:
        pfx = self._edit_prefix.text().strip() or "QSCD"
        try:
            log_dir = _runtime_settings.resolved_log_dir()
            bin_dir = _runtime_settings.resolved_bin_dir()
            self._lbl_paths.setText(
                f"로그: {os.path.join(log_dir, f'{pfx}.QSCD.log')}\n"
                f"바이너리: {os.path.join(bin_dir, f'{pfx}{REPLAY_SUFFIX}')}"
            )
        except ValueError:
            self._lbl_paths.setText("저장 경로 오류 — 메뉴 → 기본 설정을 확인하세요.")

    def _ensure_save_dirs(self) -> Tuple[str, str]:
        try:
            log_dir = _runtime_settings.resolved_log_dir()
            bin_dir = _runtime_settings.resolved_bin_dir()
        except ValueError as e:
            QtWidgets.QMessageBox.warning(self, "경로 오류", str(e))
            raise
        for d in (log_dir, bin_dir):
            if not os.path.isdir(d):
                try:
                    os.makedirs(d, exist_ok=True)
                except OSError as ex:
                    QtWidgets.QMessageBox.critical(self, "경로 오류", str(ex))
                    raise
        return log_dir, bin_dir

    def _on_start(self) -> None:
        if self._receiver is not None:
            return
        try:
            log_dir, bin_dir = self._ensure_save_dirs()
        except (ValueError, OSError):
            return

        prefix = self._edit_prefix.text().strip()
        try:
            prefix = sanitize_file_prefix(prefix)
        except ValueError as e:
            QtWidgets.QMessageBox.warning(self, "prefix 오류", str(e))
            return

        log_path = os.path.join(log_dir, f"{prefix}.QSCD.log")
        bin_path = os.path.join(bin_dir, f"{prefix}{REPLAY_SUFFIX}")
        existing = [p for p in (log_path, bin_path) if os.path.exists(p)]
        if existing:
            ans = QtWidgets.QMessageBox.question(
                self,
                "파일 덮어쓰기",
                "같은 이름의 파일이 이미 있습니다. 내용을 지우고 새로 기록할까요?\n\n"
                + "\n".join(existing),
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
                QtWidgets.QMessageBox.No,
            )
            if ans != QtWidgets.QMessageBox.Yes:
                return

        try:
            # 덮어쓰기 확인을 받았으므로 로그도 bin과 같이 새로 쓴다(기본값 append 아님).
            fh = logging.FileHandler(log_path, mode="w", encoding="utf-8")
            fh.setFormatter(self._formatter)
            fh.addFilter(PacketLogKindFilter())
            self._logger.addHandler(fh)
            self._file_handler = fh
        except OSError as e:
            QtWidgets.QMessageBox.critical(self, "로그 오류", str(e))
            return

        try:
            self._data_fp = open(bin_path, "wb")
            write_qscd20_bin_header(self._data_fp)
        except OSError as e:
            if self._data_fp is not None:
                try:
                    self._data_fp.close()
                except OSError:
                    pass
                self._data_fp = None
            if self._file_handler is not None:
                self._logger.removeHandler(self._file_handler)
                self._file_handler.close()
                self._file_handler = None
            QtWidgets.QMessageBox.critical(self, "파일 오류", str(e))
            return

        self._station_bufs.clear()
        self._bin_flush_pending = 0
        self._live_chart_dirty = False
        self._selected_station = ""
        self._clear_gui_log()
        self._combo_station.blockSignals(True)
        self._combo_station.clear()
        self._combo_station.addItem("(관측소 선택)")
        self._combo_station.blockSignals(False)
        self._chart_window_sec = int(self._combo_time_window.currentData())
        self._live_charts.set_window_sec(self._chart_window_sec)
        self._live_charts.set_active_panels(self._get_checked_panels())
        self._reset_live_header_labels()
        self._update_last_recv_label()

        port = int(self._spin_port.value())
        self._outputs_open = True
        self._receiver = UdpReceiver(HOST, port, self)
        self._packet_source = self._receiver
        self._receiver.timeout_warning.connect(self._on_timeout_warning)
        self._receiver.error_occurred.connect(self._on_udp_error)
        self._receiver.recv_issue.connect(self._on_recv_issue)
        self._receiver.finished.connect(self._on_receiver_finished)
        self._receiver.start()
        try:
            self._receiver.setPriority(QtCore.QThread.HighestPriority)
        except Exception:
            pass

        self._btn_start.setEnabled(False)
        self._btn_stop.setEnabled(True)
        self._spin_port.setEnabled(False)
        self._edit_prefix.setEnabled(False)
        self._set_status(f"수신 중 — UDP {HOST}:{port}")
        self._logger.info(
            f"수신 시작: {HOST}:{port}, 로그={log_path}, bin={bin_path}",
            extra={"station": ""},
        )

    def _on_stop(self) -> None:
        if self._receiver is not None:
            self._receiver.stop()
            if not self._receiver.wait(5000):
                self._receiver.terminate()
                self._receiver.wait(2000)
            self._receiver = None
        self._close_session_outputs()
        self._reset_receive_ui()

    def _drain_remaining_packets(self) -> None:
        """세션 종료 시 남은 패킷을 모두 기록한다. 양이 많으면 잠시 멈출 수 있다."""
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        try:
            self._drain_packet_queue(drain_all=True)
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()

    def _close_session_outputs(self) -> None:
        if not self._outputs_open:
            self._packet_source = None
            return
        self._outputs_open = False
        self._drain_remaining_packets()
        self._packet_source = None
        # 파일 핸들러를 떼기 전에 남겨야 로그 파일에도 종료 기록이 남는다.
        self._logger.info("수신 중지됨.", extra={"station": ""})
        if self._data_fp is not None:
            self._flush_bin_if_needed(force=True)
            try:
                self._data_fp.close()
            except OSError:
                pass
            self._data_fp = None
        if self._file_handler is not None:
            self._logger.removeHandler(self._file_handler)
            try:
                self._file_handler.close()
            except Exception:
                pass
            self._file_handler = None

    def _reset_receive_ui(self) -> None:
        self._btn_start.setEnabled(True)
        self._btn_stop.setEnabled(False)
        self._spin_port.setEnabled(True)
        self._edit_prefix.setEnabled(True)
        self._set_status("대기 중")
        self._reset_live_header_labels()
        self._update_last_recv_label()
        self._apply_last_recv_normal_style()

    def _on_receiver_finished(self) -> None:
        thr = self.sender()
        if self._receiver is thr:
            self._receiver = None
        if self._outputs_open:
            self._close_session_outputs()
            self._reset_receive_ui()
        # 남은 패킷을 모두 꺼낸 뒤에 스레드 객체를 해제한다.
        if isinstance(thr, UdpReceiver):
            thr.deleteLater()

    def _on_timeout_warning(self, msg: str) -> None:
        self._logger.warning(msg, extra={"station": ""})

    def _on_udp_error(self, msg: str) -> None:
        self._logger.error(msg, extra={"station": ""})
        QtWidgets.QMessageBox.warning(self, "UDP", msg)

    def _on_recv_issue(self, msg: str) -> None:
        self._logger.error(msg, extra={"station": ""})

    def _set_live_station_labels(self, myqscd: Tuple[Any, ...]) -> None:
        self._lbl_live_station.setText(station_code_str(myqscd) or "—")
        self._lbl_live_location.setText(location_str(myqscd) or "—")

    def _reset_live_header_labels(self) -> None:
        self._lbl_live_quality.setText("—")
        self._lbl_live_station.setText("—")
        self._lbl_live_location.setText("—")

    def _open_bin_file(self) -> None:
        try:
            start_dir = _runtime_settings.resolved_bin_dir()
        except ValueError:
            start_dir = work_directory()
        if not os.path.isdir(start_dir):
            start_dir = work_directory()
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "QSCD20.replay 열기",
            start_dir,
            "QSCD20.replay (*.QSCD20.replay);;이전 형식 (*.bin);;All (*.*)",
        )
        if not path:
            return
        try:
            loaded = read_qscd20_bin(path)
        except OSError as e:
            QtWidgets.QMessageBox.critical(self, "파일 오류", str(e))
            return
        if not loaded.records:
            self._file_records = []
            self._file_recv_diffs = None
            self._populate_file_station_combo([])
            self._lbl_file_info.setText(f"{path}\n유효한 레코드가 없습니다.")
            self._file_charts.set_static_from_records([])
            return

        self._file_records = loaded.records
        self._file_recv_diffs = loaded.recv_diffs if loaded.has_stored_diff else None

        recs = loaded.records
        stations = unique_station_codes(recs)
        t0 = format_kst_dt(float(recs[0][6]))
        t1 = format_kst_dt(float(recs[-1][6]))
        diff_note = (
            "TimeDiff: 파일에 저장된 Live 값 사용"
            if loaded.has_stored_diff
            else "TimeDiff: 저장값 없음(열기 시각 기준 근사)"
        )
        st_info = ", ".join(stations) if stations else "—"
        self._lbl_file_info.setText(
            f"{path}\n레코드 수: {len(recs)}  ·  관측소 {len(stations)}개: {st_info}\n"
            f"{diff_note}\n"
            f"전체 data time(KST): {t0} ~ {t1}"
        )
        self._populate_file_station_combo(recs)
        self._file_charts.set_window_sec(int(self._combo_file_time_window.currentData()))
        self._file_charts.set_active_panels(self._get_file_checked_panels())
        self._refresh_file_charts()

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        self._on_stop()
        if self._dlg_log is not None:
            self._dlg_log.close()
        if self._dlg_help is not None:
            self._dlg_help.close()
        if self._dlg_basic_settings is not None:
            self._dlg_basic_settings.close()
        super().closeEvent(event)


def main() -> int:
    app = QtWidgets.QApplication(sys.argv)
    w = MainWindow()
    w.show()
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
