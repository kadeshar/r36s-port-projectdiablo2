#!/usr/bin/env python3
"""Tests for R36S performance overlay, hotkeys, and system metrics."""
import os
import struct
import sys
import tempfile
import time
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OVERLAY_DIR = os.path.join(ROOT, 'sdcard', 'ports', 'projectdiablo2', 'scripts', 'overlay')
if OVERLAY_DIR not in sys.path:
    sys.path.insert(0, OVERLAY_DIR)

import overlay_metrics
import fps_tracker
import x11_hud
import performance_overlay
import hotkey_listener


class TestSystemMetrics(unittest.TestCase):
    def setUp(self):
        self.metrics = overlay_metrics.SystemMetrics()

    def test_sample_structure_and_keys(self):
        data = self.metrics.sample()
        required_keys = {
            'cpu_total', 'cpu_cores', 'cpu_mhz', 'cpu_temp',
            'ram_used_mb', 'ram_total_mb', 'ram_free_mb',
            'swap_used_mb', 'swap_total_mb', 'gpu_pct', 'gpu_mhz',
            'battery_pct', 'battery_status', 'battery_volts', 'plugged',
        }
        self.assertTrue(required_keys.issubset(data.keys()))
        self.assertIsInstance(data['cpu_total'], int)
        self.assertIsInstance(data['cpu_cores'], list)
        self.assertIsInstance(data['ram_total_mb'], int)
        self.assertGreater(data['ram_total_mb'], 0)

    def test_cpu_usage_calculation(self):
        stat_mock_1 = (
            "cpu  1000 0 1000 8000 0 0 0\n"
            "cpu0 250 0 250 2000 0 0 0\n"
            "cpu1 250 0 250 2000 0 0 0\n"
        )
        stat_mock_2 = (
            "cpu  1500 0 1500 9000 0 0 0\n"
            "cpu0 400 0 400 2200 0 0 0\n"
            "cpu1 350 0 350 2300 0 0 0\n"
        )
        with mock.patch("builtins.open", mock.mock_open(read_data=stat_mock_1)):
            total1, cores1 = self.metrics._read_cpu_usage()
            self.assertEqual(total1, 0)  # first sample is baseline

        with mock.patch("builtins.open", mock.mock_open(read_data=stat_mock_2)):
            total2, cores2 = self.metrics._read_cpu_usage()
            self.assertEqual(total2, 50)
            self.assertEqual(len(cores2), 2)
            self.assertEqual(cores2[0], 60)

    def test_meminfo_calculation(self):
        meminfo_mock = (
            "MemTotal:        1024000 kB\n"
            "MemFree:          200000 kB\n"
            "MemAvailable:     600000 kB\n"
            "Buffers:           50000 kB\n"
            "Cached:           350000 kB\n"
            "SwapTotal:        512000 kB\n"
            "SwapFree:         400000 kB\n"
        )
        with mock.patch("builtins.open", mock.mock_open(read_data=meminfo_mock)):
            used_mb, total_mb, free_mb = self.metrics._read_ram()
            swap_used_mb, swap_total_mb = self.metrics._read_swap()
            self.assertEqual(total_mb, 1000)
            self.assertEqual(free_mb, 585)
            self.assertEqual(used_mb, 415)
            self.assertEqual(swap_total_mb, 500)
            self.assertEqual(swap_used_mb, 110)


