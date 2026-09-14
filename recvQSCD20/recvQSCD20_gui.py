#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
QSCD20 UDP 수신 GUI (PyQt5 + pyqtgraph) — 설정: recvQSCD20_gui_settings.json

실행:
    pip install -r requirements.txt
    python recvQSCD20_gui.py

메뉴: 기본 설정. 로그 뷰어는 Live·Detail View·File View 탭 상단 아이콘. 수신(UDP·Start/Stop)은 메인 우측 패널.
"""
from __future__ import annotations

import datetime
import logging
import multiprocessing
import os
import queue
import re
import struct
import sys
import time
import zlib
from typing import Any, Dict, List, NamedTuple, Optional, Tuple

import numpy as np
import pyqtgraph as pg
from PyQt5 import QtCore, QtGui, QtWidgets


def _prepare_qtwebengine_chromium() -> None:
    """QWebEngineView GPU 실패(GLX SharedImageStub) 완화. QApplication·WebEngine import 전에 호출."""
    if not sys.platform.startswith("linux"):
        return
    extra = (
        "--disable-gpu",
        "--disable-gpu-compositing",
        "--disable-gpu-sandbox",
        "--in-process-gpu",
        "--disable-dev-shm-usage",
    )
    cur = os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", "").strip()
    parts = cur.split()
    for flag in extra:
        if flag not in parts:
            parts.append(flag)
    os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = " ".join(parts)


_prepare_qtwebengine_chromium()

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

from qscd_udp_capture import (
    QSCD_LEN,
    QSCD20_FMT,
    IDX_CRC,
    IDX_FLAG,
    IDX_TYPE,
    IDX_VER,
    IDX_STA,
    IDX_TIME,
    IDX_UDWMIN,
    IDX_UDWMAX,
    IDX_UDWAVG,
    IDX_NSWMIN,
    IDX_NSWMAX,
    IDX_NSWAVG,
    IDX_EWWMIN,
    IDX_EWWMAX,
    IDX_EWWAVG,
    IDX_UDTMIN,
    IDX_UDTMAX,
    IDX_NSTMIN,
    IDX_NSTMAX,
    IDX_EWTMIN,
    IDX_EWTMAX,
    IDX_UDMAX,
    IDX_NSMAX,
    IDX_EWMAX,
    IDX_HPGA,
    IDX_TPGA,
    IDX_UDSI,
    IDX_NSSI,
    IDX_EWSI,
    IDX_HSI,
    IDX_CORR,
    IDX_CHAN1,
    IDX_CHAN2,
    IDX_LOC,
    qscd20_loc_str,
    QSCD20_QF_GOOD_DATA,
    QSCD20_QF_GPS_UNLOCK,
    QSCD20_QF_REBOOT,
    QSCD20_QF_SPIKE,
    capture_recv_wall,
    compute_recv_time_diff,
    describe_qscd20_data_type,
    run_udp_capture_process,
)
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

FALLBACK_VERSION = "1.0"


def _load_gui_version() -> str:
    try:
        vpath = os.path.join(os.path.dirname(os.path.abspath(__file__)), "VERSION")
        with open(vpath, encoding="utf-8") as f:
            return f.read().strip() or FALLBACK_VERSION
    except OSError:
        return FALLBACK_VERSION


GUI_VERSION = _load_gui_version()

HOST = "0.0.0.0"
# QSCD20.replay: 매직 + (120B 패킷 + 8B recv−data TimeDiff) — 설정 파일에서 변경 불가
BIN_FILE_MAGIC = b"QCDX\x01"
QSCD_BIN_REC_LEN = QSCD_LEN + 8
DIFF_PACK_FMT = ">d"
REPLAY_SUFFIX = ".QSCD20.replay"
LOG_FILE_SUFFIX = ".QSCD.log"
FILE_LOG_BLOCK_CAP = 3000

KST_OFFSET = 9 * 3600
TZ_KST = "KST"
TZ_UTC = "UTC"
DISPLAY_TZ = TZ_KST

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
QWidget#TzToggle {
    background: transparent;
}
QLabel#TzToggleLabel {
    color: #334155;
    font-size: 11px;
    font-weight: 600;
}
QToolButton#BtnTz {
    min-width: 44px;
    padding: 3px 10px;
    border: 1px solid #94a3b8;
    background: #ffffff;
    color: #334155;
    font-weight: 700;
}
QToolButton#BtnTz:checked {
    background: #2563eb;
    color: #ffffff;
    border-color: #1d4ed8;
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
QFrame#LiveStationCard {
    background: #ffffff;
    border: 1px solid #64748b;
    border-radius: 4px;
}
QFrame#LiveStationSidebar {
    background: #3b82f6;
    border: none;
}
QFrame#LiveTsWrap {
    background: #ffffff;
    border-top: 3px solid #3b82f6;
}
QScrollArea#LiveOverviewScroll {
    background: #f1f5f9;
    border: 1px solid #cbd5e1;
    border-radius: 6px;
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
    "wmma_ud_m": IDX_UDWMIN,
    "wmma_ud_M": IDX_UDWMAX,
    "wmma_ud_A": IDX_UDWAVG,
    "wmma_ns_m": IDX_NSWMIN,
    "wmma_ns_M": IDX_NSWMAX,
    "wmma_ns_A": IDX_NSWAVG,
    "wmma_ew_m": IDX_EWWMIN,
    "wmma_ew_M": IDX_EWWMAX,
    "wmma_ew_A": IDX_EWWAVG,
    "tmm_ud_m": IDX_UDTMIN,
    "tmm_ud_M": IDX_UDTMAX,
    "tmm_ns_m": IDX_NSTMIN,
    "tmm_ns_M": IDX_NSTMAX,
    "tmm_ew_m": IDX_EWTMIN,
    "tmm_ew_M": IDX_EWTMAX,
    "max_Z": IDX_UDMAX,
    "max_N": IDX_NSMAX,
    "max_E": IDX_EWMAX,
    "pga_H": IDX_HPGA,
    "pga_T": IDX_TPGA,
}

DEFAULT_PANELS = frozenset({"diff", "max", "pga"})


def _apply_gui_settings(s: Optional[GuiSettings] = None, *, fallback: bool = False) -> GuiSettings:
    """설정 파일 값을 모듈 전역 및 _runtime_settings에 반영."""
    global _runtime_settings
    global DEFAULT_PORT, DEFAULT_TIME_WINDOW_SEC, TIME_WINDOW_CHOICES
    global DEFAULT_PANELS, DEFAULT_SHOW_LEGEND, LOG_MAX_LINES, CHART_REFRESH_MS
    global PACKET_DRAIN_MAX, PACKET_QUEUE_MAX, BIN_FLUSH_EVERY, LIVE_LOG_VERBOSE
    global RECV_DELAY_ALERT_SEC, RECV_ALERT_BLINK_MS, SockTimeOut, SockTimeOutCount
    global DISPLAY_TZ

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
    DISPLAY_TZ = TZ_UTC if str(cfg.display_tz).strip().upper() == TZ_UTC else TZ_KST
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


class DisplayTimeAxisItem(pg.AxisItem):
    """차트 x축 — 저장값은 UTC epoch, 화면은 DISPLAY_TZ (기본 KST)."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.enableAutoSIPrefix(False)
        self.refresh_tz_label()

    def refresh_tz_label(self) -> None:
        self.setLabel(text=f"시각 ({DISPLAY_TZ})", units=None)

    def tickStrings(self, values: List[float], scale: float, spacing: float) -> List[str]:
        out: List[str] = []
        off = display_tz_offset_sec()
        for v in values:
            try:
                t = datetime.datetime.utcfromtimestamp(v + off)
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


def _char_array_str(value: Any, length: int) -> str:
    """C char[N] → 문자열. NUL만 제거하고 공백은 유지한다."""
    if isinstance(value, str):
        raw = value.encode("latin-1", errors="replace")
    elif isinstance(value, (bytes, bytearray, memoryview)):
        raw = bytes(value)
    elif isinstance(value, int):
        raw = bytes([value & 0xFF])
    else:
        try:
            raw = bytes(value)
        except (TypeError, ValueError):
            raw = str(value).encode("latin-1", errors="replace")
    return raw[:length].decode("latin-1", errors="replace").replace("\x00", "")


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
    if q == QSCD20_QF_GOOD_DATA:
        return "Good data"
    if q == QSCD20_QF_GPS_UNLOCK:
        return "GPS Unlock"
    if q == QSCD20_QF_REBOOT:
        return "REBOOT"
    if q == QSCD20_QF_SPIKE:
        return "SPIKE"
    return "Reserved for Future Use"


def station_code_bytes(myqscd: Tuple[Any, ...]) -> bytes:
    p = myqscd[IDX_STA]
    return bytes(p) if isinstance(p, (bytes, bytearray)) else bytes(p)


def station_code_str(myqscd: Tuple[Any, ...]) -> str:
    raw = station_code_bytes(myqscd)
    return _decode_bytes(raw).strip() or raw.decode("latin-1", errors="replace").strip()


def location_str(myqscd: Tuple[Any, ...]) -> str:
    """char loc[2] → 2글자 문자열. 0x00 은 '0' (예: \\x00\\x00 → '00')."""
    return qscd20_loc_str(myqscd[IDX_LOC])


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
    q = byte_to_u8(myqscd[IDX_FLAG])
    return f"0x{q:02X} — {describe_quality_flag(q)}"


def format_kst_dt(epoch_sec: float) -> str:
    return format_display_dt(epoch_sec, tz=TZ_KST)


def normalize_display_tz(value: Any = None) -> str:
    raw = DISPLAY_TZ if value is None else value
    return TZ_UTC if str(raw).strip().upper() == TZ_UTC else TZ_KST


def display_tz_offset_sec(tz: Any = None) -> int:
    return KST_OFFSET if normalize_display_tz(tz) == TZ_KST else 0


