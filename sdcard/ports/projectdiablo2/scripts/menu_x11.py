#!/usr/bin/env python3
"""Small authenticated CORE X11 menu. No Xlib, SDL, grabs or file writes.

Screen(font, labels) blocks until its managed window is mapped and exposed.
All protocol, visibility and connection failures raise OSError (fail closed).
"""
import select
import socket
import struct
import time

import x11_probe

TIMEOUT = 5.0
MAX_FRAME = 262144
MAX_EVENTS = 1024
WIDTH, HEIGHT = 640, 480
KEYSYMS = {0xff52: 'up', 0xff54: 'down', 0xff51: 'left',
           0xff53: 'right', 0xff0d: 'accept', 0x20: 'accept',
           0xff1b: 'cancel', 0xff8d: 'accept'}


class MenuDisplayError(OSError):
    """Public diagnostic enum; never includes server strings or auth bytes."""
    CODES = frozenset(('connect_failed', 'auth_failed', 'setup_invalid',
                       'window_failed', 'not_visible', 'protocol_error',
                       'disconnected', 'timeout'))

    def __init__(self, code):
        if code not in self.CODES:
            raise ValueError('invalid display error code')
        self.code = code
        super().__init__(code)


def _pad(data):
    return data + b'\0' * (-len(data) % 4)


def _setup(data):
    """Validate the complete variable-length setup, including all screens."""
    if len(data) < 32:
        raise MenuDisplayError('setup_invalid')
    base, mask = struct.unpack_from('<II', data, 4)
    vendor_len, maximum = struct.unpack_from('<HH', data, 16)
    roots, formats = data[20:22]
    low, high = data[26:28]
    if not roots or not formats or maximum < 16 or low < 8 or high < low:
        raise MenuDisplayError('setup_invalid')
    if not base or base & mask or bin(mask).count('1') < 2:
        raise MenuDisplayError('setup_invalid')
    pos = 32 + ((vendor_len + 3) & ~3)
    if pos + formats * 8 > len(data):
        raise MenuDisplayError('setup_invalid')
    depths = set()
    for offset in range(pos, pos + formats * 8, 8):
        depth, bpp, scanpad = data[offset:offset + 3]
        if not 1 <= depth <= 32 or bpp not in (1, 4, 8, 16, 24, 32) or depth > bpp or scanpad not in (8, 16, 32):
            raise MenuDisplayError('setup_invalid')
        depths.add(depth)
    pos += formats * 8
    chosen = None
    for index in range(roots):
        if pos + 40 > len(data):
            raise MenuDisplayError('setup_invalid')
        root, cmap = struct.unpack_from('<II', data, pos)
        width, height = struct.unpack_from('<HH', data, pos + 20)
        visual = struct.unpack_from('<I', data, pos + 32)[0]
        depth, count = data[pos + 38:pos + 40]
        if not root or not cmap or not visual or not width or not height or depth not in depths or not count:
            raise MenuDisplayError('setup_invalid')
        pos += 40
        found = None
        for _ in range(count):
            if pos + 8 > len(data):
                raise MenuDisplayError('setup_invalid')
            vd = data[pos]
            nvisuals = struct.unpack_from('<H', data, pos + 2)[0]
            pos += 8
            if pos + nvisuals * 24 > len(data):
                raise MenuDisplayError('setup_invalid')
            for offset in range(pos, pos + nvisuals * 24, 24):
                vid, kind, bits, entries, red, green, blue = struct.unpack_from('<IBBHIII', data, offset)
                if vid == visual and vd == depth:
                    masks = (red, green, blue)
                    if kind != 4 or not 1 <= bits <= 32 or not entries:
                        raise MenuDisplayError('setup_invalid')
                    if any(not value or value >> depth for value in masks) or red & green or red & blue or green & blue:
                        raise MenuDisplayError('setup_invalid')
                    for value in masks:
                        shifted = value // (value & -value)
                        if shifted & (shifted + 1):
                            raise MenuDisplayError('setup_invalid')
                    found = masks
            pos += nvisuals * 24
        if found is None:
            raise MenuDisplayError('setup_invalid')
        if index == 0:
            chosen = (root, cmap, visual, depth, found)
    if pos != len(data):
        raise MenuDisplayError('setup_invalid')
    return base, mask, maximum, low, high, chosen


