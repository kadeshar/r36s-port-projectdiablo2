#!/usr/bin/env python3
"""Zero-dependency X11 HUD renderer for R36S performance overlay.

Connects directly to the X11 Unix socket using core X11 protocol over AF_UNIX.
Uses an unmanaged override_redirect window with double-buffered Pixmap rendering.
Can reparent to the game's X11 window hierarchy for guaranteed scanout under Weston kiosk-shell.
No Xlib, Pygame, Tkinter, or external dependencies required.
"""
import glob
import os
import socket
import struct
import sys
import time

FONT_6X9 = {
    ' ': '000000000000000000',
    '0': '1e2123252931211e00',
    '1': '0c1c0c0c0c0c0c1e00',
    '2': '1e2101020408103f00',
    '3': '1e21010e0101211e00',
    '4': '02060a12223f020200',
    '5': '3f20203e0101211e00',
    '6': '1e21203e2121211e00',
    '7': '3f0102040810101000',
    '8': '1e21211e2121211e00',
    '9': '1e2121211f01211e00',
    'A': '1e2121213f21212100',
    'B': '3e21213e2121213e00',
    'C': '1e2120202020211e00',
    'D': '3c2221212121223c00',
    'E': '3f20203e2020203f00',
    'F': '3f20203e2020202000',
    'G': '1e2120202721211e00',
    'H': '2121213f2121212100',
    'I': '1e0c0c0c0c0c0c1e00',
    'J': '070202020222221c00',
    'K': '212224382422212100',
    'L': '202020202020203f00',
    'M': '21332d212121212100',
    'N': '213129252321212100',
    'O': '1e2121212121211e00',
    'P': '3e21213e2020202000',
    'Q': '1e2121212125221d00',
    'R': '3e21213e2422212100',
    'S': '1e21201e0101211e00',
    'T': '3f0c0c0c0c0c0c0c00',
    'U': '212121212121211e00',
    'V': '2121212121120c0c00',
    'W': '212121212d2d332100',
    'X': '2121120c0c12212100',
    'Y': '2121120c0c0c0c0c00',
    'Z': '3f0204081020203f00',
    ':': '000c0c00000c0c0000',
    '.': '0000000000000c0c00',
    '%': '313204081013230000',
    '|': '0c0c0c0c0c0c0c0c00',
    '-': '0000003f0000000000',
    '+': '000c0c3f0c0c000000',
    '/': '010204081020000000',
    '[': '1c1010101010101c00',
    ']': '0e0202020202020e00',
    '~': '12123f3f3f0c0c0c00',  # Wall AC Plug Icon
    'a': '00001e021e22221e00',
    'b': '20203c222222223c00',
    'c': '00001e212020211e00',
    'd': '02021e222222221e00',
    'e': '00001e213f20211e00',
    'f': '0c12103e1010101000',
    'g': '00001e22221e021c00',
    'h': '20203a262222222200',
    'i': '000c001c0c0c0c1e00',
    'j': '020006020202221c00',
    'k': '202022243824222100',
    'l': '181818181818181c00',
    'm': '000036292929292100',
    'n': '00003a262222222200',
    'o': '00001e222222221e00',
    'p': '00003c22223c202000',
    'q': '00001e22221e020200',
    'r': '00002e322020202000',
    's': '00001e201e01211e00',
    't': '10103e101010120c00',
    'u': '000022222222261a00',
    'v': '000022222214140800',
    'w': '000022222a2a362200',
    'x': '000022221408142200',
    'y': '00002222221e021c00',
    'z': '00003e040810203e00',
    '°': '001824180000000000',  # Degree symbol
}

# ---------------------------------------------------------------------------
# Overlay Layout & Positioning Configuration
# Easy to customize for other handhelds, resolutions, or AI agents
# ---------------------------------------------------------------------------
SCREEN_WIDTH = 640
SCREEN_HEIGHT = 480

# Glued to top edge by default for levels 2, 3, 4
OVERLAY_TOP_Y = 0

# Solid black background (False eliminates 1-bit stipple font noise)
TRANSPARENT_BG = False

# Level 1 (minimal FPS number pill)
LEVEL1_WIDTH = 34
LEVEL1_HEIGHT = 16
LEVEL1_X = 8
LEVEL1_Y = OVERLAY_TOP_Y

# Level 2 (compact horizontal bar)
# ALIGN: 'center', 'left', 'right', or integer X coordinate
LEVEL2_ALIGN = 'center'
LEVEL2_WIDTH = 410
LEVEL2_HEIGHT = 20
LEVEL2_Y = OVERLAY_TOP_Y

# Level 3 (multi-line HUD)
LEVEL3_WIDTH = 205
LEVEL3_HEIGHT = 176
LEVEL3_X = 8
LEVEL3_Y = OVERLAY_TOP_Y

# Level 4 (full detailed HUD with live frametime graph & Y scale)
LEVEL4_WIDTH = 205
LEVEL4_HEIGHT = 266
LEVEL4_X = 8
LEVEL4_Y = OVERLAY_TOP_Y

# R36S HUD Palette (RGB)
C_BG = (10, 12, 16)             # Deep translucent black backing
C_BG_ALPHA = 175                # ~68% opacity (semi-transparent black backing)
C_BORDER = (40, 46, 56)         # Subtle dark slate frame
C_SEP = (130, 95, 145)          # Purple/Violet Separator (|)