def format_display_dt(epoch_sec: float, *, tz: Any = None, with_ms: bool = False) -> str:
    name = normalize_display_tz(tz)
    t = datetime.datetime.utcfromtimestamp(float(epoch_sec) + display_tz_offset_sec(name))
    if with_ms:
        body = t.strftime("%Y-%m-%d %H:%M:%S,") + f"{int(t.microsecond / 1000):03d}"
    else:
        body = t.strftime("%Y-%m-%d %H:%M:%S")
    return f"{body} {name}"


def format_display_hms(epoch_sec: float, *, tz: Any = None) -> str:
    name = normalize_display_tz(tz)
    t = datetime.datetime.utcfromtimestamp(float(epoch_sec) + display_tz_offset_sec(name))
    return t.strftime("%H:%M:%S")


_DISPLAY_DT_RE = re.compile(
    r"(?P<dt>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})(?P<frac>[,.]\d+)?"
)


def shift_utc_text_for_display(text: str, tz: Any = None) -> str:
    """로그 파일에 저장된 UTC 시각 문자열을 화면 표시 시차로 바꾼다."""
    name = normalize_display_tz(tz)
    if name == TZ_UTC or not text:
        return text
    delta = datetime.timedelta(seconds=display_tz_offset_sec(name))

    def _repl(match: re.Match) -> str:
        stamp = match.group("dt")
        frac = match.group("frac") or ""
        try:
            dt = datetime.datetime.strptime(stamp, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return match.group(0)
        return (dt + delta).strftime("%Y-%m-%d %H:%M:%S") + frac

    return _DISPLAY_DT_RE.sub(_repl, text)


class UtcLogFormatter(logging.Formatter):
    """파일·화면 원본 로그의 asctime 을 UTC 로 기록한다."""

    converter = time.gmtime


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


def make_log_viewer_toolbutton(
    parent: Optional[QtWidgets.QWidget],
    tooltip: str,
    slot: Any,
) -> QtWidgets.QToolButton:
    btn = QtWidgets.QToolButton(parent)
    btn.setObjectName("BtnLogViewer")
    btn.setIcon(make_log_viewer_icon(22))
    btn.setIconSize(QtCore.QSize(22, 22))
    btn.setFixedSize(32, 32)
    btn.setAutoRaise(False)
    btn.setCursor(QtCore.Qt.PointingHandCursor)
    btn.setToolTip(tooltip)
    btn.setAccessibleName("로그 뷰어")
    btn.clicked.connect(slot)
    return btn


def _sync_combo_from(src: QtWidgets.QComboBox, dst: QtWidgets.QComboBox) -> None:
    """src의 항목·선택·활성 상태를 dst에 그대로 복사한다."""
    cur = src.currentText()
    dst.blockSignals(True)
    dst.clear()
    for i in range(src.count()):
        dst.addItem(src.itemText(i), src.itemData(i))
    idx = dst.findText(cur)
    dst.setCurrentIndex(idx if idx >= 0 else 0)
    dst.setEnabled(src.isEnabled())
    dst.blockSignals(False)


class TzToggleWidget(QtWidgets.QWidget):
    """KST / UTC 배타 토글. 저장값은 UTC, 화면 표출만 바꾼다."""

    tz_changed = QtCore.pyqtSignal(str)

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None, *, show_label: bool = True) -> None:
        super().__init__(parent)
        self.setObjectName("TzToggle")
        row = QtWidgets.QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)
        if show_label:
            lbl = QtWidgets.QLabel("시간")
            lbl.setObjectName("TzToggleLabel")
            row.addWidget(lbl)
        self._btn_kst = QtWidgets.QToolButton()
        self._btn_kst.setObjectName("BtnTz")
        self._btn_kst.setText(TZ_KST)
        self._btn_kst.setCheckable(True)
        self._btn_kst.setToolTip("한국 표준시(UTC+9)로 표시합니다. 저장 값은 UTC입니다.")
        self._btn_utc = QtWidgets.QToolButton()
        self._btn_utc.setObjectName("BtnTz")
        self._btn_utc.setText(TZ_UTC)
        self._btn_utc.setCheckable(True)
        self._btn_utc.setToolTip("UTC로 표시합니다. 로그·QSCD 데이터 저장 형식과 같습니다.")
        group = QtWidgets.QButtonGroup(self)
        group.setExclusive(True)
        group.addButton(self._btn_kst)
        group.addButton(self._btn_utc)
        self._btn_kst.clicked.connect(lambda: self._emit(TZ_KST))
        self._btn_utc.clicked.connect(lambda: self._emit(TZ_UTC))
        row.addWidget(self._btn_kst)
        row.addWidget(self._btn_utc)
        self.set_tz(DISPLAY_TZ)

    def _emit(self, tz: str) -> None:
        self.tz_changed.emit(normalize_display_tz(tz))

    def set_tz(self, tz: Any) -> None:
        name = normalize_display_tz(tz)
        self._btn_kst.blockSignals(True)
        self._btn_utc.blockSignals(True)
        self._btn_kst.setChecked(name == TZ_KST)
        self._btn_utc.setChecked(name == TZ_UTC)
        self._btn_kst.blockSignals(False)
        self._btn_utc.blockSignals(False)


class FileLogBlock(NamedTuple):
    epoch: float
    station: str
    text: str


_RECV_TIME_RE = re.compile(r"Recv\s*:\s*(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")
_STATION_CODE_RE = re.compile(r"Station Code(?: \(5B\))?:\s*(\S+)")
_PACKET_SEP = "#########################################################################"


def replay_prefix_from_path(path: str) -> str:
    name = os.path.basename(path)
    if name.endswith(REPLAY_SUFFIX):
        return name[: -len(REPLAY_SUFFIX)]
    root, _ext = os.path.splitext(name)
    return root or name


def companion_log_candidates(replay_path: str, log_dir: Optional[str] = None) -> List[str]:
    prefix = replay_prefix_from_path(replay_path)
    replay_dir = os.path.dirname(os.path.abspath(replay_path))
    name = f"{prefix}{LOG_FILE_SUFFIX}"
    out: List[str] = [os.path.join(replay_dir, name)]
    if log_dir:
        out.append(os.path.join(os.path.abspath(log_dir), name))
    seen = set()
    uniq: List[str] = []
    for p in out:
        key = os.path.normcase(os.path.normpath(p))
        if key in seen:
            continue
        seen.add(key)
        uniq.append(p)
    return uniq


def find_companion_log(replay_path: str, log_dir: Optional[str] = None) -> Optional[str]:
    for path in companion_log_candidates(replay_path, log_dir):
        if os.path.isfile(path):
            return path
    return None


