#!/usr/bin/env python3
"""On-screen keyboard for Diablo II character creation on R36S.

Direct CORE X11 client (DISPLAY=:0) with uinput keyboard injection.
Zero external GUI dependencies (no Xlib, pygame, Tkinter, or SDL video).
Displays an authentic Diablo II themed virtual keyboard navigable via
physical gamepad (D-Pad, sticks, buttons) or X11 keyboard.
"""
import contextlib
try:
    import fcntl
except ImportError:
    fcntl = None
import json
import os
from pathlib import Path
import select
import signal
import socket
import stat
import struct
import sys
import time

try:
    import x11_probe
except ImportError:
    x11_probe = None

# Linux input event constants
EV_SYN, EV_KEY, EV_ABS = 0, 1, 3
SYN_REPORT = 0
ABS_X, ABS_Y = 0, 1
KEY_MAX = 0x2ff
BUS_USB = 3

UI_SET_EVBIT = 0x40045564
UI_SET_KEYBIT = 0x40045565
UI_DEV_CREATE = 0x5501
UI_DEV_DESTROY = 0x5502

EVENT = struct.Struct('@llHHi')
EV_SIZE = EVENT.size

# Keycodes (linux/input-event-codes.h)
KEY_ESC = 1
KEY_1, KEY_2, KEY_3, KEY_4, KEY_5, KEY_6, KEY_7, KEY_8, KEY_9, KEY_0 = range(2, 12)
KEY_MINUS = 12
KEY_EQUAL = 13
KEY_BACKSPACE = 14
KEY_TAB = 15
KEY_Q, KEY_W, KEY_E, KEY_R, KEY_T, KEY_Y, KEY_U, KEY_I, KEY_O, KEY_P = range(16, 26)
KEY_ENTER = 28
KEY_LEFTCTRL = 29
KEY_A, KEY_S, KEY_D, KEY_F, KEY_G, KEY_H, KEY_J, KEY_K, KEY_L = range(30, 39)
KEY_LEFTSHIFT = 42
KEY_Z, KEY_X, KEY_C, KEY_V, KEY_B, KEY_N, KEY_M = range(44, 51)
KEY_DOT = 52
KEY_SPACE = 57

ALL_VIRTUAL_KEYS = (
    KEY_ESC, KEY_ENTER, KEY_BACKSPACE, KEY_TAB, KEY_SPACE, KEY_LEFTSHIFT, KEY_LEFTCTRL, KEY_MINUS, KEY_DOT,
    KEY_1, KEY_2, KEY_3, KEY_4, KEY_5, KEY_6, KEY_7, KEY_8, KEY_9, KEY_0,
    KEY_Q, KEY_W, KEY_E, KEY_R, KEY_T, KEY_Y, KEY_U, KEY_I, KEY_O, KEY_P,
    KEY_A, KEY_S, KEY_D, KEY_F, KEY_G, KEY_H, KEY_J, KEY_K, KEY_L,
    KEY_Z, KEY_X, KEY_C, KEY_V, KEY_B, KEY_N, KEY_M,
)

CHAR_MAP = {
    'a': (KEY_A, False), 'b': (KEY_B, False), 'c': (KEY_C, False), 'd': (KEY_D, False),
    'e': (KEY_E, False), 'f': (KEY_F, False), 'g': (KEY_G, False), 'h': (KEY_H, False),
    'i': (KEY_I, False), 'j': (KEY_J, False), 'k': (KEY_K, False), 'l': (KEY_L, False),
    'm': (KEY_M, False), 'n': (KEY_N, False), 'o': (KEY_O, False), 'p': (KEY_P, False),
    'q': (KEY_Q, False), 'r': (KEY_R, False), 's': (KEY_S, False), 't': (KEY_T, False),
    'u': (KEY_U, False), 'v': (KEY_V, False), 'w': (KEY_W, False), 'x': (KEY_X, False),
    'y': (KEY_Y, False), 'z': (KEY_Z, False),
    'A': (KEY_A, True), 'B': (KEY_B, True), 'C': (KEY_C, True), 'D': (KEY_D, True),
    'E': (KEY_E, True), 'F': (KEY_F, True), 'G': (KEY_G, True), 'H': (KEY_H, True),
    'I': (KEY_I, True), 'J': (KEY_J, True), 'K': (KEY_K, True), 'L': (KEY_L, True),
    'M': (KEY_M, True), 'N': (KEY_N, True), 'O': (KEY_O, True), 'P': (KEY_P, True),
    'Q': (KEY_Q, True), 'R': (KEY_R, True), 'S': (KEY_S, True), 'T': (KEY_T, True),
    'U': (KEY_U, True), 'V': (KEY_V, True), 'W': (KEY_W, True), 'X': (KEY_X, True),
    'Y': (KEY_Y, True), 'Z': (KEY_Z, True),
    '1': (KEY_1, False), '2': (KEY_2, False), '3': (KEY_3, False), '4': (KEY_4, False),
    '5': (KEY_5, False), '6': (KEY_6, False), '7': (KEY_7, False), '8': (KEY_8, False),
    '9': (KEY_9, False), '0': (KEY_0, False),
    '-': (KEY_MINUS, False), '_': (KEY_MINUS, True),
    ' ': (KEY_SPACE, False), '.': (KEY_DOT, False),
}

# Physical R36S controller codes
PAD_UP, PAD_DOWN, PAD_LEFT, PAD_RIGHT = 0x220, 0x221, 0x222, 0x223
PAD_A, PAD_B, PAD_X, PAD_Y = 0x131, 0x130, 0x133, 0x134
PAD_START, PAD_SELECT = 0x2c1, 0x2c0
PAD_L3, PAD_R3, PAD_MENU = 0x2c2, 0x2c3, 0x2c4

