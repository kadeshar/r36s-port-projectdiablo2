"""Comprehensive tests for on-screen keyboard (OSK) logic, uinput, and X11 wire."""
import contextlib
import io
from pathlib import Path
import struct
import sys
import types
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'sdcard/ports/projectdiablo2/scripts'
sys.path.insert(0, str(SCRIPTS))

# Platform mocking for Windows test runner
if sys.platform != 'linux':
    with mock.patch.dict(sys.modules, {'fcntl': types.ModuleType('fcntl')}):
        import osk
    osk.fcntl.ioctl = mock.Mock()
else:
    import osk


class OSKModelTests(unittest.TestCase):
    def test_initial_state_and_truncation(self):
        m = osk.OSKModel('PaladinWarriorExtraLong', max_len=15)
        self.assertEqual(m.text, 'PaladinWarriorE')
        self.assertEqual(len(m.text), 15)
        self.assertEqual(m.row, 1)
        self.assertEqual(m.col, 0)
        self.assertTrue(m.caps)
        self.assertIsNone(m.result)

    def test_grid_navigation_and_wrapping(self):
        m = osk.OSKModel()
        m.row, m.col = 0, 0
        # Up from row 0 wraps to bottom row
        m.action('up')
        self.assertEqual(m.row, len(osk.KEYBOARD_ROWS) - 1)
        # Down wraps back to 0
        m.action('down')
        self.assertEqual(m.row, 0)
        # Left from col 0 wraps to end of row
        m.action('left')
        self.assertEqual(m.col, len(osk.KEYBOARD_ROWS[0]) - 1)
        # Right wraps back to 0
        m.action('right')
        self.assertEqual(m.col, 0)

    def test_navigation_row_clamping(self):
        m = osk.OSKModel()
        m.row = 0
        m.col = 11  # Last key of row 0
        m.action('down')  # Row 1 has only 10 keys (cols 0..9)
        self.assertEqual(m.row, 1)
        self.assertEqual(m.col, 9)

    def test_typing_letters_with_caps_toggle(self):
        m = osk.OSKModel()
        # Row 1, col 0 is 'Q'
        m.row, m.col = 1, 0
        m.caps = True
        m.action('select')
        self.assertEqual(m.text, 'Q')

        # Toggle caps
        m.action('caps')
        self.assertFalse(m.caps)
        # Row 2, col 0 is 'A' -> lowercase 'a'
        m.row, m.col = 2, 0
        m.action('select')
        self.assertEqual(m.text, 'Qa')

    def test_backspace_and_space_actions(self):
        m = osk.OSKModel('Hero')
        m.action('backspace')
        self.assertEqual(m.text, 'Her')
        m.action('space')
        self.assertEqual(m.text, 'Her ')
        # Direct key actions
        m.press_key('BKSP')
        self.assertEqual(m.text, 'Her')
        m.press_key('CLEAR')
        self.assertEqual(m.text, '')

    def test_confirm_validation(self):
        m = osk.OSKModel('')
        # Too short: rejected
        m.action('confirm')
        self.assertIsNone(m.result)
        self.assertIn('TOO SHORT', m.message)

        # 1 char: rejected
        m.text = 'A'
        m.action('confirm')
        self.assertIsNone(m.result)
        self.assertIn('TOO SHORT', m.message)

        # 2+ chars: accepted
        m.text = 'Diablo'
        m.action('confirm')
        self.assertEqual(m.result, 'confirm')

    def test_cancel_action(self):
        m = osk.OSKModel('Hero')
        m.action('cancel')
        self.assertEqual(m.result, 'cancel')


class OSKFontTests(unittest.TestCase):
    def test_font_glyphs_validity(self):
        self.assertIn(' ', osk.FONT)
        for char, hex_rows in osk.FONT.items():
            self.assertEqual(len(hex_rows), 14, f'Char {char!r} does not have 14 hex digits')
            for r in range(7):
                val = int(hex_rows[r * 2:r * 2 + 2], 16)
                self.assertTrue(0 <= val <= 31, f'Char {char!r} row {r} out of 5-bit range: {val}')

    def test_font_contains_all_ascii_alphanumeric(self):
        for c in 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_ ':
            self.assertIn(c, osk.FONT)


