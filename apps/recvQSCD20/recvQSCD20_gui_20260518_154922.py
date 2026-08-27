#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
QSCD20 UDP 수신 GUI v3.1 (PyQt5 + pyqtgraph)

실행:
    pip install -r requirements.txt
    python recvQSCD20_gui.py
"""
from __future__ import annotations

import datetime
import logging
import os
import socket
import struct
import sys
import time
import zlib
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pyqtgraph as pg
from PyQt5 import QtCore, QtGui, QtWidgets

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
HOST = "0.0.0.0"
DEFAULT_PORT = 9908
QSCD_LEN = 120
QSCD20_FMT = ">Lccc2s3sIfffffffffffffffffffffffffcc2s"

CHART_WINDOW_SEC = 600   # 차트 표시 구간 (초)
LOG_MAX_LINES = 5000
KST_OFFSET = 9 * 3600
CHART_REFRESH_MS = 200     # 차트 갱신 최소 간격 (성능)

SockTimeOut = 2
SockTimeOutCount = 5

Y_LABEL_DIFF = "시간(초)"
Y_LABEL_GAL = "gal(cm/sec2)"

pg.setConfigOptions(antialias=False, background="w", foreground="k", useOpenGL=False)

# panel_id -> (title, curves)
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
    return _decode_bytes(raw).strip() or raw.hex().upper()


def format_station_code_line(myqscd: Tuple[Any, ...]) -> str:
    raw = station_code_bytes(myqscd)
    asc = _decode_bytes(raw).strip() or raw.decode("latin-1", errors="replace")
    return f"{asc} | hex {raw.hex().upper()}"


def format_quality_flag_line(myqscd: Tuple[Any, ...]) -> str:
    q = byte_to_u8(myqscd[1])
    return f"0x{q:02X} — {describe_quality_flag(q)}"


def format_kst_dt(epoch_sec: float) -> str:
    t = datetime.datetime.utcfromtimestamp(epoch_sec) + datetime.timedelta(hours=9)
    return t.strftime("%Y-%m-%d %H:%M:%S KST")


def build_second_grid(
    buckets: Dict[int, Dict[str, float]],
    field: str,
    window_sec: int = CHART_WINDOW_SEC,
) -> Tuple[np.ndarray, np.ndarray]:
    """1초 격자 x(UTC epoch), y(NaN=공백)."""
    if not buckets:
        return np.array([], dtype=np.float64), np.array([], dtype=np.float64)

    max_sec = max(buckets.keys())
    min_sec = max(min(buckets.keys()), max_sec - window_sec + 1)
    secs = np.arange(min_sec, max_sec + 1, dtype=np.float64)
    ys = np.full(secs.shape, np.nan, dtype=np.float64)
    for i, s in enumerate(secs):
        si = int(s)
        row = buckets.get(si)
        if row is not None and field in row:
            ys[i] = row[field]
    return secs, ys


def records_to_buckets(
    records: List[Tuple[Any, ...]],
    recv_ts: Optional[float] = None,
) -> Dict[int, Dict[str, float]]:
    """파일/정적 데이터 → 초 단위 버킷 (동일 초는 마지막 값)."""
    buckets: Dict[int, Dict[str, float]] = {}
    base_recv = recv_ts if recv_ts is not None else time.time()
    for r in records:
        sec = int(float(r[6]))
        row: Dict[str, float] = {"diff": base_recv - float(r[6])}
        for name, idx in SERIES_IDX.items():
            row[name] = float(r[idx])
        buckets[sec] = row
    return buckets


def log_qscd_packet(logger: logging.Logger, pmyqscd: bytes, myqscd: Tuple[Any, ...], station: str) -> None:
    rtime = datetime.datetime.utcnow()
    dtime = datetime.datetime.utcfromtimestamp(myqscd[6])
    diff = rtime.timestamp() - float(myqscd[6])
    extra = {"station": station}

    logger.info("#########################################################################", extra=extra)
    logger.info("Quality Flag: {}".format(format_quality_flag_line(myqscd)), extra=extra)
    logger.info("Station Code (5B): {}".format(format_station_code_line(myqscd)), extra=extra)
    logger.info(
        "{:2s}/{:3s}/{} Recv : {} : Now : {} : Diff : {:.4f} s".format(
            _decode_bytes(myqscd[4]),
            _decode_bytes(myqscd[5]),
            _decode_bytes(myqscd[34]),
            dtime,
            rtime,
            diff,
        ),
        extra=extra,
    )

    buf_4_crc = pmyqscd[4:]
    mycrc = zlib.crc32(buf_4_crc) & 0xFFFFFFFF
    crc_recv = myqscd[0] & 0xFFFFFFFF
    if mycrc != crc_recv:
        logger.info(
            "     CRC : received {} calculated {} :::: Un-matched ".format(crc_recv, mycrc),
            extra=extra,
        )
    else:
        logger.info("     CRC : received {} calculated {}".format(crc_recv, mycrc), extra=extra)

    logger.info("Data Type / Reserved: {} / {}".format(myqscd[2], myqscd[3]), extra=extra)
    logger.info(
        "U-D WMMA : m {:.10f} M {:10f} A {:10f}".format(myqscd[7], myqscd[8], myqscd[9]),
        extra=extra,
    )
    logger.info(
        "N-S WMMA : m {:.10f} M {:10f} A {:10f}".format(myqscd[10], myqscd[11], myqscd[12]),
        extra=extra,
    )
    logger.info(
        "E-W WMMA : m {:.10f} M {:10f} A {:10f}".format(myqscd[13], myqscd[14], myqscd[15]),
        extra=extra,
    )
    logger.info("U-D TMM  : m {:.10f} M {:10f}".format(myqscd[16], myqscd[17]), extra=extra)
    logger.info("N-S TMM  : m {:.10f} M {:10f}".format(myqscd[18], myqscd[19]), extra=extra)
    logger.info("E-W TMM  : m {:.10f} M {:10f}".format(myqscd[20], myqscd[21]), extra=extra)
    logger.info(
        "Maximum  : Z {:.10f} N {:10f} E {:10f}".format(myqscd[22], myqscd[23], myqscd[24]),
        extra=extra,
    )
    logger.info("    PGA  : H {:.10f} T {:10f}".format(myqscd[25], myqscd[26]), extra=extra)
    logger.info(
        " Each SI : Z {:.10f} N {:10f} E {:10f} H {}".format(
            myqscd[27], myqscd[28], myqscd[29], myqscd[30]
        ),
        extra=extra,
    )
    logger.info(
        "Correlate: C {:.10f} Ch1 {} Ch2 {}".format(myqscd[31], myqscd[32], myqscd[33]),
        extra=extra,
    )


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
class StationGuiLogFilter(logging.Filter):
    """화면 로그: 시스템 메시지는 항상, 패킷 로그는 선택 관측소만."""

    def __init__(self, window: "MainWindow") -> None:
        super().__init__()
        self._window = window

    def filter(self, record: logging.LogRecord) -> bool:
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
    packet_received = QtCore.pyqtSignal(bytes, tuple)
    timeout_warning = QtCore.pyqtSignal(str)
    error_occurred = QtCore.pyqtSignal(str)
    recv_issue = QtCore.pyqtSignal(str)

    def __init__(self, host: str, port: int, parent: Optional[QtCore.QObject] = None) -> None:
        super().__init__(parent)
        self._host = host
        self._port = int(port)
        self._stop = False
        self._sock: Optional[socket.socket] = None

    def stop(self) -> None:
        self._stop = True
        s = self._sock
        if s is not None:
            try:
                s.close()
            except OSError:
                pass

    def run(self) -> None:
        self._stop = False
        timeout_cnt = 0
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._sock = sock
            try:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            except OSError:
                pass
            sock.bind((self._host, self._port))
            sock.settimeout(SockTimeOut)
        except OSError as e:
            self.error_occurred.emit(f"UDP bind 실패 ({self._host}:{self._port}): {e}")
            self._sock = None
            return

        while not self._stop:
            try:
                pmyqscd, _addr = sock.recvfrom(QSCD_LEN)
                timeout_cnt = 0
                if len(pmyqscd) != QSCD_LEN:
                    continue
                try:
                    myqscd = struct.unpack(QSCD20_FMT, pmyqscd)
                except struct.error as e:
                    self.recv_issue.emit(f"struct unpack 오류: {e}")
                    continue
                self.packet_received.emit(pmyqscd, myqscd)
            except socket.timeout:
                timeout_cnt += 1
                if timeout_cnt >= SockTimeOutCount:
                    self.timeout_warning.emit(
                        "Could not receive data for last "
                        + str(SockTimeOut * SockTimeOutCount)
                        + " secs."
                    )
                    timeout_cnt = 0
            except OSError:
                if self._stop:
                    break
            except Exception as e:
                self.recv_issue.emit(f"UDP 수신 오류: {e}")

        try:
            sock.close()
        except OSError:
            pass
        self._sock = None


# ---------------------------------------------------------------------------
# Station buffer (초 단위, NaN 공백)
# ---------------------------------------------------------------------------
class StationBuffer:
    def __init__(self, window_sec: int = CHART_WINDOW_SEC) -> None:
        self.buckets: Dict[int, Dict[str, float]] = {}
        self.last_recv_wall: Optional[float] = None
        self.window_sec = int(window_sec)
        self.version: int = 0

    def set_window_sec(self, window_sec: int) -> None:
        self.window_sec = int(window_sec)
        self.version += 1
        self._prune()

    def append(self, myqscd: Tuple[Any, ...], recv_wall: Optional[float] = None) -> None:
        recv_wall = recv_wall if recv_wall is not None else time.time()
        self.last_recv_wall = recv_wall
        sec = int(float(myqscd[6]))
        row: Dict[str, float] = {"diff": recv_wall - float(myqscd[6])}
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
# Chart dashboard
# ---------------------------------------------------------------------------
class QscdChartDashboard(QtWidgets.QWidget):
    def __init__(
        self,
        parent: Optional[QtWidgets.QWidget] = None,
        *,
        live_mode: bool = False,
        window_sec: int = CHART_WINDOW_SEC,
    ) -> None:
        super().__init__(parent)
        self._live_mode = live_mode
        self._window_sec = int(window_sec)
        self._scroll = QtWidgets.QScrollArea()
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
        self._plot_items: List[pg.PlotItem] = []
        self._active_panels: List[str] = []
        self._cache_key: Optional[Tuple[int, int]] = None
        self._grid_cache: Dict[str, Tuple[np.ndarray, np.ndarray]] = {}

    def set_window_sec(self, window_sec: int) -> None:
        self._window_sec = int(window_sec)
        self._cache_key = None
        self._grid_cache.clear()

    def set_live_mode(self, live: bool) -> None:
        self._live_mode = live

    def _make_plot(
        self,
        gl: pg.GraphicsLayoutWidget,
        title: str,
        curves_def: List[Tuple[str, str, Tuple[int, int, int, int]]],
        y_label: str,
        row: int,
    ) -> Dict[str, pg.PlotDataItem]:
        axis = KSTTimeAxisItem(orientation="bottom")
        vb = ChartViewBox()
        plot = gl.addPlot(row=row, col=0, title=title, viewBox=vb, axisItems={"bottom": axis})
        plot.setLabel("left", y_label)
        plot.showGrid(x=True, y=True, alpha=0.3)
        plot.addLegend(offset=(-10, 10))
        plot.setClipToView(True)
        plot.setDownsampling(auto=True, mode="peak")
        self._plot_items.append(plot)
        curves: Dict[str, pg.PlotDataItem] = {}
        for cid, label, rgba in curves_def:
            pen = pg.mkPen(color=rgba, width=1.5)
            curves[cid] = plot.plot(
                [], [], pen=pen, name=label, connect="finite", skipFiniteCheck=True
            )
        return curves

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
        self._plot_items.clear()
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
            curves = self._make_plot(gl, title, curves_def, y_label, 0)
            self._panels[pid] = (gl, curves)
            self._cont_layout.addWidget(gl)
        self._cont_layout.addStretch()

    def _rebuild_grid_cache(self, buckets: Dict[int, Dict[str, float]], version: int) -> None:
        self._cache_key = (version, self._window_sec)
        self._grid_cache.clear()
        fields = {"diff"}
        fields.update(SERIES_IDX.keys())
        for f in fields:
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
            for _gl, curves in self._panels.values():
                for c in curves.values():
                    c.setData([], [])
            return

        cache_key = (version, self._window_sec)
        if cache_key != self._cache_key:
            self._rebuild_grid_cache(buckets, version)

        for _pid, (_gl, curves) in self._panels.items():
            for cid, curve in curves.items():
                field = "diff" if cid == "diff" else cid
                x, y = self._grid_cache.get(field, (np.array([]), np.array([])))
                curve.setData(x, y, skipFiniteCheck=True)

        self._apply_plot_ranges(buckets)

    def update_from_buffer(self, buf: StationBuffer) -> None:
        self.update_from_buckets(buf.buckets, buf.version)

    def set_static_from_records(self, records: List[Tuple[Any, ...]]) -> None:
        buckets = records_to_buckets(records)
        self._cache_key = None
        self._grid_cache.clear()
        for plot in self._plot_items:
            vb = plot.getViewBox()
            if isinstance(vb, ChartViewBox):
                vb.user_zoomed = False
        self.update_from_buckets(buckets, version=1)


def read_qscd20_bin(path: str) -> List[Tuple[Any, ...]]:
    records: List[Tuple[Any, ...]] = []
    with open(path, "rb") as f:
        while True:
            chunk = f.read(QSCD_LEN)
            if not chunk:
                break
            if len(chunk) != QSCD_LEN:
                break
            try:
                records.append(struct.unpack(QSCD20_FMT, chunk))
            except struct.error:
                break
    return records


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------
class MainWindow(QtWidgets.QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("QSCD20 UDP Receiver v3.1")
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
        self._chart_window_sec: int = CHART_WINDOW_SEC
        self._file_records: List[Tuple[Any, ...]] = []

        self._chart_timer = QtCore.QTimer(self)
        self._chart_timer.setInterval(CHART_REFRESH_MS)
        self._chart_timer.timeout.connect(self._flush_chart_refresh)
        self._chart_timer.start()

        self._build_ui()
        self._gui_log_filter = StationGuiLogFilter(self)
        self._qt_handler.addFilter(self._gui_log_filter)
        self._qt_handler.log_signal.connect(self._append_log_line)

    def _build_ui(self) -> None:
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        root_layout = QtWidgets.QVBoxLayout(central)
        root_layout.setContentsMargins(4, 4, 4, 4)

        ctrl = QtWidgets.QGroupBox("수신 설정")
        grid = QtWidgets.QGridLayout(ctrl)
        grid.addWidget(QtWidgets.QLabel("UDP Port"), 0, 0)
        self._spin_port = QtWidgets.QSpinBox()
        self._spin_port.setRange(1, 65535)
        self._spin_port.setValue(DEFAULT_PORT)
        grid.addWidget(self._spin_port, 0, 1)

        grid.addWidget(QtWidgets.QLabel("로그 저장 디렉터리"), 0, 2)
        self._edit_dir = QtWidgets.QLineEdit(os.getcwd())
        btn_browse = QtWidgets.QPushButton("찾아보기…")
        btn_browse.clicked.connect(self._browse_dir)
        grid.addWidget(self._edit_dir, 0, 3)
        grid.addWidget(btn_browse, 0, 4)

        grid.addWidget(QtWidgets.QLabel("파일 prefix"), 1, 0)
        self._edit_prefix = QtWidgets.QLineEdit(datetime.datetime.now().strftime("%Y%m%d_%H%M%S"))
        grid.addWidget(self._edit_prefix, 1, 1, 1, 3)

        self._lbl_paths = QtWidgets.QLabel("")
        self._lbl_paths.setWordWrap(True)
        self._update_path_labels()
        self._edit_prefix.textChanged.connect(lambda _: self._update_path_labels())
        self._edit_dir.textChanged.connect(lambda _: self._update_path_labels())
        grid.addWidget(self._lbl_paths, 2, 0, 1, 5)

        self._btn_start = QtWidgets.QPushButton("▶ Start")
        self._btn_stop = QtWidgets.QPushButton("■ Stop")
        self._btn_stop.setEnabled(False)
        self._btn_start.clicked.connect(self._on_start)
        self._btn_stop.clicked.connect(self._on_stop)
        self._lbl_status = QtWidgets.QLabel("대기 중")
        btn_row = QtWidgets.QHBoxLayout()
        btn_row.addWidget(self._btn_start)
        btn_row.addWidget(self._btn_stop)
        btn_row.addStretch()
        btn_row.addWidget(QtWidgets.QLabel("상태:"))
        btn_row.addWidget(self._lbl_status)
        grid.addLayout(btn_row, 3, 0, 1, 5)
        root_layout.addWidget(ctrl)

        tabs = QtWidgets.QTabWidget()
        root_layout.addWidget(tabs, stretch=1)

        # Live
        live_widget = QtWidgets.QWidget()
        live_vbox = QtWidgets.QVBoxLayout(live_widget)

        hdr_bar = QtWidgets.QHBoxLayout()
        hdr_bar.addWidget(QtWidgets.QLabel("수신 관측소:"))
        self._combo_station = QtWidgets.QComboBox()
        self._combo_station.setMinimumWidth(140)
        self._combo_station.addItem("(관측소 선택)")
        self._combo_station.currentTextChanged.connect(self._on_station_selected)
        hdr_bar.addWidget(self._combo_station)
        self._lbl_last_recv = QtWidgets.QLabel("최종 수신: —")
        self._lbl_last_recv.setMinimumWidth(220)
        hdr_bar.addWidget(self._lbl_last_recv)
        hdr_bar.addWidget(QtWidgets.QLabel("  Quality:"))
        self._lbl_live_quality = QtWidgets.QLabel("—")
        self._lbl_live_quality.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        hdr_bar.addWidget(self._lbl_live_quality)
        hdr_bar.addWidget(QtWidgets.QLabel("  Station:"))
        self._lbl_live_station = QtWidgets.QLabel("—")
        self._lbl_live_station.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        hdr_bar.addWidget(self._lbl_live_station, stretch=1)
        live_vbox.addLayout(hdr_bar)

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

        tw_box = QtWidgets.QGroupBox("차트 타임 윈도우")
        tw_layout = QtWidgets.QHBoxLayout(tw_box)
        tw_layout.addWidget(QtWidgets.QLabel("표시 구간 (초):"))
        self._spin_time_window = QtWidgets.QSpinBox()
        self._spin_time_window.setRange(30, 7200)
        self._spin_time_window.setValue(CHART_WINDOW_SEC)
        self._spin_time_window.setSingleStep(30)
        self._spin_time_window.setToolTip("X축에 표시할 최근 데이터 구간(초). 1초 격자.")
        self._spin_time_window.valueChanged.connect(self._on_time_window_changed)
        tw_layout.addWidget(self._spin_time_window)
        tw_layout.addWidget(
            QtWidgets.QLabel("  · 드래그: 줌인  · 더블클릭: 줌아웃  · Live는 최신 구간 자동 스크롤")
        )
        tw_layout.addStretch()
        live_vbox.addWidget(tw_box)

        vsplit = QtWidgets.QSplitter(QtCore.Qt.Vertical)
        self._live_charts = QscdChartDashboard(live_mode=True, window_sec=self._chart_window_sec)
        self._live_charts.set_active_panels(self._get_checked_panels())
        vsplit.addWidget(self._live_charts)
        self._log_view = QtWidgets.QPlainTextEdit()
        self._log_view.setReadOnly(True)
        self._log_view.setMaximumBlockCount(LOG_MAX_LINES)
        self._log_view.setMaximumHeight(220)
        vsplit.addWidget(self._log_view)
        vsplit.setStretchFactor(0, 4)
        vsplit.setStretchFactor(1, 1)
        live_vbox.addWidget(vsplit, stretch=1)
        tabs.addTab(live_widget, "Live")

        # File viewer
        file_widget = QtWidgets.QWidget()
        file_vbox = QtWidgets.QVBoxLayout(file_widget)
        file_top = QtWidgets.QHBoxLayout()
        self._btn_open_bin = QtWidgets.QPushButton("QSCD20 .bin 열기…")
        self._btn_open_bin.clicked.connect(self._open_bin_file)
        self._lbl_file_info = QtWidgets.QLabel("파일을 선택하세요.")
        self._lbl_file_info.setWordWrap(True)
        file_top.addWidget(self._btn_open_bin)
        file_top.addWidget(self._lbl_file_info, stretch=1)
        file_vbox.addLayout(file_top)

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

        ftw_layout = QtWidgets.QHBoxLayout()
        ftw_layout.addWidget(QtWidgets.QLabel("표시 구간 (초):"))
        self._spin_file_time_window = QtWidgets.QSpinBox()
        self._spin_file_time_window.setRange(30, 7200)
        self._spin_file_time_window.setValue(CHART_WINDOW_SEC)
        self._spin_file_time_window.setSingleStep(30)
        self._spin_file_time_window.valueChanged.connect(self._on_file_time_window_changed)
        ftw_layout.addWidget(self._spin_file_time_window)
        ftw_layout.addStretch()
        file_vbox.addLayout(ftw_layout)

        self._file_charts = QscdChartDashboard(live_mode=False, window_sec=self._chart_window_sec)
        self._file_charts.set_active_panels(self._get_file_checked_panels())
        file_vbox.addWidget(self._file_charts, stretch=1)
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

    def _on_time_window_changed(self, value: int) -> None:
        self._chart_window_sec = int(value)
        self._live_charts.set_window_sec(self._chart_window_sec)
        for buf in self._station_bufs.values():
            buf.set_window_sec(self._chart_window_sec)
        self._refresh_live_charts_now()

    def _on_file_time_window_changed(self, value: int) -> None:
        self._file_charts.set_window_sec(int(value))
        if self._file_records:
            self._file_charts.set_static_from_records(self._file_records)

    def _on_station_selected(self, text: str) -> None:
        self._selected_station = text if text != "(관측소 선택)" else ""
        self._log_view.clear()
        self._update_last_recv_label()
        for plot in self._live_charts._plot_items:
            vb = plot.getViewBox()
            if isinstance(vb, ChartViewBox):
                vb.user_zoomed = False
        self._refresh_live_charts_now()

    def _update_last_recv_label(self) -> None:
        st = self._selected_station
        if not st or st not in self._station_bufs:
            self._lbl_last_recv.setText("최종 수신: —")
            return
        buf = self._station_bufs[st]
        if buf.last_recv_wall is None:
            self._lbl_last_recv.setText("최종 수신: —")
            return
        self._lbl_last_recv.setText(f"최종 수신: {format_kst_dt(buf.last_recv_wall)}")

    def _refresh_live_charts_now(self) -> None:
        st = self._selected_station
        if not st or st not in self._station_bufs:
            return
        self._live_charts.update_from_buffer(self._station_bufs[st])

    def _flush_chart_refresh(self) -> None:
        self._refresh_live_charts_now()

    def _append_log_line(self, line: str) -> None:
        self._log_view.appendPlainText(line)

    def _update_path_labels(self) -> None:
        d = self._edit_dir.text().strip() or os.getcwd()
        pfx = self._edit_prefix.text().strip() or "QSCD"
        self._lbl_paths.setText(
            f"로그 파일: {os.path.join(d, f'{pfx}.QSCD.log')}   "
            f"바이너리: {os.path.join(d, f'{pfx}.QSCD20.bin')}"
        )

    def _browse_dir(self) -> None:
        d = QtWidgets.QFileDialog.getExistingDirectory(self, "로그 저장 디렉터리", self._edit_dir.text())
        if d:
            self._edit_dir.setText(d)

    def _on_start(self) -> None:
        if self._receiver is not None:
            return
        log_dir = self._edit_dir.text().strip()
        if not log_dir:
            QtWidgets.QMessageBox.warning(self, "경로 오류", "로그 디렉터리를 입력하세요.")
            return
        if not os.path.isdir(log_dir):
            try:
                os.makedirs(log_dir, exist_ok=True)
            except OSError as e:
                QtWidgets.QMessageBox.critical(self, "경로 오류", str(e))
                return

        prefix = self._edit_prefix.text().strip()
        if not prefix:
            QtWidgets.QMessageBox.warning(self, "prefix 오류", "파일 prefix를 입력하세요.")
            return

        log_path = os.path.join(log_dir, f"{prefix}.QSCD.log")
        bin_path = os.path.join(log_dir, f"{prefix}.QSCD20.bin")

        try:
            fh = logging.FileHandler(log_path, encoding="utf-8")
            fh.setFormatter(self._formatter)
            self._logger.addHandler(fh)
            self._file_handler = fh
        except OSError as e:
            QtWidgets.QMessageBox.critical(self, "로그 오류", str(e))
            return

        try:
            self._data_fp = open(bin_path, "wb")
        except OSError as e:
            if self._file_handler:
                self._logger.removeHandler(self._file_handler)
                self._file_handler.close()
                self._file_handler = None
            QtWidgets.QMessageBox.critical(self, "파일 오류", str(e))
            return

        self._station_bufs.clear()
        self._selected_station = ""
        self._log_view.clear()
        self._combo_station.blockSignals(True)
        self._combo_station.clear()
        self._combo_station.addItem("(관측소 선택)")
        self._combo_station.blockSignals(False)
        self._chart_window_sec = int(self._spin_time_window.value())
        self._live_charts.set_window_sec(self._chart_window_sec)
        self._live_charts.set_active_panels(self._get_checked_panels())
        self._reset_live_header_labels()
        self._update_last_recv_label()

        port = int(self._spin_port.value())
        self._outputs_open = True
        self._receiver = UdpReceiver(HOST, port, self)
        self._receiver.packet_received.connect(self._on_packet)
        self._receiver.timeout_warning.connect(self._on_timeout_warning)
        self._receiver.error_occurred.connect(self._on_udp_error)
        self._receiver.recv_issue.connect(self._on_recv_issue)
        self._receiver.finished.connect(self._on_receiver_finished)
        self._receiver.start()

        self._btn_start.setEnabled(False)
        self._btn_stop.setEnabled(True)
        self._spin_port.setEnabled(False)
        self._lbl_status.setText(f"수신 중 — UDP {HOST}:{port}")
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
        self._logger.info("수신 중지됨.", extra={"station": ""})

    def _close_session_outputs(self) -> None:
        if not self._outputs_open:
            return
        self._outputs_open = False
        if self._data_fp is not None:
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
        self._lbl_status.setText("대기 중")
        self._reset_live_header_labels()
        self._update_last_recv_label()

    def _on_receiver_finished(self) -> None:
        thr = self.sender()
        if isinstance(thr, UdpReceiver):
            thr.deleteLater()
        if self._receiver is thr:
            self._receiver = None
        if self._outputs_open:
            self._close_session_outputs()
            self._reset_receive_ui()

    def _on_packet(self, pmyqscd: bytes, myqscd: Tuple[Any, ...]) -> None:
        st = station_code_str(myqscd)
        recv_wall = time.time()

        if st not in self._station_bufs:
            self._station_bufs[st] = StationBuffer(window_sec=self._chart_window_sec)
            self._combo_station.addItem(st)

        buf = self._station_bufs[st]
        buf.append(myqscd, recv_wall)

        if self._data_fp is not None:
            try:
                self._data_fp.write(pmyqscd)
                self._data_fp.flush()
            except OSError as e:
                self._logger.error(f"바이너리 쓰기 오류: {e}", extra={"station": st})

        # 디스크 로그는 모든 관측소 기록, 화면은 Filter로 선택 관측소만
        log_qscd_packet(self._logger, pmyqscd, myqscd, st)

        if self._selected_station != st:
            return

        self._lbl_live_quality.setText(format_quality_flag_line(myqscd))
        self._lbl_live_station.setText(format_station_code_line(myqscd))
        self._update_last_recv_label()
        self._refresh_live_charts_now()

    def _on_timeout_warning(self, msg: str) -> None:
        self._logger.warning(msg, extra={"station": ""})

    def _on_udp_error(self, msg: str) -> None:
        self._logger.error(msg, extra={"station": ""})
        QtWidgets.QMessageBox.warning(self, "UDP", msg)

    def _on_recv_issue(self, msg: str) -> None:
        self._logger.error(msg, extra={"station": ""})

    def _reset_live_header_labels(self) -> None:
        self._lbl_live_quality.setText("—")
        self._lbl_live_station.setText("—")

    def _open_bin_file(self) -> None:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "QSCD20 바이너리 열기", self._edit_dir.text(), "QSCD20 (*.bin);;All (*.*)"
        )
        if not path:
            return
        try:
            recs = read_qscd20_bin(path)
        except OSError as e:
            QtWidgets.QMessageBox.critical(self, "파일 오류", str(e))
            return
        if not recs:
            self._file_records = []
            self._lbl_file_info.setText(f"{path}\n유효한 레코드가 없습니다.")
            self._file_charts.set_static_from_records([])
            return

        self._file_records = recs

        t0 = format_kst_dt(float(recs[0][6]))
        t1 = format_kst_dt(float(recs[-1][6]))
        st0 = format_station_code_line(recs[0])
        q0 = format_quality_flag_line(recs[0])
        self._lbl_file_info.setText(
            f"{path}\n레코드 수: {len(recs)}\n시작(KST, data time): {t0}\n종료: {t1}\n"
            f"Quality: {q0}\nStation: {st0}"
        )
        self._file_charts.set_window_sec(self._spin_file_time_window.value())
        self._file_charts.set_active_panels(self._get_file_checked_panels())
        self._file_charts.set_static_from_records(recs)

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        self._on_stop()
        super().closeEvent(event)


def main() -> int:
    app = QtWidgets.QApplication(sys.argv)
    w = MainWindow()
    w.show()
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