def read_text_file_guess(path: str) -> str:
    with open(path, "rb") as fp:
        raw = fp.read()
    for enc in ("utf-8-sig", "utf-8", "cp949"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def utc_log_time_to_epoch(stamp: str) -> Optional[float]:
    try:
        dt = datetime.datetime.strptime(stamp, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None
    return dt.replace(tzinfo=datetime.timezone.utc).timestamp()


def parse_qscd_log_blocks(text: str) -> List[FileLogBlock]:
    """`.QSCD.log` 상세 패킷 블록을 data time(Unix epoch) 기준으로 나눈다."""
    blocks: List[FileLogBlock] = []
    current: List[str] = []

    def flush(chunk: List[str]) -> None:
        if not chunk:
            return
        body = "\n".join(chunk)
        matched = _RECV_TIME_RE.search(body)
        if not matched:
            return
        epoch = utc_log_time_to_epoch(matched.group(1))
        if epoch is None:
            return
        sm = _STATION_CODE_RE.search(body)
        station = sm.group(1).strip() if sm else ""
        blocks.append(FileLogBlock(float(epoch), station, body))

    for line in text.splitlines():
        if _PACKET_SEP in line and current:
            flush(current)
            current = [line]
        else:
            current.append(line)
    flush(current)
    return blocks


def filter_file_log_blocks(
    blocks: List[FileLogBlock],
    *,
    x0: Optional[float] = None,
    x1: Optional[float] = None,
    station: str = "",
) -> List[FileLogBlock]:
    st = station.strip()
    out: List[FileLogBlock] = []
    for block in blocks:
        if st and block.station and block.station != st:
            continue
        if x0 is not None and block.epoch < float(x0):
            continue
        if x1 is not None and block.epoch > float(x1):
            continue
        out.append(block)
    return out


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
        sec = int(float(r[IDX_TIME]))
        if recv_diffs is not None and i < len(recv_diffs):
            diff = float(recv_diffs[i])
        else:
            diff = fallback_recv - float(r[IDX_TIME])
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
    *,
    tz: Any = TZ_UTC,
) -> Tuple[datetime.datetime, datetime.datetime, float]:
    off = display_tz_offset_sec(tz)
    wall = float(recv_wall) if recv_wall is not None else time.time()
    rtime = datetime.datetime.utcfromtimestamp(wall + off)
    dtime = datetime.datetime.utcfromtimestamp(float(myqscd[IDX_TIME]) + off)
    if recv_diff is not None:
        diff = float(recv_diff)
    elif recv_wall is not None:
        diff = compute_recv_time_diff(recv_wall, myqscd)
    else:
        diff = wall - float(myqscd[IDX_TIME])
    return rtime, dtime, diff


def format_qscd_packet_summary_line(
    myqscd: Tuple[Any, ...],
    station: str,
    *,
    recv_wall: Optional[float] = None,
    recv_diff: Optional[float] = None,
    tz: Any = TZ_UTC,
) -> str:
    _rtime, _dtime, diff = _packet_recv_times(myqscd, recv_wall, recv_diff, tz=tz)
    return (
        "[{}] Q={} st={} loc={} | data={} diff={:.3f}s | Zmax={:.6g} Hpga={:.6g}".format(
            station,
            describe_quality_flag(byte_to_u8(myqscd[IDX_FLAG])),
            station_code_str(myqscd),
            location_str(myqscd) or "—",
            format_display_dt(float(myqscd[IDX_TIME]), tz=tz),
            diff,
            float(myqscd[IDX_UDMAX]),
            float(myqscd[IDX_HPGA]),
        )
    )


def format_qscd_packet_detail_lines(
    pmyqscd: bytes,
    myqscd: Tuple[Any, ...],
    *,
    recv_wall: Optional[float] = None,
    recv_diff: Optional[float] = None,
    tz: Any = TZ_UTC,
) -> List[str]:
    rtime, dtime, diff = _packet_recv_times(myqscd, recv_wall, recv_diff, tz=tz)
    buf_4_crc = pmyqscd[4:]
    mycrc = zlib.crc32(buf_4_crc) & 0xFFFFFFFF
    crc_recv = myqscd[IDX_CRC] & 0xFFFFFFFF
    if mycrc != crc_recv:
        crc_line = "     CRC : received {} calculated {} :::: Un-matched ".format(crc_recv, mycrc)
    else:
        crc_line = "     CRC : received {} calculated {}".format(crc_recv, mycrc)
    sta = station_code_bytes(myqscd)
    return [
        "#########################################################################",
        "Quality Flag: {}".format(format_quality_flag_line(myqscd)),
        "Station Code: {}".format(format_station_code_line(myqscd)),
        "{:2s}/{:3s}/{:2s} Recv : {} : Now : {} : Diff : {:.4f} s".format(
            _decode_bytes(sta[:2]),
            _decode_bytes(sta[2:5]),
            location_str(myqscd),
            dtime,
            rtime,
            diff,
        ),
        crc_line,
        "Data Type / Ver: {} / {}".format(
            describe_qscd20_data_type(byte_to_u8(myqscd[IDX_TYPE])),
            byte_to_u8(myqscd[IDX_VER]),
        ),
        "U-D WMMA : m {:.10f} M {:10f} A {:10f}".format(
            myqscd[IDX_UDWMIN], myqscd[IDX_UDWMAX], myqscd[IDX_UDWAVG]
        ),
        "N-S WMMA : m {:.10f} M {:10f} A {:10f}".format(
            myqscd[IDX_NSWMIN], myqscd[IDX_NSWMAX], myqscd[IDX_NSWAVG]
        ),
        "E-W WMMA : m {:.10f} M {:10f} A {:10f}".format(
            myqscd[IDX_EWWMIN], myqscd[IDX_EWWMAX], myqscd[IDX_EWWAVG]
        ),
        "U-D TMM  : m {:.10f} M {:10f}".format(myqscd[IDX_UDTMIN], myqscd[IDX_UDTMAX]),
        "N-S TMM  : m {:.10f} M {:10f}".format(myqscd[IDX_NSTMIN], myqscd[IDX_NSTMAX]),
        "E-W TMM  : m {:.10f} M {:10f}".format(myqscd[IDX_EWTMIN], myqscd[IDX_EWTMAX]),
        "Maximum  : Z {:.10f} N {:10f} E {:10f}".format(
            myqscd[IDX_UDMAX], myqscd[IDX_NSMAX], myqscd[IDX_EWMAX]
        ),
        "    PGA  : H {:.10f} T {:10f}".format(myqscd[IDX_HPGA], myqscd[IDX_TPGA]),
        " Each SI : Z {:.10f} N {:10f} E {:10f} H {}".format(
            myqscd[IDX_UDSI], myqscd[IDX_NSSI], myqscd[IDX_EWSI], myqscd[IDX_HSI]
        ),
        "Correlate: C {:.10f} Ch1 {} Ch2 {} Loc {}".format(
            myqscd[IDX_CORR],
            _char_array_str(myqscd[IDX_CHAN1], 1),
            _char_array_str(myqscd[IDX_CHAN2], 1),
            location_str(myqscd),
        ),
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
# UDP 수신 펌프 스레드 (TimeDiff 확정은 전용 프로세스)
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
        self._packets: queue.Queue = queue.Queue(maxsize=max(200, PACKET_QUEUE_MAX))
        self._sock_timeout = max(MIN_SOCK_TIMEOUT_SEC, float(SockTimeOut))
        self._sock_timeout_count = int(SockTimeOutCount)
        # GUI가 쓰고 캡처 프로세스가 읽는다.
        self._pending_timeout: Optional[float] = None
        self._drop_count = 0
        self._stop_ev: Any = None
        self._timeout_sec_val: Any = None
        self._timeout_count_val: Any = None
        self._capture_proc: Any = None

    def stop(self) -> None:
        self._stop = True
        ev = self._stop_ev
        if ev is not None:
            try:
                ev.set()
            except Exception:
                pass

    def set_sock_params(self, timeout_sec: float, timeout_count: int) -> None:
        """캡처 프로세스가 다음 루프에서 적용하도록 예약만 한다."""
        self._sock_timeout_count = int(timeout_count)
        self._pending_timeout = max(MIN_SOCK_TIMEOUT_SEC, float(timeout_sec))
        if self._timeout_sec_val is not None:
            self._timeout_sec_val.value = float(self._pending_timeout)
            self._timeout_count_val.value = int(self._sock_timeout_count)

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

    def _dispatch_capture_msg(self, msg: Tuple[str, Any]) -> bool:
        """캡처 프로세스 메시지 처리. True면 수신 루프를 종료한다."""
        kind, payload = msg
        if kind == "pkt":
            self._enqueue(payload)
            return False
        if kind == "timeout":
            self.timeout_warning.emit(str(payload))
            return False
        if kind == "issue":
            self.recv_issue.emit(str(payload))
            return False
        if kind == "error":
            self.error_occurred.emit(str(payload))
            return True
        return False

    def run(self) -> None:
        """캡처 프로세스에서 TimeDiff를 확정하고, 이 스레드는 GUI 큐로만 전달한다."""
        self._stop = False
        ctx = multiprocessing.get_context("spawn")
        qmax = max(200, int(PACKET_QUEUE_MAX))
        out_q = ctx.Queue(maxsize=qmax)
        stop_ev = ctx.Event()
        timeout_sec = (
            float(self._pending_timeout)
            if self._pending_timeout is not None
            else float(self._sock_timeout)
        )
        timeout_sec = max(MIN_SOCK_TIMEOUT_SEC, timeout_sec)
        if self._pending_timeout is not None:
            self._sock_timeout = timeout_sec
            self._pending_timeout = None
        timeout_sec_val = ctx.Value("d", timeout_sec)
        timeout_count_val = ctx.Value("i", int(self._sock_timeout_count))
        self._stop_ev = stop_ev
        self._timeout_sec_val = timeout_sec_val
        self._timeout_count_val = timeout_count_val
        proc = ctx.Process(
            target=run_udp_capture_process,
            args=(
                self._host,
                self._port,
                qmax,
                out_q,
                stop_ev,
                timeout_sec_val,
                timeout_count_val,
            ),
            daemon=True,
        )
        self._capture_proc = proc
        proc.start()
        try:
            while not self._stop:
                try:
                    msg = out_q.get(timeout=0.05)
                except queue.Empty:
                    if proc.is_alive() or self._stop:
                        continue
                    while True:
                        try:
                            if self._dispatch_capture_msg(out_q.get_nowait()):
                                return
                        except queue.Empty:
                            break
                    self.error_occurred.emit("UDP 수신 프로세스가 예기치 않게 종료되었습니다.")
                    break
                else:
                    if self._dispatch_capture_msg(msg):
                        break
        finally:
            try:
                stop_ev.set()
            except Exception:
                pass
            if proc.is_alive():
                proc.join(timeout=2.0)
            if proc.is_alive():
                proc.terminate()
                proc.join(timeout=1.0)
            self._capture_proc = None
            self._stop_ev = None
            self._timeout_sec_val = None
            self._timeout_count_val = None


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
        sec = int(float(myqscd[IDX_TIME]))
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
            clock = format_display_hms(ts)
        except (OSError, ValueError, OverflowError):
            clock = "?"
        lines = [f"시각({DISPLAY_TZ}) {clock}"]
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
    x_range_changed = QtCore.pyqtSignal(float, float)

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
        self._xrange_timer = QtCore.QTimer(self)
        self._xrange_timer.setSingleShot(True)
        self._xrange_timer.setInterval(80)
        self._xrange_timer.timeout.connect(self._emit_visible_x_range)
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

    def visible_x_range(self) -> Optional[Tuple[float, float]]:
        for plot in self._plot_items:
            vb = plot.getViewBox()
            if vb is None:
                continue
            (x0, x1), _yr = vb.viewRange()
            return float(x0), float(x1)
        return None

    def _on_view_xrange_changed(self, *_args: Any) -> None:
        if self._live_mode:
            return
        self._xrange_timer.start()

    def _emit_visible_x_range(self) -> None:
        xr = self.visible_x_range()
        if xr is None:
            return
        self.x_range_changed.emit(xr[0], xr[1])

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
        axis = DisplayTimeAxisItem(orientation="bottom")
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
        if not self._live_mode and len(self._plot_items) > 1:
            plot.setXLink(self._plot_items[0])
        vb.sigXRangeChanged.connect(self._on_view_xrange_changed)
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

    def apply_display_tz(self) -> None:
        for plot in self._plot_items:
            axis = plot.getAxis("bottom")
            if isinstance(axis, DisplayTimeAxisItem):
                axis.refresh_tz_label()
            plot.update()

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


LIVE_PGA_H_RGBA = (201, 162, 39, 255)
LIVE_PGA_T_RGBA = (13, 148, 136, 255)
LIVE_CARD_HEIGHT = 248


def live_station_key(myqscd: Tuple[Any, ...]) -> str:
    return f"{station_code_str(myqscd)}|{location_str(myqscd)}"


def quality_badge_style(q: int) -> str:
    q &= 0xFF
    if q == QSCD20_QF_GOOD_DATA:
        bg = "#16a34a"
    elif q == QSCD20_QF_GPS_UNLOCK:
        bg = "#d97706"
    elif q == QSCD20_QF_REBOOT:
        bg = "#dc2626"
    elif q == QSCD20_QF_SPIKE:
        bg = "#ea580c"
    else:
        bg = "#64748b"
    return (
        f"background: {bg}; color: #ffffff; font-weight: 700; font-size: 11px; "
        "padding: 8px 6px; border-radius: 4px;"
    )


class LivePgaBarChart(pg.PlotWidget):
    """PGA H/T 막대. mode='current' 는 값, mode='peak' 는 시각/gal."""

    def __init__(self, mode: str, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(
            parent,
            axisItems={"left": PlainGalAxisItem(orientation="left")},
            background="#ffffff",
        )
        self._mode = mode
        self.setMinimumWidth(150)
        self.setMaximumWidth(200)
        self.setMouseEnabled(x=False, y=False)
        self.hideButtons()
        self.setMenuEnabled(False)
        pi = self.getPlotItem()
        pi.showGrid(x=False, y=True, alpha=0.25)
        pi.setLabel("left", "gal")
        pi.getAxis("bottom").setTicks([[(0, "H"), (1, "T")]])
        pi.getAxis("bottom").setHeight(22)
        pi.getViewBox().setDefaultPadding(0.08)
        h_brush = pg.mkBrush(*LIVE_PGA_H_RGBA)
        t_brush = pg.mkBrush(*LIVE_PGA_T_RGBA)
        self._h_brush = h_brush
        self._t_brush = t_brush
        self._pen = pg.mkPen("#1e293b", width=0.6)
        self._show_h = True
        self._show_t = True
        self._last_h = 0.0
        self._last_t = 0.0
        self._last_h_time: Optional[float] = None
        self._last_t_time: Optional[float] = None
        self._bars = pg.BarGraphItem(
            x=[0, 1],
            height=[0.0, 0.0],
            width=0.55,
            brushes=[h_brush, t_brush],
            pen=self._pen,
        )
        pi.addItem(self._bars)
        self._texts = [
            pg.TextItem(anchor=(0.5, 1), color=(30, 41, 59)),
            pg.TextItem(anchor=(0.5, 1), color=(30, 41, 59)),
        ]
        for t in self._texts:
            t.setZValue(20)
            pi.addItem(t, ignoreBounds=True)
        title = "현재 값" if mode == "current" else "누적 최대"
        pi.setTitle(title, color="#334155", size="10pt")

    def set_channels(self, show_h: bool, show_t: bool) -> None:
        self._show_h = bool(show_h)
        self._show_t = bool(show_t)
        self._apply_values()

    def set_values(
        self,
        h: float,
        t: float,
        *,
        h_time: Optional[float] = None,
        t_time: Optional[float] = None,
    ) -> None:
        self._last_h = float(h)
        self._last_t = float(t)
        self._last_h_time = h_time
        self._last_t_time = t_time
        self._apply_values()

    def _channel_specs(self) -> List[Tuple[str, float, Optional[float], Any]]:
        specs: List[Tuple[str, float, Optional[float], Any]] = []
        if self._show_h:
            specs.append(("H", self._last_h, self._last_h_time, self._h_brush))
        if self._show_t:
            specs.append(("T", self._last_t, self._last_t_time, self._t_brush))
        return specs

    def _format_label(self, value: float, when: Optional[float]) -> str:
        if self._mode == "peak":
            return "{}\n{:.3f} gal".format(
                format_display_hms(when) if when is not None else "—",
                float(value),
            )
        return f"{float(value):.3f}"

    def _apply_values(self) -> None:
        specs = self._channel_specs()
        if not specs:
            self._bars.setOpts(x=[0], height=[0.0], brushes=[self._h_brush])
            self.getPlotItem().getAxis("bottom").setTicks([[]])
            for txt in self._texts:
                txt.setText("")
            self.setYRange(0.0, 1.0, padding=0.02)
            return
        xs = list(range(len(specs)))
        heights = [s[1] for s in specs]
        brushes = [s[3] for s in specs]
        ticks = [(i, s[0]) for i, s in enumerate(specs)]
        self._bars.setOpts(x=xs, height=heights, brushes=brushes)
        self.getPlotItem().getAxis("bottom").setTicks([ticks])
        ymax = max([abs(v) for v in heights] + [0.05]) * 1.35
        self.setYRange(0.0, ymax, padding=0.02)
        for i, txt in enumerate(self._texts):
            if i < len(specs):
                _name, value, when, _br = specs[i]
                txt.setText(self._format_label(value, when))
                txt.setPos(xs[i], max(float(value), 0.0))
            else:
                txt.setText("")


class LiveStationCard(QtWidgets.QFrame):
    """관측소 1개 — 좌측 정보 + PGA 바 + 타임시리즈."""

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("LiveStationCard")
        self.setMinimumHeight(LIVE_CARD_HEIGHT)
        self.setMaximumHeight(LIVE_CARD_HEIGHT + 20)
        self._window_sec = DEFAULT_TIME_WINDOW_SEC
        self._xs: List[float] = []
        self._hs: List[float] = []
        self._ts: List[float] = []
        self._ds: List[float] = []
        self._peak_h = 0.0
        self._peak_t = 0.0
        self._peak_h_time: Optional[float] = None
        self._peak_t_time: Optional[float] = None
        self._last_data_time: Optional[float] = None
        self._last_recv_diff: Optional[float] = None
        self._last_recv_wall: Optional[float] = None
        self._show_h = True
        self._show_t = True
        self._cur_h = 0.0
        self._cur_t = 0.0

        root = QtWidgets.QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        side = QtWidgets.QFrame()
        side.setObjectName("LiveStationSidebar")
        side.setFixedWidth(148)
        side_l = QtWidgets.QVBoxLayout(side)
        side_l.setContentsMargins(10, 10, 10, 10)
        side_l.setSpacing(4)
        cap_style = "color: #e0e7ff; font-size: 10px;"
        val_style = "color: #ffffff; font-size: 16px; font-weight: 700;"
        self._lbl_sta_cap = QtWidgets.QLabel("Station Code")
        self._lbl_sta_cap.setAlignment(QtCore.Qt.AlignCenter)
        self._lbl_sta_cap.setStyleSheet(cap_style)
        self._lbl_sta = QtWidgets.QLabel("—")
        self._lbl_sta.setAlignment(QtCore.Qt.AlignCenter)
        self._lbl_sta.setStyleSheet(val_style)
        self._lbl_loc_cap = QtWidgets.QLabel("Location Code")
        self._lbl_loc_cap.setAlignment(QtCore.Qt.AlignCenter)
        self._lbl_loc_cap.setStyleSheet(cap_style)
        self._lbl_loc = QtWidgets.QLabel("—")
        self._lbl_loc.setAlignment(QtCore.Qt.AlignCenter)
        self._lbl_loc.setStyleSheet(val_style)
        line = QtWidgets.QFrame()
        line.setFrameShape(QtWidgets.QFrame.HLine)
        line.setStyleSheet("color: #ffffff; background: #ffffff; max-height: 1px;")
        self._lbl_quality = QtWidgets.QLabel("—")
        self._lbl_quality.setAlignment(QtCore.Qt.AlignCenter)
        self._lbl_quality.setWordWrap(True)
        self._lbl_quality.setStyleSheet(quality_badge_style(QSCD20_QF_GOOD_DATA))
        self._lbl_latency = QtWidgets.QLabel("—")
        self._lbl_latency.setAlignment(QtCore.Qt.AlignCenter)
        self._lbl_latency.setStyleSheet(
            "color: #ffffff; font-size: 22px; font-weight: 800;"
        )
        self._lbl_latency_cap = QtWidgets.QLabel("LATENCY (SEC)")
        self._lbl_latency_cap.setAlignment(QtCore.Qt.AlignCenter)
        self._lbl_latency_cap.setStyleSheet("color: #e0e7ff; font-size: 10px;")
        self._lbl_last = QtWidgets.QLabel("Last Data : —")
        self._lbl_last.setAlignment(QtCore.Qt.AlignCenter)
        self._lbl_last.setStyleSheet("color: #ffffff; font-size: 11px;")
        side_l.addWidget(self._lbl_sta_cap)
        side_l.addWidget(self._lbl_sta)
        side_l.addWidget(self._lbl_loc_cap)
        side_l.addWidget(self._lbl_loc)
        side_l.addWidget(line)
        side_l.addStretch(1)
        side_l.addWidget(self._lbl_quality)
        side_l.addSpacing(8)
        side_l.addWidget(self._lbl_latency)
        side_l.addWidget(self._lbl_latency_cap)
        side_l.addStretch(1)
        side_l.addWidget(self._lbl_last)
        root.addWidget(side)

        self._bar_current = LivePgaBarChart("current")
        self._bar_peak = LivePgaBarChart("peak")
        root.addWidget(self._bar_current)
        root.addWidget(self._bar_peak)

        ts_wrap = QtWidgets.QFrame()
        ts_wrap.setObjectName("LiveTsWrap")
        ts_l = QtWidgets.QVBoxLayout(ts_wrap)
        ts_l.setContentsMargins(0, 2, 0, 0)
        ts_l.setSpacing(0)
        self._ts_plot = pg.PlotWidget(
            axisItems={
                "bottom": DisplayTimeAxisItem(orientation="bottom"),
                "left": PlainGalAxisItem(orientation="left"),
            },
            viewBox=ChartViewBox(),
            background="#ffffff",
        )
        self._ts_plot.setMinimumWidth(240)
        self._ts_plot.showGrid(x=False, y=True, alpha=0.3)
        self._ts_plot.setLabel("left", "gal")
        self._ts_plot.hideButtons()
        pi = self._ts_plot.getPlotItem()
        pi.getAxis("left").setWidth(36)
        self._curve_h = self._ts_plot.plot(pen=pg.mkPen(LIVE_PGA_H_RGBA, width=2), name="H")
        self._curve_t = self._ts_plot.plot(pen=pg.mkPen(LIVE_PGA_T_RGBA, width=2), name="T")
        pi.addLegend(offset=(8, 8))
        self._hover = ChartHoverTooltip(
            pi,
            {"pga_H": self._curve_h, "pga_T": self._curve_t},
            {"pga_H": "H", "pga_T": "T"},
            hover_target=self._ts_plot,
        )
        ts_l.addWidget(self._ts_plot)
        root.addWidget(ts_wrap, stretch=1)

    def set_pga_channels(self, show_h: bool, show_t: bool) -> None:
        self._show_h = bool(show_h)
        self._show_t = bool(show_t)
        self._bar_current.set_channels(self._show_h, self._show_t)
        self._bar_peak.set_channels(self._show_h, self._show_t)
        self._curve_h.setVisible(self._show_h)
        self._curve_t.setVisible(self._show_t)
        self._redraw_series()

    def set_window_sec(self, window_sec: int) -> None:
        self._window_sec = int(window_sec)
        self._prune()
        self._refresh_window_peaks()
        self._redraw_series()

    def apply_display_tz(self) -> None:
        axis = self._ts_plot.getPlotItem().getAxis("bottom")
        if isinstance(axis, DisplayTimeAxisItem):
            axis.refresh_tz_label()
        if self._last_data_time is not None:
            self._lbl_last.setText(f"Last Data : {format_display_hms(self._last_data_time)}")
        self._bar_peak.set_values(
            self._peak_h,
            self._peak_t,
            h_time=self._peak_h_time,
            t_time=self._peak_t_time,
        )
        self._update_latency()
        self._ts_plot.update()

    def ingest(
        self,
        myqscd: Tuple[Any, ...],
        recv_wall: float,
        recv_diff: Optional[float] = None,
    ) -> None:
        sta = station_code_str(myqscd) or "—"
        loc = location_str(myqscd) or "—"
        q = byte_to_u8(myqscd[IDX_FLAG])
        data_time = float(myqscd[IDX_TIME])
        hpga = float(myqscd[IDX_HPGA])
        tpga = float(myqscd[IDX_TPGA])
        self._lbl_sta.setText(sta)
        self._lbl_loc.setText(loc)
        self._lbl_quality.setText(describe_quality_flag(q))
        self._lbl_quality.setStyleSheet(quality_badge_style(q))
        self._last_data_time = data_time
        self._last_recv_diff = (
            float(recv_diff) if recv_diff is not None else compute_recv_time_diff(recv_wall, myqscd)
        )
        self._last_recv_wall = float(recv_wall)
        self._lbl_last.setText(f"Last Data : {format_display_hms(data_time)}")
        self._update_latency()

        wall = float(recv_wall)
        self._xs.append(wall)
        self._hs.append(hpga)
        self._ts.append(tpga)
        self._ds.append(data_time)
        self._cur_h = hpga
        self._cur_t = tpga
        self._bar_current.set_values(hpga, tpga)
        self._prune()
        self._refresh_window_peaks()
        self._redraw_series()

    def tick_now(self) -> None:
        self._prune()
        self._refresh_window_peaks()
        self._update_latency()
        self._redraw_series()

    def _update_latency(self) -> None:
        style_ok = "color: #ffffff; font-size: 22px; font-weight: 800;"
        style_alert = "color: #f87171; font-size: 22px; font-weight: 800;"
        if self._last_recv_wall is None and self._last_recv_diff is None:
            self._lbl_latency.setText("—")
            self._lbl_latency.setStyleSheet(style_ok)
            return
        stale: Optional[float] = None
        if self._last_recv_wall is not None:
            stale = time.time() - float(self._last_recv_wall)
        packet_diff = (
            float(self._last_recv_diff) if self._last_recv_diff is not None else None
        )
        if stale is not None and stale > RECV_DELAY_ALERT_SEC:
            self._lbl_latency.setText(f"{stale:.1f}")
            self._lbl_latency.setStyleSheet(style_alert)
            return
        if packet_diff is None:
            self._lbl_latency.setText("—")
            self._lbl_latency.setStyleSheet(style_ok)
            return
        self._lbl_latency.setText(f"{packet_diff:.3f}")
        if abs(packet_diff) > RECV_DELAY_ALERT_SEC:
            self._lbl_latency.setStyleSheet(style_alert)
        else:
            self._lbl_latency.setStyleSheet(style_ok)

    def _window_cutoff(self) -> float:
        return time.time() - float(self._window_sec)

    def _prune(self) -> None:
        if not self._xs:
            return
        cutoff = self._window_cutoff() - 5.0
        i = 0
        n = len(self._xs)
        while i < n and self._xs[i] < cutoff:
            i += 1
        if i:
            del self._xs[:i]
            del self._hs[:i]
            del self._ts[:i]
            del self._ds[:i]

    def _refresh_window_peaks(self) -> None:
        """선택한 타임윈도우 안의 PGA H/T 최댓값만 누적 최대로 표시한다."""
        cutoff = self._window_cutoff()
        peak_h = 0.0
        peak_t = 0.0
        peak_h_time: Optional[float] = None
        peak_t_time: Optional[float] = None
        for i, wall in enumerate(self._xs):
            if wall < cutoff:
                continue
            h = self._hs[i]
            t = self._ts[i]
            dt = self._ds[i]
            if peak_h_time is None or h >= peak_h:
                peak_h = h
                peak_h_time = dt
            if peak_t_time is None or t >= peak_t:
                peak_t = t
                peak_t_time = dt
        if (
            peak_h != self._peak_h
            or peak_t != self._peak_t
            or peak_h_time != self._peak_h_time
            or peak_t_time != self._peak_t_time
        ):
            self._peak_h = peak_h
            self._peak_t = peak_t
            self._peak_h_time = peak_h_time
            self._peak_t_time = peak_t_time
            self._bar_peak.set_values(
                self._peak_h,
                self._peak_t,
                h_time=self._peak_h_time,
                t_time=self._peak_t_time,
            )

    def _redraw_series(self) -> None:
        now = time.time()
        x0 = now - float(self._window_sec)
        if self._xs:
            xa = np.asarray(self._xs, dtype=float)
            ha = np.asarray(self._hs, dtype=float)
            ta = np.asarray(self._ts, dtype=float)
            if self._show_h:
                self._curve_h.setData(xa, ha, skipFiniteCheck=True)
            else:
                self._curve_h.setData([], [])
            if self._show_t:
                self._curve_t.setData(xa, ta, skipFiniteCheck=True)
            else:
                self._curve_t.setData([], [])
            hover_ys: Dict[str, np.ndarray] = {}
            if self._show_h:
                hover_ys["pga_H"] = ha
            if self._show_t:
                hover_ys["pga_T"] = ta
            self._hover._fields = list(hover_ys.keys())
            self._hover._curves = {
                "pga_H": self._curve_h,
                "pga_T": self._curve_t,
            }
            self._hover._labels = {"pga_H": "H", "pga_T": "T"}
            self._hover.set_grid_data(xa, hover_ys)
            ymaxs = [0.05]
            if self._show_h:
                ymaxs.append(float(np.nanmax(ha)))
            if self._show_t:
                ymaxs.append(float(np.nanmax(ta)))
            ymax = max(ymaxs)
            self._ts_plot.setYRange(0.0, ymax * 1.15, padding=0.02)
        else:
            self._curve_h.setData([], [])
            self._curve_t.setData([], [])
        vb = self._ts_plot.getPlotItem().getViewBox()
        if isinstance(vb, ChartViewBox) and vb.user_zoomed:
            return
        self._ts_plot.setXRange(x0, now, padding=0.0)


class LiveOverviewBoard(QtWidgets.QWidget):
    """수신 관측소마다 LiveStationCard를 쌓아 보여 준다."""

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self._window_sec = DEFAULT_TIME_WINDOW_SEC
        self._show_h = True
        self._show_t = True
        self._cards: Dict[str, LiveStationCard] = {}
        self._order: List[str] = []
        v = QtWidgets.QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        self._scroll = QtWidgets.QScrollArea()
        self._scroll.setObjectName("LiveOverviewScroll")
        self._scroll.setWidgetResizable(True)
        self._host = QtWidgets.QWidget()
        self._lay = QtWidgets.QVBoxLayout(self._host)
        self._lay.setContentsMargins(6, 6, 6, 6)
        self._lay.setSpacing(8)
        self._empty = QtWidgets.QLabel(
            "Start 후 수신되는 관측소마다 PGA(H/T) 카드가 추가됩니다."
        )
        self._empty.setAlignment(QtCore.Qt.AlignCenter)
        self._empty.setStyleSheet("color: #64748b; padding: 24px;")
        self._lay.addWidget(self._empty)
        self._lay.addStretch(1)
        self._scroll.setWidget(self._host)
        v.addWidget(self._scroll)

    def set_window_sec(self, window_sec: int) -> None:
        self._window_sec = int(window_sec)
        for card in self._cards.values():
            card.set_window_sec(self._window_sec)

    def set_pga_channels(self, show_h: bool, show_t: bool) -> None:
        self._show_h = bool(show_h)
        self._show_t = bool(show_t)
        for card in self._cards.values():
            card.set_pga_channels(self._show_h, self._show_t)

    def apply_display_tz(self) -> None:
        for card in self._cards.values():
            card.apply_display_tz()

    def clear(self) -> None:
        for key in list(self._order):
            card = self._cards.pop(key)
            self._lay.removeWidget(card)
            card.setParent(None)
            card.deleteLater()
        self._order.clear()
        self._empty.show()

    def ingest(
        self,
        myqscd: Tuple[Any, ...],
        recv_wall: float,
        recv_diff: Optional[float] = None,
    ) -> None:
        key = live_station_key(myqscd)
        card = self._cards.get(key)
        if card is None:
            self._empty.hide()
            card = LiveStationCard()
            card.set_window_sec(self._window_sec)
            card.set_pga_channels(self._show_h, self._show_t)
            self._cards[key] = card
            self._order.append(key)
            stretch = self._lay.takeAt(self._lay.count() - 1)
            self._lay.addWidget(card)
            if stretch is not None:
                self._lay.addItem(stretch)
        card.ingest(myqscd, recv_wall, recv_diff)

    def tick_now(self) -> None:
        for card in self._cards.values():
            card.tick_now()


def read_qscd20_bin(path: str) -> QscdBinLoadResult:
    """QSCD20.replay (120B + TimeDiff 8B/레코드) 읽기."""
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
        self._path = readme_html_path()
        self._missing_html = (
            f"<h2>README.html 없음</h2>"
            f"<p>다음 경로에 파일이 있어야 합니다:</p>"
            f"<p><code>{self._path}</code></p>"
        )
        self._layout = QtWidgets.QVBoxLayout(self)
        self._browser: Optional[QtWidgets.QWidget] = None
        self._warn: Optional[QtWidgets.QLabel] = None
        if _HAS_WEBENGINE and QWebEngineView is not None:
            self._install_webengine()
        else:
            self._install_text_browser(
                "PyQtWebEngine 미설치 — 기본 뷰어로 표시합니다. pip install PyQtWebEngine"
            )
        foot = QtWidgets.QLabel(f"QSCD20 UDP Receiver {GUI_VERSION}")
        foot.setStyleSheet("color: #64748b; padding: 4px;")
        foot.setAlignment(QtCore.Qt.AlignRight)
        self._layout.addWidget(foot)

    def _help_url(self) -> QtCore.QUrl:
        if os.path.isfile(self._path):
            return QtCore.QUrl.fromLocalFile(os.path.abspath(self._path))
        return QtCore.QUrl()

    def _install_webengine(self) -> None:
        page = _HelpWebPage(self)  # type: ignore[possibly-undefined]
        view = QWebEngineView()
        view.setPage(page)
        url = self._help_url()
        if url.isEmpty():
            view.setHtml(self._missing_html)
        else:
            view.load(url)
        page.renderProcessTerminated.connect(self._on_webengine_terminated)
        self._replace_browser(view)

    def _on_webengine_terminated(self, *_args: Any) -> None:
        self._install_text_browser(
            "도움말 WebEngine이 GPU/GL 컨텍스트를 만들지 못해 기본 뷰어로 표시합니다."
        )

    def _install_text_browser(self, reason: str = "") -> None:
        fallback = QtWidgets.QTextBrowser()
        fallback.setOpenExternalLinks(True)
        url = self._help_url()
        if url.isEmpty():
            fallback.setHtml(self._missing_html)
        else:
            fallback.setSource(url)
        self._replace_browser(fallback)
        if reason:
            if self._warn is None:
                self._warn = QtWidgets.QLabel(reason)
                self._warn.setWordWrap(True)
                self._warn.setStyleSheet("color: #b45309; font-size: 11px; padding: 2px;")
                self._layout.insertWidget(0, self._warn)
            else:
                self._warn.setText(reason)

    def _replace_browser(self, widget: QtWidgets.QWidget) -> None:
        if self._browser is not None:
            self._layout.removeWidget(self._browser)
            self._browser.hide()
            self._browser.deleteLater()
        self._browser = widget
        # 푸터 위에 본문 삽입
        self._layout.insertWidget(self._layout.count() - 1 if self._layout.count() else 0, widget, stretch=1)


class PanelCheckEditor(QtWidgets.QWidget):
    """기본 ON 차트 패널 — PANEL_DEFS 항목을 체크박스로 선택."""

    def __init__(
        self,
        selected: List[str],
        tooltip: str,
        parent: Optional[QtWidgets.QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setToolTip(tooltip)
        lay = QtWidgets.QGridLayout(self)
        lay.setContentsMargins(0, 2, 0, 2)
        lay.setHorizontalSpacing(12)
        lay.setVerticalSpacing(4)
        self._checks: Dict[str, QtWidgets.QCheckBox] = {}
        want = set(selected)
        for i, (pid, (title, _)) in enumerate(PANEL_DEFS.items()):
            chk = QtWidgets.QCheckBox(title)
            chk.setChecked(pid in want)
            chk.setToolTip(f"{tooltip}\nID: {pid}")
            row, col = divmod(i, 3)
            lay.addWidget(chk, row, col)
            self._checks[pid] = chk

    def selected_ids(self) -> List[str]:
        return [pid for pid in PANEL_DEFS if self._checks[pid].isChecked()]

    def set_selected_ids(self, ids: List[str]) -> None:
        want = set(ids)
        for pid, chk in self._checks.items():
            chk.setChecked(pid in want)


class BasicSettingsDialog(QtWidgets.QDialog):
    """recvQSCD20_gui_settings.json 편집 (BIN_FILE_MAGIC 제외)."""

    def __init__(self, main: "MainWindow") -> None:
        super().__init__(main)
        self._main = main
        self.setWindowTitle(f"기본 설정 — QSCD20 {GUI_VERSION}")
        self.setMinimumSize(560, 560)
        self.resize(620, 680)
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
            elif kind == "panel_ids":
                w = PanelCheckEditor(list(getattr(s, key)), tooltip)
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
            elif kind == "choice":
                w = QtWidgets.QComboBox()
                if key == "display_tz":
                    w.addItem("KST (한국 표준시)", TZ_KST)
                    w.addItem("UTC", TZ_UTC)
                idx = w.findData(str(getattr(s, key)))
                w.setCurrentIndex(max(0, idx))
            else:
                continue
            if kind != "path":
                w.setToolTip(tooltip)
            lbl = QtWidgets.QLabel(label_text)
            lbl.setToolTip(tooltip)
            if kind == "panel_ids":
                lbl.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignTop)
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
            elif kind == "panel_ids":
                setattr(s, key, list(w.selected_ids()))  # type: ignore[union-attr]
            elif kind == "path":
                raw = w.text().strip()  # type: ignore[union-attr]
                if raw:
                    try:
                        raw = path_for_settings_storage(raw)
                    except ValueError:
                        pass
                setattr(s, key, raw)
            elif kind == "choice":
                setattr(s, key, str(w.currentData() or TZ_KST))  # type: ignore[union-attr]
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
            elif kind == "panel_ids":
                w.set_selected_ids(list(val))  # type: ignore[union-attr]
            elif kind == "path":
                w.setText(str(val))  # type: ignore[union-attr]
            elif kind == "choice":
                idx = w.findData(str(val))  # type: ignore[union-attr]
                w.setCurrentIndex(max(0, idx))

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
        st_lbl = QtWidgets.QLabel("관측소:")
        self._combo_station = QtWidgets.QComboBox()
        self._combo_station.setMinimumWidth(140)
        self._combo_station.setToolTip("화면 로그에 표시할 관측소")
        self._combo_station.addItem("(관측소 선택)")
        self._combo_station.currentTextChanged.connect(main._on_log_viewer_station_changed)
        btn_row.addWidget(st_lbl)
        btn_row.addWidget(self._combo_station)
        hint = QtWidgets.QLabel("선택한 관측소 패킷 로그 · Start/Stop 등 시스템 메시지 포함")
        hint.setStyleSheet("color: #64748b; font-size: 11px;")
        btn_row.addWidget(hint)
        btn_row.addStretch()
        btn_row.addWidget(main._register_tz_toggle(TzToggleWidget(self)))
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


class FileLogViewerDialog(QtWidgets.QDialog):
    """File View용 `.QSCD.log` 뷰어 — 차트 줌 구간의 data time에 맞춰 표시."""

    def __init__(self, main: "MainWindow") -> None:
        super().__init__(main)
        self._main = main
        self.setWindowTitle(f"로그 뷰어 (File) — QSCD20 {GUI_VERSION}")
        self.setMinimumSize(880, 480)
        self.resize(960, 520)
        self.setWindowFlag(QtCore.Qt.Window, True)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)

        self._lbl_info = QtWidgets.QLabel("QSCD20.replay 파일을 열면 짝이 되는 로그를 불러옵니다.")
        self._lbl_info.setWordWrap(True)
        self._lbl_info.setStyleSheet("color: #334155; font-size: 12px;")
        layout.addWidget(self._lbl_info)

        self._view = QtWidgets.QPlainTextEdit()
        self._view.setObjectName("LogView")
        self._view.setReadOnly(True)
        layout.addWidget(self._view, stretch=1)

        btn_row = QtWidgets.QHBoxLayout()
        st_lbl = QtWidgets.QLabel("관측소:")
        self._combo_station = QtWidgets.QComboBox()
        self._combo_station.setMinimumWidth(160)
        self._combo_station.setToolTip("로그에 표시할 관측소")
        self._combo_station.addItem("(관측소 선택)")
        self._combo_station.setEnabled(False)
        self._combo_station.currentIndexChanged.connect(main._on_file_log_viewer_station_changed)
        btn_row.addWidget(st_lbl)
        btn_row.addWidget(self._combo_station)
        self._chk_follow_zoom = QtWidgets.QCheckBox("차트 줌 구간에 맞추기")
        self._chk_follow_zoom.setChecked(True)
        self._chk_follow_zoom.setToolTip(
            "켜면 File View 차트에 보이는 시간(줌인 구간)의 로그만 표시합니다.\n"
            "끄면 선택한 관측소의 로그 전체를 보여 줍니다."
        )
        self._chk_follow_zoom.toggled.connect(lambda _checked=False: main._refresh_file_log_view())
        btn_row.addWidget(self._chk_follow_zoom)
        btn_row.addStretch()
        btn_row.addWidget(main._register_tz_toggle(TzToggleWidget(self)))
        btn_reload = QtWidgets.QPushButton("다시 읽기")
        btn_reload.clicked.connect(main._reload_file_log)
        btn_row.addWidget(btn_reload)
        btn_browse = QtWidgets.QPushButton("로그 파일 찾아보기…")
        btn_browse.clicked.connect(main._browse_file_log)
        btn_row.addWidget(btn_browse)
        layout.addLayout(btn_row)

    def set_info(self, text: str) -> None:
        self._lbl_info.setText(text)

    def set_log_text(self, text: str) -> None:
        self._view.setUpdatesEnabled(False)
        try:
            self._view.setPlainText(text)
            self._view.moveCursor(QtGui.QTextCursor.Start)
        finally:
            self._view.setUpdatesEnabled(True)

    def follow_zoom(self) -> bool:
        return bool(self._chk_follow_zoom.isChecked())


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
        self._formatter = UtcLogFormatter("[%(levelname)s] %(asctime)s > %(message)s")
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
        self._file_replay_path: str = ""
        self._file_log_path: str = ""
        self._file_log_blocks: List[FileLogBlock] = []
        self._file_info_meta: Dict[str, Any] = {}
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
        self._dlg_file_log: Optional[FileLogViewerDialog] = None
        self._dlg_help: Optional[HelpManualDialog] = None
        self._dlg_basic_settings: Optional[BasicSettingsDialog] = None
        self._tz_toggles: List[TzToggleWidget] = []

        self._build_ui()
        self._build_menubar()
        self.setStyleSheet(APP_STYLESHEET)
        self._set_status("대기 중")
        self._gui_log_filter = StationGuiLogFilter(self)
        self._qt_handler.addFilter(self._gui_log_filter)
        self._qt_handler.log_signal.connect(self._append_log_line)

    def _build_receive_sidebar(self) -> QtWidgets.QWidget:
        """Live·File View 탭 우측 — 수신 제어 패널."""
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
        act_log.triggered.connect(self._show_current_log_viewer)
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
        if hasattr(self, "_live_overview"):
            self._live_overview.set_window_sec(
                int(self._combo_overview_time_window.currentData())
            )
        self._update_path_labels()
        self._set_display_tz(getattr(s, "display_tz", DISPLAY_TZ), persist=False)

    def _rebuild_time_window_combos(self) -> None:
        live_sec = self._combo_time_window.currentData()
        file_sec = self._combo_file_time_window.currentData()
        overview_sec = (
            self._combo_overview_time_window.currentData()
            if hasattr(self, "_combo_overview_time_window")
            else DEFAULT_TIME_WINDOW_SEC
        )

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
        if hasattr(self, "_combo_overview_time_window"):
            fill(
                self._combo_overview_time_window,
                overview_sec if overview_sec is not None else DEFAULT_TIME_WINDOW_SEC,
            )
            if hasattr(self, "_live_overview"):
                self._live_overview.set_window_sec(
                    int(self._combo_overview_time_window.currentData())
                )
        self._chart_window_sec = int(self._combo_time_window.currentData())

    def _register_tz_toggle(self, widget: TzToggleWidget) -> TzToggleWidget:
        widget.set_tz(DISPLAY_TZ)
        widget.tz_changed.connect(self._on_display_tz_changed)
        self._tz_toggles.append(widget)
        return widget

    def _on_display_tz_changed(self, tz: str) -> None:
        self._set_display_tz(tz, persist=True)

    def _set_display_tz(self, tz: Any, *, persist: bool = False) -> None:
        global DISPLAY_TZ
        name = normalize_display_tz(tz)
        DISPLAY_TZ = name
        for toggle in self._tz_toggles:
            toggle.set_tz(name)
        if hasattr(self, "_live_charts"):
            self._live_charts.apply_display_tz()
        if hasattr(self, "_file_charts"):
            self._file_charts.apply_display_tz()
        if hasattr(self, "_live_overview"):
            self._live_overview.apply_display_tz()
        if hasattr(self, "_lbl_last_recv"):
            self._update_last_recv_label()
        if hasattr(self, "_log_view"):
            self._rebuild_gui_log_view()
        if self._dlg_file_log is not None:
            self._refresh_file_log_view()
        self._refresh_file_info_times()
        if persist:
            s = deepcopy(_runtime_settings)
            s.display_tz = name
            try:
                save_settings(s)
            except OSError:
                return
            _apply_gui_settings(s)

    def _sync_log_viewer_station_combo(self) -> None:
        if self._dlg_log is None:
            return
        _sync_combo_from(self._combo_station, self._dlg_log._combo_station)

    def _sync_log_viewer_station_selection(self, text: str) -> None:
        if self._dlg_log is None:
            return
        combo = self._dlg_log._combo_station
        if combo.currentText() == text:
            return
        combo.blockSignals(True)
        idx = combo.findText(text)
        if idx >= 0:
            combo.setCurrentIndex(idx)
        combo.blockSignals(False)

    def _on_log_viewer_station_changed(self, text: str) -> None:
        if self._combo_station.currentText() == text:
            return
        idx = self._combo_station.findText(text)
        if idx >= 0:
            self._combo_station.setCurrentIndex(idx)

    def _sync_file_log_station_combo(self) -> None:
        if self._dlg_file_log is None:
            return
        _sync_combo_from(self._combo_file_station, self._dlg_file_log._combo_station)

    def _on_file_log_viewer_station_changed(self, _index: int = 0) -> None:
        dlg = self._dlg_file_log
        if dlg is None:
            return
        text = dlg._combo_station.currentText()
        if self._combo_file_station.currentText() == text:
            return
        idx = self._combo_file_station.findText(text)
        if idx >= 0:
            self._combo_file_station.setCurrentIndex(idx)

    def _show_current_log_viewer(self) -> None:
        if getattr(self, "_tabs", None) is not None and self._tabs.currentWidget() is getattr(
            self, "_tab_file", None
        ):
            self._show_file_log_viewer()
            return
        self._show_log_viewer()

    def _show_log_viewer(self) -> None:
        if self._dlg_log is None:
            self._dlg_log = LogViewerDialog(self)
        self._sync_log_viewer_station_combo()
        self._dlg_log._chk_verbose.blockSignals(True)
        self._dlg_log._chk_verbose.setChecked(GUI_LOG_VERBOSE)
        self._dlg_log._chk_verbose.blockSignals(False)
        self._dlg_log.show()
        self._dlg_log.raise_()
        self._dlg_log.activateWindow()

    def _file_log_dir(self) -> Optional[str]:
        try:
            return _runtime_settings.resolved_log_dir()
        except ValueError:
            return None

    def _clear_file_log_state(self) -> None:
        self._file_replay_path = ""
        self._file_log_path = ""
        self._file_log_blocks = []
        self._file_info_meta = {}

    def _bind_file_log_to_replay(self, replay_path: str) -> None:
        self._file_replay_path = replay_path
        self._file_log_path = find_companion_log(replay_path, self._file_log_dir()) or ""
        self._file_log_blocks = []
        if self._file_log_path:
            self._load_file_log_path(self._file_log_path)
        elif self._dlg_file_log is not None and self._dlg_file_log.isVisible():
            self._refresh_file_log_view()

    def _load_file_log_path(self, path: str) -> bool:
        try:
            text = read_text_file_guess(path)
        except OSError as e:
            QtWidgets.QMessageBox.warning(self, "로그 파일", str(e))
            return False
        self._file_log_path = path
        self._file_log_blocks = parse_qscd_log_blocks(text)
        self._refresh_file_log_view()
        return True

    def _show_file_log_viewer(self) -> None:
        if not self._file_replay_path:
            QtWidgets.QMessageBox.information(
                self, "로그 뷰어", "먼저 File View에서 QSCD20.replay 파일을 여세요."
            )
            return
        if self._dlg_file_log is None:
            self._dlg_file_log = FileLogViewerDialog(self)
        if not self._file_log_path:
            guessed = find_companion_log(self._file_replay_path, self._file_log_dir())
            if guessed:
                self._load_file_log_path(guessed)
            else:
                self._refresh_file_log_view()
        elif not self._file_log_blocks:
            self._load_file_log_path(self._file_log_path)
        else:
            self._refresh_file_log_view()
        self._sync_file_log_station_combo()
        self._dlg_file_log.show()
        self._dlg_file_log.raise_()
        self._dlg_file_log.activateWindow()

    def _browse_file_log(self) -> None:
        start = ""
        if self._file_log_path:
            start = os.path.dirname(self._file_log_path)
        elif self._file_replay_path:
            start = os.path.dirname(self._file_replay_path)
        else:
            start = self._file_log_dir() or work_directory()
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "QSCD.log 열기",
            start,
            f"QSCD 로그 (*{LOG_FILE_SUFFIX});;All (*.*)",
        )
        if not path:
            return
        self._load_file_log_path(path)

    def _reload_file_log(self) -> None:
        if not self._file_log_path:
            self._browse_file_log()
            return
        self._load_file_log_path(self._file_log_path)

    def _on_file_chart_x_range(self, _x0: float, _x1: float) -> None:
        if self._dlg_file_log is not None and self._dlg_file_log.isVisible():
            self._refresh_file_log_view()

    def _refresh_file_log_view(self) -> None:
        dlg = self._dlg_file_log
        if dlg is None:
            return
        if not self._file_log_path:
            cands = (
                companion_log_candidates(self._file_replay_path, self._file_log_dir())
                if self._file_replay_path
                else []
            )
            hint = "짝이 되는 로그 파일을 찾지 못했습니다."
            if cands:
                hint += "\n찾아본 위치:\n" + "\n".join(cands)
            hint += "\n「로그 파일 찾아보기…」로 직접 선택할 수 있습니다."
            dlg.set_info(hint)
            dlg.set_log_text("")
            return

        follow = dlg.follow_zoom()
        x0 = x1 = None
        if follow:
            xr = self._file_charts.visible_x_range()
            if xr is not None:
                x0, x1 = xr
        station = self._selected_file_station()
        filtered = filter_file_log_blocks(
            self._file_log_blocks, x0=x0, x1=x1, station=station
        )
        extra = ""
        if len(filtered) > FILE_LOG_BLOCK_CAP:
            extra = f"\n표시는 앞 {FILE_LOG_BLOCK_CAP}개 패킷만 (전체 {len(filtered)}개)."
            filtered = filtered[:FILE_LOG_BLOCK_CAP]
        range_txt = "전체"
        if x0 is not None and x1 is not None:
            range_txt = f"{format_display_dt(x0)}  ~  {format_display_dt(x1)}"
        st_txt = station or "모든 관측소"
        dlg.set_info(
            f"로그: {self._file_log_path}  ·  표시 {DISPLAY_TZ} (파일 원본 UTC)\n"
            f"관측소: {st_txt}  ·  구간: {range_txt}  ·  {len(filtered)}개 패킷"
            f"{extra}"
        )
        if not filtered:
            dlg.set_log_text("이 구간에 해당하는 로그가 없습니다.")
            return
        dlg.set_log_text(shift_utc_text_for_display("\n".join(block.text for block in filtered)))

    def _refresh_file_info_times(self) -> None:
        meta = getattr(self, "_file_info_meta", None)
        if not meta or not self._file_records:
            return
        recs = self._file_records
        t0 = format_display_dt(float(recs[0][IDX_TIME]))
        t1 = format_display_dt(float(recs[-1][IDX_TIME]))
        self._lbl_file_info.setText(
            f"{meta['path']}\n"
            f"레코드 수: {meta['nrec']}  ·  관측소 {meta['nst']}개: {meta['st_info']}\n"
            f"{meta['diff_note']}\n"
            f"전체 data time({DISPLAY_TZ}): {t0} ~ {t1}"
        )

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
        self._tabs = tabs
        tabs.setElideMode(QtCore.Qt.ElideNone)
        tabs.tabBar().setExpanding(False)
        tabs.tabBar().setUsesScrollButtons(False)
        content_row.addWidget(tabs, stretch=1)
        content_row.addWidget(self._build_receive_sidebar())
        root_layout.addLayout(content_row, stretch=1)

        # Live (관측소별 PGA overview)
        overview_widget = QtWidgets.QWidget()
        ov_vbox = QtWidgets.QVBoxLayout(overview_widget)
        ov_meta = QtWidgets.QFrame()
        ov_meta.setObjectName("MetaBar")
        ov_meta_l = QtWidgets.QHBoxLayout(ov_meta)
        ov_meta_l.setContentsMargins(8, 6, 8, 6)
        ov_meta_l.addWidget(QtWidgets.QLabel("시간 선택:"))
        self._combo_overview_time_window = QtWidgets.QComboBox()
        for sec in TIME_WINDOW_CHOICES:
            self._combo_overview_time_window.addItem(f"{sec}초", sec)
        idx = TIME_WINDOW_CHOICES.index(DEFAULT_TIME_WINDOW_SEC) if DEFAULT_TIME_WINDOW_SEC in TIME_WINDOW_CHOICES else 0
        self._combo_overview_time_window.setCurrentIndex(idx)
        self._combo_overview_time_window.currentIndexChanged.connect(
            self._on_overview_time_window_changed
        )
        ov_meta_l.addWidget(self._combo_overview_time_window)
        ov_meta_l.addSpacing(12)
        ov_meta_l.addWidget(QtWidgets.QLabel("PGA:"))
        self._chk_pga_h = QtWidgets.QCheckBox("H")
        self._chk_pga_t = QtWidgets.QCheckBox("T")
        self._chk_pga_h.setChecked(True)
        self._chk_pga_t.setChecked(True)
        self._chk_pga_h.setToolTip("PGA H 채널 표시")
        self._chk_pga_t.setToolTip("PGA T 채널 표시")
        self._chk_pga_h.toggled.connect(self._on_overview_pga_toggled)
        self._chk_pga_t.toggled.connect(self._on_overview_pga_toggled)
        ov_meta_l.addWidget(self._chk_pga_h)
        ov_meta_l.addWidget(self._chk_pga_t)
        ov_hint = QtWidgets.QLabel("현재값 · 누적 최대(선택 시간 창, 시각/gal) · 타임시리즈(수신 시각)")
        ov_hint.setStyleSheet("color: #64748b; font-size: 11px;")
        ov_meta_l.addWidget(ov_hint)
        ov_meta_l.addStretch(1)
        ov_meta_l.addWidget(self._register_tz_toggle(TzToggleWidget(ov_meta)))
        self._btn_overview_log = make_log_viewer_toolbutton(
            ov_meta, "로그 뷰어 열기 (Ctrl+L)", self._show_log_viewer
        )
        ov_meta_l.addWidget(self._btn_overview_log)
        ov_vbox.addWidget(ov_meta)
        self._live_overview = LiveOverviewBoard()
        self._live_overview.set_window_sec(int(self._combo_overview_time_window.currentData()))
        ov_vbox.addWidget(self._live_overview, stretch=1)
        self._tab_overview = overview_widget
        tabs.addTab(overview_widget, "Live")

        # Detail View (기존 상세 차트)
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
        meta_layout.addWidget(self._register_tz_toggle(TzToggleWidget(meta)))
        self._btn_log_viewer = make_log_viewer_toolbutton(
            meta, "로그 뷰어 열기 (Ctrl+L)", self._show_log_viewer
        )
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
        self._tab_live = live_widget
        tabs.addTab(live_widget, "Detail View")

        # File viewer
        file_widget = QtWidgets.QWidget()
        self._tab_file = file_widget
        file_vbox = QtWidgets.QVBoxLayout(file_widget)
        file_meta = QtWidgets.QFrame()
        file_meta.setObjectName("FileMetaBar")
        file_top = QtWidgets.QHBoxLayout(file_meta)
        file_top.setContentsMargins(8, 6, 8, 6)
        self._btn_open_bin = QtWidgets.QPushButton("QSCD20.replay 열기…")
        self._btn_open_bin.clicked.connect(self._open_bin_file)
        self._lbl_file_info = QtWidgets.QLabel("파일을 선택하세요.")
        self._lbl_file_info.setWordWrap(True)
        file_top.addWidget(self._btn_open_bin)
        file_top.addWidget(self._lbl_file_info, stretch=1)
        file_top.addWidget(self._register_tz_toggle(TzToggleWidget(file_meta)))
        self._btn_file_log_viewer = make_log_viewer_toolbutton(
            file_meta, "짝이 되는 QSCD.log 열기 (Ctrl+L)", self._show_file_log_viewer
        )
        file_top.addWidget(self._btn_file_log_viewer)
        file_vbox.addWidget(file_meta)

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
        self._file_charts.x_range_changed.connect(self._on_file_chart_x_range)
        file_chart_layout.addWidget(self._file_charts)
        file_vbox.addWidget(file_chart_area, stretch=1)
        tabs.addTab(file_widget, "File View")

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

    def _on_overview_time_window_changed(self, _index: int = 0) -> None:
        sec = int(self._combo_overview_time_window.currentData())
        self._live_overview.set_window_sec(sec)

    def _on_overview_pga_toggled(self, _checked: bool = False) -> None:
        show_h = self._chk_pga_h.isChecked()
        show_t = self._chk_pga_t.isChecked()
        if not show_h and not show_t:
            sender = self.sender()
            if isinstance(sender, QtWidgets.QCheckBox):
                sender.blockSignals(True)
                sender.setChecked(True)
                sender.blockSignals(False)
            return
        self._live_overview.set_pga_channels(show_h, show_t)

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
        self._sync_file_log_station_combo()

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
        self._sync_file_log_station_combo()
        self._refresh_file_charts()
        if self._dlg_file_log is not None and self._dlg_file_log.isVisible():
            self._refresh_file_log_view()

    def _on_station_selected(self, text: str) -> None:
        self._selected_station = text if text != "(관측소 선택)" else ""
        self._sync_log_viewer_station_selection(text)
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
                f"최종 수신: {format_display_dt(buf.last_recv_wall)}  "
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
        self._lbl_last_recv.setText(f"최종 수신: {format_display_dt(buf.last_recv_wall)}")
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
        if self._receiver is not None:
            self._live_overview.tick_now()

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
                if self._dlg_log is not None:
                    self._dlg_log._combo_station.addItem(st)

            self._station_bufs[st].append(myqscd, recv_wall, recv_diff)
            self._live_overview.ingest(myqscd, recv_wall, recv_diff)

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
        return format_display_dt(ts, with_ms=True)

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
                pmyqscd, myqscd, recv_wall=recv_wall, recv_diff=recv_diff, tz=DISPLAY_TZ
            )
        return [
            format_qscd_packet_summary_line(
                myqscd, station, recv_wall=recv_wall, recv_diff=recv_diff, tz=DISPLAY_TZ
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
        self._log_view.appendPlainText(shift_utc_text_for_display(line))

    def _clear_gui_log(self) -> None:
        self._gui_log_items.clear()
        self._log_view.clear()

    def _rebuild_gui_log_view(self) -> None:
        lines: List[str] = []
        for item in self._gui_log_items:
            if item[0] == "sys":
                lines.append(shift_utc_text_for_display(item[1]))
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
        self._live_overview.clear()
        self._bin_flush_pending = 0
        self._live_chart_dirty = False
        self._selected_station = ""
        self._clear_gui_log()
        self._combo_station.blockSignals(True)
        self._combo_station.clear()
        self._combo_station.addItem("(관측소 선택)")
        self._combo_station.blockSignals(False)
        self._sync_log_viewer_station_combo()
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
            "QSCD20.replay (*.QSCD20.replay);;All (*.*)",
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
            self._clear_file_log_state()
            self._populate_file_station_combo([])
            self._lbl_file_info.setText(f"{path}\n유효한 레코드가 없습니다.")
            self._file_charts.set_static_from_records([])
            if self._dlg_file_log is not None and self._dlg_file_log.isVisible():
                self._refresh_file_log_view()
            return

        self._file_records = loaded.records
        self._file_recv_diffs = loaded.recv_diffs if loaded.has_stored_diff else None
        self._bind_file_log_to_replay(path)

        recs = loaded.records
        stations = unique_station_codes(recs)
        diff_note = (
            "TimeDiff: 파일에 저장된 Live 값 사용"
            if loaded.has_stored_diff
            else "TimeDiff: 저장값 없음(열기 시각 기준 근사)"
        )
        st_info = ", ".join(stations) if stations else "—"
        self._file_info_meta = {
            "path": path,
            "nrec": len(recs),
            "nst": len(stations),
            "st_info": st_info,
            "diff_note": diff_note,
        }
        self._refresh_file_info_times()
        self._populate_file_station_combo(recs)
        self._file_charts.set_window_sec(int(self._combo_file_time_window.currentData()))
        self._file_charts.set_active_panels(self._get_file_checked_panels())
        self._refresh_file_charts()
        if self._dlg_file_log is not None and self._dlg_file_log.isVisible():
            self._refresh_file_log_view()

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        self._on_stop()
        if self._dlg_log is not None:
            self._dlg_log.close()
        if self._dlg_file_log is not None:
            self._dlg_file_log.close()
        if self._dlg_help is not None:
            self._dlg_help.close()
        if self._dlg_basic_settings is not None:
            self._dlg_basic_settings.close()
        super().closeEvent(event)


def main() -> int:
    multiprocessing.freeze_support()
    _prepare_qtwebengine_chromium()
    app = QtWidgets.QApplication(sys.argv)
    w = MainWindow()
    w.show()
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