PAD_BUTTON_ACTIONS = {
    PAD_UP: 'up', PAD_DOWN: 'down', PAD_LEFT: 'left', PAD_RIGHT: 'right',
    PAD_A: 'select', PAD_B: 'backspace', PAD_X: 'space', PAD_Y: 'caps',
    PAD_START: 'confirm', PAD_SELECT: 'cancel', PAD_MENU: 'cancel',
}

# X11 keysyms
KEYSYMS = {
    0xff52: 'up', 0xff54: 'down', 0xff51: 'left', 0xff53: 'right',
    0xff0d: 'confirm', 0xff1b: 'cancel', 0xff08: 'backspace', 0x20: 'space',
}

# 5x7 bitmap font
FONT = {
    'A': '0E11111F111111', 'B': '1E11111E11111E', 'C': '0F10101010100F', 'D': '1E11111111111E',
    'E': '1F10101E10101F', 'F': '1F10101E101010', 'G': '0F10101711110F', 'H': '1111111F111111',
    'I': '0E04040404040E', 'J': '0101010111110E', 'K': '11121418141211', 'L': '1010101010101F',
    'M': '111B1515111111', 'N': '11191513111111', 'O': '0E11111111110E', 'P': '1E11111E101010',
    'Q': '0E11111115120D', 'R': '1E11111E141211', 'S': '0F10100E01011E', 'T': '1F040404040404',
    'U': '1111111111110E', 'V': '11111111110A04', 'W': '11111115151B11', 'X': '11110A040A1111',
    'Y': '11110A04040404', 'Z': '1F01020408101F',
    'a': '00000E010F110F', 'b': '10101E1111111E', 'c': '00000E1110110E', 'd': '01010F1111110F',
    'e': '00000E111F100F', 'f': '0609081C080808', 'g': '000F11110F010E', 'h': '10101E11111111',
    'i': '04000C0404040E', 'j': '0200060202120C', 'k': '10101214181412', 'l': '0C04040404040E',
    'm': '00001A15151515', 'n': '00001E11111111', 'o': '00000E1111110E', 'p': '001E111E101010',
    'q': '000F110F010101', 'r': '00001619101010', 's': '00000F100E011E', 't': '08081E08080906',
    'u': '0000111111110F', 'v': '00001111110A04', 'w': '0000111515150A', 'x': '0000110A040A11',
    'y': '0011110F01110E', 'z': '00001F0204081F',
    '0': '0E11131519110E', '1': '040C040404040E', '2': '0E11010204081F', '3': '1E01010601011E',
    '4': '02060A121F0202', '5': '1F10101E01011E', '6': '0E10101E11110E', '7': '1F010204080808',
    '8': '0E11110E11110E', '9': '0E11110F01010E',
    ' ': '00000000000000', '-': '0000001F000000', '_': '0000000000001F', ':': '00040000000400',
    '/': '01020404081010', '<': '02040810080402', '>': '08040201020408', '.': '00000000000C0C',
    '!': '04040404040004', '?': '0E110102040004'
}

KEYBOARD_ROWS = [
    ['1', '2', '3', '4', '5', '6', '7', '8', '9', '0', '-', '_'],
    ['Q', 'W', 'E', 'R', 'T', 'Y', 'U', 'I', 'O', 'P'],
    ['A', 'S', 'D', 'F', 'G', 'H', 'J', 'K', 'L'],
    ['Z', 'X', 'C', 'V', 'B', 'N', 'M'],
    ['SPACE', 'BKSP', 'CLEAR', 'CAPS', 'DONE', 'CANCEL'],
]

WIDTH, HEIGHT = 640, 480
TIMEOUT = 5.0
MAX_FRAME = 262144
MAX_EVENTS = 1024


class OSKDisplayError(OSError):
    """X11 communication or display failure."""


def _pad(data):
    return data + b'\0' * (-len(data) % 4)


def _setup(data):
    """Validate X11 setup bytes and extract screen info."""
    if len(data) < 32:
        raise OSKDisplayError('setup_invalid')
    base, mask = struct.unpack_from('<II', data, 4)
    vendor_len, maximum = struct.unpack_from('<HH', data, 16)
    roots, formats = data[20:22]
    low, high = data[26:28]
    if not roots or not formats or maximum < 16 or low < 8 or high < low:
        raise OSKDisplayError('setup_invalid')
    if not base or base & mask or bin(mask).count('1') < 2:
        raise OSKDisplayError('setup_invalid')
    pos = 32 + ((vendor_len + 3) & ~3)
    if pos + formats * 8 > len(data):
        raise OSKDisplayError('setup_invalid')
    depths = set()
    for offset in range(pos, pos + formats * 8, 8):
        depth, bpp, scanpad = data[offset:offset + 3]
        if not 1 <= depth <= 32 or bpp not in (1, 4, 8, 16, 24, 32) or depth > bpp:
            raise OSKDisplayError('setup_invalid')
        depths.add(depth)
    pos += formats * 8
    chosen = None
    for index in range(roots):
        if pos + 40 > len(data):
            raise OSKDisplayError('setup_invalid')
        root, cmap = struct.unpack_from('<II', data, pos)
        w, h = struct.unpack_from('<HH', data, pos + 20)
        visual = struct.unpack_from('<I', data, pos + 32)[0]
        depth, count = data[pos + 38:pos + 40]
        if not root or not cmap or not visual or not w or not h or depth not in depths or not count:
            raise OSKDisplayError('setup_invalid')
        pos += 40
        found = None
        for _ in range(count):
            if pos + 8 > len(data):
                raise OSKDisplayError('setup_invalid')
            vd = data[pos]
            nvisuals = struct.unpack_from('<H', data, pos + 2)[0]
            pos += 8
            if pos + nvisuals * 24 > len(data):
                raise OSKDisplayError('setup_invalid')
            for offset in range(pos, pos + nvisuals * 24, 24):
                vid, kind, bits, entries, red, green, blue = struct.unpack_from('<IBBHIII', data, offset)
                if vid == visual and vd == depth:
                    masks = (red, green, blue)
                    if kind != 4 or not 1 <= bits <= 32 or not entries:
                        raise OSKDisplayError('setup_invalid')
                    found = masks
            pos += nvisuals * 24
        if found is None:
            raise OSKDisplayError('setup_invalid')
        if index == 0:
            chosen = (root, cmap, visual, depth, found)
    if pos != len(data):
        raise OSKDisplayError('setup_invalid')
    return base, mask, maximum, low, high, chosen