class TestFPSTracker(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.work_dir = self.tmp_dir.name
        self.d2_dir = os.path.join(self.work_dir, 'ProjectD2')
        os.makedirs(self.d2_dir, exist_ok=True)
        self.tracker = fps_tracker.FPSTracker(work_dir=self.work_dir)

    def tearDown(self):
        self.tracker.close()
        self.tmp_dir.cleanup()

    def test_initial_state(self):
        data = self.tracker.update()
        self.assertEqual(data['fps'], 0)
        self.assertEqual(data['avg_fps'], 0.0)
        self.assertEqual(data['low_1pct'], 0.0)
        self.assertEqual(data['low_01pct'], 0.0)
        self.assertEqual(len(data['history']), 200)

    def test_manual_record_frame_and_percentiles(self):
        # Record 100 frames: 90 frames at 60 FPS (16.6ms), 10 frames at 30 FPS (33.3ms)
        for _ in range(90):
            self.tracker.record_frame(16.6)
        for _ in range(10):
            self.tracker.record_frame(33.3)

        self.assertEqual(self.tracker.fps, 30)
        self.assertEqual(self.tracker.min_fps, 30)
        self.assertEqual(self.tracker.max_fps, 60)
        self.assertAlmostEqual(self.tracker.avg_fps, 57.0, places=1)
        # 1% low is average of lowest 1 frame out of 100
        self.assertEqual(self.tracker.low_1pct, 30.0)
        self.assertEqual(self.tracker.low_01pct, 30.0)

    def test_telemetry_file_reading(self):
        present_file = os.path.join(self.d2_dir, 'pd2-present.jsonl')
        with open(present_file, 'w', encoding='ascii') as f:
            f.write('{"event":1,"backend":1,"frames":30,"duration_ms":1000,"width":640,"height":480}\n')

        data = self.tracker.update()
        self.assertEqual(data['fps'], 30)
        self.assertEqual(data['frametime_ms'], 33.3)
        self.assertEqual(data['avg_fps'], 30.0)

        # Append next sample
        with open(present_file, 'a', encoding='ascii') as f:
            f.write('{"event":1,"backend":1,"frames":20,"duration_ms":1000,"width":640,"height":480}\n')

        data = self.tracker.update()
        self.assertEqual(data['fps'], 20)
        self.assertEqual(data['frametime_ms'], 50.0)
        self.assertAlmostEqual(data['avg_fps'], 25.0, places=1)
        self.assertEqual(data['low_1pct'], 20.0)

    def test_reset_data(self):
        self.tracker.record_frame(16.6)
        self.tracker.record_frame(33.3)
        self.assertGreater(self.tracker.avg_fps, 0)
        self.assertGreater(len(self.tracker.history), 0)

        self.tracker.reset()
        self.assertEqual(self.tracker.fps, 0)
        self.assertEqual(self.tracker.frametime_ms, 0.0)
        self.assertEqual(self.tracker.avg_fps, 0.0)
        self.assertEqual(self.tracker.low_1pct, 0.0)
        self.assertEqual(self.tracker.low_01pct, 0.0)
        self.assertEqual(len(self.tracker.history), 0)
        self.assertEqual(len(self.tracker.all_fps_samples), 0)


class TestX11HUD(unittest.TestCase):
    def test_chart_color_thresholds(self):
        # > 20 FPS: green (< 50.0ms)
        self.assertEqual(x11_hud.get_chart_color(16.6), x11_hud.C_CHART_OK)    # ~60 FPS
        self.assertEqual(x11_hud.get_chart_color(33.3), x11_hud.C_CHART_OK)    # ~30 FPS
        self.assertEqual(x11_hud.get_chart_color(40.0), x11_hud.C_CHART_OK)    # 25 FPS
        self.assertEqual(x11_hud.get_chart_color(49.9), x11_hud.C_CHART_OK)    # > 20 FPS

        # 15-20 FPS: orange (50.0ms - 66.7ms)
        self.assertEqual(x11_hud.get_chart_color(50.0), x11_hud.C_CHART_WARN)  # 20 FPS
        self.assertEqual(x11_hud.get_chart_color(55.0), x11_hud.C_CHART_WARN)  # ~18.2 FPS
        self.assertEqual(x11_hud.get_chart_color(60.0), x11_hud.C_CHART_WARN)  # ~16.7 FPS
        self.assertEqual(x11_hud.get_chart_color(66.6), x11_hud.C_CHART_WARN)  # ~15.0 FPS
        self.assertEqual(x11_hud.get_chart_color(66.7), x11_hud.C_CHART_WARN)  # 15 FPS

        # < 15 FPS: red (> 66.7ms)
        self.assertEqual(x11_hud.get_chart_color(66.8), x11_hud.C_CHART_BAD)   # < 15 FPS
        self.assertEqual(x11_hud.get_chart_color(70.0), x11_hud.C_CHART_BAD)   # ~14.3 FPS
        self.assertEqual(x11_hud.get_chart_color(100.0), x11_hud.C_CHART_BAD)  # 10 FPS

        # Edge cases
        self.assertEqual(x11_hud.get_chart_color(0), x11_hud.C_CHART_OK)
        self.assertEqual(x11_hud.get_chart_color(-10), x11_hud.C_CHART_OK)

    def test_dimensions_per_level(self):
        hud1 = x11_hud.X11HUD(level=1)
        self.assertEqual((hud1.width, hud1.height), (x11_hud.LEVEL1_WIDTH, x11_hud.LEVEL1_HEIGHT))

        hud2 = x11_hud.X11HUD(level=2)
        self.assertEqual((hud2.width, hud2.height), (410, 20))
        self.assertEqual(hud2.x, (640 - 410) // 2)  # Centered horizontally
        self.assertEqual(hud2.y, 0)  # Glued to top edge

        hud3 = x11_hud.X11HUD(level=3)
        self.assertEqual((hud3.width, hud3.height), (205, 176))
        self.assertEqual(hud3.y, 0)  # Glued to top edge

        hud4 = x11_hud.X11HUD(level=4)
        self.assertEqual((hud4.width, hud4.height), (205, 266))
        self.assertEqual(hud4.y, 0)  # Glued to top edge

    def test_set_level_resizes_hud(self):
        hud = x11_hud.X11HUD(level=1)
        mock_sock = mock.MagicMock()
        mock_sock.recv.return_value = b'\x01' + b'\x00' * 31
        hud.sock = mock_sock
        hud.window = 1234
        hud.pixmap = 5678

        # Switch to level 2 (must be centered properly)
        mock_sock.reset_mock()
        hud.set_level(2)
        self.assertEqual(hud.level, 2)
        self.assertEqual((hud.width, hud.height), (410, 20))
        self.assertEqual(hud.x, (640 - 410) // 2)
        self.assertEqual(hud.y, 0)
        self.assertTrue(mock_sock.sendall.called)

        # Switch to level 3
        hud.set_level(3)
        self.assertEqual(hud.level, 3)
        self.assertEqual((hud.width, hud.height), (205, 176))
        self.assertEqual(hud.x, 8)
        self.assertEqual(hud.y, 0)
        self.assertTrue(mock_sock.sendall.called)

        # Switch to level 0 (hidden)
        mock_sock.reset_mock()
        hud.set_level(0)
        self.assertEqual(hud.level, 0)
        self.assertTrue(mock_sock.sendall.called)

    def test_xauth_parsing(self):
        def field(v): return struct.pack('>H', len(v)) + v
        cookie = b'1234567890abcdef'
        record = struct.pack('>H', 65535) + field(b'') + field(b'0') + field(b'MIT-MAGIC-COOKIE-1') + field(cookie)
        self.assertEqual(x11_hud.X11HUD._parse_xauth(record), cookie)

        garbled = b'prefix_junk' + record
        self.assertEqual(x11_hud.X11HUD._parse_xauth(garbled), cookie)

    def test_pixel_calculation(self):
        hud = x11_hud.X11HUD()
        self.assertEqual(hud._pixel((255, 0, 0)), 0xff0000)
        self.assertEqual(hud._pixel((0, 255, 0)), 0x00ff00)
        self.assertEqual(hud._pixel((0, 0, 255)), 0x0000ff)
        self.assertEqual(hud._pixel((18, 20, 26)), 0x12141a)

    def test_mock_render_all_levels_with_new_sections(self):
        mock_sock = mock.MagicMock()
        for lvl in (1, 2, 3, 4):
            hud = x11_hud.X11HUD(level=lvl)
            hud.sock = mock_sock
            m = {
                'cpu_total': 45, 'cpu_cores': [40, 50, 42, 48],
                'cpu_mhz': 1300, 'cpu_temp': 48,
                'ram_used_mb': 412, 'ram_total_mb': 1024,
                'swap_used_mb': 15, 'swap_total_mb': 512,
                'gpu_pct': 30, 'gpu_mhz': 500,
                'battery_pct': 85, 'battery_status': 'Discharging',
                'battery_volts': 4.1,
            }
            f = {
                'fps': 60, 'frametime_ms': 16.6, 'min_fps': 58, 'max_fps': 62,
                'avg_fps': 59.8, 'low_1pct': 58.2, 'low_01pct': 57.0,
                'history': [16.6] * 20,
            }
            hud.render(m, f)
            self.assertTrue(mock_sock.sendall.called)

    def test_level1_skips_redraw_when_fps_unchanged(self):
        mock_sock = mock.MagicMock()
        hud = x11_hud.X11HUD(level=1)
        hud.sock = mock_sock
        f = {'fps': 30}
        hud.render({}, f)
        call_count1 = mock_sock.sendall.call_count
        self.assertGreater(call_count1, 0)

        # Same FPS: must skip sending any requests
        hud.render({}, f)
        self.assertEqual(mock_sock.sendall.call_count, call_count1)

        # Changed FPS: must redraw
        hud.render({}, {'fps': 35})
        self.assertGreater(mock_sock.sendall.call_count, call_count1)


class TestHotkeyListener(unittest.TestCase):
    def setUp(self):
        self.switches = 0
        self.resets = 0

        def on_switch():
            self.switches += 1

        def on_reset():
            self.resets += 1

        self.listener = hotkey_listener.HotkeyListener(
            on_switch_level=on_switch,
            on_reset_data=on_reset,
            debounce_seconds=0.01,
        )

    def tearDown(self):
        self.listener.stop()

    def _pack_event(self, etype, code, val):
        return struct.pack(hotkey_listener.EVENT_FORMAT, 0, 0, etype, code, val)

    def test_fn_plus_r1_triggers_switch_level(self):
        # 1. Press FN (code 0x2c4)
        evt_fn_down = self._pack_event(hotkey_listener.EV_KEY, hotkey_listener.BTN_TRIGGER_HAPPY5, 1)
        self.listener.process_data(evt_fn_down)
        self.assertEqual(self.switches, 0)

        # 2. Press R1 (code 0x137) while holding FN
        evt_r1_down = self._pack_event(hotkey_listener.EV_KEY, hotkey_listener.BTN_TR, 1)
        self.listener.process_data(evt_r1_down)
        self.assertEqual(self.switches, 1)

        sw, rs = self.listener.poll_actions()
        self.assertTrue(sw)
        self.assertFalse(rs)

    def test_fn_plus_r2_triggers_reset_data(self):
        # 1. Press FN (code 0x2c4)
        evt_fn_down = self._pack_event(hotkey_listener.EV_KEY, hotkey_listener.BTN_TRIGGER_HAPPY5, 1)
        self.listener.process_data(evt_fn_down)
        self.assertEqual(self.resets, 0)

        # 2. Press R2 (code 0x139) while holding FN
        evt_r2_down = self._pack_event(hotkey_listener.EV_KEY, hotkey_listener.BTN_TR2, 1)
        self.listener.process_data(evt_r2_down)
        self.assertEqual(self.resets, 1)

        sw, rs = self.listener.poll_actions()
        self.assertFalse(sw)
        self.assertTrue(rs)

    def test_fn_plus_analog_r2_axis_triggers_reset_data(self):
        # 1. Press FN (code 0x13c / BTN_MODE on Xbox pad)
        evt_fn_down = self._pack_event(hotkey_listener.EV_KEY, hotkey_listener.BTN_MODE, 1)
        self.listener.process_data(evt_fn_down)

        # 2. Trigger ABS_RZ axis >= 128
        evt_rz = self._pack_event(hotkey_listener.EV_ABS, hotkey_listener.ABS_RZ, 255)
        self.listener.process_data(evt_rz)
        self.assertEqual(self.resets, 1)


class TestOptimizationLevelMetrics(unittest.TestCase):
    def setUp(self):
        self.metrics = overlay_metrics.SystemMetrics()

    def test_level1_collects_zero_metrics(self):
        data = self.metrics.sample(level=1)
        self.assertEqual(data, {})

    def test_level2_omits_unneeded_metrics(self):
        data = self.metrics.sample(level=2)
        self.assertEqual(data['cpu_cores'], [])
        self.assertEqual(data['swap_used_mb'], 0)


class TestPerformanceOverlayCLI(unittest.TestCase):
    def test_cli_mode_single_iteration(self):
        # Target PID that is not running immediately terminates the loop
        rc = performance_overlay.run_overlay(level=2, target_pid=99999999, cli_mode=True)
        self.assertEqual(rc, 0)


if __name__ == '__main__':
    unittest.main()