class Screen:
    def __init__(self, font, labels):
        self.socket = None
        self.window = self.gc = self.pixmap = None
        self.font, self.labels = dict(font), tuple(labels)
        self._buffer = bytearray()
        self._sequence = 0
        self._menu = None
        self._held = set()
        self._release = None
        self._keys = {}
        self._initializing = True
        self._mapped = self._exposed = False
        self._pending = []
        if len(self.labels) not in (4, 5) or ' ' not in self.font:
            raise ValueError('valid labels and a space glyph required')
        for glyph in self.font.values():
            if not isinstance(glyph, str) or len(glyph) != 14:
                raise ValueError('font must contain seven hex rows')
            try:
                if any(int(glyph[i:i + 2], 16) > 31 for i in range(0, 14, 2)):
                    raise ValueError('font row outside five pixels')
            except ValueError:
                raise ValueError('invalid 5x7 font') from None
        stage = 'auth_failed'
        try:
            status, cookie = x11_probe._auth_status()
            if status != 'ready' or not isinstance(cookie, bytes) or len(cookie) != 16:
                raise MenuDisplayError('auth_failed')
            stage = 'connect_failed'
            deadline = time.monotonic() + TIMEOUT
            if not hasattr(socket, 'AF_UNIX'):
                raise MenuDisplayError('connect_failed')
            self.socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self.socket.settimeout(self._remaining(deadline))
            self.socket.connect('/tmp/.X11-unix/X0')
            stage = 'setup_invalid'
            name = x11_probe.AUTH_NAME
            self._send(struct.pack('<BBHHHHH', ord('l'), 0, 11, 0, len(name), len(cookie), 0) + _pad(name) + _pad(cookie), deadline)
            header = self._receive(8, deadline)
            status, _, major, minor, units = struct.unpack('<BBHHH', header)
            if status in (0, 2):
                raise MenuDisplayError('auth_failed')
            if status != 1 or major != 11 or minor != 0 or units < 8:
                raise MenuDisplayError('setup_invalid')
            setup = _setup(self._receive(units * 4, deadline))
            base, mask, self.maximum, self.low, self.high, root = setup
            self.root, self.colormap, self.visual, self.depth, self.masks = root
            bit1 = mask & -mask
            bit2 = (mask ^ bit1) & -(mask ^ bit1)
            self.window, self.gc = base | bit1, base | bit2
            # Two available resource bits yield three distinct nonzero IDs.
            self.pixmap = base | bit1 | bit2
            stage = 'window_failed'
            self._keyboard(deadline)
            # Managed InputOutput window: override_redirect is deliberately absent.
            event_mask = 1 | 2 | (1 << 15) | (1 << 16) | (1 << 17)
            self._request(1, self.depth, struct.pack('<IIhhHHHHIIIII', self.window, self.root,
                          0, 0, WIDTH, HEIGHT, 0, 1, self.visual,
                          2 | 2048 | 8192, self._pixel((12, 16, 24)), event_mask, self.colormap), deadline)
            self._property(39, b'Diablo II', deadline)  # WM_NAME / STRING
            self._property(67, b'game.exe\0game.exe\0', deadline)  # WM_CLASS
            # Compose off-screen at the window's depth; the same GC can serve
            # both drawables. graphics_exposures=False avoids CopyArea events.
            self._request(53, self.depth, struct.pack('<IIHH', self.pixmap, self.window, WIDTH, HEIGHT), deadline)
            self._request(55, 0, struct.pack('<IIIII', self.gc, self.window, 4 | 65536, 0, 0), deadline)
            self._request(8, 0, struct.pack('<I', self.window), deadline)
            self._roundtrip(deadline)
            stage = 'not_visible'
            while not (self._mapped and self._exposed):
                self._event(self._frame(deadline))
            reply = self._reply(3, struct.pack('<I', self.window), deadline)
            if len(reply) != 44 or reply[26] != 2:
                raise MenuDisplayError('not_visible')
            # Snapshot server key state after mapping: held Enter must be released.
            reply = self._reply(44, b'', deadline)
            if len(reply) != 40:
                raise MenuDisplayError('protocol_error')
            self._held.update(code for code in range(256) if reply[8 + code // 8] & (1 << (code % 8)))
            self._initializing = False
        except MenuDisplayError:
            self.close()
            raise
        except OSError:
            self.close()
            raise MenuDisplayError(stage) from None
        except BaseException:
            self.close()
            raise

    @staticmethod
    def _remaining(deadline):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise MenuDisplayError('timeout')
        return remaining

    def _send(self, data, deadline):
        self.socket.settimeout(self._remaining(deadline))
        try:
            self.socket.sendall(data)
        except TimeoutError:
            raise MenuDisplayError('timeout') from None
        except OSError:
            raise MenuDisplayError('disconnected') from None

    def _receive(self, count, deadline):
        if count > MAX_FRAME:
            raise MenuDisplayError('protocol_error')
        while len(self._buffer) < count:
            self.socket.settimeout(self._remaining(deadline))
            try:
                chunk = self.socket.recv(min(65536, count - len(self._buffer)))
            except TimeoutError:
                raise MenuDisplayError('timeout') from None
            except OSError:
                raise MenuDisplayError('disconnected') from None
            if not chunk:
                raise MenuDisplayError('disconnected')
            self._buffer.extend(chunk)
        result = bytes(self._buffer[:count])
        del self._buffer[:count]
        return result

    def _frame(self, deadline):
        header = self._receive(32, deadline)
        kind = header[0] & 127
        if kind == 0:
            raise MenuDisplayError('protocol_error')
        # GenericEvent also carries a length, unlike core fixed-size events.
        units = struct.unpack_from('<I', header, 4)[0] if kind in (1, 35) else 0
        if units > (MAX_FRAME - 32) // 4:
            raise MenuDisplayError('protocol_error')
        return header + self._receive(units * 4, deadline)

    def _request(self, opcode, detail, body, deadline):
        body = _pad(body)
        units = 1 + len(body) // 4
        if units > self.maximum or units > 65535:
            raise MenuDisplayError('protocol_error')
        self._sequence = (self._sequence + 1) & 65535
        self._send(struct.pack('<BBH', opcode, detail, units) + body, deadline)
        return self._sequence

    def _reply(self, opcode, body, deadline):
        sequence = self._request(opcode, 0, body, deadline)
        for _ in range(MAX_EVENTS):
            frame = self._frame(deadline)
            if frame[0] == 1:
                if struct.unpack_from('<H', frame, 2)[0] != sequence:
                    raise MenuDisplayError('protocol_error')
                return frame
            self._event(frame)
        raise MenuDisplayError('protocol_error')

    def _roundtrip(self, deadline):
        self._reply(43, b'', deadline)  # GetInputFocus: flush/check preceding void requests.

    def _property(self, atom, value, deadline):
        self._request(18, 0, struct.pack('<IIIB3xI', self.window, atom, 31, 8, len(value)) + value, deadline)

    def _keyboard(self, deadline):
        count = self.high - self.low + 1
        reply = self._reply(101, struct.pack('<BB2x', self.low, count), deadline)
        per = reply[1]
        if not per or len(reply) != 32 + count * per * 4:
            raise MenuDisplayError('protocol_error')
        keys = {}
        for index in range(count):
            symbols = struct.unpack_from('<' + 'I' * per, reply, 32 + index * per * 4)
            actions = {KEYSYMS[symbol] for symbol in symbols if symbol in KEYSYMS}
            if len(actions) == 1:
                keys[self.low + index] = actions.pop()
        self._keys = keys

    def _event(self, frame):
        kind = frame[0] & 127
        if frame[0] & 128:  # Do not accept synthetic key/map events as proof.
            return
        # CORE autorepeat is a release/press pair with the same server time.
        # Delay the release until the next event so a held Enter never re-arms
        # from autorepeat (including a pair split across actions() calls).
        if self._release is not None and kind in (2, 3) and struct.unpack_from('<I', frame, 12)[0] == self.window:
            code, stamp = self._release
            self._release = None
            if kind == 2 and frame[1] == code and struct.unpack_from('<I', frame, 4)[0] == stamp:
                return
            self._held.discard(code)
        if kind == 19 and struct.unpack_from('<I', frame, 8)[0] == self.window:
            self._mapped = True
        elif kind == 12 and struct.unpack_from('<I', frame, 4)[0] == self.window:
            self._exposed = True
            if self._menu is not None and not self._initializing:
                self._repaint = True
        elif kind in (17, 18) and struct.unpack_from('<I', frame, 8)[0] == self.window:
            raise MenuDisplayError('not_visible')
        elif kind in (2, 3) and struct.unpack_from('<I', frame, 12)[0] == self.window:
            code = frame[1]
            if kind == 3:
                self._release = (code, struct.unpack_from('<I', frame, 4)[0])
            else:
                if not self._initializing and code not in self._held and code in self._keys:
                    if len(self._pending) >= MAX_EVENTS:
                        raise MenuDisplayError('protocol_error')
                    self._pending.append(self._keys[code])
                self._held.add(code)
        elif kind == 34 and frame[4] == 1:
            self._remap = True

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
                if x < 0 or y < 0 or width <= 0 or height <= 0 or x + width > WIDTH or y + height > HEIGHT:
                    raise ValueError('rectangle outside menu')
                body.extend(struct.pack('<hhHH', x, y, width, height))
            self._request(70, 0, body, deadline)

    def _text(self, x, y, text, color, deadline):
        rectangles = []
        for char in text:
            glyph = self.font.get(char, self.font[' '])
            for row in range(7):
                bits = int(glyph[row * 2:row * 2 + 2], 16)
                for col in range(5):
                    px, py = x + col * 3, y + row * 3
                    if bits & (1 << (4 - col)) and 0 <= px < WIDTH and 0 <= py < HEIGHT:
                        rectangles.append((px, py, min(3, WIDTH - px), min(3, HEIGHT - py)))
            x += 18
        self._rectangles(rectangles, color, deadline)

    def draw(self, menu):
        if self.socket is None:
            raise MenuDisplayError('protocol_error')
        if menu.row not in range(4) or menu.resolution not in range(len(self.labels)):
            raise ValueError('invalid menu selection')
        self._menu = menu
        self._repaint = False
        deadline = time.monotonic() + TIMEOUT

        # Gothic dark charcoal background
        self._rectangles([(0, 0, WIDTH, HEIGHT)], (12, 10, 10), deadline)

        # Outer decorative frame (burnished gold)
        gold_frame = (140, 105, 35)
        self._rectangles([
            (6, 6, 628, 2),
            (6, 472, 628, 2),
            (6, 6, 2, 468),
            (632, 6, 2, 468),
        ], gold_frame, deadline)

        # Inner decorative frame (deep blood crimson)
        crimson_frame = (95, 20, 20)
        self._rectangles([
            (12, 12, 616, 1),
            (12, 467, 616, 1),
            (12, 12, 1, 456),
            (627, 12, 1, 456),
        ], crimson_frame, deadline)

        # Header titles
        self._text(167, 26, 'PROJECT DIABLO II', (235, 195, 60), deadline)
        self._text(86, 60, 'LORD OF DESTRUCTION - R36S', (185, 45, 35), deadline)

        # Decorative header divider lines
        self._rectangles([(40, 94, 560, 2)], (160, 125, 45), deadline)
        self._rectangles([(40, 97, 560, 1)], (95, 20, 20), deadline)

        # Show actual inherited settings, not an unexplained DEFAULT label.
        resolution = self.labels[menu.resolution]
        if menu.resolution == 0:
            inherited = getattr(menu, 'inherited_resolution', '640x480')
            if len(self.labels) == 5:
                label_map = {
                    '640x480': 'LCD 640X480',
                    '800x600': '800X600',
                    '1024x768': '1024X768',
                    'native': 'PD2 1068X600',
                }
                resolution = label_map.get(inherited, inherited.upper())
            else:
                resolution = 'NATIVE 1068X600' if inherited == 'native' else inherited.upper()
        fps = menu.fps if menu.fps_changed else getattr(menu, 'inherited_fps', False)
        # Even the longest row, '> RESOLUTION: NATIVE 1068X600', fits the
        # 548-pixel text area at the existing 3x font scale (501 pixels).
        rows = (
            'RESOLUTION: ' + resolution,
            'FPS COUNTER: ' + ('ON' if fps else 'OFF'),
            'ENTER SANCTUARY / LAUNCH',
            'EXIT TO SYSTEM',
        )

        # Highlight background box for selected row
        sel_y = 118 + 50 * menu.row
        self._rectangles([(34, sel_y - 4, 572, 32)], (42, 14, 14), deadline)
        self._rectangles([
            (34, sel_y - 4, 572, 2),
            (34, sel_y + 26, 572, 2),
            (34, sel_y - 4, 2, 32),
            (604, sel_y - 4, 2, 32),
        ], (210, 170, 60), deadline)

        # Draw rows text
        for i, label in enumerate(rows):
            is_sel = (i == menu.row)
            prefix = '> ' if is_sel else '  '
            color = (255, 225, 100) if is_sel else (185, 175, 160)
            self._text(46, 118 + 50 * i, prefix + label, color, deadline)

        # Decorative footer divider lines
        self._rectangles([(40, 334, 560, 1)], (95, 20, 20), deadline)
        self._rectangles([(40, 336, 560, 2)], (160, 125, 45), deadline)

        # Footer control instructions
        footer_color = (140, 130, 120)
        for y, label in (
            (354, 'DPAD / ARROWS: NAVIGATE / CHANGE'),
            (388, 'A / START / ENTER: SELECT'),
            (422, 'B / SELECT / ESC: QUIT'),
        ):
            self._text(46, y, label, footer_color, deadline)

        # Never clear the visible window while assembling text and borders.
        # Publish only the complete frame, in one core-X11 CopyArea request.
        self._request(62, 0, struct.pack('<IIIhhhhHH', self.pixmap, self.window,
                      self.gc, 0, 0, 0, 0, WIDTH, HEIGHT), deadline)
        self._roundtrip(deadline)

    def actions(self):
        if self.socket is None:
            raise MenuDisplayError('protocol_error')
        deadline = time.monotonic() + TIMEOUT
        # A readable partial frame must finish within the same bounded timeout.
        for _ in range(MAX_EVENTS):
            if not self._buffer and not select.select([self.socket], [], [], 0)[0]:
                break
            frame = self._frame(deadline)
            if frame[0] == 1:
                raise MenuDisplayError('protocol_error')
            self._event(frame)
        else:
            raise MenuDisplayError('protocol_error')
        if getattr(self, '_remap', False):
            self._remap = False
            self._keyboard(deadline)
        if getattr(self, '_repaint', False):
            self.draw(self._menu)
        result, self._pending = self._pending, []
        return result

    def close(self):
        # Disconnect destroys this client's resources, even after a server error.
        client, self.socket = self.socket, None
        if client is not None:
            client.close()
        self.window = self.gc = self.pixmap = None
