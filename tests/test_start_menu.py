"""Synthetic menu/input/launcher tests: never open DRM, pad or run a game."""
import importlib.util
import io
import os
import re
from pathlib import Path
import struct
import subprocess
import sys
import types
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'sdcard/ports/projectdiablo2/scripts'
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
        self.draws.append((menu.row, menu.resolution, menu.fps))

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
        self.assertEqual((menu.row, menu.resolution, menu.fps, menu.result), (2, 0, False, None))
        with self.assertRaises(ValueError):
            menu.selection()
        for action in ('accept',):
            menu.action(action)
        self.assertEqual(menu.selection(), ('default', 'default'))

    def test_inherited_values_are_displayed_without_overriding_selection(self):
        with mock.patch.dict(os.environ, {'PD2_GAME_RESOLUTION': '1024x768', 'PD2_FPS': '1'}):
            menu = m.Menu()
        self.assertEqual((menu.inherited_resolution, menu.inherited_fps), ('1024x768', True))
        menu.action('accept')
        self.assertEqual(menu.selection(), ('default', 'default'))

    def test_first_fps_toggle_inverts_the_inherited_setting(self):
        with mock.patch.dict(os.environ, {'PD2_FPS': '1'}):
            menu = m.Menu()
        menu.action('up')
        menu.action('accept')
        self.assertFalse(menu.fps)
        menu.action('down')
        menu.action('accept')
        self.assertEqual(menu.selection(), ('default', '0'))

    def test_invalid_inherited_resolution_uses_safe_display_default(self):
        with mock.patch.dict(os.environ, {'PD2_GAME_RESOLUTION': 'invalid', 'PD2_FPS': 'invalid'}):
            menu = m.Menu()
        self.assertEqual((menu.inherited_resolution, menu.inherited_fps), ('800x600', False))

    def test_all_12_resolution_fps_choices(self):
        choices = set()
        for index, resolution in enumerate(m.RESOLUTIONS):
            for fps in ('default', '0', '1'):
                menu = m.Menu()
                for _ in range(2):
                    menu.action('up')
                for _ in range(index):
                    menu.action('right')
                menu.action('down')
                if fps != 'default':
                    menu.action('accept')
                    if fps == '0':
                        menu.action('accept')
                menu.action('down')
                menu.action('accept')
                self.assertEqual(menu.selection(), (resolution, fps))
                choices.add(menu.selection())
                menu.action('cancel')
                self.assertEqual(menu.result, 'launch')
        self.assertEqual(len(choices), 12)

    def test_native_disables_override_and_resolution_wraps(self):
        menu = m.Menu()
        menu.action('up')
        menu.action('up')
        menu.action('left')
        self.assertEqual(menu.resolution, 3)
        menu.action('right')
        self.assertEqual(menu.resolution, 0)
        menu.action('accept')
        self.assertEqual(menu.resolution, 1)
        for _ in range(3):
            menu.action('right')
        self.assertEqual(menu.resolution, 0)

    def test_fps_toggle_off_and_row_wrap(self):
        menu = m.Menu()
        menu.action('up')
        menu.action('right')
        self.assertTrue(menu.fps)
        menu.action('left')
        self.assertFalse(menu.fps)
        menu.action('down')
        menu.action('right')
        self.assertIsNone(menu.result)  # only accept launches
        menu.action('accept')
        self.assertEqual(menu.selection(), ('default', '0'))
        menu = m.Menu()
        menu.action('down')
        self.assertEqual(menu.row, 3)
        menu.action('down')
        self.assertEqual(menu.row, 0)
        menu.action('up')
        self.assertEqual(menu.row, 3)

    def test_cancel_button_and_cancel_row(self):
        for actions in (['cancel'], ['down', 'accept']):
            menu = m.Menu()
            for action in actions:
                menu.action(action)
            self.assertEqual(menu.result, 'cancel')
            with self.assertRaises(ValueError):
                menu.selection()

    def test_real_r36s_codes_and_keyboard(self):
        decoder = m.KeyDecoder(m.PAD_ACTIONS)
        codes = (0x220, 0x221, 0x222, 0x223, 0x131, 0x130, 0x2c1, 0x2c0)
        self.assertEqual(decoder.feed(b''.join(event(1, c, 1) for c in codes)),
                         ['up', 'down', 'left', 'right', 'accept', 'cancel', 'accept', 'cancel'])


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
        pad = FakePad([['up', 'up', 'right', 'right', 'down', 'accept', 'down']])
        screen = FakeScreen([['accept']])
        self.assertEqual(m.run(screen, pad, sleep=lambda _: None), ('800x600', '1'))

    def test_protocol_cancel_error_and_cleanup(self):
        for actions, expected, output in (([['accept']], 0, 'default default\n'),
                                          ([['cancel']], 10, '')):
            screen, pad = FakeScreen(actions), FakePad()
            stdout, stderr = io.StringIO(), io.StringIO()
            result = m.main(lambda: screen, lambda: pad, stdout, stderr)
            self.assertEqual((result, stdout.getvalue(), stderr.getvalue()), (expected, output, ''))
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
            factory.assert_called_once_with(m.FONT, m.LABELS)
            self.assertEqual(os.environ['DISPLAY'], ':0')
        self.assertTrue(all(len(glyph) == 14 for glyph in m.FONT.values()))

    def test_ports_accept_key_is_discarded_and_never_autostarts(self):
        screen, pad = FakeScreen(), FakePad()
        screen.frames = iter([['accept'], [], [], ['cancel']])
        self.assertIsNone(m.run(screen, pad, sleep=lambda _: None))
        self.assertEqual(len(screen.draws), 1)  # Idle polls must not repaint.

    def test_idle_and_noop_input_do_not_redraw_but_changes_do(self):
        screen = FakeScreen([[], [], ['left'], ['up'], [], ['accept'], [], ['cancel']])
        self.assertIsNone(m.run(screen, FakePad(), sleep=lambda _: None))
        self.assertEqual(screen.draws, [(2, 0, False), (1, 0, False), (1, 0, True)])

    def test_input_batch_paints_only_its_final_state(self):
        screen = FakeScreen([['up', 'up', 'right', 'down'], ['cancel']])
        self.assertIsNone(m.run(screen, FakePad(), sleep=lambda _: None))
        self.assertEqual(screen.draws, [(2, 0, False), (1, 1, False)])

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
        self.assertEqual(m.RESOLUTIONS, ('default', 'native', '800x600', '1024x768'))
        self.assertEqual(len(m.LABELS), 4)
        self.assertEqual(m.LABELS[0], '800X600')
        for resolution in m.RESOLUTIONS:
            for fps in ('default', '0', '1'):
                self.assertIn("'" + resolution + ' ' + fps + "'", self.weston)
        protocol = self.weston.split('case "$menu_selection" in', 1)[1].split('esac', 1)[0]
        expected = {resolution + ' ' + fps for resolution in m.RESOLUTIONS
                    for fps in ('default', '0', '1')}
        self.assertEqual(set(re.findall(r"'([^']+)'", protocol)), expected)
        self.assertEqual(len(re.findall(r"'([^']+)'", protocol)), 12)
        self.assertIn('menu_resolution="${menu_selection%% *}"', self.weston)
        self.assertIn('menu_fps="${menu_selection#* }"', self.weston)

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
        self.assertIn('"status":"selected"', selected)
        self.assertIn('"status":"failed"', fallback)
        self.assertIn('>&2', fallback)
        self.assertNotIn('"status":"selected"', fallback)
        self.assertNotIn('export ', fallback)
        self.assertIn('exit 1', fallback)
        # No accidental resetting of other launch modes or persistent settings.
        assigned = re.findall(r'\b(PD2_[A-Z_]+)=', block)
        self.assertCountEqual(assigned, ['PD2_GAME_RESOLUTION', 'PD2_FPS'])
        self.assertNotIn('settings.json', block)