def create_virtual_keyboard():
    """Create a Linux uinput virtual keyboard device."""
    fd = os.open('/dev/uinput', os.O_WRONLY | os.O_NONBLOCK)
    try:
        fcntl.ioctl(fd, UI_SET_EVBIT, EV_KEY)
        fcntl.ioctl(fd, UI_SET_EVBIT, EV_SYN)
        for code in ALL_VIRTUAL_KEYS:
            fcntl.ioctl(fd, UI_SET_KEYBIT, code)
        header = struct.pack('<80sHHHHI', b'PD2 Virtual Keyboard', BUS_USB,
                             0x1234, 0x5678, 1, 0)
        arrays = [[0] * 64 for _ in range(4)]
        payload = header + b''.join(struct.pack('<64i', *array) for array in arrays)
        if os.write(fd, payload) != len(payload):
            raise OSError('short uinput write')
        fcntl.ioctl(fd, UI_DEV_CREATE)
        return fd
    except BaseException:
        os.close(fd)
        raise


def destroy_virtual_keyboard(fd):
    """Destroy uinput virtual keyboard."""
    if fd is not None:
        try:
            fcntl.ioctl(fd, UI_DEV_DESTROY)
        except OSError:
            pass
        os.close(fd)


def emit_key(fd, code, value):
    """Write an EV_KEY event followed by SYN_REPORT."""
    os.write(fd, EVENT.pack(0, 0, EV_KEY, code, value))
    os.write(fd, EVENT.pack(0, 0, EV_SYN, SYN_REPORT, 0))


def name_key_sequence(text, replace=False):
    """Shared keysym/Linux-key/modifier plan for all typing backends.

    Replace the entire D2 name field with Ctrl+A, then Backspace.
    The third item is Shift (bool), or 'ctrl' for the selection shortcut.
    """
    keys = []
    if replace:
        keys.extend([(ord('a'), KEY_A, 'ctrl'), (0xff08, KEY_BACKSPACE, False)])
    keys.extend((ord(ch), CHAR_MAP[ch][0], CHAR_MAP[ch][1])
                for ch in text if ch in CHAR_MAP)
    return keys


def type_string(fd, text, send_enter=True, sleep_fn=time.sleep, replace=False):
    """Emit keystrokes for text through uinput device into game window."""
    for _sym, code, modifier in name_key_sequence(text, replace):
        modifier_code = KEY_LEFTCTRL if modifier == 'ctrl' else KEY_LEFTSHIFT
        if modifier:
            emit_key(fd, modifier_code, 1)
            sleep_fn(0.015)
        try:
            emit_key(fd, code, 1)
            sleep_fn(0.02)
            emit_key(fd, code, 0)
            sleep_fn(0.015)
        finally:
            if modifier:
                emit_key(fd, modifier_code, 0)
                sleep_fn(0.015)
    if send_enter:
        sleep_fn(0.1)
        emit_key(fd, KEY_ENTER, 1)
        sleep_fn(0.025)
        emit_key(fd, KEY_ENTER, 0)


def type_via_libxtst(text, send_enter=False, delay=0.035, sleep_fn=time.sleep, replace=False):
    """Type string into focused X11 window using libXtst and libX11 ctypes."""
    try:
        import ctypes
        x11 = ctypes.CDLL('libX11.so.6')
        xtst = ctypes.CDLL('libXtst.so.6')
    except (OSError, AttributeError):
        return False

    display_env = os.environ.get('DISPLAY', ':0')
    display_name = display_env.encode('ascii') if isinstance(display_env, str) else b':0'

    x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
    x11.XOpenDisplay.restype = ctypes.c_void_p
    dpy = x11.XOpenDisplay(display_name)
    if not dpy:
        dpy = x11.XOpenDisplay(b':0')
    if not dpy:
        return False

    try:
        x11.XKeysymToKeycode.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        x11.XKeysymToKeycode.restype = ctypes.c_ubyte
        x11.XStringToKeysym.argtypes = [ctypes.c_char_p]
        x11.XStringToKeysym.restype = ctypes.c_ulong
        x11.XFlush.argtypes = [ctypes.c_void_p]
        x11.XFlush.restype = ctypes.c_int
        x11.XSync.argtypes = [ctypes.c_void_p, ctypes.c_int]
        x11.XSync.restype = ctypes.c_int
        x11.XCloseDisplay.argtypes = [ctypes.c_void_p]
        x11.XCloseDisplay.restype = ctypes.c_int
        xtst.XTestFakeKeyEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_int, ctypes.c_ulong]
        xtst.XTestFakeKeyEvent.restype = ctypes.c_int

        shift_sym = x11.XStringToKeysym(b'Shift_L')
        shift_code = int(x11.XKeysymToKeycode(dpy, shift_sym)) if shift_sym else 50
        if not shift_code:
            shift_code = 50

        for sym, linux_code, modifier in name_key_sequence(text, replace):
            modifier_code = shift_code
            if modifier == 'ctrl':
                modifier_code = int(x11.XKeysymToKeycode(dpy, 0xffe3)) or KEY_LEFTCTRL + 8
            code = int(x11.XKeysymToKeycode(dpy, sym))
            if not code and modifier and chr(sym).isupper():
                code = int(x11.XKeysymToKeycode(dpy, ord(chr(sym).lower())))
            if not code:
                code = linux_code + 8

            if not code:
                continue

            if modifier:
                xtst.XTestFakeKeyEvent(dpy, modifier_code, 1, 0)
                sleep_fn(0.015)
            try:
                xtst.XTestFakeKeyEvent(dpy, code, 1, 0)
                sleep_fn(delay)
                xtst.XTestFakeKeyEvent(dpy, code, 0, 0)
                sleep_fn(delay)
            finally:
                if modifier:
                    xtst.XTestFakeKeyEvent(dpy, modifier_code, 0, 0)
                    sleep_fn(0.015)
            x11.XFlush(dpy)

        if send_enter:
            enter_sym = x11.XStringToKeysym(b'Return')
            enter_code = int(x11.XKeysymToKeycode(dpy, enter_sym)) if enter_sym else 36
            if not enter_code:
                enter_code = 36
            sleep_fn(0.04)
            xtst.XTestFakeKeyEvent(dpy, enter_code, 1, 0)
            sleep_fn(delay)
            xtst.XTestFakeKeyEvent(dpy, enter_code, 0, 0)
            x11.XFlush(dpy)

        x11.XSync(dpy, 0)
        return True
    finally:
        x11.XCloseDisplay(dpy)



