"""CORE X11 wire tests: no display, installed GUI libraries or game required."""
import os
from pathlib import Path
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock

SCRIPTS = Path(__file__).resolve().parents[1] / 'sdcard/ports/projectdiablo2/scripts'
sys.path.insert(0, str(SCRIPTS))
import menu_x11 as x11

FONT = {' ': '00000000000000', '>': '08040201020408',
        'A': '0E11111F111111'}
LABELS = ('640x480', '640x480', '800x600', '1024x768', '1068x600')


def setup_body():
    body = bytearray(32)
    struct.pack_into('<IIIIHH', body, 0, 1, 0x200000, 0x1fffff, 0, 0, 4096)
    body[20:28] = bytes((1, 1, 0, 0, 32, 32, 8, 255))
    body += bytes((24, 32, 32, 0, 0, 0, 0, 0))
    root = bytearray(40)
    struct.pack_into('<II', root, 0, 0x100, 0x20)
    struct.pack_into('<HHHH', root, 20, 640, 480, 160, 120)
    struct.pack_into('<I', root, 32, 0x21)
    root[38:40] = bytes((24, 1))
    body += root + struct.pack('<BxH4x', 24, 1)
    body += struct.pack('<IBBHIIII', 0x21, 4, 8, 256, 0xff0000, 0xff00, 0xff, 0)
    return bytes(body)