# FPS & Frametime
C_LABEL_FPS = (242, 100, 90)    # Salmon / Coral Red
C_VAL_FPS = (235, 245, 255)     # Cool White
C_CHART_OK = (70, 225, 95)      # Emerald / Lime Green (> 20 FPS)
C_CHART_WARN = (255, 180, 50)   # Orange (15-20 FPS)
C_CHART_BAD = (255, 75, 75)     # Red (< 15 FPS)

# CPU
C_LABEL_CPU = (55, 155, 255)    # Dodger / Sky Blue
C_VAL_CPU = (255, 255, 255)     # White

# GPU
C_LABEL_GPU = (60, 215, 115)    # Emerald Green
C_VAL_GPU = (255, 255, 255)     # White

# RAM
C_LABEL_RAM = (220, 105, 195)   # Orchid / Pink
C_VAL_RAM = (255, 255, 255)     # White

# BATT & Power
C_LABEL_BAT = (242, 100, 90)    # Salmon / Coral Red
C_VAL_BAT = (255, 255, 255)     # White
C_PLUG = (110, 230, 255)        # Bright Cyan for Wall AC Plug Icon
C_ACCENT = (110, 195, 255)      # Light Cyan Accent
C_MUTED = (110, 120, 132)       # Dim Slate for units


def get_chart_color(frametime_ms):
    """Return chart line color based on frametime / FPS:
    > 20 FPS: Green (frametime < 50.0ms)
    15-20 FPS: Orange (50.0ms <= frametime <= 66.7ms)
    < 15 FPS: Red (frametime > 66.7ms)
    """
    try:
        val = float(frametime_ms)
    except (TypeError, ValueError):
        return C_CHART_OK

    if val <= 0:
        return C_CHART_OK
    if val < 50.0:
        return C_CHART_OK
    elif val <= 66.7:
        return C_CHART_WARN
    return C_CHART_BAD


def _log(msg):
    try:
        from pathlib import Path
        log_dir = Path(__file__).resolve().parents[2] / 'logs'
        path = str(log_dir / 'overlay.log') if log_dir.is_dir() else '/tmp/overlay.log'
        with open(path, 'a', encoding='utf-8') as f:
            f.write(f'{time.strftime("%H:%M:%S")} [x11_hud] {msg}\n')
    except Exception:
        pass


def _pad(b):
    return b + b'\0' * (-len(b) % 4)