@unittest.skipUnless(sys.platform.startswith('linux') or os.environ.get('PD2_TEST_BASH'),
                     'Real Bash harness requires Linux or explicit PD2_TEST_BASH')
class LauncherShellTests(unittest.TestCase):
    """Execute only the real menu branch, with runuser replaced by a fake.

    Cross-platform source contracts above remain active without this harness.
    No compositor, mount, sudo, game, DRM, audio or input device is opened.
    """

    def test_selected_failure_cancel_and_disabled_environment(self):
        text = (SCRIPTS / 'weston-session.sh').read_text(encoding='utf-8')
        block = text.split('stage x11_ready', 1)[1].split('stage volatile_work_prepare', 1)[0]
        harness = ('set -u\n'
                   'runuser() { printf "%s" "$MOCK_RESULT"; return "$MOCK_RC"; }\n'
                   + block + '\nprintf "FLAGS:%s|%s|%s|%s|%s\\n" '
                   '"$PD2_GAME_RESOLUTION" "$PD2_FPS" "$PD2_INPUT_MODE" '
                   '"$PD2_CONTROLLER_TEST" "$PD2_AUDIO_TEST"\n'
                   'printf "VOLATILE_AND_GAME_WOULD_START\\n"\n')
        cases = []
        for resolution in m.RESOLUTIONS:
            for fps in ('default', '0', '1'):
                # Current menu has two fields; audio is not a menu choice.
                cases.append((resolution + ' ' + fps, '0', '1', 'selected',
                              '1024x768' if resolution == 'default' else resolution,
                              '1' if fps == 'default' else fps, '0'))
        for result, rc in (('', '1'), ('native 0 1', '1'), ('', '0'),
                           ('native 0 1\necho BAD', '0'), ('$(echo BAD) 1 1', '0'),
                           ('default 2 0', '0'), ('native  0 1', '0'), (' native 0 1', '0'),
                           ('native', '0'), ('default default extra', '0'), ('native 0 2', '0'),
                           ('native 0 ON', '0'), ('native 0 1 extra', '0'),
                           ('native\t0 1', '0'), ('native 0 1 ', '0'),
                           ('1068x600 0 0', '0'), ('native 0 1;echo BAD', '0')):
            cases.append((result, rc, '1', 'failed', None, None, None))
        cases += [('native 0 1', '0', '0', None, '1024x768', '1', '0'),
                  ('native 0 1', '10', '1', 'cancelled', None, None, None)]
        for result, rc, enabled, status, resolution, fps, audio in cases:
            with self.subTest(result=result, rc=rc, enabled=enabled):
                env = dict(os.environ, MOCK_RESULT=result, MOCK_RC=rc, PD2_START_MENU=enabled,
                           PD2_GAME_RESOLUTION='1024x768', PD2_FPS='1', PD2_INPUT_MODE='mapper',
                           PD2_CONTROLLER_TEST='1', PD2_AUDIO_TEST='0', PD2_USER='fake-user',
                           PD2_PORT='/fake/path with spaces', W='/fake/weston', CRUSTY_LIBSDL='/fake/resolved64.so')
                process = subprocess.run([os.environ.get('PD2_TEST_BASH', 'bash'), '-c', harness],
                                         env=env, capture_output=True, text=True)
                self.assertEqual(process.returncode, 1 if status == 'failed' else 0, process.stderr)
                if status:
                    self.assertIn('"status":"' + status + '"', process.stdout)
                else:
                    self.assertNotIn('"check":"start_menu"', process.stdout)
                if status in ('cancelled', 'failed'):
                    self.assertNotIn('FLAGS:', process.stdout)
                    self.assertNotIn('VOLATILE_AND_GAME_WOULD_START', process.stdout)
                else:
                    self.assertIn('FLAGS:' + resolution + '|' + fps + '|mapper|1|' + audio, process.stdout)
                    self.assertIn('VOLATILE_AND_GAME_WOULD_START', process.stdout)
                self.assertNotIn('\nBAD', process.stdout)


if __name__ == '__main__':
    unittest.main()