def reply(sequence, body=b'', detail=0):
    result = bytearray(32)
    struct.pack_into('<BBHI', result, 0, 1, detail, sequence, len(body) // 4)
    return bytes(result) + body


def event(kind, window, key=0, stamp=0):
    result = bytearray(32)
    result[0:2] = bytes((kind, key))
    if kind in (2, 3):
        struct.pack_into('<I', result, 4, stamp)
    offset = 4 if kind == 12 else 12 if kind in (2, 3) else 8
    struct.pack_into('<I', result, offset, window)
    return bytes(result)


class FakeSocket:
    """Little-endian X server, fragments every response down to one byte."""
    def __init__(self, *, chunk=1, mapped=True, exposed=True, viewable=True,
                 bad_request=None, held=(), initial=(), setup=None):
        self.incoming = bytearray()
        self.requests = []
        self.connected = None
        self.closed = False
        self.chunk = chunk
        self.sequence = 0
        self.mapped, self.exposed, self.viewable = mapped, exposed, viewable
        self.bad_request, self.held, self.initial = bad_request, held, initial
        self.setup = setup_body() if setup is None else setup
        self.timeouts = []

    def connect(self, path):
        self.connected = path

    def settimeout(self, timeout):
        self.timeouts.append(timeout)

    def sendall(self, data):
        data = bytes(data)
        self.requests.append(data)
        if data[0] == ord('l') and len(self.requests) == 1:
            self.incoming.extend(struct.pack('<BBHHH', 1, 0, 11, 0, len(self.setup) // 4) + self.setup)
            return
        self.sequence = (self.sequence + 1) & 65535
        opcode, detail, units = struct.unpack_from('<BBH', data)
        assert len(data) == units * 4
        if opcode == 1:
            self.window = struct.unpack_from('<I', data, 4)[0]
        if opcode == self.bad_request:
            error = bytearray(32)
            error[1] = 3
            struct.pack_into('<H', error, 2, self.sequence)
            error[10] = opcode
            self.incoming.extend(error)
        elif opcode == 101:
            low, count = data[4:6]
            mapping = {38: 0xff0d, 40: 0xff52, 41: 0xff1b, 42: 0x20}
            self.incoming.extend(reply(self.sequence, b''.join(struct.pack('<I', mapping.get(k, 0)) for k in range(low, low + count)), 1))
        elif opcode == 1:
            self.window = struct.unpack_from('<I', data, 4)[0]
        elif opcode == 8:
            if self.mapped:
                self.incoming.extend(event(19, self.window))
            if self.exposed:
                self.incoming.extend(event(12, self.window))
            for kind, code in self.initial:
                self.incoming.extend(event(kind, self.window, code))
        elif opcode == 43:
            self.incoming.extend(reply(self.sequence))
        elif opcode == 3:
            response = bytearray(reply(self.sequence, bytes(12)))
            response[26] = 2 if self.viewable else 1
            self.incoming.extend(response)
        elif opcode == 44:
            keys = bytearray(32)
            for code in self.held:
                keys[code // 8] |= 1 << (code % 8)
            response = bytearray(reply(self.sequence, bytes(8)))
            response[8:40] = keys
            self.incoming.extend(response)

    def recv(self, count):
        if not self.incoming:
            raise TimeoutError()
        count = min(count, self.chunk, len(self.incoming))
        data = bytes(self.incoming[:count])
        del self.incoming[:count]
        return data

    def close(self):
        self.closed = True


def ready(sockets, *_args):
    return ([sockets[0]] if sockets[0].incoming else [], [], [])


class Menu:
    row = 3
    resolution = 0
    fps = False
    fps_changed = False
    audio = 'default'


class ProtocolTests(unittest.TestCase):
    def screen(self, server=None):
        server = server or FakeSocket()
        with mock.patch.object(x11.x11_probe, '_auth_status', return_value=('ready', b'k' * 16)), \
             mock.patch.object(x11.socket, 'socket', return_value=server), \
             mock.patch.object(x11.socket, 'AF_UNIX', 1, create=True):
            screen = x11.Screen(FONT, LABELS)
        self.addCleanup(screen.close)
        return screen, server

    def test_authenticated_setup_managed_window_and_kiosk_properties(self):
        screen, server = self.screen()
        self.assertEqual(server.connected, '/tmp/.X11-unix/X0')
        self.assertEqual(server.requests[0], struct.pack('<BBHHHHH', 108, 0, 11, 0, 18, 16, 0) + b'MIT-MAGIC-COOKIE-1\0\0' + b'k' * 16)
        create = next(p for p in server.requests[1:] if p[0] == 1)
        self.assertEqual(create[1], 24)
        self.assertEqual(struct.unpack_from('<HH', create, 16), (640, 480))
        self.assertEqual(struct.unpack_from('<H', create, 22)[0], 1)
        self.assertEqual(struct.unpack_from('<I', create, 28)[0], 2 | 2048 | 8192)
        properties = [p for p in server.requests[1:] if p[0] == 18]
        self.assertEqual([struct.unpack_from('<I', p, 8)[0] for p in properties], [39, 67])
        self.assertEqual(properties[0][24:33], b'Diablo II')
        self.assertEqual(properties[1][24:42], b'game.exe\0game.exe\0')
        self.assertTrue(screen._mapped and screen._exposed)
        self.assertTrue(all(0 < value <= x11.TIMEOUT for value in server.timeouts))

    def test_auth_fails_before_any_connection(self):
        with mock.patch.object(x11.x11_probe, '_auth_status', return_value=('invalid', None)), \
             mock.patch.object(x11.socket, 'socket') as factory:
            with self.assertRaises(x11.MenuDisplayError) as raised:
                x11.Screen(FONT, LABELS)
            self.assertEqual(raised.exception.code, 'auth_failed')
            factory.assert_not_called()

    def test_no_hidden_success_without_actual_map_expose_and_viewability(self):
        for kwargs in ({'mapped': False}, {'exposed': False}, {'viewable': False}):
            server = FakeSocket(**kwargs)
            with self.subTest(kwargs=kwargs), self.assertRaises(OSError):
                self.screen(server)
            self.assertTrue(server.closed)

    def test_create_and_draw_server_errors_fail_closed(self):
        server = FakeSocket(bad_request=1)
        with self.assertRaises(x11.MenuDisplayError) as raised:
            self.screen(server)
        self.assertEqual(raised.exception.code, 'protocol_error')
        self.assertTrue(server.closed)
        screen, server = self.screen()
        server.bad_request = 70
        with self.assertRaises(x11.MenuDisplayError):
            screen.draw(Menu())

    def test_draw_batched_bounded_rectangles_and_roundtrip(self):
        screen, server = self.screen()
        screen.font = {char: '1F1F1F1F1F1F1F' for char in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 -:/<>.'}
        screen.maximum = 64  # Exercise request splitting, not just recv fragmentation.
        screen.draw(Menu())
        draws = [p for p in server.requests[1:] if p[0] == 70]
        self.assertGreater(len(draws), 20)
        for packet in draws:
            self.assertLessEqual(len(packet), 256)
            for offset in range(12, len(packet), 8):
                x, y, width, height = struct.unpack_from('<hhHH', packet, offset)
                self.assertTrue(0 <= x < 640 and 0 <= y < 480)
                self.assertTrue(width > 0 and height > 0 and x + width <= 640 and y + height <= 480)
        self.assertEqual(server.requests[-1][0], 43)
        with self.assertRaises(ValueError):
            screen._rectangles([(639, 0, 3, 3)], (0, 0, 0), 1e20)
        for resolution in range(5):
            menu = Menu()
            menu.resolution = resolution
            screen.draw(menu)

    def test_missing_inherited_resolution_draws_lcd_default(self):
        screen, _ = self.screen()
        with mock.patch.object(screen, '_text') as text:
            screen.draw(Menu())
        labels = [call.args[2] for call in text.call_args_list]
        self.assertIn('  RESOLUTION: 640x480', labels)
        self.assertNotIn('  RESOLUTION: 800x600', labels)

    def test_current_four_row_labels_and_selection_bounds(self):
        import start_menu
        screen, _ = self.screen()
        with mock.patch.dict(os.environ, {'PD2_GAME_RESOLUTION': '800x600', 'PD2_FPS': '0'}):
            menu = start_menu.Menu()
        with mock.patch.object(screen, '_text') as text:
            screen.draw(menu)
        labels = [call.args[2] for call in text.call_args_list]
        self.assertIn('> ENTER SANCTUARY / LAUNCH', labels)
        self.assertIn('  EXIT TO SYSTEM', labels)
        self.assertIn('  PERF OVERLAY: OFF', labels)
        self.assertIn('  RESOLUTION: 800x600', labels)
        self.assertFalse(any('DEFAULT' in label for label in labels))
        for row in range(4):
            menu.row = row
            screen.draw(menu)
        for row in (-1, 4, 5):
            menu.row = row
            with self.assertRaises(ValueError):
                screen.draw(menu)

    def test_resolved_labels_and_all_rows_fit_inside_highlight(self):
        import start_menu
        screen, _ = self.screen()
        for inherited in ('640x480', '800x600', '1024x768', 'native'):
            for fps in ('0', '1', '2', '3', '4'):
                with mock.patch.dict(os.environ, {'PD2_GAME_RESOLUTION': inherited, 'PD2_FPS': fps}):
                    menu = start_menu.Menu()
                with mock.patch.object(screen, '_text') as text:
                    screen.draw(menu)
                labels = [call.args[2] for call in text.call_args_list]
                expected = '1068x600' if inherited == 'native' else inherited
                expected_overlay = {'0': 'OFF', '1': 'LEVEL 1', '2': 'LEVEL 2', '3': 'LEVEL 3', '4': 'LEVEL 4'}[fps]
                self.assertIn('  RESOLUTION: ' + expected, labels)
                self.assertIn('  PERF OVERLAY: ' + expected_overlay, labels)
                for resolution in range(len(screen.labels)):
                    menu.resolution = resolution
                    with mock.patch.object(screen, '_text') as text:
                        screen.draw(menu)
                    for call in text.call_args_list:
                        x, y, label = call.args[:3]
                        if y in (118, 168, 218, 268):
                            self.assertLessEqual(x + len(label) * 18 - 3, 604)

    def test_frame_is_composed_offscreen_and_published_once(self):
        screen, server = self.screen()
        create = next(p for p in server.requests[1:] if p[0] == 53)
        self.assertEqual(create[1], screen.depth)
        self.assertEqual(struct.unpack_from('<IIHH', create, 4),
                         (screen.pixmap, screen.window, 640, 480))
        self.assertEqual(len({screen.window, screen.gc, screen.pixmap}), 3)
        before = len(server.requests)
        screen.draw(Menu())
        packets = server.requests[before:]
        draws = [p for p in packets if p[0] == 70]
        self.assertTrue(draws)
        self.assertTrue(all(struct.unpack_from('<II', p, 4) ==
                            (screen.pixmap, screen.gc) for p in draws))
        copies = [p for p in packets if p[0] == 62]
        self.assertEqual(len(copies), 1)
        # CORE CopyArea order: source xy, destination xy, then width/height.
        self.assertEqual(struct.unpack_from('<IIIhhhhHH', copies[0], 4),
                         (screen.pixmap, screen.window, screen.gc, 0, 0, 0, 0, 640, 480))
        self.assertEqual([p[0] for p in packets[-2:]], [62, 43])
        with mock.patch.object(x11.select, 'select', side_effect=ready):
            before = len(server.requests)
            for _ in range(100):
                self.assertEqual(screen.actions(), [])
            self.assertEqual(len(server.requests), before)

    def test_pixmap_and_copy_errors_fail_closed(self):
        server = FakeSocket(bad_request=53)
        with self.assertRaises(x11.MenuDisplayError):
            self.screen(server)
        self.assertTrue(server.closed)
        screen, server = self.screen()
        server.bad_request = 62
        with self.assertRaises(x11.MenuDisplayError):
            screen.draw(Menu())

    def test_keyboard_mapping_held_entry_and_release_arming(self):
        screen, server = self.screen(FakeSocket(held=(38,), initial=((2, 38), (2, 40))))
        with mock.patch.object(x11.select, 'select', side_effect=ready):
            server.incoming.extend(event(2, screen.window, 38))
            self.assertEqual(screen.actions(), [])
            server.incoming.extend(event(3, screen.window, 38) + event(2, screen.window, 38, stamp=1))
            self.assertEqual(screen.actions(), ['accept'])
            server.incoming.extend(event(2, screen.window, 38))
            self.assertEqual(screen.actions(), [])
            server.incoming.extend(event(3, screen.window, 40) + event(2, screen.window, 40, stamp=1))
            self.assertEqual(screen.actions(), ['up'])
            server.incoming.extend(event(2, screen.window, 41))
            self.assertEqual(screen.actions(), ['cancel'])

    def test_legacy_autorepeat_does_not_rearm_held_enter(self):
        screen, server = self.screen(FakeSocket(held=(38,)))
        with mock.patch.object(x11.select, 'select', side_effect=ready):
            for stamp in (100, 200, 300):
                server.incoming.extend(event(3, screen.window, 38, stamp))
                self.assertEqual(screen.actions(), [])
                server.incoming.extend(event(2, screen.window, 38, stamp))
                self.assertEqual(screen.actions(), [])
            server.incoming.extend(event(3, screen.window, 38, 400))
            self.assertEqual(screen.actions(), [])
            server.incoming.extend(event(2, screen.window, 38, 500))
            self.assertEqual(screen.actions(), ['accept'])

    def test_expose_repaints_and_disconnect_is_not_success(self):
        screen, server = self.screen()
        screen.draw(Menu())
        before = len(server.requests)
        server.incoming.extend(event(12, screen.window))
        with mock.patch.object(x11.select, 'select', side_effect=ready):
            self.assertEqual(screen.actions(), [])
        self.assertGreater(len(server.requests), before)
        with mock.patch.object(x11.select, 'select', return_value=([server], [], [])), \
             mock.patch.object(server, 'recv', return_value=b''):
            with self.assertRaises(x11.MenuDisplayError) as raised:
                screen.actions()
        self.assertEqual(raised.exception.code, 'disconnected')

    def test_frame_parsing_bounds_errors_and_partial_timeout(self):
        screen, server = self.screen()
        for data in (reply(1, detail=0)[:4] + struct.pack('<I', 0xffffffff) + bytes(24),
                     bytes(32), bytes((12,))):
            server.incoming[:] = data
            with self.assertRaises(OSError):
                screen._frame(__import__('time').monotonic() + 0.1)
        with self.assertRaises(x11.MenuDisplayError) as raised:
            screen._frame(0)
        self.assertEqual(raised.exception.code, 'timeout')

    def test_setup_rejects_truncation_bad_root_masks_and_resource_ids(self):
        good = setup_body()
        self.assertEqual(x11._setup(good)[-1], (0x100, 0x20, 0x21, 24, (0xff0000, 0xff00, 0xff)))
        for length in range(len(good)):
            with self.subTest(length=length), self.assertRaises(OSError):
                x11._setup(good[:length])
        for offset, value, fmt in ((4, 0, '<I'), (8, 1, '<I'), (40, 0, '<I'),
                                    (44, 0, '<I'), (78, 16, '<B'), (92, 3, '<B'),
                                    (96, 0x00ff00, '<I'), (96, 0xa00000, '<I')):
            bad = bytearray(good)
            struct.pack_into(fmt, bad, offset, value)
            with self.subTest(offset=offset, value=value), self.assertRaises(OSError):
                x11._setup(bad)

    def test_close_idempotent_and_closed_methods_fail(self):
        screen, server = self.screen()
        screen.close()
        screen.close()
        self.assertTrue(server.closed)
        with self.assertRaises(OSError):
            screen.draw(Menu())
        with self.assertRaises(OSError):
            screen.actions()

    def test_setup_rejection_headers_and_bad_keyboard_reply(self):
        class BadServer(FakeSocket):
            def sendall(self, data):
                super().sendall(data)
                if len(self.requests) == 1:
                    self.incoming[0] = status
                elif data[0] == 101:
                    self.incoming[1] = 0
        for status in (0, 2, 3, 1):
            server = BadServer()
            with self.subTest(status=status), self.assertRaises(x11.MenuDisplayError) as raised:
                self.screen(server)
            self.assertEqual(raised.exception.code, 'auth_failed' if status in (0, 2) else 'setup_invalid' if status == 3 else 'protocol_error')
            self.assertTrue(server.closed)

    def test_socketpair_server_parses_fragmented_requests_and_replies(self):
        try:
            client, peer = socket.socketpair()
        except (AttributeError, OSError):
            self.skipTest('socketpair unavailable')
        peer.settimeout(3)
        protocol = FakeSocket()
        failures = []
        class ConnectedClient:
            def connect(self, path):
                if path != '/tmp/.X11-unix/X0':
                    raise AssertionError('nonlocal endpoint')
            def __getattr__(self, name):
                return getattr(client, name)
        def receive(count):
            result = bytearray()
            while len(result) < count:
                chunk = peer.recv(1)
                if not chunk:
                    if not result:
                        return None
                    raise AssertionError('truncated client request')
                result.extend(chunk)
            return bytes(result)
        def serve():
            try:
                header = receive(12)
                name, cookie = struct.unpack_from('<HH', header, 6)
                protocol.sendall(header + receive(((name + 3) & ~3) + ((cookie + 3) & ~3)))
                while True:
                    while protocol.incoming:
                        peer.sendall(bytes(protocol.incoming[:3]))
                        del protocol.incoming[:3]
                    header = receive(4)
                    if header is None:
                        break
                    size = struct.unpack_from('<H', header, 2)[0] * 4 - 4
                    protocol.sendall(header + (receive(size) if size else b''))
            except BaseException as exc:
                failures.append(exc)
            finally:
                peer.close()
        thread = threading.Thread(target=serve)
        thread.start()
        screen = None
        try:
            with mock.patch.object(x11.x11_probe, '_auth_status', return_value=('ready', b'k' * 16)), \
                 mock.patch.object(x11.socket, 'socket', return_value=ConnectedClient()), \
                 mock.patch.object(x11.socket, 'AF_UNIX', 1, create=True):
                screen = x11.Screen(FONT, LABELS)
            screen.draw(Menu())
        finally:
            if screen is not None:
                screen.close()
            else:
                client.close()
            thread.join(4)
        self.assertFalse(thread.is_alive())
        self.assertEqual(failures, [])
        self.assertIn(1, [packet[0] for packet in protocol.requests[1:]])
        self.assertEqual(protocol.requests[-1][0], 43)

    def test_real_socketpair_fragmented_frame(self):
        try:
            client, peer = socket.socketpair()
        except (AttributeError, OSError):
            self.skipTest('socketpair unavailable')
        screen = x11.Screen.__new__(x11.Screen)
        screen.socket, screen._buffer = client, bytearray()
        failures = []
        data = reply(11, b'abcd')
        def sender():
            try:
                for byte in data:
                    peer.sendall(bytes((byte,)))
            except OSError as exc:
                failures.append(exc)
            finally:
                peer.close()
        thread = threading.Thread(target=sender)
        thread.start()
        try:
            self.assertEqual(screen._frame(__import__('time').monotonic() + 2), data)
        finally:
            client.close()
            thread.join(2)
        self.assertFalse(thread.is_alive())
        self.assertEqual(failures, [])


@unittest.skipUnless(os.environ.get('PD2_TEST_XVFB') == '1', 'opt-in real Xvfb protocol test')
class RealXvfbTests(unittest.TestCase):
    def test_real_server_create_map_draw_and_pixels(self):
        """Uses exactly X0 and private cookie; never connects an existing display."""
        executable = shutil.which('Xvfb')
        if not executable or not hasattr(os, 'geteuid') or not hasattr(socket, 'AF_UNIX'):
            self.skipTest('Xvfb/local UNIX unavailable')
        if Path('/tmp/.X11-unix/X0').exists() or Path('/tmp/.X0-lock').exists():
            self.skipTest('X0 already occupied; do not touch another session')
        with tempfile.TemporaryDirectory(prefix='pd2-menu-x11-') as run:
            auth = Path(run) / 'xauthority'
            cookie = os.urandom(16)
            fields = (b'', b'0', b'MIT-MAGIC-COOKIE-1', cookie)
            auth.write_bytes(struct.pack('>H', 65535) + b''.join(struct.pack('>H', len(f)) + f for f in fields))
            auth.chmod(0o600)
            proc = subprocess.Popen([executable, ':0', '-screen', '0', '640x480x24', '-auth', str(auth), '-nolisten', 'tcp'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                import time
                end = time.monotonic() + 5
                while not Path('/tmp/.X11-unix/X0').exists():
                    if proc.poll() is not None or time.monotonic() >= end:
                        self.fail('Xvfb failed to create X0')
                    time.sleep(0.02)
                with mock.patch.dict(os.environ, PD2_RUN=run, PD2_XAUTHORITY=str(auth)):
                    screen = x11.Screen(FONT, LABELS)
                try:
                    screen.draw(Menu())
                    # GetImage ZPixmap confirms drawable pixels, not just setup.
                    sequence = screen._request(73, 2, struct.pack('<IhhHHI', screen.window, 0, 0, 1, 1, 0xffffffff), time.monotonic() + 2)
                    for _ in range(1024):
                        frame = screen._frame(time.monotonic() + 2)
                        if frame[0] == 1:
                            self.assertEqual(struct.unpack_from('<H', frame, 2)[0], sequence)
                            self.assertEqual(struct.unpack_from('<I', frame, 32)[0] & 0xffffff, screen._pixel((12, 10, 10)))
                            break
                        screen._event(frame)
                    else:
                        self.fail('no GetImage reply')
                finally:
                    screen.close()
            finally:
                proc.terminate()
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=3)


@unittest.skipUnless(os.environ.get('PD2_MENU_LIVE_X11') == '1', 'opt-in local X11 smoke test')
class LiveX11Tests(unittest.TestCase):
    def test_local_create_map_draw_roundtrip(self):
        """WSLg smoke only: test auth override never changes production policy."""
        import time
        import start_menu
        if not hasattr(socket, 'AF_UNIX') or not Path('/tmp/.X11-unix/X0').exists():
            self.skipTest('local X0 unavailable')
        # A local WSLg server may authorize this peer without MIT credentials.
        # No xhost/auth changes and no real cookie is read, printed or persisted.
        with mock.patch.object(x11.x11_probe, '_auth_status', return_value=('ready', bytes(16))):
            screen = x11.Screen(start_menu.FONT, LABELS)
        try:
            self.assertTrue(screen._mapped and screen._exposed)
            screen.draw(Menu())
            screen._roundtrip(time.monotonic() + 2)
            for x, y, rgb in ((0, 0, (12, 10, 10)), (6, 6, (140, 105, 35))):
                deadline = time.monotonic() + 2
                sequence = screen._request(73, 2, struct.pack('<IhhHHI', screen.window, x, y, 1, 1, 0xffffffff), deadline)
                for _ in range(1024):
                    frame = screen._frame(deadline)
                    if frame[0] == 1:
                        self.assertEqual(struct.unpack_from('<H', frame, 2)[0], sequence)
                        masks = screen.masks[0] | screen.masks[1] | screen.masks[2]
                        self.assertEqual(struct.unpack_from('<I', frame, 32)[0] & masks, screen._pixel(rgb))
                        break
                    screen._event(frame)
                else:
                    self.fail('no GetImage reply')
            time.sleep(1)
            screen.actions()
        finally:
            screen.close()


if __name__ == '__main__':
    unittest.main()
