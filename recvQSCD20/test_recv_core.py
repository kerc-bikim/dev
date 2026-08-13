# -*- coding: utf-8 -*-
"""수신 핵심 로직 테스트 — PyQt5/numpy/pyqtgraph 가 있어야 실행됩니다."""
from __future__ import annotations

import os
import queue
import struct
import tempfile
import unittest

try:
    from PyQt5 import QtCore

    import recvQSCD20_gui as app

    HAVE_APP = True
except Exception:  # pragma: no cover - 의존성 미설치 환경
    HAVE_APP = False


def make_packet(data_time: int = 1_700_000_000, zmax: float = 1.5) -> bytes:
    values = [0, b"A", b"B", b"C", b"KG", b"001", data_time]
    floats = [0.0] * 25
    floats[22 - 7] = zmax
    values += floats
    values += [b"X", b"Y", b"ZZ"]
    return struct.pack(app.QSCD20_FMT, *values)


@unittest.skipUnless(HAVE_APP, "PyQt5/numpy/pyqtgraph 미설치")
class TimeDiffTests(unittest.TestCase):
    def test_uses_capture_time_not_now(self) -> None:
        myqscd = struct.unpack(app.QSCD20_FMT, make_packet(1000))
        self.assertAlmostEqual(app.compute_recv_time_diff(1002.5, myqscd), 2.5, places=6)

    def test_station_buffer_keeps_given_diff(self) -> None:
        myqscd = struct.unpack(app.QSCD20_FMT, make_packet(1000))
        buf = app.StationBuffer(window_sec=60)
        buf.append(myqscd, recv_wall=9999.0, recv_diff=0.25)
        self.assertAlmostEqual(buf.buckets[1000]["diff"], 0.25, places=6)


@unittest.skipUnless(HAVE_APP, "PyQt5/numpy/pyqtgraph 미설치")
class QcdxRoundTripTests(unittest.TestCase):
    def test_pack_and_read(self) -> None:
        pmy = make_packet(1_700_000_123, zmax=2.5)
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "t.QSCD20.bin")
            with open(path, "wb") as fp:
                app.write_qscd20_bin_header(fp)
                fp.write(app.pack_qscd20_bin_record(pmy, 1.25))
                fp.write(app.pack_qscd20_bin_record(pmy, -0.5))
            loaded = app.read_qscd20_bin(path)
        self.assertTrue(loaded.has_stored_diff)
        self.assertEqual(len(loaded.records), 2)
        assert loaded.recv_diffs is not None
        self.assertAlmostEqual(loaded.recv_diffs[0], 1.25, places=6)
        self.assertAlmostEqual(loaded.recv_diffs[1], -0.5, places=6)
        self.assertEqual(int(loaded.records[0][6]), 1_700_000_123)


@unittest.skipUnless(HAVE_APP, "PyQt5/numpy/pyqtgraph 미설치")
class ReceiverQueueTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._qapp = QtCore.QCoreApplication.instance() or QtCore.QCoreApplication([])

    def _receiver(self, maxsize: int) -> "app.UdpReceiver":
        recv = app.UdpReceiver("127.0.0.1", 9999)
        recv._packets = queue.Queue(maxsize=maxsize)
        return recv

    def test_full_queue_drops_newest(self) -> None:
        recv = self._receiver(2)
        for i in range(4):
            recv._enqueue((b"", (), float(i), 0.0))
        kept = [item[2] for item in recv.drain_packets()]
        self.assertEqual(kept, [0.0, 1.0])
        self.assertEqual(recv._drop_count, 2)

    def test_drain_respects_limit(self) -> None:
        recv = self._receiver(10)
        for i in range(5):
            recv._enqueue((b"", (), float(i), 0.0))
        self.assertEqual(len(recv.drain_packets(2)), 2)
        self.assertEqual(len(recv.drain_packets()), 3)
        self.assertEqual(recv.drain_packets(), [])

    def test_timeout_is_applied_by_worker_not_caller(self) -> None:
        recv = self._receiver(4)
        before = recv._sock_timeout
        recv.set_sock_params(2.0, 7)
        self.assertEqual(recv._sock_timeout, before)
        self.assertEqual(recv._pending_timeout, 2.0)
        self.assertEqual(recv._sock_timeout_count, 7)

    def test_timeout_floor(self) -> None:
        recv = self._receiver(4)
        recv.set_sock_params(0.0, 10)
        self.assertGreaterEqual(recv._pending_timeout or 0.0, app.MIN_SOCK_TIMEOUT_SEC)


if __name__ == "__main__":
    unittest.main()