class X11HUD:
    def __init__(self, level=1, display=':0', x=None, y=None):
        self.level = level
        self.display = display
        self.sock = None
        self.window = 1
        self.gc = 2
        self.pixmap = 3
        self.root = None
        self.visual = None
        self.visual_32 = None
        self.use_argb = False
        self.depth = 24
        self.masks = (0xff0000, 0x00ff00, 0x0000ff)
        self.colormap = 0
        self.default_colormap = 0
        self.parent_is_game = False
        self._prev_rendered_fps = None
        self._frame_count = 0

        self.width, self.height = self._get_dimensions(level)
        self.x = self._get_default_x(level) if x is None else x
        self.y = self._get_default_y(level) if y is None else y

    def _get_dimensions(self, level):
        if level in (0, 1):
            return LEVEL1_WIDTH, LEVEL1_HEIGHT
        elif level == 2:
            return LEVEL2_WIDTH, LEVEL2_HEIGHT
        elif level == 3:
            return LEVEL3_WIDTH, LEVEL3_HEIGHT
        elif level == 4:
            return LEVEL4_WIDTH, LEVEL4_HEIGHT
        return LEVEL1_WIDTH, LEVEL1_HEIGHT

    def _get_default_x(self, level, width=None):
        target_w = width if width is not None else self._get_dimensions(level)[0]
        if level in (0, 1):
            return LEVEL1_X
        elif level == 2:
            if LEVEL2_ALIGN == 'center':
                return (SCREEN_WIDTH - target_w) // 2
            elif LEVEL2_ALIGN == 'right':
                return SCREEN_WIDTH - target_w - 8
            elif isinstance(LEVEL2_ALIGN, int):
                return LEVEL2_ALIGN
            return 8
        elif level == 3:
            return LEVEL3_X
        elif level == 4:
            return LEVEL4_X
        return 8

    def _get_default_y(self, level):
        if level in (2, 3, 4):
            return OVERLAY_TOP_Y
        return LEVEL1_Y

    def connect(self):
        auth_cookie = self._find_cookie()
        _log(f'auth_cookie found: {bool(auth_cookie)} (len={len(auth_cookie) if auth_cookie else 0})')
        disp_num = 0
        if self.display.startswith(':'):
            try:
                disp_num = int(self.display.split(':')[1].split('.')[0])
            except ValueError:
                disp_num = 0

        socket_path = f'/tmp/.X11-unix/X{disp_num}'
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(5.0)
        self.sock.connect(socket_path)

        # Connection setup request
        auth_name = b'MIT-MAGIC-COOKIE-1' if auth_cookie else b''
        auth_data = auth_cookie if auth_cookie else b''
        req = struct.pack('<BBHHHHH', ord('l'), 0, 11, 0, len(auth_name), len(auth_data), 0)
        req += _pad(auth_name) + _pad(auth_data)
        self.sock.sendall(req)

        header = self._recv_exact(8)
        status, _, major, minor, units = struct.unpack('<BBHHH', header)
        if status != 1:
            reason = self._recv_exact(units * 4) if units > 0 else b''
            raise RuntimeError(f'X11 connection rejected (status {status}): {reason!r}')

        body = self._recv_exact(units * 4)
        base, mask = struct.unpack_from('<II', body, 4)
        vendor_len = struct.unpack_from('<H', body, 16)[0]
        roots, formats = body[20], body[21]
        pos = 32 + ((vendor_len + 3) & ~3) + formats * 8

        self.root, self.default_colormap = struct.unpack_from('<II', body, pos)
        self.root_visual = struct.unpack_from('<I', body, pos + 32)[0]
        self.root_depth = body[pos + 38]
        num_depths = body[pos + 39]

        # Scan allowed depths for 32-bit TrueColor visual (class 4) for alpha transparency
        d_pos = pos + 40
        self.visual_32 = None
        for _ in range(num_depths):
            if d_pos + 8 > len(body):
                break
            d_val, _, num_types = struct.unpack_from('<BBH', body, d_pos)
            d_pos += 8
            for _ in range(num_types):
                if d_pos + 24 > len(body):
                    break
                v_id, v_class = struct.unpack_from('<IB', body, d_pos)
                if d_val == 32 and v_class == 4 and self.visual_32 is None:
                    self.visual_32 = v_id
                d_pos += 24

        bit1 = mask & -mask
        bit2 = (mask ^ bit1) & -(mask ^ bit1)
        bit3 = (mask ^ bit1 ^ bit2) & -(mask ^ bit1 ^ bit2)
        bit4 = (mask ^ bit1 ^ bit2 ^ bit3) & -(mask ^ bit1 ^ bit2 ^ bit3)
        self.window = base | bit1
        self.gc = base | bit2
        self.pixmap = base | bit1 | bit2
        self.mask_pixmap = base | bit3
        self.mask_gc = base | bit4

        if self.visual_32 is not None:
            self.depth = 32
            self.visual = self.visual_32
            self.colormap = base | bit4
            # CreateColormap (Opcode 78): mid, window(root), visual, alloc=0 (AllocNone)
            self._send_req_raw(struct.pack('<BBHIII', 78, 0, 4, self.colormap, self.root, self.visual_32))
            self.use_argb = True
            _log(f'Depth 32 ARGB active: visual={hex(self.visual_32)}, colormap={hex(self.colormap)}')
        else:
            self.depth = self.root_depth
            self.visual = self.root_visual
            self.colormap = self.default_colormap
            self.use_argb = False
            _log(f'Depth {self.depth} fallback (no 32-bit visual found)')

        # Create unmanaged override-redirect window
        # Value mask: CWBackPixel (0x02) | CWBorderPixel (0x08) | CWOverrideRedirect (0x0200) | CWColormap (0x2000)
        # Total mask: 0x220a = 8714
        bg_pixel = self._pixel(C_BG, alpha=C_BG_ALPHA if self.use_argb else 255)
        border_pixel = self._pixel(C_BORDER)
        val_bytes = struct.pack('<IIII', bg_pixel, border_pixel, 1, self.colormap)
        create_req = struct.pack('<IIhhHHHHII', self.window, self.root,
                                self.x, self.y, self.width, self.height, 0, 1, self.visual, 8714) + val_bytes
        self._send_req(1, self.depth, create_req)

        # Set WM_NAME and WM_CLASS matching Diablo II / Wine for Weston scanout
        self.set_property(39, b'Diablo II')
        self.set_property(67, b'game.exe\0game.exe\0')

        # Create double-buffered off-screen pixmap
        self._send_req(53, self.depth, struct.pack('<IIHH', self.pixmap, self.window, self.width, self.height))

        # Create Graphics Context (GC)
        # 0x0004 = GCForeground, 0x0008 = GCBackground
        self._send_req(55, 0, struct.pack('<IIIII', self.gc, self.window, 12, 0, 0))

        # Map window if level > 0
        if self.level > 0:
            self._send_req(8, 0, struct.pack('<I', self.window))

        # Stack mode Above (ConfigureWindow, stack-mode = 0)
        self._send_req(12, 0, struct.pack('<III', self.window, 64, 0))

        # Roundtrip to flush initial setup
        self._roundtrip()

        # Setup shape transparency if enabled
        if TRANSPARENT_BG:
            self._setup_shape_transparency()

        # Try to reparent into game window if game already opened its X11 window
        self.try_reparent_to_game()

    def set_level(self, new_level):
        """Switch HUD level dynamically, adjusting window geometry and pixmap."""
        if new_level == self.level:
            return
        old_level = self.level
        self.level = new_level
        _log(f'X11HUD switching level from {old_level} to {new_level}')

        if new_level == 0:
            if self.sock and self.window:
                self._send_req(10, 0, struct.pack('<I', self.window))
                self._roundtrip()
            return

        new_w, new_h = self._get_dimensions(new_level)
        new_x = self._get_default_x(new_level, width=new_w)
        new_y = self._get_default_y(new_level)

        if not self.sock or not self.window:
            self.width, self.height = new_w, new_h
            self.x, self.y = new_x, new_y
            return

        # Free old pixmap (Opcode 54)
        if self.pixmap:
            self._send_req(54, 0, struct.pack('<I', self.pixmap))

        # Create new pixmap with updated size (Opcode 53)
        self._send_req(53, self.depth, struct.pack('<IIHH', self.pixmap, self.window, new_w, new_h))

        # Resize and reposition window: ConfigureWindow (opcode 12)
        # Value mask: X(0x1) | Y(0x2) | Width(0x4) | Height(0x8) | StackMode(0x40) = 0x4f
        conf_payload = struct.pack('<IHHiiIII', self.window, 0x004f, 0, new_x, new_y, new_w, new_h, 0)
        self._send_req(12, 0, conf_payload)

        self.width, self.height = new_w, new_h
        self.x, self.y = new_x, new_y

        # If previously hidden, map window (Opcode 8)
        if old_level == 0:
            self._send_req(8, 0, struct.pack('<I', self.window))

        # Restack Above
        self._send_req(12, 0, struct.pack('<III', self.window, 64, 0))
        self._roundtrip()

    def _find_cookie(self):
        candidates = []
        for var in ('XAUTHORITY', 'PD2_XAUTHORITY'):
            val = os.environ.get(var)
            if val and val not in candidates:
                candidates.append(val)

        run_dir = os.environ.get('PD2_RUN', '')
        if run_dir:
            candidates.append(os.path.join(run_dir, 'xauthority'))

        candidates.extend(glob.glob('/tmp/pd2-r36s-*/xauthority'))
        candidates.extend(glob.glob('/run/pd2-r36s-*/xauthority'))
        candidates.extend(glob.glob('/run/*-r36s-*/xauthority'))

        home = os.environ.get('HOME', '')
        if home:
            candidates.append(os.path.join(home, '.Xauthority'))

        for p in candidates:
            if not os.path.isfile(p):
                continue
            try:
                with open(p, 'rb') as f:
                    data = f.read(4096)
                cookie = self._parse_xauth(data)
                _log(f'checking {p}, data_len={len(data)}, cookie_found={bool(cookie)}')
                if cookie:
                    return cookie
            except Exception as e:
                _log(f'error reading {p}: {e}')
                continue
        _log(f'no cookie found in candidates: {candidates}')
        return None

    @staticmethod
    def _parse_xauth(data):
        pos = 0
        while pos + 2 <= len(data):
            pos += 2  # skip family uint16
            fields = []
            for _ in range(4):
                if pos + 2 > len(data):
                    break
                length = struct.unpack_from('>H', data, pos)[0]
                pos += 2
                if pos + length > len(data):
                    break
                fields.append(data[pos:pos + length])
                pos += length
            if len(fields) == 4:
                address, number, name, cookie = fields
                if name == b'MIT-MAGIC-COOKIE-1' and len(cookie) == 16:
                    return cookie
        # Fallback binary search: name followed by 2-byte length then 16-byte cookie
        idx = data.find(b'MIT-MAGIC-COOKIE-1')
        if idx != -1 and idx + 36 <= len(data):
            candidate = data[idx + 20: idx + 36]
            if len(candidate) == 16:
                return candidate
        return None

    def _roundtrip(self):
        # Opcode 43: GetInputFocus -> flushes preceding requests and reads reply
        self._send_req(43, 0, b'')
        reply = self._recv_exact(32)
        if reply[0] == 1:
            extra_units = struct.unpack_from('<I', reply, 4)[0]
            if extra_units > 0:
                self._recv_exact(extra_units * 4)
        elif reply[0] == 0:
            err_code = reply[1]
            seq = struct.unpack_from('<H', reply, 2)[0]
            bad_val = struct.unpack_from('<I', reply, 4)[0]
            minor = reply[8]
            major = reply[9]
            _log(f'X11 Error: code={err_code}, seq={seq}, bad_val={hex(bad_val)}, major={major}, minor={minor}')
        return reply

    def set_property(self, atom, value):
        # Opcode 18: ChangeProperty (mode=0 Replace, format=8, type=31 STRING)
        padded = _pad(value)
        payload = struct.pack('<IIIB3xI', self.window, atom, 31, 8, len(value)) + padded
        self._send_req(18, 0, payload)

    def try_reparent_to_game(self):
        if self.use_argb or self.parent_is_game or not self.sock:
            return
        try:
            # QueryTree on root (Opcode 15)
            self._send_req(15, 0, struct.pack('<I', self.root))
            reply = self._recv_exact(32)
            if reply[0] != 1:
                return
            reply_len = struct.unpack_from('<I', reply, 4)[0]
            if reply_len == 0:
                return
            children_data = self._recv_exact(reply_len * 4)
            children = [struct.unpack_from('<I', children_data, i * 4)[0] for i in range(reply_len)]
            for child in reversed(children):
                if child == self.window:
                    continue
                # GetProperty on child (Opcode 20): property=67 (WM_CLASS), type=0
                req = struct.pack('<IIIII', child, 67, 0, 0, 32)
                self._send_req(20, 0, req)
                prop_reply = self._recv_exact(32)
                if prop_reply[0] != 1:
                    continue
                prop_data_units = struct.unpack_from('<I', prop_reply, 4)[0]
                val_bytes = self._recv_exact(prop_data_units * 4) if prop_data_units > 0 else b''
                val_lower = val_bytes.lower()
                if any(k in val_lower for k in (b'game', b'wine', b'diablo', b'explorer')):
                    _log(f'Found game window {hex(child)}: {val_bytes!r}. Reparenting HUD.')
                    # 1. Set WM_TRANSIENT_FOR to child
                    transient_payload = struct.pack('<IIIB3xII', self.window, 68, 33, 32, 1, int(child))
                    self._send_req(18, 0, transient_payload)

                    # 2. Reparent window into game window
                    reparent_payload = struct.pack('<IIhh', self.window, int(child), int(self.x), int(self.y))
                    self._send_req(7, 0, reparent_payload)

                    # 3. Raise above
                    self._send_req(12, 0, struct.pack('<III', self.window, 64, 0))

                    # 4. Map window under new parent
                    self._send_req(8, 0, struct.pack('<I', self.window))

                    self._roundtrip()
                    self.parent_is_game = True
                    _log(f'Successfully reparented to game window {hex(child)}')
                    break
        except Exception as e:
            _log(f'try_reparent_to_game exception: {e}')

    def _send_req(self, opcode, data_byte, payload):
        length = 1 + (len(payload) // 4)
        header = struct.pack('<BBH', opcode, data_byte, length)
        self.sock.sendall(header + payload)

    def _recv_exact(self, count):
        buf = bytearray()
        while len(buf) < count:
            chunk = self.sock.recv(count - len(buf))
            if not chunk:
                raise RuntimeError('X11 connection broken')
            buf.extend(chunk)
        return bytes(buf)

    def _pixel(self, rgb, alpha=255):
        r, g, b = rgb
        if self.use_argb:
            # Premultiplied ARGB
            r_pre = (r * alpha) // 255
            g_pre = (g * alpha) // 255
            b_pre = (b * alpha) // 255
            return ((alpha & 0xff) << 24) | ((r_pre & 0xff) << 16) | ((g_pre & 0xff) << 8) | (b_pre & 0xff)
        return ((r & 0xff) << 16) | ((g & 0xff) << 8) | (b & 0xff)

    def set_color(self, rgb, alpha=255):
        px = self._pixel(rgb, alpha=alpha)
        self._send_req(56, 0, struct.pack('<III', self.gc, 4, px))

    def fill_rect(self, x, y, w, h):
        rect = struct.pack('<hhHH', x, y, max(1, w), max(1, h))
        self._send_req(70, 0, struct.pack('<II', self.pixmap, self.gc) + rect)

    def draw_text(self, x, y, text, color, scale=1):
        self.set_color(color, alpha=255)
        rectangles = bytearray()
        step = 7 * scale
        curr_x = x
        for ch in text:
            hex_glyph = FONT_6X9.get(ch, FONT_6X9.get(ch.upper(), FONT_6X9[' ']))
            for row in range(9):
                row_val = int(hex_glyph[row * 2: (row + 1) * 2], 16)
                for col in range(6):
                    if row_val & (1 << (5 - col)):
                        rectangles.extend(struct.pack('<hhHH',
                            curr_x + col * scale, y + row * scale, scale, scale))
            curr_x += step

        if rectangles:
            payload = struct.pack('<II', self.pixmap, self.gc) + bytes(rectangles)
            self._send_req(70, 0, payload)

    def draw_chart(self, x, y, w, h, history, with_border=True, show_y_scale=False):
        # Frametime live line chart
        label_w = 16 if show_y_scale else 0
        chart_w = w - label_w - (4 if show_y_scale else 0)

        if with_border:
            # Draw chart container border
            self.set_color(C_BORDER, alpha=220 if self.use_argb else 255)
            self.fill_rect(x, y, chart_w, 1)                  # top
            self.fill_rect(x, y + h - 1, chart_w, 1)          # bottom
            self.fill_rect(x, y, 1, h)                        # left
            self.fill_rect(x + chart_w - 1, y, 1, h)          # right

        inner_x = x + (2 if with_border else 0)
        inner_y = y + (2 if with_border else 0)
        inner_w = max(1, chart_w - (4 if with_border else 0))
        inner_h = max(1, h - (4 if with_border else 0))

        # In show_y_scale mode, max scale is 50.0ms; otherwise 80.0ms (supports down to 12.5 FPS)
        max_ms = 50.0 if show_y_scale else 80.0

        # Y scale ticks and horizontal grid lines for 50, 40, 30, 20, 10, 0 ms
        if show_y_scale:
            for val in (50, 40, 30, 20, 10, 0):
                norm = val / 50.0
                ty = inner_y + inner_h - 1 - int(norm * (inner_h - 1))
                # Subtle grid line
                self.set_color((28, 34, 44), alpha=160 if self.use_argb else 255)
                self.fill_rect(inner_x, ty, inner_w, 1)
                # Tick outside chart
                self.set_color(C_BORDER, alpha=200 if self.use_argb else 255)
                self.fill_rect(x + chart_w, ty, 2, 1)
                # Label
                self.draw_text(x + chart_w + 4, ty - 4, f'{val:>2}', C_MUTED)
        elif inner_h >= 14:
            # Subtle 50.0ms (20 FPS) target threshold guide line
            y_guide = inner_y + inner_h - 1 - int(min(1.0, 50.0 / max_ms) * (inner_h - 1))
            self.set_color((25, 30, 40), alpha=150 if self.use_argb else 255)
            self.fill_rect(inner_x, y_guide, inner_w, 1)

        if not history:
            self.set_color(C_CHART_OK, alpha=255)
            self.fill_rect(inner_x, inner_y + inner_h // 2, inner_w, 1)
            return

        samples = list(history)
        n_samples = len(samples)

        prev_py = None
        for col in range(inner_w):
            px = inner_x + col
            # Map column across all available samples
            if n_samples <= inner_w:
                idx = int(col * (n_samples - 1) / max(1, inner_w - 1))
            else:
                idx = n_samples - inner_w + col
            val = float(samples[min(idx, n_samples - 1)])

            norm = min(max_ms, max(0.0, val)) / max_ms
            py = inner_y + inner_h - 1 - int(norm * (inner_h - 1))
            color = get_chart_color(val)

            if prev_py is not None:
                y_start = min(prev_py, py)
                y_len = max(1, abs(prev_py - py) + 1)
                self.set_color(color, alpha=255)
                self.fill_rect(px, y_start, 1, y_len)
            else:
                self.set_color(color, alpha=255)
                self.fill_rect(px, py, 1, 1)
            prev_py = py

    def _setup_shape_transparency(self):
        try:
            name = b'SHAPE'
            pad = b'\0' * (-len(name) % 4)
            req = struct.pack('<BBHH2x', 98, 0, 2 + (len(name) + len(pad)) // 4, len(name)) + name + pad
            self._send_req_raw(req)
            reply = self._recv_exact(32)
            if reply[0] != 1 or reply[8] == 0:
                _log('SHAPE extension not available')
                return
            shape_opcode = reply[9]

            # 1-bit mask Pixmap
            mask_pm = self.mask_pixmap
            mask_gc = self.mask_gc

            pm_req = struct.pack('<BBH', 53, 1, 4) + struct.pack('<IIHH', mask_pm, self.window, self.width, self.height)
            self._send_req_raw(pm_req)

            gc_req = struct.pack('<BBH', 55, 0, 4) + struct.pack('<III', mask_gc, mask_pm, 0)
            self._send_req_raw(gc_req)

            # 50% checkerboard dither mask (even rows 0xAA, odd rows 0x55)
            row_bytes = (self.width + 7) // 8
            padded_row_bytes = (row_bytes + 3) & ~3
            data = bytearray()
            for row in range(self.height):
                b = 0xAA if (row % 2 == 0) else 0x55
                row_data = bytes([b] * row_bytes)
                row_data += b'\0' * (padded_row_bytes - row_bytes)
                data.extend(row_data)

            put_hdr = struct.pack('<IIHHhhBBH', mask_pm, mask_gc, self.width, self.height, 0, 0, 0, 1, 0)
            length = 1 + (len(put_hdr) + len(data)) // 4
            self._send_req_raw(struct.pack('<BBH', 72, 0, length) + put_hdr + bytes(data))

            # ShapeMask request: opcode, minor=2, length=5 units
            # Payload: op (0=ShapeSet), kind (0=ShapeBounding), 2x pad, window, x_off (0), y_off (0), mask_pm
            shape_payload = struct.pack('<BB2xIhhI', 0, 0, self.window, 0, 0, mask_pm)
            shape_req = struct.pack('<BBH', shape_opcode, 2, 1 + len(shape_payload) // 4) + shape_payload
            self._send_req_raw(shape_req)
            self._roundtrip()
            _log('Successfully applied 50% transparency shape mask')
        except Exception as e:
            _log(f'Shape transparency failed (fallback to solid): {e}')

    def _send_req_raw(self, raw_bytes):
        self.sock.sendall(raw_bytes)

    def render(self, metrics, fps_info):
        if not self.sock:
            return

        fps = fps_info.get('fps', 0)

        # In Level 1, skip redrawing if FPS value has not changed
        if self.level == 1 and self._prev_rendered_fps == fps:
            return
        self._prev_rendered_fps = fps

        if not self.use_argb and not self.parent_is_game:
            self.try_reparent_to_game()

        # Re-stack window occasionally, not on every frame
        self._frame_count += 1
        if self._frame_count % 30 == 1:
            self._send_req(12, 0, struct.pack('<III', self.window, 64, 0))

        w, h = self.width, self.height

        # Background fill (semi-transparent in depth 32 ARGB)
        self.set_color(C_BG, alpha=C_BG_ALPHA if self.use_argb else 255)
        self.fill_rect(0, 0, w, h)

        # Border frame
        self.set_color(C_BORDER, alpha=230 if self.use_argb else 255)
        self.fill_rect(0, 0, w, 1)
        self.fill_rect(0, h - 1, w, 1)
        self.fill_rect(0, 0, 1, h)
        self.fill_rect(w - 1, 0, 1, h)

        fps = fps_info.get('fps', 0)

        if self.level == 1:
            self._render_level_1(fps)
        elif self.level == 2:
            self._render_level_2(metrics, fps_info)
        elif self.level == 3:
            self._render_level_3(metrics, fps_info)
        elif self.level == 4:
            self._render_level_4(metrics, fps_info)

        # Copy backbuffer pixmap to visible window (XCopyArea opcode 62)
        # Payload: src(pixmap), dst(window), gc, src_x(0), src_y(0), dst_x(0), dst_y(0), w, h
        copy_payload = struct.pack('<IIIhhhhHH', self.pixmap, self.window, self.gc, 0, 0, 0, 0, w, h)
        self._send_req(62, 0, copy_payload)

    def _render_level_1(self, fps):
        # R36S Level 1: Minimal pill with only FPS value
        fps_str = f'{fps:>2}'
        self.draw_text(6, 4, fps_str, C_VAL_FPS)

    def _render_level_2(self, metrics, fps_info):
        # R36S Level 2: Compact Horizontal Status Bar
        fps = fps_info.get('fps', 0)
        history = fps_info.get('history', [])
        cpu_pct = metrics.get('cpu_total', 0)
        gpu_pct = metrics.get('gpu_pct', 0)
        ram_mb = metrics.get('ram_used_mb', 0)
        bat_pct = metrics.get('battery_pct', 100)
        plugged = metrics.get('plugged', False)

        y = 5
        x = 8

        # 1. FPS label & value
        self.draw_text(x, y, 'FPS', C_LABEL_FPS); x += 25
        fps_text = f'{fps:>2}'
        self.draw_text(x, y, fps_text, C_VAL_FPS); x += 18

        # 2. Separator
        self.draw_text(x, y, '|', C_SEP); x += 12

        # 3. Small live frametime line chart
        self.draw_chart(x, y, 42, 9, history, with_border=False); x += 46

        # 4. Separator
        self.draw_text(x, y, '|', C_SEP); x += 12

        # 5. CPU % (frequency omitted per request)
        self.draw_text(x, y, 'CPU', C_LABEL_CPU); x += 25
        cpu_text = f'{cpu_pct:>2}%'
        self.draw_text(x, y, cpu_text, C_VAL_CPU); x += len(cpu_text) * 7 + 5

        # 6. Separator
        self.draw_text(x, y, '|', C_SEP); x += 12

        # 7. GPU %
        self.draw_text(x, y, 'GPU', C_LABEL_GPU); x += 25
        gpu_text = f'{gpu_pct:>2}%'
        self.draw_text(x, y, gpu_text, C_VAL_GPU); x += len(gpu_text) * 7 + 5

        # 8. Separator
        self.draw_text(x, y, '|', C_SEP); x += 12

        # 9. RAM
        self.draw_text(x, y, 'RAM', C_LABEL_RAM); x += 25
        ram_text = f'{ram_mb}M'
        self.draw_text(x, y, ram_text, C_VAL_RAM); x += len(ram_text) * 7 + 5

        # 10. Separator
        self.draw_text(x, y, '|', C_SEP); x += 12

        # 11. BATT
        self.draw_text(x, y, 'BATT', C_LABEL_BAT); x += 32
        if plugged:
            self.draw_text(x, y, '~', C_PLUG); x += 10
        bat_text = f'{bat_pct}%'
        self.draw_text(x, y, bat_text, C_VAL_BAT)

    def _render_level_3(self, metrics, fps_info):
        # R36S Level 3: Multi-Line HUD
        fps = fps_info.get('fps', 0)
        ft = fps_info.get('frametime_ms', 0.0)
        min_fps = fps_info.get('min_fps', 0)
        max_fps = fps_info.get('max_fps', 0)
        history = fps_info.get('history', [])

        cpu_pct = metrics.get('cpu_total', 0)
        cpu_mhz = metrics.get('cpu_mhz', 1296)
        cpu_temp = metrics.get('cpu_temp', 0)
        gpu_pct = metrics.get('gpu_pct', 0)
        gpu_mhz = metrics.get('gpu_mhz', 500)
        ram_used = metrics.get('ram_used_mb', 0)
        ram_total = metrics.get('ram_total_mb', 1024)
        bat_pct = metrics.get('battery_pct', 100)
        bat_volts = metrics.get('battery_volts', 4.1)
        plugged = metrics.get('plugged', False)

        y = 5
        # GPU block (mimics Level 4)
        self.draw_text(8, y, 'GPU', C_LABEL_GPU)
        self.draw_text(40, y, f'{gpu_pct:>2}%', C_VAL_GPU)
        self.draw_text(110, y, f'{cpu_temp}°C', C_VAL_GPU)
        y += 12
        self.draw_text(40, y, f'{gpu_mhz} MHz', C_MUTED)

        # CPU block (mimics Level 4)
        y += 12
        self.draw_text(8, y, 'CPU', C_LABEL_CPU)
        self.draw_text(40, y, f'{cpu_pct:>2}%', C_VAL_CPU)
        self.draw_text(110, y, f'{cpu_temp}°C', C_VAL_CPU)
        y += 12
        self.draw_text(40, y, f'{cpu_mhz} MHz', C_MUTED)

        # RAM block
        y += 12
        self.draw_text(8, y, 'RAM', C_LABEL_RAM)
        self.draw_text(40, y, f'{ram_used}M', C_VAL_RAM)
        self.draw_text(110, y, f'/ {ram_total}M', C_MUTED)

        # BATT block
        y += 12
        self.draw_text(8, y, 'BATT', C_LABEL_BAT)
        x_bat = 40
        if plugged:
            self.draw_text(x_bat, y, '~', C_PLUG); x_bat += 10
        self.draw_text(x_bat, y, f'{bat_pct}%', C_VAL_BAT)
        self.draw_text(110, y, f'{bat_volts}V', C_MUTED)

        avg_fps = fps_info.get('avg_fps', 0.0)
        low_1pct = fps_info.get('low_1pct', 0.0)
        low_01pct = fps_info.get('low_01pct', 0.0)

        # FPS sections (replaces GAMESCOPE per user specification)
        y += 12
        self.draw_text(8, y, 'FPS', C_LABEL_FPS)
        self.draw_text(76, y, f'{fps:>3} FPS', C_VAL_FPS)

        y += 12
        self.draw_text(8, y, 'AVG', C_LABEL_FPS)
        self.draw_text(76, y, f'{int(avg_fps):>3} FPS', C_VAL_FPS)

        y += 12
        self.draw_text(8, y, '1% LOW', C_LABEL_FPS)
        self.draw_text(76, y, f'{int(low_1pct):>3} FPS', C_VAL_FPS)

        y += 12
        self.draw_text(8, y, '0.1%low', C_LABEL_FPS)
        self.draw_text(76, y, f'{int(low_01pct):>3} FPS', C_VAL_FPS)

        # Frametime block
        y += 12
        self.draw_text(8, y, 'Frametime', C_LABEL_BAT)
        self.draw_text(76, y, f'{ft:.1f}ms', C_MUTED)

        # Frametime Live Line Chart across full width inside border, taking full remaining height
        chart_x = 8
        chart_y = y + 10
        chart_w = self.width - 16
        chart_h = max(10, self.height - chart_y - 4)
        self.draw_chart(chart_x, chart_y, chart_w, chart_h, history, with_border=True)

    def _render_level_4(self, metrics, fps_info):
        # R36S Level 4: Full Detailed HUD with live frametime graph & Y scale
        fps = fps_info.get('fps', 0)
        ft = fps_info.get('frametime_ms', 0.0)
        min_fps = fps_info.get('min_fps', 0)
        max_fps = fps_info.get('max_fps', 0)
        history = fps_info.get('history', [])

        cpu_pct = metrics.get('cpu_total', 0)
        cpu_mhz = metrics.get('cpu_mhz', 1296)
        cpu_temp = metrics.get('cpu_temp', 0)
        cores = metrics.get('cpu_cores', [])
        gpu_pct = metrics.get('gpu_pct', 0)
        gpu_mhz = metrics.get('gpu_mhz', 500)
        ram_used = metrics.get('ram_used_mb', 0)
        ram_total = metrics.get('ram_total_mb', 1024)
        bat_pct = metrics.get('battery_pct', 100)
        bat_volts = metrics.get('battery_volts', 4.1)
        plugged = metrics.get('plugged', False)

        y = 5
        # Header: Time HH:MM:SS   R36S 1.0
        time_str = time.strftime('%H:%M:%S')
        self.draw_text(8, y, f'Time {time_str}', C_VAL_BAT)
        self.draw_text(138, y, 'R36S 1.0', C_MUTED)

        # GPU block
        y += 12
        self.draw_text(8, y, 'GPU', C_LABEL_GPU)
        self.draw_text(40, y, f'{gpu_pct:>2}%', C_VAL_GPU)
        self.draw_text(110, y, f'{cpu_temp}°C', C_VAL_GPU)
        y += 12
        self.draw_text(40, y, f'{gpu_mhz} MHz', C_MUTED)

        # CPU block
        y += 12
        self.draw_text(8, y, 'CPU', C_LABEL_CPU)
        self.draw_text(40, y, f'{cpu_pct:>2}%', C_VAL_CPU)
        self.draw_text(110, y, f'{cpu_temp}°C', C_VAL_CPU)
        y += 12
        self.draw_text(40, y, f'{cpu_mhz} MHz', C_MUTED)

        # CPU per-core (4 cores on RK3326)
        for i in range(min(4, len(cores))):
            y += 12
            c_pct = cores[i]
            self.draw_text(8, y, f'CPU{i}', C_LABEL_CPU)
            self.draw_text(40, y, f'{c_pct:>2}%', C_VAL_CPU)
            self.draw_text(110, y, f'{cpu_mhz} MHz', C_MUTED)

        # RAM block
        y += 12
        self.draw_text(8, y, 'RAM', C_LABEL_RAM)
        self.draw_text(40, y, f'{ram_used}M', C_VAL_RAM)
        self.draw_text(110, y, f'/ {ram_total}M', C_MUTED)

        # Battery block
        y += 12
        self.draw_text(8, y, 'BATT', C_LABEL_BAT)
        x_b = 40
        if plugged:
            self.draw_text(x_b, y, '~', C_PLUG); x_b += 10
        self.draw_text(x_b, y, f'{bat_pct}%', C_VAL_BAT)
        self.draw_text(110, y, f'{bat_volts}V', C_MUTED)

        avg_fps = fps_info.get('avg_fps', 0.0)
        low_1pct = fps_info.get('low_1pct', 0.0)
        low_01pct = fps_info.get('low_01pct', 0.0)

        # FPS sections (replaces GAMESCOPE per user specification)
        y += 12
        self.draw_text(8, y, 'FPS', C_LABEL_FPS)
        self.draw_text(76, y, f'{fps:>3} FPS', C_VAL_FPS)

        y += 12
        self.draw_text(8, y, 'AVG', C_LABEL_FPS)
        self.draw_text(76, y, f'{int(avg_fps):>3} FPS', C_VAL_FPS)

        y += 12
        self.draw_text(8, y, '1% LOW', C_LABEL_FPS)
        self.draw_text(76, y, f'{int(low_1pct):>3} FPS', C_VAL_FPS)

        y += 12
        self.draw_text(8, y, '0.1%low', C_LABEL_FPS)
        self.draw_text(76, y, f'{int(low_01pct):>3} FPS', C_VAL_FPS)

        # Frametime block
        y += 12
        self.draw_text(8, y, 'Frametime', C_LABEL_BAT)
        self.draw_text(76, y, f'{ft:.1f}ms', C_MUTED)

        # Live Frametime Line Graph across full width inside border
        chart_x = 8
        chart_y = y + 10
        chart_w = self.width - 16
        chart_h = 48
        self.draw_chart(chart_x, chart_y, chart_w, chart_h, history, with_border=True, show_y_scale=False)

        # Display Hz
        y = chart_y + chart_h + 3
        self.draw_text(8, y, 'Display Hz', C_LABEL_BAT)
        self.draw_text(110, y, '60', C_VAL_FPS)

    def close(self):
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass
            self.sock = None