class OSKModel:
    """State management for on-screen keyboard text input and navigation."""
    def __init__(self, initial_text='', max_len=15):
        self.text = initial_text[:max_len]
        self.max_len = max_len
        self.row = 1  # Start on QWERTY row
        self.col = 0
        self.caps = True
        self.message = ''
        self.result = None  # None, 'confirm', 'cancel'

    def move(self, dx, dy):
        if dy:
            self.row = (self.row + dy) % len(KEYBOARD_ROWS)
            self.col = min(self.col, len(KEYBOARD_ROWS[self.row]) - 1)
        if dx:
            self.col = (self.col + dx) % len(KEYBOARD_ROWS[self.row])
        self.message = ''

    def current_key(self):
        return KEYBOARD_ROWS[self.row][self.col]

    def press_key(self, key):
        self.message = ''
        if key == 'SPACE':
            if len(self.text) < self.max_len:
                self.text += ' '
        elif key == 'BKSP':
            self.text = self.text[:-1]
        elif key == 'CLEAR':
            self.text = ''
        elif key == 'CAPS':
            self.caps = not self.caps
        elif key == 'DONE':
            if len(self.text.strip()) < 2:
                self.message = 'NAME TOO SHORT (MIN 2 CHARS)'
            else:
                self.result = 'confirm'
        elif key == 'CANCEL':
            self.result = 'cancel'
        else:
            # Letter, digit, or symbol
            char = key.upper() if self.caps else key.lower()
            if len(self.text) < self.max_len:
                self.text += char

    def action(self, act):
        if self.result is not None:
            return
        if act == 'up':
            self.move(0, -1)
        elif act == 'down':
            self.move(0, 1)
        elif act == 'left':
            self.move(-1, 0)
        elif act == 'right':
            self.move(1, 0)
        elif act == 'select':
            self.press_key(self.current_key())
        elif act == 'backspace':
            self.press_key('BKSP')
        elif act == 'space':
            self.press_key('SPACE')
        elif act == 'caps':
            self.press_key('CAPS')
        elif act == 'confirm':
            self.press_key('DONE')
        elif act == 'cancel':
            self.press_key('CANCEL')