class OSKVirtualKeyboardTests(unittest.TestCase):
    def test_char_map_covers_all_alphanumerics(self):
        for c in 'abcdefghijklmnopqrstuvwxyz':
            self.assertIn(c, osk.CHAR_MAP)
            code, shift = osk.CHAR_MAP[c]
            self.assertFalse(shift)
            self.assertIn(code, osk.ALL_VIRTUAL_KEYS)
        for c in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ':
            self.assertIn(c, osk.CHAR_MAP)
            code, shift = osk.CHAR_MAP[c]
            self.assertTrue(shift)
            self.assertIn(code, osk.ALL_VIRTUAL_KEYS)
        for c in '0123456789':
            self.assertIn(c, osk.CHAR_MAP)
        self.assertIn('-', osk.CHAR_MAP)
        self.assertIn('_', osk.CHAR_MAP)

    def test_create_and_destroy_virtual_keyboard(self):
        with mock.patch.object(osk.os, 'O_NONBLOCK', 2048, create=True), \
             mock.patch.object(osk.os, 'open', return_value=42) as mock_open, \
             mock.patch.object(osk.os, 'write', side_effect=lambda fd, data: len(data)) as mock_write, \
             mock.patch.object(osk.os, 'close') as mock_close, \
             mock.patch.object(osk.fcntl, 'ioctl', return_value=0) as mock_ioctl:
            fd = osk.create_virtual_keyboard()
            self.assertEqual(fd, 42)
            mock_open.assert_called_once_with('/dev/uinput', mock.ANY)
            mock_write.assert_called_once()
            self.assertEqual(len(mock_write.call_args[0][1]), 1116)

            osk.destroy_virtual_keyboard(fd)
            mock_close.assert_called_once_with(42)

    def test_type_string_event_sequence(self):
        emitted = []
        def fake_write(fd, data):
            for entry in osk.EVENT.iter_unpack(data):
                emitted.append((entry[2], entry[3], entry[4]))  # kind, code, value
            return len(data)

        with mock.patch.object(osk.os, 'write', side_effect=fake_write):
            osk.type_string(10, 'A1', send_enter=True, sleep_fn=lambda s: None)

        # 'A' = Shift down, Key_A down, Key_A up, Shift up
        # '1' = Key_1 down, Key_1 up
        # Enter = Key_Enter down, Key_Enter up
        keys = [(code, val) for kind, code, val in emitted if kind == osk.EV_KEY]
        expected = [
            (osk.KEY_LEFTSHIFT, 1),
            (osk.KEY_A, 1),
            (osk.KEY_A, 0),
            (osk.KEY_LEFTSHIFT, 0),
            (osk.KEY_1, 1),
            (osk.KEY_1, 0),
            (osk.KEY_ENTER, 1),
            (osk.KEY_ENTER, 0),
        ]
        self.assertEqual(keys, expected)

    def test_screen_type_string_xtest(self):
        screen = osk.OSKScreen.__new__(osk.OSKScreen)
        screen._xtest_opcode = 130
        screen.window = 1234
        screen._keysym_map = {
            ord('H'): (43, True),
            ord('i'): (31, False),
        }
        screen._shift_code = 50
        screen._enter_code = 36
        requests = []
        screen._request = lambda opcode, detail, body, deadline: requests.append((opcode, detail, body))
        screen._roundtrip = lambda deadline: None

        ok = screen.type_string('Hi', send_enter=True, delay=0, sleep_fn=lambda s: None)
        self.assertTrue(ok)
        # First request must be UnmapWindow (opcode 10)
        self.assertEqual(requests[0][0], 10)
        # Subsequent requests must be XTEST (opcode 130, detail 2)
        xtest_reqs = [r for r in requests if r[0] == 130]
        # 'H' needs shift: Shift down, H down, H up, Shift up
        # 'i': i down, i up
        # Enter: enter down, enter up
        # Total = 8 fake input requests
        self.assertEqual(len(xtest_reqs), 8)
        self.assertTrue(all(r[1] == 2 for r in xtest_reqs))

    def test_type_via_libxtst_mock(self):
        mock_x11 = mock.MagicMock()
        mock_xtst = mock.MagicMock()
        mock_x11.XOpenDisplay.return_value = 0x1000
        mock_x11.XStringToKeysym.return_value = 0xffe1
        mock_x11.XKeysymToKeycode.side_effect = lambda dpy, sym: 50 if sym == 0xffe1 else 38

        with mock.patch('ctypes.CDLL', side_effect=[mock_x11, mock_xtst]):
            ok = osk.type_via_libxtst('A', send_enter=False, delay=0, sleep_fn=lambda s: None)
        self.assertTrue(ok)
        mock_x11.XOpenDisplay.assert_called_once()
        mock_xtst.XTestFakeKeyEvent.assert_called()
        mock_x11.XCloseDisplay.assert_called_once_with(0x1000)



