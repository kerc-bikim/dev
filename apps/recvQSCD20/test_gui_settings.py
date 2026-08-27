# -*- coding: utf-8 -*-
"""gui_settings 단위 테스트 (PyQt/numpy 불필요)."""
from __future__ import annotations

import os
import unittest

import gui_settings as gs


class SanitizePrefixTests(unittest.TestCase):
    def test_ok(self) -> None:
        self.assertEqual(gs.sanitize_file_prefix(" 20260813_1030 "), "20260813_1030")

    def test_empty(self) -> None:
        with self.assertRaises(ValueError):
            gs.sanitize_file_prefix("  ")

    def test_path_sep(self) -> None:
        with self.assertRaises(ValueError):
            gs.sanitize_file_prefix("a/b")
        with self.assertRaises(ValueError):
            gs.sanitize_file_prefix("a\\b")

    def test_dotdot(self) -> None:
        with self.assertRaises(ValueError):
            gs.sanitize_file_prefix("..")
        with self.assertRaises(ValueError):
            gs.sanitize_file_prefix("..hidden")

    def test_reserved_device_names(self) -> None:
        for name in ("CON", "nul", "Com1", "LPT9"):
            with self.assertRaises(ValueError, msg=name):
                gs.sanitize_file_prefix(name)

    def test_trailing_dot_or_space(self) -> None:
        with self.assertRaises(ValueError):
            gs.sanitize_file_prefix("run.")

    def test_dots_inside_allowed(self) -> None:
        self.assertEqual(gs.sanitize_file_prefix("site.a.1"), "site.a.1")


class PathStorageTests(unittest.TestCase):
    def test_relative_under_work(self) -> None:
        work = gs.work_directory()
        rel = gs.path_for_settings_storage(os.path.join(work, "logs"))
        self.assertEqual(rel.replace("\\", "/"), "logs")

    def test_outside_work_stays_absolute(self) -> None:
        outside = os.path.abspath(os.path.join(gs.work_directory(), os.pardir, "elsewhere"))
        self.assertTrue(os.path.isabs(gs.path_for_settings_storage(outside)))

    def test_resolve_relative(self) -> None:
        p = gs.resolve_data_dir("logs")
        self.assertTrue(os.path.isabs(p))
        self.assertTrue(p.endswith("logs"))


class SettingsValidateTests(unittest.TestCase):
    def test_default_ok(self) -> None:
        gs.validate_settings(gs.default_settings(), ["diff", "max", "pga"])

    def test_zero_sock_timeout_rejected(self) -> None:
        s = gs.default_settings()
        s.sock_timeout_sec = 0.0
        with self.assertRaises(ValueError):
            gs.validate_settings(s)

    def test_zero_sock_timeout_coerced_on_load(self) -> None:
        s = gs.settings_from_dict({"sock_timeout_sec": 0})
        self.assertGreaterEqual(s.sock_timeout_sec, gs.MIN_SOCK_TIMEOUT_SEC)
        gs.validate_settings(s)

    def test_window_mismatch_coerced_on_load(self) -> None:
        s = gs.settings_from_dict(
            {"time_window_choices": [60, 120], "default_time_window_sec": 999}
        )
        self.assertEqual(s.default_time_window_sec, 60)
        gs.validate_settings(s)

    def test_unknown_panel(self) -> None:
        s = gs.default_settings()
        s.default_panels = ["nope"]
        with self.assertRaises(ValueError):
            gs.validate_settings(s, ["diff", "max"])


class SerializationTests(unittest.TestCase):
    def test_roundtrip_dict(self) -> None:
        s = gs.default_settings()
        s.packet_queue_max = 5000
        loaded = gs.settings_from_dict(gs.settings_to_dict(s))
        self.assertEqual(loaded.packet_queue_max, 5000)

    def test_unknown_key_ignored(self) -> None:
        s = gs.settings_from_dict({"nope": 1, "default_port": 1234})
        self.assertEqual(s.default_port, 1234)


class ApplyNoteTests(unittest.TestCase):
    def test_no_change_no_note(self) -> None:
        self.assertEqual(gs.pending_apply_notes(gs.default_settings(), gs.default_settings()), [])

    def test_restart_required_panels(self) -> None:
        new = gs.default_settings()
        new.default_panels = ["diff"]
        notes = gs.pending_apply_notes(gs.default_settings(), new)
        self.assertEqual(len(notes), 1)
        self.assertIn("다시 시작", notes[0])

    def test_receive_restart_queue_max(self) -> None:
        new = gs.default_settings()
        new.packet_queue_max = 999
        notes = gs.pending_apply_notes(gs.default_settings(), new)
        self.assertEqual(len(notes), 1)
        self.assertIn("Start", notes[0])

    def test_immediate_key_has_no_note(self) -> None:
        new = gs.default_settings()
        new.chart_refresh_ms = 500
        self.assertEqual(gs.pending_apply_notes(gs.default_settings(), new), [])

    def test_changed_keys(self) -> None:
        new = gs.default_settings()
        new.default_port = 1
        self.assertEqual(gs.changed_setting_keys(gs.default_settings(), new), ["default_port"])


if __name__ == "__main__":
    unittest.main()
