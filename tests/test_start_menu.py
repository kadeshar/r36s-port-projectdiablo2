"""Synthetic menu/input/launcher tests: never open DRM, pad or run a game."""
import importlib.util
import io
import json
import os
import re
import shutil
import tempfile
from pathlib import Path
import struct
import subprocess
import sys
import types
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'sdcard/ports/projectdiablo2/scripts'
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location('start_menu', SCRIPTS / 'start_menu.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def event(kind, code, value):
    return m.EVENT.pack(0, 0, kind, code, value)


class FakeScreen:
    def __init__(self, actions=()):
        self.frames = iter([[]] + list(actions))
        self.closed = False
        self.draws = []

    def actions(self):
        return next(self.frames, ['cancel'])

    def draw(self, menu):
        self.draws.append((menu.row, menu.resolution, menu.fps, menu.fps_changed))

    def close(self):
        self.closed = True


class FakePad:
    def __init__(self, actions=()):
        self.frames = iter([[]] + list(actions))
        self.closed = False

    def actions(self):
        return next(self.frames, [])

    def close(self):
        self.closed = True


class MenuTests(unittest.TestCase):
    def test_defaults_ignore_environment_and_need_confirmation(self):
        with mock.patch.dict(os.environ, {'PD2_GAME_RESOLUTION': '1024x768', 'PD2_FPS': '1', 'PD2_AUDIO_TEST': '1'}):
            menu = m.Menu()
        self.assertEqual((menu.row, menu.resolution, menu.fps, menu.result), (0, 0, 0, None))
        self.assertEqual(menu.screen, 'main')
        with self.assertRaises(ValueError):
            menu.selection()
        # Row 0 is Start Game: confirming it launches.
        menu.action('accept')
        self.assertEqual(menu.result, 'launch')
        self.assertEqual(menu.selection(), ('default', 'default', 'default', 'pd2'))

    def test_inherited_values_are_displayed_without_overriding_selection(self):
        with mock.patch.dict(os.environ, {'PD2_GAME_RESOLUTION': '1024x768', 'PD2_FPS': '1'}):
            menu = m.Menu()
        self.assertEqual((menu.inherited_resolution, menu.inherited_fps), ('1024x768', True))
        menu.action('accept')
        self.assertEqual(menu.selection(), ('default', 'default', 'default', 'pd2'))

    def test_first_fps_toggle_inverts_the_inherited_setting(self):
        with mock.patch.dict(os.environ, {'PD2_FPS': '1'}):
            menu = m.Menu()
        # Navigate to Options (row 1 on main)
        menu.action('down')
        menu.action('accept')
        self.assertEqual(menu.screen, 'options')
        # Row 2 in Options is FPS
        menu.action('down')
        menu.action('down')
        menu.action('accept')
        self.assertFalse(menu.fps)
        # Back to main (row 5 in Options is BACK)
        menu.action('down')
        menu.action('down')
        menu.action('down')
        menu.action('accept')
        self.assertEqual(menu.screen, 'main')
        self.assertEqual(menu.row, 1)
        # Select Start Game (row 0)
        menu.action('up')
        menu.action('accept')
        self.assertEqual(menu.selection(), ('default', '0', 'default', 'pd2'))

    def test_missing_inherited_resolution_defaults_to_lcd(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            menu = m.Menu()
        self.assertEqual((menu.inherited_resolution, menu.inherited_fps), ('640x480', False))
        menu.action('accept')
        self.assertEqual(menu.selection(), ('default', 'default', 'default', 'pd2'))

    def test_explicit_800x600_inheritance_and_selection_are_preserved(self):
        with mock.patch.dict(os.environ, {'PD2_GAME_RESOLUTION': '800x600'}):
            menu = m.Menu()
        self.assertEqual(menu.inherited_resolution, '800x600')
        # Enter options:
        menu.action('down')
        menu.action('accept')
        self.assertEqual(menu.screen, 'options')
        self.assertEqual(menu.row, 0)
        # Move down to resolution (row 1)
        menu.action('down')
        self.assertEqual(menu.row, 1)
        # First right advances directly from 800x600 to 1024x768 without duplicate step.
        for expected in ('1024x768', 'native', '640x480', '800x600'):
            menu.action('right')
            self.assertEqual(m.RESOLUTIONS[menu.resolution], expected)
        self.assertEqual(m.LABELS[menu.resolution], '800x600')
        # Go to BACK (row 5)
        for _ in range(4):
            menu.action('down')
        menu.action('accept')
        self.assertEqual(menu.screen, 'main')
        menu.action('up')
        menu.action('accept')
        self.assertEqual(menu.selection(), ('800x600', 'default', 'default', 'pd2'))

    def test_invalid_inherited_resolution_uses_safe_display_default(self):
        with mock.patch.dict(os.environ, {'PD2_GAME_RESOLUTION': 'invalid', 'PD2_FPS': 'invalid'}):
            menu = m.Menu()
        self.assertEqual((menu.inherited_resolution, menu.inherited_fps), ('640x480', False))

    def test_all_15_resolution_fps_choices(self):
        choices = set()
        for steps in range(len(m.RESOLUTIONS)):
            for fps in ('default', '0', '1'):
                with mock.patch.dict(os.environ, {}, clear=True):
                    menu = m.Menu()
                # Enter options
                menu.action('down')
                menu.action('accept')
                # Move to resolution row (row 1)
                menu.action('down')
                for _ in range(steps):
                    menu.action('right')
                expected_res = ('default', '800x600', '1024x768', 'native', '640x480')[steps]
                # Move to FPS row (row 2)
                menu.action('down')
                if fps != 'default':
                    menu.action('accept')
                    if fps == '0':
                        menu.action('accept')
                # Move to BACK (row 5) and accept (down 3 times: 2 -> 3 -> 4 -> 5)
                menu.action('down')
                menu.action('down')
                menu.action('down')
                menu.action('accept')
                # On main: row 1 (Options). Go up to row 0 (Start Game) and accept
                menu.action('up')
                menu.action('accept')
                self.assertEqual(menu.selection(), (expected_res, fps, 'default', 'pd2'))
                choices.add(menu.selection())
                menu.action('cancel')
                self.assertEqual(menu.result, 'launch')
        self.assertEqual(len(choices), 15)

    def test_native_disables_override_and_resolution_wraps(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            menu = m.Menu()
        # Enter options
        menu.action('down')
        menu.action('accept')
        self.assertEqual(menu.screen, 'options')
        self.assertEqual(menu.row, 0)
        # Move down to resolution (row 1)
        menu.action('down')
        self.assertEqual(menu.row, 1)
        # From 640x480 default: left -> native (4), left -> 1024x768 (3), right -> native (4), right -> 640x480 (1).
        menu.action('left')
        self.assertEqual(menu.resolution, 4)
        menu.action('left')
        self.assertEqual(menu.resolution, 3)
        menu.action('right')
        self.assertEqual(menu.resolution, 4)
        menu.action('right')
        self.assertEqual(menu.resolution, 1)

    def test_fps_toggle_off_and_row_wrap(self):
        menu = m.Menu()
        menu.action('down')
        menu.action('accept')
        self.assertEqual(menu.screen, 'options')
        menu.action('down')
        menu.action('down')
        menu.action('right')
        self.assertTrue(menu.fps)
        menu.action('left')
        self.assertFalse(menu.fps)
        menu.action('down')
        menu.action('right')
        self.assertIsNone(menu.result)  # row 3 cycles filters, never launches
        menu.action('accept')
        self.assertIsNone(menu.result)  # confirming the filter row still does not launch
        menu.action('down')
        menu.action('down')
        menu.action('accept')
        self.assertEqual(menu.screen, 'main')
        menu.action('up')
        menu.action('accept')
        self.assertEqual(menu.selection(), ('default', '0', 'default', 'pd2'))
        menu = m.Menu()
        self.assertEqual(menu.row, 0)
        self.assertEqual(menu.screen, 'main')
        menu.action('down')
        self.assertEqual(menu.row, 1)
        menu.action('down')
        self.assertEqual(menu.row, 2)
        menu.action('down')
        self.assertEqual(menu.row, 0)
        menu.action('up')
        self.assertEqual(menu.row, 2)

    def test_cancel_button_and_cancel_row(self):
        for actions in (['cancel'], ['down', 'down', 'accept']):
            menu = m.Menu()
            for action in actions:
                menu.action(action)
            self.assertEqual(menu.result, 'cancel')
            with self.assertRaises(ValueError):
                menu.selection()

    def test_filter_row_cycles_selects_and_wraps(self):
        with mock.patch.object(m, '_filter_options', return_value=['Alpha.filter', 'Beta.filter']):
            menu = m.Menu()
        menu.action('down')
        menu.action('accept')
        self.assertEqual(menu.screen, 'options')
        menu.action('down')
        menu.action('down')
        menu.action('down')
        self.assertEqual(menu.row, 3)
        self.assertEqual(menu.filter_index, 0)
        self.assertEqual(menu.filter_label, 'DEFAULT')
        menu.action('right')
        self.assertEqual((menu.filter_index, menu.filter_label), (1, 'ALPHA.FILTER'))
        menu.action('right')
        self.assertEqual((menu.filter_index, menu.filter_label), (2, 'BETA.FILTER'))
        menu.action('right')
        self.assertEqual(menu.filter_index, 0)
        menu.action('left')
        self.assertEqual(menu.filter_index, 2)
        menu.action('accept')
        self.assertEqual(menu.filter_index, 0)  # confirm cycles too
        self.assertIsNone(menu.result)
        menu.action('right')
        menu.action('right')
        menu.action('down')
        menu.action('down')
        menu.action('accept')
        self.assertEqual(menu.screen, 'main')
        menu.action('up')
        menu.action('accept')
        self.assertEqual(menu.selection(), ('default', 'default', 'Beta.filter', 'pd2'))

    def test_edition_row_cycles_and_selects_vanilla114(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            menu = m.Menu()
        menu.action('down')
        menu.action('accept')
        self.assertEqual(menu.screen, 'options')
        self.assertEqual(menu.row, 0)
        self.assertEqual(menu.edition, 'pd2')
        self.assertEqual(menu.edition_label, 'PROJECT DIABLO 2')
        menu.action('right')
        self.assertEqual(menu.edition, 'vanilla')
        self.assertEqual(menu.edition_label, 'VANILLA 1.13')
        menu.action('right')
        self.assertEqual(menu.edition, 'vanilla114')
        self.assertEqual(menu.edition_label, 'VANILLA 1.14')
        menu.action('right')
        self.assertEqual(menu.edition, 'pd2')
        menu.action('left')
        self.assertEqual(menu.edition, 'vanilla114')
        menu.action('down')
        menu.action('down')
        menu.action('down')
        menu.action('down')
        menu.action('down')
        menu.action('accept')
        self.assertEqual(menu.screen, 'main')
        menu.action('up')
        menu.action('accept')
        self.assertEqual(menu.result, 'launch')
        self.assertEqual(menu.selection(), ('800x600', 'default', 'default', 'vanilla114'))

    def test_options_perf_overlay_changeable_under_vanilla(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            menu = m.Menu()
        menu.action('down')
        menu.action('accept')
        self.assertEqual(menu.screen, 'options')
        menu.action('right')
        self.assertEqual(menu.edition, 'vanilla')
        # Row 1 (Resolution): changeable under vanilla (640x480 <-> 800x600)
        menu.action('down')
        self.assertEqual(menu.row, 1)
        menu.action('right')
        self.assertTrue(menu.resolution_changed)
        self.assertEqual(menu.current_resolution(), '800x600')
        # Row 2 (Perf Overlay): allowed under vanilla
        menu.action('down')
        self.assertEqual(menu.row, 2)
        menu.action('right')
        self.assertEqual(menu.fps, 1)
        self.assertTrue(menu.fps_changed)
        # Row 3 (Loot Filter): locked under vanilla
        menu.action('down')
        self.assertEqual(menu.row, 3)
        menu.action('right')
        self.assertEqual(menu.filter_index, 0)
        # Back to main, launch
        menu.action('down')
        menu.action('down')
        menu.action('accept')
        self.assertEqual(menu.screen, 'main')
        menu.action('up')
        menu.action('accept')
        self.assertEqual(menu.result, 'launch')
        self.assertEqual(menu.selection(), ('800x600', '1', 'default', 'vanilla'))

    def test_menu_detects_available_editions_from_gamedata(self):
        with tempfile.TemporaryDirectory() as td:
            port = Path(td)
            data = port / 'gamedata/Diablo II'
            data.mkdir(parents=True)
            for f in ('d2data.mpq', 'd2exp.mpq', 'd2char.mpq'):
                (data / f).write_bytes(b'dummy')
            (data / 'Game.exe').write_bytes(b'x' * 1_200_000)
            (data / 'ProjectD2').mkdir()
            for f in ('Game.exe', 'ProjectDiablo.dll'):
                (data / 'ProjectD2' / f).write_bytes(b'dummy')

            with mock.patch.dict(os.environ, {'PD2_PORT': str(port)}):
                menu = m.Menu()
            self.assertEqual(menu.editions, ('pd2', 'vanilla114'))
            self.assertEqual(menu.edition_labels, ('PROJECT DIABLO 2', 'VANILLA 1.14'))
            menu.action('down')
            menu.action('accept')
            self.assertEqual(menu.edition, 'pd2')
            menu.action('right')
            self.assertEqual(menu.edition, 'vanilla114')
            menu.action('right')
            self.assertEqual(menu.edition, 'pd2')

    def test_run_detects_edition_change_and_repaints_immediately(self):
        draw_calls = []
        class MockScreen:
            def draw(self, menu):
                draw_calls.append((menu.screen, menu.row, menu.edition))
            def actions(self):
                return []
        class MockPad:
            def __init__(self):
                self.seq = [[], ['down'], ['accept'], ['right'], ['cancel'], ['cancel']]
            def actions(self):
                return self.seq.pop(0) if self.seq else []

        screen = MockScreen()
        pad = MockPad()
        with mock.patch.dict(os.environ, {}, clear=True):
            m.run(screen, pad, sleep=lambda s: None)
        self.assertTrue(any(call == ('options', 0, 'vanilla') for call in draw_calls))

    def test_filter_label_is_uppercase_and_truncated(self):
        name = 'a' * 40 + '.filter'
        with mock.patch.object(m, '_filter_options', return_value=[name]):
            menu = m.Menu()
        menu.action('down')
        menu.action('accept')
        menu.action('down')
        menu.action('down')
        menu.action('down')
        menu.action('right')
        self.assertEqual(len(menu.filter_label), 16)
        self.assertEqual(menu.filter_label, menu.filter_label.upper())

    def test_inherited_filter_opens_on_last_choice_and_stale_name_falls_back(self):
        with mock.patch.object(m, '_filter_options', return_value=['Alpha.filter', 'Beta.filter']):
            with mock.patch.dict(os.environ, {'PD2_LOOT_FILTER': 'Beta.filter'}):
                menu = m.Menu()
            self.assertEqual((menu.filter_index, menu.filter_label), (2, 'BETA.FILTER'))
            with mock.patch.dict(os.environ, {'PD2_LOOT_FILTER': 'Deleted.filter'}):
                stale = m.Menu()
            self.assertEqual(stale.filter_index, 0)

    def test_filter_listing_unavailable_degrades_to_default_with_closed_event(self):
        stderr = io.StringIO()
        with mock.patch.dict(os.environ, {'PD2_PORT': '/private/port'}), \
                mock.patch.dict(sys.modules, {'layout': None}), \
                mock.patch.object(sys, 'stderr', stderr):
            self.assertEqual(m._filter_options(), [])
        line = stderr.getvalue().strip()
        event = json.loads(line.removeprefix('PD2_EVENT '))
        self.assertEqual(event, {'event': 'session_probe', 'phase': 'launch',
                                 'check': 'loot_filter', 'status': 'unavailable'})
        self.assertNotIn('/private/port', stderr.getvalue())
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(m._filter_options(), [])  # no port: silent, no event

    def test_main_emits_three_tokens_and_closed_loot_filter_event(self):
        screen = FakeScreen([['accept']])
        pad = FakePad()
        stdout, stderr = io.StringIO(), io.StringIO()
        with mock.patch.object(m, '_filter_options', return_value=['Alpha.filter']):
            result = m.main(lambda: screen, lambda: pad, stdout, stderr)
        self.assertEqual(result, 0)
        self.assertEqual(stdout.getvalue(), 'default default default pd2\n')
        events = [json.loads(line.removeprefix('PD2_EVENT '))
                  for line in stderr.getvalue().splitlines() if line.startswith('PD2_EVENT ')]
        self.assertEqual(events, [{'event': 'session_probe', 'phase': 'launch',
                                   'check': 'loot_filter', 'status': 'default', 'count': 1}])
        for line in (stdout.getvalue() + stderr.getvalue()).splitlines():
            self.assertNotIn('Alpha.filter', line)

    def test_real_r36s_codes_and_keyboard(self):
        decoder = m.KeyDecoder(m.PAD_ACTIONS)
        codes = (0x220, 0x221, 0x222, 0x223, 0x131, 0x130, 0x2c1, 0x2c0)
        self.assertEqual(decoder.feed(b''.join(event(1, c, 1) for c in codes)),
                         ['up', 'down', 'left', 'right', 'accept', 'cancel', 'accept', 'cancel'])

    def test_rg353v_standard_gamepad_hat_and_stick_inputs(self):
        actions = m.get_pad_actions()
        decoder = m.KeyDecoder(actions)
        # Standard buttons: BTN_START (0x13b), BTN_SELECT (0x13a), keyboard arrows (103, 108, 105, 106)
        std_codes = (103, 108, 105, 106, 0x13b, 0x13a, 28, 1)
        self.assertEqual(decoder.feed(b''.join(event(1, c, 1) for c in std_codes)),
                         ['up', 'down', 'left', 'right', 'accept', 'cancel', 'accept', 'cancel'])
        # D-pad Hat input: ABS_HAT0X (16), ABS_HAT0Y (17)
        self.assertEqual(decoder.feed(event(3, 16, -1)), ['left'])
        self.assertEqual(decoder.feed(event(3, 16, 0)), [])
        self.assertEqual(decoder.feed(event(3, 16, 1)), ['right'])
        self.assertEqual(decoder.feed(event(3, 16, 0)), [])
        self.assertEqual(decoder.feed(event(3, 17, -1)), ['up'])
        self.assertEqual(decoder.feed(event(3, 17, 0)), [])
        self.assertEqual(decoder.feed(event(3, 17, 1)), ['down'])
        self.assertEqual(decoder.feed(event(3, 17, 0)), [])
        # Left Analog Stick: ABS_X (0), ABS_Y (1)
        self.assertEqual(decoder.feed(event(3, 0, -20000)), ['left'])
        self.assertEqual(decoder.feed(event(3, 0, 0)), [])
        self.assertEqual(decoder.feed(event(3, 0, 20000)), ['right'])
        self.assertEqual(decoder.feed(event(3, 0, 0)), [])
        self.assertEqual(decoder.feed(event(3, 1, -20000)), ['up'])
        self.assertEqual(decoder.feed(event(3, 1, 0)), [])
        self.assertEqual(decoder.feed(event(3, 1, 20000)), ['down'])
        self.assertEqual(decoder.feed(event(3, 1, 0)), [])


    def test_partial_evdev_frames_held_repeat_unknown_and_release(self):
        decoder = m.KeyDecoder(m.PAD_ACTIONS, held=[0x131])
        self.assertEqual(decoder.feed(event(1, 0x131, 1) + event(1, 0x131, 2)), [])
        self.assertEqual(decoder.feed(event(1, 0x131, 0)), [])
        raw = event(1, 0x131, 1)
        self.assertEqual(decoder.feed(raw[:3]), [])
        self.assertEqual(decoder.feed(raw[3:]), ['accept'])
        self.assertEqual(decoder.feed(raw + event(1, 999, 1) + event(3, 0, 255)), [])
        with self.assertRaises(OSError):
            decoder.feed(event(0, 3, 0))

    def test_pad_discovery_readonly_held_state_and_fd_cleanup(self):
        mask = bytearray(96)
        mask[0x131 // 8] |= 1 << (0x131 % 8)
        fcntl = types.SimpleNamespace(ioctl=mock.Mock(return_value=bytes(mask)))
        mapper = types.SimpleNamespace(choose_pad=mock.Mock(return_value=('/dev/input/event3',)),
                                       physical_devices=mock.Mock(return_value=['synthetic']),
                                       evread=mock.Mock(return_value=123))
        with mock.patch.dict(sys.modules, {'fcntl': fcntl, 'xbox_mapper': mapper}), \
                mock.patch.object(m.os, 'O_NONBLOCK', 0x800, create=True), \
                mock.patch.object(m.os, 'open', return_value=7) as opened, \
                mock.patch.object(m.os, 'close') as closed:
            pad = m.Pad()
            self.assertEqual(pad.decoder.held, {0x131})
            self.assertEqual(opened.call_args.args[0], '/dev/input/event3')
            self.assertEqual(opened.call_args.args[1] & 3, os.O_RDONLY)
            self.assertEqual(fcntl.ioctl.call_count, 1)  # state read only; no EVIOCGRAB.
            with mock.patch.object(m.select, 'select', return_value=([7], [], [])), \
                    mock.patch.object(m.os, 'read', return_value=b''):
                with self.assertRaises(OSError):
                    pad.actions()
            pad.close()
            pad.close()
            closed.assert_called_once_with(7)
        fcntl.ioctl.side_effect = PermissionError()
        with mock.patch.dict(sys.modules, {'fcntl': fcntl, 'xbox_mapper': mapper}), \
                mock.patch.object(m.os, 'O_NONBLOCK', 0x800, create=True), \
                mock.patch.object(m.os, 'open', return_value=8), mock.patch.object(m.os, 'close') as closed:
            with self.assertRaises(PermissionError):
                m.Pad()
            closed.assert_called_once_with(8)

    def test_pad_navigation_and_keyboard_confirm(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            pad = FakePad([['down', 'accept', 'down', 'right', 'down', 'accept', 'down', 'down', 'down', 'accept', 'up']])
            screen = FakeScreen([['accept']])
            self.assertEqual(m.run(screen, pad, sleep=lambda _: None), ('800x600', '1', 'default', 'pd2'))

    def test_protocol_cancel_error_and_cleanup(self):
        launch_event = {'event': 'session_probe', 'phase': 'launch',
                        'check': 'loot_filter', 'status': 'default', 'count': 0}
        for actions, expected, output, loot_event in (
                (([['accept']], 0, 'default default default pd2\n', launch_event),
                 ([['cancel']], 10, '', None))):
            screen, pad = FakeScreen(actions), FakePad()
            stdout, stderr = io.StringIO(), io.StringIO()
            result = m.main(lambda: screen, lambda: pad, stdout, stderr)
            self.assertEqual((result, stdout.getvalue()), (expected, output))
            lines = [line for line in stderr.getvalue().splitlines() if line.startswith('PD2_EVENT ')]
            if loot_event is None:
                self.assertEqual(lines, [])
            else:
                self.assertEqual(len(lines), 1)
                self.assertEqual(json.loads(lines[0].removeprefix('PD2_EVENT ')), loot_event)
            self.assertTrue(screen.closed and pad.closed)
        screen = FakeScreen()
        stdout, stderr = io.StringIO(), io.StringIO()
        def denied():
            raise PermissionError('private input details must not leak')
        self.assertEqual(m.main(lambda: screen, denied, stdout, stderr), 1)
        self.assertEqual(stdout.getvalue(), '')
        self.assertNotIn('private input', stderr.getvalue())
        self.assertTrue(screen.closed)

    def test_direct_x11_provider_without_native_gui_dependencies(self):
        factory = mock.Mock()
        module = types.SimpleNamespace(Screen=factory)
        with mock.patch.dict(sys.modules, {'menu_x11': module}), mock.patch.dict(os.environ, {'DISPLAY': ':0'}):
            self.assertIs(m.Screen(), factory.return_value)
            factory.assert_called_once_with(m.FONT, m.LABELS, m._subtitle())
            self.assertEqual(os.environ['DISPLAY'], ':0')
        self.assertTrue(all(len(glyph) == 14 for glyph in m.FONT.values()))

    def test_subtitle_uses_layout_version_pin(self):
        fake = types.SimpleNamespace(VERSION='1.3-test.1')
        with mock.patch.dict(sys.modules, {'layout': fake}):
            self.assertEqual(m._subtitle(), 'R36S PORT 1.3-test.1')

    def test_subtitle_falls_back_without_layout(self):
        with mock.patch.dict(sys.modules, {'layout': None}):
            self.assertEqual(m._subtitle(), 'R36S PORT')
        with mock.patch.dict(sys.modules, {'layout': types.SimpleNamespace(VERSION='   ')}):
            self.assertEqual(m._subtitle(), 'R36S PORT')

    def test_ports_accept_key_is_discarded_and_never_autostarts(self):
        screen, pad = FakeScreen(), FakePad()
        screen.frames = iter([['accept'], [], [], ['cancel']])
        self.assertIsNone(m.run(screen, pad, sleep=lambda _: None))
        self.assertEqual(len(screen.draws), 1)  # Idle polls must not repaint.

    def test_idle_and_noop_input_do_not_redraw_but_changes_do(self):
        screen = FakeScreen([[], ['down'], ['down'], ['accept']])
        self.assertIsNone(m.run(screen, FakePad(), sleep=lambda _: None))
        self.assertEqual(screen.draws, [(0, 0, 0, False), (1, 0, 0, False), (2, 0, 0, False)])

    def test_input_batch_paints_only_its_final_state(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            screen = FakeScreen([['down', 'down'], ['cancel']])
            self.assertIsNone(m.run(screen, FakePad(), sleep=lambda _: None))
        self.assertEqual(screen.draws, [(0, 0, 0, False), (2, 0, 0, False)])

    def test_float_active_matrix(self):
        # 'DEFAULT' is virtual (index 0); _filter_options lists real files only.
        with mock.patch.object(m, '_filter_options',
                               return_value=('Short.filter', 'Hiim_Crafting_Sorceress_Focused.filter')):
            menu = m.Menu()
            menu.screen = 'options'
        for index, row, expected in ((0, 3, False), (1, 3, False), (2, 3, True),
                                     (2, 0, False), (2, 1, False), (2, 2, False), (2, 4, False), (2, 5, False)):
            with self.subTest(index=index, row=row):
                menu.filter_index = index
                menu.row = row
                self.assertEqual(menu.float_active(), expected)

    def test_long_filter_float_repaints_without_input(self):
        # While a long filter name is held on row 3 of options, the marquee animates: the
        # loop repaints on its timer even with no new input.
        with mock.patch.object(m, '_filter_options',
                               return_value=('Hiim_Crafting_Sorceress_Focused.filter',)), \
                mock.patch.dict(os.environ, {'PD2_LOOT_FILTER': 'Hiim_Crafting_Sorceress_Focused.filter'}):
            screen = FakeScreen([['down', 'accept'], ['down', 'down', 'down'], [], [], [], ['cancel']])
            self.assertIsNone(m.run(screen, FakePad(), sleep=lambda _: None))
        self.assertEqual(len(screen.draws), 7)  # initial + options + row 3 + 3 animation frames + cancel to main

    def test_short_filter_never_animates_repaint(self):
        # A short filter name never floats: idle polling must stay repaint-free.
        with mock.patch.object(m, '_filter_options', return_value=('Short.filter',)), \
                mock.patch.dict(os.environ, {'PD2_LOOT_FILTER': 'Short.filter'}):
            screen = FakeScreen([['down', 'accept'], ['down', 'down', 'down'], ['cancel']])
            self.assertIsNone(m.run(screen, FakePad(), sleep=lambda _: None))
        self.assertEqual(len(screen.draws), 4)

    def test_controller_mode_and_calibration_workflow(self):
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(m, 'get_config_dir', return_value=Path(td)):
                menu = m.Menu()
                # Navigate to Options
                menu.action('down')
                menu.action('accept')
                # Navigate to Controller Setup (row 4)
                for _ in range(4):
                    menu.action('down')
                menu.action('accept')
                self.assertEqual(menu.screen, 'controller')
                self.assertEqual(menu.row, 0)
                # Cycle modes
                self.assertEqual(menu.controller_mode, 'auto')
                menu.action('right')
                self.assertEqual(menu.controller_mode, 'r36s')
                menu.action('right')
                self.assertEqual(menu.controller_mode, 'retrogame')
                # In non-manual mode, row 1 is disabled: down jumps to row 2 (BACK)
                menu.action('down')
                self.assertEqual(menu.row, 2)
                menu.action('up')
                self.assertEqual(menu.row, 0)
                # Cycle modes until manual
                while menu.controller_mode != 'manual':
                    menu.action('right')
                self.assertEqual(menu.controller_mode, 'manual')
                # In manual mode, row 1 (Assign buttons) is accessible
                menu.action('down')
                self.assertEqual(menu.row, 1)
                menu.action('accept')
                self.assertEqual(menu.screen, 'calibrate')
                # Calibrate first step: A button (evdev code 304)
                self.assertIn('A', menu.calib_target_label)
                menu.record_calibration_step(304)
                # Next step is B button (evdev code 305)
                self.assertIn('B', menu.calib_target_label)
                # Skip remaining steps
                while menu.screen == 'calibrate':
                    menu.skip_calibration_step()
                self.assertEqual(menu.screen, 'controller')
                self.assertEqual(menu.controller_mode, 'manual')
                custom_file = Path(td) / 'custom_pad.json'
                self.assertTrue(custom_file.exists())
                data = json.loads(custom_file.read_text(encoding='utf-8'))
                self.assertEqual(data.get('keys', {}).get('304'), 'A')

    def test_calibration_press_and_release_advances_only_on_release(self):
        menu = m.Menu()
        menu.start_calibration()
        self.assertEqual(menu.screen, 'calibrate')
        self.assertEqual(menu.calib_step, 0)
        self.assertIn('A', menu.calib_target_label)

        # Press A down (value=1): does NOT advance step!
        menu.handle_calibration_event(1, 304, 1)
        self.assertEqual(menu.calib_step, 0)
        self.assertEqual(menu.calib_held_code, 304)

        # Autorepeat while held (value=2): does NOT advance step!
        menu.handle_calibration_event(1, 304, 2)
        self.assertEqual(menu.calib_step, 0)
        self.assertEqual(menu.calib_held_code, 304)

        # Other button press while A is held: ignored!
        menu.handle_calibration_event(1, 305, 1)
        self.assertEqual(menu.calib_step, 0)
        self.assertEqual(menu.calib_held_code, 304)

        # Release A (value=0): now it advances to step 1 (B)!
        menu.handle_calibration_event(1, 304, 0)
        self.assertEqual(menu.calib_step, 1)
        self.assertIsNone(menu.calib_held_code)
        self.assertIn('B', menu.calib_target_label)
        self.assertEqual(menu.calib_keys[304], 'A')

        # Test trigger (LT / L2): advance to LT step
        while menu.calib_step < len(m.CALIB_TARGETS) and m.CALIB_TARGETS[menu.calib_step][0] != 'LT':
            menu.skip_calibration_step()
        self.assertEqual(m.CALIB_TARGETS[menu.calib_step][0], 'LT')
        # Pull trigger (value=255): does NOT advance step!
        menu.handle_calibration_event(3, 2, 255)
        self.assertEqual(m.CALIB_TARGETS[menu.calib_step][0], 'LT')
        self.assertEqual(menu.calib_held_code, 2)
        # Release trigger (value=0): advances!
        menu.handle_calibration_event(3, 2, 0)
        self.assertEqual(menu.calib_triggers[2], 2)

    def test_calibration_stick_deflection_and_release(self):
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(m, 'get_config_dir', return_value=Path(td)):
                menu = m.Menu()
                menu.start_calibration()
                # Skip to LS_X
                while menu.calib_step < len(m.CALIB_TARGETS) and m.CALIB_TARGETS[menu.calib_step][0] != 'LS_X':
                    menu.skip_calibration_step()
                self.assertEqual(m.CALIB_TARGETS[menu.calib_step][0], 'LS_X')
                self.assertIn('L-STICK', menu.calib_target_label)

                # Initialize axis 0 center at 128
                menu.handle_calibration_event(3, 0, 128)
                self.assertEqual(menu.calib_axis_centers[0], 128)
                self.assertIsNone(menu.calib_held_code)
                self.assertEqual(m.CALIB_TARGETS[menu.calib_step][0], 'LS_X')

                # Small noise (delta < 50): no hold
                menu.handle_calibration_event(3, 0, 140)
                self.assertIsNone(menu.calib_held_code)

                # Push stick left (delta > 50): held, does not advance
                menu.handle_calibration_event(3, 0, 255)
                self.assertEqual(menu.calib_held_code, 0)
                self.assertEqual(menu.calib_held_kind, 3)
                self.assertEqual(m.CALIB_TARGETS[menu.calib_step][0], 'LS_X')

                # Release stick back to center (delta < 30): advances to LS_Y
                menu.handle_calibration_event(3, 0, 130)
                self.assertEqual(m.CALIB_TARGETS[menu.calib_step][0], 'LS_Y')
                self.assertEqual(menu.calib_axis_map[0], 0)  # ABS_X mapped to 0
                self.assertIsNone(menu.calib_held_code)

                # Calibrate LS_Y on axis 1 (ABS_Y)
                menu.handle_calibration_event(3, 1, 128)  # center
                menu.handle_calibration_event(3, 1, 0)    # push up
                self.assertEqual(menu.calib_held_code, 1)
                menu.handle_calibration_event(3, 1, 127)  # release
                self.assertEqual(m.CALIB_TARGETS[menu.calib_step][0], 'RS_X')
                self.assertEqual(menu.calib_axis_map[1], 1)  # ABS_Y mapped to 1

                # Skip rest and verify saved custom_pad.json
                while menu.screen == 'calibrate':
                    menu.skip_calibration_step()

                custom_file = Path(td) / 'custom_pad.json'
                self.assertTrue(custom_file.exists())
                data = json.loads(custom_file.read_text(encoding='utf-8'))
                self.assertEqual(data.get('axis_map', {}).get('0'), 0)
                self.assertEqual(data.get('axis_map', {}).get('1'), 1)

    def test_calibration_stick_r36s_hardware_range_and_tick_release(self):
        menu = m.Menu()
        menu.start_calibration()
        while menu.calib_step < len(m.CALIB_TARGETS) and m.CALIB_TARGETS[menu.calib_step][0] != 'LS_X':
            menu.skip_calibration_step()
        self.assertEqual(m.CALIB_TARGETS[menu.calib_step][0], 'LS_X')

        # Fake pad with R36S axis_info: (value, min, max, fuzz, flat, res)
        # axis 0: cur=0, min=-1800, max=1800, flat=32
        fake_pad = mock.Mock()
        fake_pad.axis_info.return_value = (0, -1800, 1800, 32, 32, 0)
        fake_pad.axis_val.return_value = 0

        # Push stick left (-1800)
        menu.handle_calibration_event(3, 0, -1800, pad=fake_pad)
        self.assertEqual(menu.calib_held_code, 0)
        self.assertEqual(menu.calib_held_kind, 3)
        self.assertEqual(menu.calib_held_peak, 1800)
        self.assertEqual(m.CALIB_TARGETS[menu.calib_step][0], 'LS_X')

        # Stick released to resting position (e.g. -35 due to deadband flat=32)
        menu.handle_calibration_event(3, 0, -35, pad=fake_pad)
        # Must advance to LS_Y! (Not freeze!)
        self.assertEqual(m.CALIB_TARGETS[menu.calib_step][0], 'LS_Y')
        self.assertEqual(menu.calib_axis_map[0], 0)
        self.assertIsNone(menu.calib_held_code)

        # Test tick polling release: push LS_Y (code 1)
        menu.handle_calibration_event(3, 1, -1800, pad=fake_pad)
        self.assertEqual(menu.calib_held_code, 1)
        # Hardware sends no release event, but axis_val returns 0 (spring-back)
        fake_pad.axis_val.return_value = 0
        menu.tick_calibration(pad=fake_pad)
        # Must advance to RS_X!
        self.assertEqual(m.CALIB_TARGETS[menu.calib_step][0], 'RS_X')
        self.assertEqual(menu.calib_axis_map[1], 1)
        self.assertIsNone(menu.calib_held_code)

        # Test hold safety auto-advance (stuck axis > 2.0s)
        menu.handle_calibration_event(3, 3, -1800, pad=fake_pad)
        self.assertEqual(menu.calib_held_code, 3)
        fake_pad.axis_val.return_value = -1800  # remains deflected
        menu.calib_held_start = m.time.monotonic() - 2.5
        menu.tick_calibration(pad=fake_pad)
        # Must auto-advance to RS_Y instead of freezing!
        self.assertEqual(m.CALIB_TARGETS[menu.calib_step][0], 'RS_Y')
        self.assertEqual(menu.calib_axis_map[3], 3)
        self.assertIsNone(menu.calib_held_code)

    def test_calibration_default_stick_axis_map(self):
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(m, 'get_config_dir', return_value=Path(td)):
                menu = m.Menu()
                menu.start_calibration()
                # Calibrate only A button and skip all sticks
                menu.handle_calibration_event(1, 305, 1)
                menu.handle_calibration_event(1, 305, 0)
                while menu.screen == 'calibrate':
                    menu.skip_calibration_step()
                custom_file = Path(td) / 'custom_pad.json'
                self.assertTrue(custom_file.exists())
                data = json.loads(custom_file.read_text(encoding='utf-8'))
                # Axis map must default to standard sticks 0, 1, 3, 4
                self.assertEqual(data.get('axis_map'), {'0': 0, '1': 1, '3': 3, '4': 4})
                self.assertEqual(data.get('keys', {}).get('305'), 'A')

    def test_calibration_fn_button_and_select_record_without_canceling(self):
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(m, 'get_config_dir', return_value=Path(td)):
                menu = m.Menu()
                menu.start_calibration()
                # Advance to SELECT step
                while menu.calib_step < len(m.CALIB_TARGETS) and m.CALIB_TARGETS[menu.calib_step][0] != 'SELECT':
                    menu.skip_calibration_step()
                self.assertEqual(m.CALIB_TARGETS[menu.calib_step][0], 'SELECT')
                # Press and release SELECT (0x2c0) -> records cleanly!
                menu.handle_calibration_event(1, 0x2c0, 1)
                menu.handle_calibration_event(1, 0x2c0, 0)
                self.assertEqual(menu.calib_keys[0x2c0], 'SELECT')
                self.assertEqual(m.CALIB_TARGETS[menu.calib_step][0], 'START')

                # Advance to MODE (FN) step
                while menu.calib_step < len(m.CALIB_TARGETS) and m.CALIB_TARGETS[menu.calib_step][0] != 'MODE':
                    menu.skip_calibration_step()
                self.assertEqual(m.CALIB_TARGETS[menu.calib_step][0], 'MODE')
                # Press and release FN (0x2c4) -> records cleanly and finishes!
                menu.handle_calibration_event(1, 0x2c4, 1)
                menu.handle_calibration_event(1, 0x2c4, 0)
                self.assertEqual(menu.screen, 'controller')
                custom_file = Path(td) / 'custom_pad.json'
                self.assertTrue(custom_file.exists())
                data = json.loads(custom_file.read_text(encoding='utf-8'))
                self.assertEqual(data.get('keys', {}).get(str(0x2c4)), 'MODE')

    def test_display_error_logs_only_fixed_code_and_never_selection(self):
        def failed():
            error = OSError('private cookie or driver error must not leak')
            error.code = 'not_visible'
            raise error
        stdout, stderr = io.StringIO(), io.StringIO()
        self.assertEqual(m.main(failed, FakePad, stdout, stderr), 1)
        self.assertEqual(stdout.getvalue(), '')
        self.assertIn('"check":"menu_display","status":"not_visible"', stderr.getvalue())
        self.assertIn('NOT started', stderr.getvalue())
        self.assertNotIn('private cookie', stderr.getvalue())

class LauncherContractTests(unittest.TestCase):
    """Source contracts run on Windows too; no root/DRM/game/Bash needed."""

    @classmethod
    def setUpClass(cls):
        cls.main = (ROOT / 'sdcard/ports/Project Diablo 2.sh').read_text(encoding='utf-8')
        cls.weston = (SCRIPTS / 'weston-session.sh').read_text(encoding='utf-8')

    def test_main_requests_menu_with_audio_on_by_default(self):
        self.assertIn('export PD2_START_MENU="${PD2_START_MENU:-1}"', self.main)
        self.assertIn('export PD2_AUDIO_TEST="${PD2_AUDIO_TEST:-1}"', self.main)
        self.assertIn('export PD2_AUDIO_PROBE="${PD2_AUDIO_PROBE:-0}"', self.main)

    def test_main_passes_menu_flag_after_resolving_stored_resolution(self):
        invocation = self.main[self.main.index('sudo '):] if 'sudo ' in self.main else self.main
        self.assertRegex(invocation, r'PD2_START_MENU=[^\n]+')
        self.assertLess(self.main.index('layout_get game_resolution'),
                        self.main.index('bash "$PD2_PORT/scripts/weston-session.sh"'))
        self.assertNotIn('start_menu.py', self.main)

    def test_menu_after_x11_before_any_volatile_layout_or_game(self):
        text = self.weston
        menu = text.index('start_menu.py')
        self.assertLess(text.index('stage x11_ready'), menu)
        for marker in ('stage volatile_work_prepare', '--volatile-work', 'stage volatile_work_ready',
                       'bash "$R/game-session.sh"'):
            self.assertLess(menu, text.index(marker))
        command = text[text.rfind('menu_selection=$(', 0, menu):menu]
        self.assertIn('runuser -u "$PD2_USER" --preserve-environment', command)
        self.assertNotIn('PD2_MENU_SDL', command)
        self.assertNotIn('LD_LIBRARY_PATH', command)
        block = text[text.index('stage x11_ready'):text.index('stage volatile_work_prepare')]
        self.assertIn('PD2_START_MENU', block)
        self.assertNotRegex(block, r'(?:eval|source)\s')

    def test_default_and_explicit_protocol_whitelisted(self):
        self.assertEqual(m.RESOLUTIONS, ('default', '640x480', '800x600', '1024x768', 'native'))
        self.assertEqual(m.LABELS, ('640x480', '640x480', '800x600', '1024x768', '1068x600'))
        self.assertIn('x', m.FONT)
        self.assertEqual(m.LABELS[0], '640x480')
        # Fixed four-token protocol: resolution fps loot_filter edition. Each field is
        # validated against its own closed whitelist; a fifth token fails.
        self.assertIn('read -r menu_resolution menu_fps menu_filter menu_edition menu_extra <<< "$menu_selection"', self.weston)
        self.assertIn('case "$menu_resolution" in default|640x480|800x600|1024x768|native) menu_res_ok=1;; esac', self.weston)
        self.assertIn('case "$menu_fps" in default|0|1|2|3|4) menu_fps_ok=1;; esac', self.weston)
        self.assertIn('[[ "$menu_filter" == default ]]', self.weston)
        self.assertIn(r'^[A-Za-z0-9][A-Za-z0-9._-]{0,123}\.filter$', self.weston)
        self.assertIn('-f "$PD2_PORT/filters/$menu_filter"', self.weston)
        self.assertIn('! -L "$PD2_PORT/filters/$menu_filter"', self.weston)
        self.assertIn('case "$menu_edition" in pd2|vanilla|vanilla114) menu_edition_ok=1;; esac', self.weston)
        self.assertIn('-z "$menu_extra"', self.weston)
        # The menu itself prints exactly the four whitelisted tokens.
        menu_source = (SCRIPTS / 'start_menu.py').read_text(encoding='utf-8')
        self.assertIn("print(' '.join(selection), file=stdout, flush=True)", menu_source)
        self.assertIn("return (res,", menu_source)

    def test_audio_forwarded_to_unprivileged_game_with_off_fallback(self):
        self.assertIn('ln -s "$PD2_PORT/scripts/run-game.sh" "$R/game-session.sh"', self.weston)
        self.assertIn('runuser -u "$PD2_USER" --preserve-environment -- env '
                      'PD2_AUDIO_TEST="${PD2_AUDIO_TEST:-1}" bash "$R/game-session.sh"', self.weston)

    def test_safe_log_menu_statuses_are_closed_and_no_dynamic_output_is_accepted(self):
        spec = importlib.util.spec_from_file_location('menu_safe_log', SCRIPTS / 'safe_log.py')
        logger = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(logger)
        for status in ('selected', 'failed', 'cancelled'):
            value = dict(event='session_probe', phase='launch', check='start_menu', status=status)
            self.assertEqual(logger.validate_event(value), value)
            for extra in ({'output': 'private data'}, {'selection': 'native 0'},
                          {'error': '/private/path'}, {'count': 1}):
                self.assertIsNone(logger.validate_event(dict(value, **extra)))
            self.assertIsNone(logger.validate_event(dict(value, phase='game')))
        for status in ('fallback', 'success', 'native 0', 'private data', '', None):
            self.assertIsNone(logger.validate_event(dict(event='session_probe', phase='launch',
                                                        check='start_menu', status=status)))

    def test_failure_and_cancel_cannot_mutate_resolved_flags(self):
        block = self.weston.split('stage x11_ready', 1)[1].split('stage volatile_work_prepare', 1)[0]
        cancel = block.split('if [[ "$menu_rc" == 10 ]]; then', 1)[1].split('fi', 1)[0]
        self.assertIn('exit 0', cancel)
        self.assertIn('"status":"cancelled"', cancel)
        self.assertNotIn('export ', cancel)
        self.assertLess(block.index('"$menu_rc" == 10'), block.index('menu_valid=0'))
        self.assertIn('if [[ "$menu_rc" == 0 ]]; then', block)
        self.assertIn('if [[ "$menu_valid" == 1 ]]; then', block)
        selected, fallback = re.split(r'\n\s*else\s*\n',
                                      block.split('if [[ "$menu_valid" == 1 ]]; then', 1)[1], maxsplit=1)
        self.assertIn('[[ "$menu_resolution" == default ]] || export PD2_GAME_RESOLUTION="$menu_resolution"', selected)
        self.assertIn('[[ "$menu_fps" == default ]] || export PD2_FPS="$menu_fps"', selected)
        self.assertIn('export PD2_LOOT_FILTER="$menu_filter"', selected)
        self.assertIn('"check":"loot_filter"', selected)
        self.assertIn('"status":"selected"', selected)
        self.assertIn('"status":"failed"', fallback)
        self.assertIn('>&2', fallback)
        self.assertNotIn('"status":"selected"', fallback)
        self.assertNotIn('export ', fallback)
        self.assertNotIn('PD2_LOOT_FILTER', fallback)
        self.assertIn('exit 1', fallback)
        # No accidental resetting of other launch modes or persistent settings.
        assigned = re.findall(r'\b(PD2_[A-Z_]+)=', block)
        self.assertCountEqual(assigned, ['PD2_EDITION', 'PD2_GAME_RESOLUTION', 'PD2_FPS', 'PD2_LOOT_FILTER', 'PD2_EDITION'])
        self.assertNotIn('settings.json', block)

    def test_confirmed_menu_saves_settings_and_private_launcher_reads_perf_overlay(self):
        self.assertIn('save_menu_settings=1', self.weston)
        self.assertIn('--volatile-work ${save_flag:+"$save_flag"}', self.weston)
        private = (ROOT / 'sdcard/ports/projectdiablo2/private-launcher.sh').read_text(encoding='utf-8')
        self.assertIn('perf_overlay) export PD2_FPS="$layout_value";;', private)
        # PortMaster mod_*.txt hooks (e.g. mangohud_portmaster.env) must not override PD2_FPS.
        get_controls_pos = private.index('get_controls || error unsupported_runtime')
        layout_pos = private.index('layout.py" --port "$PD2_PORT" --state "$PD2_STATE"')
        restore_block = private[get_controls_pos:layout_pos]
        self.assertIn('if [[ -n $_pd2_caller_fps ]]; then export PD2_FPS="$_pd2_caller_fps"; else unset PD2_FPS; fi', restore_block)
        self.assertIn('unset MANGOHUD MANGOHUD_CONFIGFILE PERFOVERLAY_ENABLED PERFOVERLAY_LEVEL', restore_block)
        self.assertIn('display_resolution) export PD2_DISPLAY_RESOLUTION="$layout_value";;', private)
        self.assertIn('PD2_DISPLAY_RESOLUTION="$PD2_DISPLAY_RESOLUTION"', private)
        self.assertIn('DISPLAY_WIDTH', private)
        self.assertIn('DISPLAY_HEIGHT', private)


@unittest.skipUnless(sys.platform.startswith('linux') or os.environ.get('PD2_TEST_BASH'),
                     'Real Bash harness requires Linux or explicit PD2_TEST_BASH')
class LauncherShellTests(unittest.TestCase):
    """Execute only the real menu branch, with runuser replaced by a fake.

    Cross-platform source contracts above remain active without this harness.
    No compositor, mount, sudo, game, DRM, audio or input device is opened.
    """

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='pd2-menu-harness-'))
        self.addCleanup(shutil.rmtree, self.tmp)
        self.port = self.tmp / 'port'
        filters = self.port / 'filters'
        filters.mkdir(parents=True)
        (filters / 'Good.filter').write_text('synthetic filter body\n', encoding='utf-8')
        self.symlink_filter = None
        try:
            (filters / 'Link.filter').symlink_to('Good.filter')
            self.symlink_filter = 'Link.filter'
        except OSError:
            pass

    def test_selected_failure_cancel_and_disabled_environment(self):
        text = (SCRIPTS / 'weston-session.sh').read_text(encoding='utf-8')
        block = text.split('stage x11_ready', 1)[1].split('stage volatile_work_prepare', 1)[0]
        harness = ('set -u\n'
                   'runuser() { printf "%s" "$MOCK_RESULT"; return "$MOCK_RC"; }\n'
                   + block + '\nprintf "FLAGS:%s|%s|%s|%s|%s|%s|SAVE:%s\\n" '
                   '"$PD2_GAME_RESOLUTION" "$PD2_FPS" "$PD2_LOOT_FILTER" "$PD2_INPUT_MODE" '
                   '"$PD2_CONTROLLER_TEST" "$PD2_AUDIO_TEST" "$save_menu_settings"\n'
                   'printf "VOLATILE_AND_GAME_WOULD_START\\n"\n')
        cases = []
        for resolution in m.RESOLUTIONS:
            for fps in ('default', '0', '1', '2', '3', '4'):
                # Current menu has three fields; audio is not a menu choice.
                cases.append((resolution + ' ' + fps + ' default', '0', '1', 'selected',
                              '1024x768' if resolution == 'default' else resolution,
                              '1' if fps == 'default' else fps, 'default', '0'))
        # A named filter is accepted only for a regular, non-symlink file that
        # actually exists under the port's filters directory (real temp port).
        cases.append(('default default Good.filter', '0', '1', 'selected',
                      '1024x768', '1', 'Good.filter', '0'))
        for result, rc in (('', '1'), ('native 0 default', '1'), ('', '0'),
                           ('native 0 1\necho BAD', '0'), ('$(echo BAD) 1 1', '0'),
                           ('default 2 0', '0'), ('native  0 1', '0'), (' native 0 1', '0'),
                           ('native', '0'), ('default default extra', '0'), ('native 0 2', '0'),
                           ('native 0 ON', '0'), ('native 0 1 extra', '0'),
                           ('native\t0 1', '0'), ('native 0 1 ', '0'),
                           ('1068x600 0 0', '0'), ('native 0 1;echo BAD', '0'),
                           ('default default Missing.filter', '0'),
                           ('default default ..%2fBad.filter', '0'),
                           ('native 0 Good.filter extra', '0')):
            cases.append((result, rc, '1', 'failed', None, None, None, None))
        if self.symlink_filter:
            cases.append(('default default ' + self.symlink_filter, '0', '1',
                          'failed', None, None, None, None))
        cases += [('native 0 default', '0', '0', None, '1024x768', '1', 'default', '0'),
                  ('native 0 default', '10', '1', 'cancelled', None, None, None, None)]
        for result, rc, enabled, status, resolution, fps, filter_name, audio in cases:
            with self.subTest(result=result, rc=rc, enabled=enabled):
                env = dict(os.environ, MOCK_RESULT=result, MOCK_RC=rc, PD2_START_MENU=enabled,
                           PD2_GAME_RESOLUTION='1024x768', PD2_FPS='1', PD2_LOOT_FILTER='default',
                           PD2_INPUT_MODE='mapper', PD2_CONTROLLER_TEST='1', PD2_AUDIO_TEST='0',
                           PD2_USER='fake-user', PD2_PORT=str(self.port), W='/fake/weston',
                           CRUSTY_LIBSDL='/fake/resolved64.so')
                process = subprocess.run([os.environ.get('PD2_TEST_BASH', 'bash'), '-c', harness],
                                         env=env, capture_output=True, text=True)
                self.assertEqual(process.returncode, 1 if status == 'failed' else 0, process.stderr)
                if status == 'selected':
                    loot_status = 'selected' if filter_name != 'default' else 'default'
                    self.assertIn('"check":"loot_filter","status":"' + loot_status + '"', process.stdout)
                if status:
                    self.assertIn('"status":"' + status + '"', process.stdout)
                else:
                    self.assertNotIn('"check":"start_menu"', process.stdout)
                if status in ('cancelled', 'failed'):
                    self.assertNotIn('FLAGS:', process.stdout)
                    self.assertNotIn('VOLATILE_AND_GAME_WOULD_START', process.stdout)
                else:
                    expected_save = '1' if status == 'selected' else '0'
                    self.assertIn('FLAGS:' + resolution + '|' + fps + '|' + filter_name + '|mapper|1|' + audio + '|SAVE:' + expected_save,
                                  process.stdout)
                    self.assertIn('VOLATILE_AND_GAME_WOULD_START', process.stdout)
                self.assertNotIn('\nBAD', process.stdout)


if __name__ == '__main__':
    unittest.main()