class OSKScreen:
    """Core X11 client window that displays the on-screen keyboard."""
    def __init__(self, font=FONT):
        self.font = font
        self.socket = None
        self.window = self.gc = self.pixmap = None
        self._buffer = bytearray()
        self._sequence = 0
        self._mapped = self._exposed = False
        self._keys = {}
        self._held = set()
        self._release = None
        self._pending = []

        if x11_probe is not None:
            status, cookie = x11_probe._auth_status()
        else:
            status, cookie = 'ready', bytes(16)
        if status != 'ready' or not isinstance(cookie, bytes) or len(cookie) != 16:
            raise OSKDisplayError('auth_failed')

        deadline = time.monotonic() + TIMEOUT
        if not hasattr(socket, 'AF_UNIX'):
            raise OSKDisplayError('connect_failed')
        self.socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.socket.settimeout(TIMEOUT)
        self.socket.connect('/tmp/.X11-unix/X0')

        name = getattr(x11_probe, 'AUTH_NAME', b'MIT-MAGIC-COOKIE-1')
        self._send(struct.pack('<BBHHHHH', ord('l'), 0, 11, 0, len(name), len(cookie), 0) +
                   _pad(name) + _pad(cookie), deadline)
        header = self._receive(8, deadline)
        setup_status, _, major, minor, units = struct.unpack('<BBHHH', header)
        if setup_status != 1 or major != 11 or minor != 0:
            raise OSKDisplayError('setup_invalid')
        setup = _setup(self._receive(units * 4, deadline))
        base, mask, self.maximum, self.low, self.high, root = setup
        self.root, self.colormap, self.visual, self.depth, self.masks = root
        bit1 = mask & -mask
        bit2 = (mask ^ bit1) & -(mask ^ bit1)
        self.window, self.gc = base | bit1, base | bit2
        self.pixmap = base | bit1 | bit2

        self._keyboard(deadline)
        self._xtest_opcode = None
        try:
            present, opcode = self._query_extension(b'XTEST', deadline)
            if present:
                self._xtest_opcode = opcode
        except Exception:
            self._xtest_opcode = None
        event_mask = 1 | 2 | (1 << 15) | (1 << 16) | (1 << 17)
        self._request(1, self.depth, struct.pack('<IIhhHHHHIIIII', self.window, self.root,
                      0, 0, WIDTH, HEIGHT, 0, 1, self.visual,
                      2 | 2048 | 8192, self._pixel((12, 10, 10)), event_mask, self.colormap), deadline)
        # Match Diablo II / Wine window class for Weston kiosk-shell scanout
        self._property(39, b'Diablo II', deadline)
        self._property(67, b'game.exe\0game.exe\0', deadline)

        self._request(53, self.depth, struct.pack('<IIHH', self.pixmap, self.window, WIDTH, HEIGHT), deadline)
        self._request(55, 0, struct.pack('<IIIII', self.gc, self.window, 4 | 65536, 0, 0), deadline)
        self._request(8, 0, struct.pack('<I', self.window), deadline)
        self._roundtrip(deadline)

        while not (self._mapped and self._exposed):
            self._event(self._frame(deadline))

    def _remaining(self, deadline):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise OSKDisplayError('timeout')
        return remaining

    def _send(self, data, deadline):
        self.socket.settimeout(self._remaining(deadline))
        try:
            self.socket.sendall(data)
        except OSError:
            raise OSKDisplayError('disconnected') from None

    def _receive(self, count, deadline):
        if count > MAX_FRAME:
            raise OSKDisplayError('protocol_error')
        while len(self._buffer) < count:
            self.socket.settimeout(self._remaining(deadline))
            try:
                chunk = self.socket.recv(min(65536, count - len(self._buffer)))
            except OSError:
                raise OSKDisplayError('disconnected') from None
            if not chunk:
                raise OSKDisplayError('disconnected')
            self._buffer.extend(chunk)
        result = bytes(self._buffer[:count])
        del self._buffer[:count]
        return result

    def _frame(self, deadline):
        header = self._receive(32, deadline)
        kind = header[0] & 127
        if kind == 0:
            raise OSKDisplayError('protocol_error')
        units = struct.unpack_from('<I', header, 4)[0] if kind in (1, 35) else 0
        if units > (MAX_FRAME - 32) // 4:
            raise OSKDisplayError('protocol_error')
        return header + self._receive(units * 4, deadline)

    def _request(self, opcode, detail, body, deadline):
        body = _pad(body)
        units = 1 + len(body) // 4
        self._sequence = (self._sequence + 1) & 65535
        self._send(struct.pack('<BBH', opcode, detail, units) + body, deadline)
        return self._sequence

    def _reply(self, opcode, body, deadline):
        sequence = self._request(opcode, 0, body, deadline)
        for _ in range(MAX_EVENTS):
            frame = self._frame(deadline)
            if frame[0] == 1:
                if struct.unpack_from('<H', frame, 2)[0] != sequence:
                    raise OSKDisplayError('protocol_error')
                return frame
            self._event(frame)
        raise OSKDisplayError('protocol_error')

    def _roundtrip(self, deadline):
        self._reply(43, b'', deadline)

    def _property(self, atom, value, deadline):
        self._request(18, 0, struct.pack('<IIIB3xI', self.window, atom, 31, 8, len(value)) + value, deadline)

    def _query_extension(self, name, deadline):
        nlen = len(name)
        pad = (-nlen) % 4
        body = struct.pack('<HH', nlen, 0) + name + (b'\0' * pad)
        reply = self._reply(98, body, deadline)
        present = bool(reply[8])
        major_opcode = reply[9]
        return present, major_opcode

    def _keyboard(self, deadline):
        count = self.high - self.low + 1
        reply = self._reply(101, struct.pack('<BB2x', self.low, count), deadline)
        per = reply[1]
        keys = {}
        keysym_map = {}
        for index in range(count):
            code = self.low + index
            symbols = struct.unpack_from('<' + 'I' * per, reply, 32 + index * per * 4)
            actions = {KEYSYMS[s] for s in symbols if s in KEYSYMS}
            if len(actions) == 1:
                keys[code] = actions.pop()
            if len(symbols) > 0 and symbols[0] and symbols[0] not in keysym_map:
                keysym_map[symbols[0]] = (code, False)
            if len(symbols) > 1 and symbols[1] and symbols[1] not in keysym_map:
                keysym_map[symbols[1]] = (code, True)
        self._keys = keys
        self._keysym_map = keysym_map
        self._shift_code = None
        for sym in (0xffe1, 0xffe2):
            if sym in keysym_map:
                self._shift_code = keysym_map[sym][0]
                break
        if not self._shift_code:
            self._shift_code = 50
        self._enter_code = keysym_map.get(0xff0d, (36, False))[0]

    def type_string(self, text, send_enter=False, delay=0.035, sleep_fn=time.sleep, replace=False):
        """Type characters into active window via XTEST extension."""
        if not self._xtest_opcode:
            return False
        deadline = time.monotonic() + TIMEOUT

        # 1. Unmap window so Weston restores focus to Game.exe
        self._request(10, 0, struct.pack('<I', self.window), deadline)
        self._roundtrip(deadline)
        # Give Weston and Xwayland time to activate Game.exe
        sleep_fn(0.25)

        def send_key(code, is_press):
            kind = 2 if is_press else 3  # 2=KeyPress, 3=KeyRelease
            body = struct.pack('<BBHIIIIhhIHBB',
                               kind, code, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)
            self._request(self._xtest_opcode, 2, body, deadline)

        for sym, linux_code, modifier in name_key_sequence(text, replace):
            code, mapped_shift = self._keysym_map.get(sym, (linux_code + 8, modifier))
            if modifier == 'ctrl':
                modifier_code = self._keysym_map.get(0xffe3, (KEY_LEFTCTRL + 8, False))[0]
            else:
                modifier = mapped_shift
                modifier_code = self._shift_code

            if modifier:
                send_key(modifier_code, True)
                sleep_fn(0.015)
            try:
                send_key(code, True)
                sleep_fn(delay)
                send_key(code, False)
                sleep_fn(delay)
            finally:
                if modifier:
                    send_key(modifier_code, False)
                    sleep_fn(0.015)
            self._roundtrip(deadline)

        if send_enter:
            sleep_fn(0.04)
            send_key(self._enter_code, True)
            sleep_fn(delay)
            send_key(self._enter_code, False)
            self._roundtrip(deadline)

        return True

    def _event(self, frame):
        kind = frame[0] & 127
        if kind == 19 and struct.unpack_from('<I', frame, 8)[0] == self.window:
            self._mapped = True
        elif kind == 12 and struct.unpack_from('<I', frame, 4)[0] == self.window:
            self._exposed = True
        elif kind in (2, 3) and struct.unpack_from('<I', frame, 12)[0] == self.window:
            code = frame[1]
            if kind == 2 and code in self._keys and code not in self._held:
                self._pending.append(self._keys[code])
                self._held.add(code)
            elif kind == 3:
                self._held.discard(code)

    def actions(self):
        """Poll incoming X11 key events."""
        deadline = time.monotonic() + 0.001
        while self.socket is not None and select.select([self.socket], [], [], 0)[0]:
            try:
                frame = self._frame(deadline)
                self._event(frame)
            except OSError:
                break
        res = self._pending[:]
        self._pending.clear()
        return res

    def _pixel(self, rgb):
        result = 0
        for component, mask in zip(rgb, self.masks):
            bit = mask & -mask
            result |= ((component * (mask // bit) + 127) // 255) * bit
        return result

    def _rectangles(self, rectangles, color, deadline):
        if not rectangles:
            return
        self._request(56, 0, struct.pack('<III', self.gc, 4, self._pixel(color)), deadline)
        batch = min(2048, (self.maximum - 3) // 2)
        for start in range(0, len(rectangles), batch):
            body = bytearray(struct.pack('<II', self.pixmap, self.gc))
            for x, y, width, height in rectangles[start:start + batch]:
                if 0 <= x < WIDTH and 0 <= y < HEIGHT:
                    cw = min(width, WIDTH - x)
                    ch = min(height, HEIGHT - y)
                    body.extend(struct.pack('<hhHH', x, y, cw, ch))
            self._request(70, 0, body, deadline)

    def _text(self, x, y, text, color, scale, deadline):
        rectangles = []
        for char in text:
            glyph = self.font.get(char, self.font[' '])
            for r in range(7):
                bits = int(glyph[r * 2:r * 2 + 2], 16)
                for c in range(5):
                    if bits & (1 << (4 - c)):
                        px = x + c * scale
                        py = y + r * scale
                        rectangles.append((px, py, scale, scale))
            x += (5 + 1) * scale
        self._rectangles(rectangles, color, deadline)

    def draw(self, model):
        """Render the complete on-screen keyboard UI."""
        deadline = time.monotonic() + TIMEOUT
        # Background
        self._rectangles([(0, 0, WIDTH, HEIGHT)], (12, 10, 10), deadline)

        # Outer gold & inner crimson frames
        self._rectangles([
            (6, 6, 628, 2), (6, 472, 628, 2), (6, 6, 2, 468), (632, 6, 2, 468),
        ], (140, 105, 35), deadline)
        self._rectangles([
            (12, 12, 616, 1), (12, 467, 616, 1), (12, 12, 1, 456), (627, 12, 1, 456),
        ], (95, 20, 20), deadline)

        # Header titles
        self._text(167, 18, 'PROJECT DIABLO II', (235, 195, 60), 3, deadline)
        self._text(200, 48, 'CHARACTER NAME INPUT', (185, 45, 35), 2, deadline)

        # Input box
        self._rectangles([(78, 73, 484, 44)], (160, 125, 45), deadline)
        self._rectangles([(80, 75, 480, 40)], (20, 16, 16), deadline)
        self._text(90, 85, 'NAME: ', (200, 160, 50), 3, deadline)
        display_text = model.text + '_'
        self._text(198, 85, display_text, (255, 255, 220), 3, deadline)

        # Divider line
        self._rectangles([(40, 126, 560, 2)], (140, 105, 35), deadline)

        # Keys Grid
        row_configs = [
            (140, 30, 38, 6),
            (178, 30, 44, 6),
            (216, 30, 48, 6),
            (254, 30, 56, 8),
        ]
        for r in range(4):
            keys = KEYBOARD_ROWS[r]
            y, h, kw, gap = row_configs[r]
            total_w = len(keys) * kw + (len(keys) - 1) * gap
            start_x = (WIDTH - total_w) // 2
            for c, k in enumerate(keys):
                x = start_x + c * (kw + gap)
                is_sel = (model.row == r and model.col == c)
                bg_col = (145, 25, 20) if is_sel else (30, 24, 24)
                border_col = (255, 215, 0) if is_sel else (75, 60, 45)
                text_col = (255, 255, 220) if is_sel else (210, 200, 180)
                # Key frame & background
                self._rectangles([(x, y, kw, h)], border_col, deadline)
                self._rectangles([(x + 1, y + 1, kw - 2, h - 2)], bg_col, deadline)
                # Label
                label = k.upper() if model.caps else k.lower()
                tx = x + (kw - 12) // 2
                ty = y + (h - 14) // 2
                self._text(tx, ty, label, text_col, 2, deadline)

        # Row 4: Action buttons
        action_keys = KEYBOARD_ROWS[4]
        action_widths = [80, 75, 75, 75, 75, 80]
        action_gap = 8
        total_w = sum(action_widths) + (len(action_widths) - 1) * action_gap
        start_x = (WIDTH - total_w) // 2
        y, h = 296, 34
        cur_x = start_x
        for c, k in enumerate(action_keys):
            kw = action_widths[c]
            is_sel = (model.row == 4 and model.col == c)
            if is_sel:
                if k == 'DONE':
                    bg_col, border_col = (35, 110, 45), (255, 215, 0)
                elif k == 'CANCEL':
                    bg_col, border_col = (130, 25, 25), (255, 215, 0)
                else:
                    bg_col, border_col = (145, 25, 20), (255, 215, 0)
                text_col = (255, 255, 220)
            else:
                bg_col = (30, 24, 24)
                border_col = (75, 60, 45)
                text_col = (210, 200, 180)
            self._rectangles([(cur_x, y, kw, h)], border_col, deadline)
            self._rectangles([(cur_x + 1, y + 1, kw - 2, h - 2)], bg_col, deadline)
            label = k
            if k == 'CAPS':
                label = 'CAPS:ON' if model.caps else 'CAPS:OFF'
                label_w = len(label) * 12
                tx = cur_x + max(2, (kw - label_w) // 2)
            else:
                label_w = len(label) * 12
                tx = cur_x + max(2, (kw - label_w) // 2)
            ty = y + (h - 14) // 2
            self._text(tx, ty, label, text_col, 2, deadline)
            cur_x += kw + action_gap

        # Bottom Legend / Controller Shortcuts
        self._rectangles([(40, 348, 560, 1)], (95, 20, 20), deadline)
        self._text(68, 362, 'D-PAD: MOVE   A: TYPE   B: BKSP   X: SPACE', (170, 150, 120), 2, deadline)
        self._text(86, 386, 'Y: CAPS (UPPER/LOWER)   START: CONFIRM', (170, 150, 120), 2, deadline)
        self._text(206, 410, 'SELECT / FN: CANCEL', (170, 150, 120), 2, deadline)

        # Status or warning message
        if model.message:
            msg_w = len(model.message) * 12
            mx = (WIDTH - msg_w) // 2
            self._text(mx, 436, model.message, (255, 80, 40), 2, deadline)

        # Blit offscreen pixmap to window: Opcode 62 (CopyArea)
        self._request(62, 0, struct.pack('<IIIhhhhHH', self.pixmap, self.window,
                                         self.gc, 0, 0, 0, 0, WIDTH, HEIGHT), deadline)
        self._roundtrip(deadline)

    def close(self):
        """Close X11 connection and destroy window."""
        if self.socket is not None:
            try:
                self.socket.close()
            except OSError:
                pass
            self.socket = None


def evread(nr, size):
    return (2 << 30) | (size << 16) | (ord('E') << 8) | nr


class PadReader:
    """Read controller events from R36S gamepad evdev descriptor."""
    def __init__(self, fd, held=()):
        self.fd = fd
        self.buffer = b''
        self.held = set(held)
        self.stick_x = 0
        self.stick_y = 0

    def actions(self):
        if self.fd is None or not select.select([self.fd], [], [], 0)[0]:
            return []
        try:
            data = os.read(self.fd, EV_SIZE * 64)
        except (BlockingIOError, OSError):
            return []
        if not data:
            return []
        self.buffer += data
        acts = []
        while len(self.buffer) >= EV_SIZE:
            _, _, kind, code, value = EVENT.unpack(self.buffer[:EV_SIZE])
            self.buffer = self.buffer[EV_SIZE:]
            if kind == EV_KEY:
                if value == 0:
                    self.held.discard(code)
                elif value == 1:
                    if code not in self.held:
                        self.held.add(code)
                        if code in PAD_BUTTON_ACTIONS:
                            acts.append(PAD_BUTTON_ACTIONS[code])
            elif kind == EV_ABS:
                # Analog stick threshold detection with debouncing
                if code == ABS_X:
                    if value > 16000 and self.stick_x != 1:
                        acts.append('right')
                        self.stick_x = 1
                    elif value < -16000 and self.stick_x != -1:
                        acts.append('left')
                        self.stick_x = -1
                    elif -8000 < value < 8000:
                        self.stick_x = 0
                elif code == ABS_Y:
                    if value > 16000 and self.stick_y != 1:
                        acts.append('down')
                        self.stick_y = 1
                    elif value < -16000 and self.stick_y != -1:
                        acts.append('up')
                        self.stick_y = -1
                    elif -8000 < value < 8000:
                        self.stick_y = 0
        return acts


def is_hotkey(kind, code, value, held_keys):
    """Determine if a physical gamepad event triggers the on-screen keyboard.

    Single Fn/Menu is deliberately excluded so in-game Automap mapping is never blocked.
    Uses safe combinations: Select+X, Fn+X, L3+R3, or Select+D-Pad Down.
    """
    if kind != EV_KEY:
        return False
    if value == 1:
        # Select + X combo (PortMaster standard text shortcut)
        if code == PAD_X and PAD_SELECT in held_keys:
            return True
        if code == PAD_SELECT and PAD_X in held_keys:
            return True
        # FN + X combo
        if code == PAD_X and PAD_MENU in held_keys:
            return True
        if code == PAD_MENU and PAD_X in held_keys:
            return True
        # L3 + R3 combo (both sticks pressed)
        if code == PAD_R3 and PAD_L3 in held_keys:
            return True
        if code == PAD_L3 and PAD_R3 in held_keys:
            return True
        # Select + D-Pad Down combo
        if code == PAD_DOWN and PAD_SELECT in held_keys:
            return True
        if code == PAD_SELECT and PAD_DOWN in held_keys:
            return True
    return False


def run_osk_loop(screen, pad_reader, model, sleep_fn=time.sleep):
    """Main UI loop for on-screen keyboard."""
    screen.draw(model)
    sleep_fn(0.25)  # Discard triggering button release
    pad_reader.actions()
    screen.actions()

    last_state = (model.text, model.row, model.col, model.caps, model.message)
    while model.result is None:
        actions = pad_reader.actions() + screen.actions()
        for act in actions:
            model.action(act)
            if model.result is not None:
                break
        cur_state = (model.text, model.row, model.col, model.caps, model.message)
        if cur_state != last_state and model.result is None:
            screen.draw(model)
            last_state = cur_state
        sleep_fn(0.02)
    return model.text if model.result == 'confirm' else None


def show_osk(pfd=None, ufd_keyboard=None, initial_text='', max_len=15):
    """Display the on-screen keyboard, collect name, and type into Diablo II.

    Args:
        pfd: Open file descriptor to gamepad evdev device.
        ufd_keyboard: Optional pre-opened virtual keyboard uinput descriptor.
        initial_text: Pre-filled text string.
        max_len: Max allowed name length (Diablo II character name limit is 15).

    Returns:
        The confirmed name string, or None if cancelled.
    """
    close_pfd = False
    if pfd is None:
        import xbox_mapper
        pad = xbox_mapper.choose_pad(xbox_mapper.physical_devices())
        if pad is None:
            return None
        pfd = os.open(pad[0], os.O_RDONLY | os.O_NONBLOCK | getattr(os, 'O_NOFOLLOW', 0))
        close_pfd = True

    screen = None
    close_kfd = False
    kfd = ufd_keyboard
    try:
        held_keys = set()
        try:
            mask = fcntl.ioctl(pfd, evread(0x18, 96), bytes(96))
            held_keys = {c for c in range(min(KEY_MAX + 1, 96 * 8)) if mask[c // 8] & (1 << (c % 8))}
        except (OSError, ValueError):
            pass
        model = OSKModel(initial_text=initial_text, max_len=max_len)
        screen = OSKScreen()
        reader = PadReader(pfd, held=held_keys)
        confirmed_name = run_osk_loop(screen, reader, model)

        if confirmed_name:
            typed = False
            # 1. Direct X11 wire protocol XTEST over existing connection
            try:
                typed = screen.type_string(confirmed_name, send_enter=False, replace=True)
            except Exception as err:
                sys.stderr.write(f'PD2 OSK wire XTest error: {err}\n')
                sys.stderr.flush()

            screen.close()
            screen = None

            # 2. If wire XTEST failed, try ctypes libXtst
            if not typed:
                time.sleep(0.2)
                try:
                    typed = type_via_libxtst(confirmed_name, send_enter=False, replace=True)
                except Exception as err:
                    sys.stderr.write(f'PD2 OSK libXtst error: {err}\n')
                    sys.stderr.flush()

            # 3. If both failed, fallback to uinput
            if not typed:
                time.sleep(0.2)
                try:
                    if kfd is None:
                        kfd = create_virtual_keyboard()
                        close_kfd = True
                    if kfd is not None:
                        time.sleep(0.3)
                        type_string(kfd, confirmed_name, send_enter=False, replace=True)
                        time.sleep(0.3)
                        typed = True
                except Exception as err:
                    sys.stderr.write(f'PD2 OSK uinput error: {err}\n')
                    sys.stderr.flush()

            return confirmed_name
        return None
    except Exception as err:
        sys.stderr.write(f'PD2 OSK error: {err}\n')
        sys.stderr.flush()
        return None
    finally:
        if screen is not None:
            screen.close()
        if close_kfd and kfd is not None:
            destroy_virtual_keyboard(kfd)
        if close_pfd and pfd is not None:
            os.close(pfd)


def main():
    """CLI runner and standalone daemon."""
    mode = 'test' if '--test' in sys.argv else 'daemon' if '--daemon' in sys.argv else 'run'
    if mode == 'test':
        print('PD2 OSK: Running 5-second test or confirmation...')
        name = show_osk(initial_text='Hero')
        print(f'PD2 OSK result: {name!r}')
        return 0
    elif mode == 'run':
        name = show_osk()
        print(f'Confirmed: {name!r}')
        return 0
    elif mode == 'daemon':
        # Standalone background daemon for mapper input mode
        import xbox_mapper
        pad = xbox_mapper.choose_pad(xbox_mapper.physical_devices())
        if pad is None:
            return 1
        pfd = os.open(pad[0], os.O_RDONLY | os.O_NONBLOCK | getattr(os, 'O_NOFOLLOW', 0))
        stop = False

        def on_signal(_sig, _frame):
            nonlocal stop
            stop = True

        signal.signal(signal.SIGTERM, on_signal)
        signal.signal(signal.SIGINT, on_signal)
        held = set()
        kfd = None
        try:
            kfd = create_virtual_keyboard()
        except OSError:
            pass
        try:
            while not stop:
                r, _, _ = select.select([pfd], [], [], 0.5)
                if not r:
                    continue
                try:
                    data = os.read(pfd, EV_SIZE * 64)
                except (BlockingIOError, OSError):
                    continue
                if not data:
                    break
                for _sec, _usec, kind, code, value in EVENT.iter_unpack(data):
                    if kind == EV_KEY:
                        if value == 1:
                            held.add(code)
                        elif value == 0:
                            held.discard(code)
                        if is_hotkey(kind, code, value, held):
                            show_osk(pfd=pfd, ufd_keyboard=kfd)
                            held.clear()
            return 0
        finally:
            if kfd is not None:
                destroy_virtual_keyboard(kfd)
            os.close(pfd)


if __name__ == '__main__':
    sys.exit(main())