class OSKHotkeyTests(unittest.TestCase):
    def test_single_fn_menu_does_not_trigger_to_prevent_map_collision(self):
        # Single Fn/Menu must NOT trigger keyboard so Automap in-game remains fully functional
        self.assertFalse(osk.is_hotkey(osk.EV_KEY, osk.PAD_MENU, 1, set()))
        self.assertFalse(osk.is_hotkey(osk.EV_KEY, osk.PAD_MENU, 0, set()))

    def test_select_plus_x_combo(self):
        held = {osk.PAD_SELECT}
        self.assertTrue(osk.is_hotkey(osk.EV_KEY, osk.PAD_X, 1, held))
        self.assertTrue(osk.is_hotkey(osk.EV_KEY, osk.PAD_SELECT, 1, {osk.PAD_X}))
        self.assertFalse(osk.is_hotkey(osk.EV_KEY, osk.PAD_X, 1, set()))

    def test_fn_plus_x_combo(self):
        held = {osk.PAD_MENU}
        self.assertTrue(osk.is_hotkey(osk.EV_KEY, osk.PAD_X, 1, held))
        self.assertTrue(osk.is_hotkey(osk.EV_KEY, osk.PAD_MENU, 1, {osk.PAD_X}))

    def test_l3_plus_r3_combo(self):
        held = {osk.PAD_L3}
        self.assertTrue(osk.is_hotkey(osk.EV_KEY, osk.PAD_R3, 1, held))
        held2 = {osk.PAD_R3}
        self.assertTrue(osk.is_hotkey(osk.EV_KEY, osk.PAD_L3, 1, held2))

    def test_select_plus_dpad_down_combo(self):
        held = {osk.PAD_SELECT}
        self.assertTrue(osk.is_hotkey(osk.EV_KEY, osk.PAD_DOWN, 1, held))
        self.assertTrue(osk.is_hotkey(osk.EV_KEY, osk.PAD_SELECT, 1, {osk.PAD_DOWN}))

    def test_regular_button_returns_false(self):
        self.assertFalse(osk.is_hotkey(osk.EV_KEY, osk.PAD_A, 1, set()))
        self.assertFalse(osk.is_hotkey(osk.EV_ABS, osk.ABS_X, 1000, set()))


class OSKPadReaderTests(unittest.TestCase):
    def test_button_press_decoding(self):
        events = [
            (osk.EV_KEY, osk.PAD_UP, 1),
            (osk.EV_KEY, osk.PAD_UP, 0),  # Release ignored
            (osk.EV_KEY, osk.PAD_A, 1),
            (osk.EV_KEY, osk.PAD_START, 1),
        ]
        raw = b''.join(osk.EVENT.pack(0, 0, *e) for e in events)
        reader = osk.PadReader(fd=5)
        with mock.patch.object(osk.select, 'select', return_value=([5], [], [])), \
             mock.patch.object(osk.os, 'read', return_value=raw):
            actions = reader.actions()
        self.assertEqual(actions, ['up', 'select', 'confirm'])

    def test_analog_stick_debouncing(self):
        events = [
            (osk.EV_ABS, osk.ABS_X, 20000),  # Move right
            (osk.EV_ABS, osk.ABS_X, 25000),  # Still right -> no duplicate action
            (osk.EV_ABS, osk.ABS_X, 0),      # Center deadzone -> rearmed
            (osk.EV_ABS, osk.ABS_X, -20000), # Move left
        ]
        raw = b''.join(osk.EVENT.pack(0, 0, *e) for e in events)
        reader = osk.PadReader(fd=5)
        with mock.patch.object(osk.select, 'select', return_value=([5], [], [])), \
             mock.patch.object(osk.os, 'read', return_value=raw):
            actions = reader.actions()
        self.assertEqual(actions, ['right', 'left'])


if __name__ == '__main__':
    unittest.main()
