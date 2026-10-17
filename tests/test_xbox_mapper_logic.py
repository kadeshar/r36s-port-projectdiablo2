"""Synthetic evdev/uinput tests; never open the real controller or /dev/uinput."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import struct
import sys
import tempfile
import types
import shutil
import uuid
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if sys.platform != 'linux':
    # Keep the platform shim scoped to this module's import.
    with mock.patch.dict(sys.modules, {'fcntl': types.ModuleType('fcntl')}):
        spec = importlib.util.spec_from_file_location('xbox_mapper', ROOT / 'sdcard/ports/projectdiablo2/scripts/xbox_mapper.py')
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
    m.fcntl.ioctl = mock.Mock()
else:
    spec = importlib.util.spec_from_file_location('xbox_mapper', ROOT / 'sdcard/ports/projectdiablo2/scripts/xbox_mapper.py')
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)

KEYS = sum(1 << c for c in (0x130, 0x131, 0x133, 0x134, 0x136, 0x137,
                           0x138, 0x139, 0x220, 0x221, 0x222, 0x223,
                           0x2c0, 0x2c1, 0x2c2, 0x2c3, 0x2c4))
ABS = 0x1b
PAD = ('/dev/input/event3', 'GO-Super Gamepad', 0x484b, 0x1100, KEYS, ABS)


@contextlib.contextmanager
def fixture_dir():
    if sys.platform == 'win32':
        # Ordinary mkdir inherits workspace ACLs; TemporaryDirectory's 0700 DACL
        # on Python 3.13+ rejects the restricted Windows test token.
        path = ROOT / 'tests' / ('mapper-fixture-' + uuid.uuid4().hex)
        path.mkdir()
        try:
            yield str(path)
        finally:
            shutil.rmtree(path)
    else:
        with tempfile.TemporaryDirectory() as path:
            yield path


class MapperTests(unittest.TestCase):
    def test_linux_uapi_numbers_and_descriptor(self):
        self.assertEqual((m.UI_SET_EVBIT, m.UI_SET_KEYBIT, m.UI_SET_ABSBIT),
                         (0x40045564, 0x40045565, 0x40045567))
        self.assertEqual((m.UI_DEV_CREATE, m.UI_DEV_DESTROY), (0x5501, 0x5502))
        self.assertEqual(m.eviocgabs(0), 0x80184540)  # _IOR, not _IOWR
        data = m.device_descriptor()
        self.assertEqual(len(data), 1116)
        name, bus, vid, pid, ver, ff = struct.unpack_from('<80sHHHHI', data)
        self.assertEqual((name.rstrip(b'\0'), bus, vid, pid, ver, ff),
                         (b'Microsoft X-Box 360 pad', 3, 0x045e, 0x028e, 0x0104, 0))
        arrays = [struct.unpack_from('<64i', data, 92 + 256 * i) for i in range(4)]
        for axis, (lo, hi, fuzz, flat) in m.AXES.items():
            self.assertEqual(tuple(a[axis] for a in arrays), (hi, lo, fuzz, flat))
        self.assertEqual(m.XBOX_KEYS['SELECT'], 0x13a)
        self.assertEqual(m.XBOX_KEYS['START'], 0x13b)
        self.assertEqual(m.XBOX_KEYS['MODE'], 0x13c)
        self.assertEqual(m.XBOX_KEYS['THUMBL'], 0x13d)
        self.assertEqual(m.XBOX_KEYS['THUMBR'], 0x13e)

    def test_create_passes_integer_ioctl_arguments_and_closes_on_failure(self):
        with mock.patch.object(m.os, 'O_NONBLOCK', 2048, create=True), \
             mock.patch.object(m.os, 'open', return_value=17), \
             mock.patch.object(m.os, 'write', side_effect=lambda fd, data: len(data)) as write, \
             mock.patch.object(m.os, 'close') as close, \
             mock.patch.object(m.fcntl, 'ioctl', return_value=0) as ioctl:
            self.assertEqual(m.create_virtual_xbox(), 17)
            close.assert_not_called()
            write.assert_called_once_with(17, m.device_descriptor())
            self.assertIn(mock.call(17, m.UI_SET_ABSBIT, 17), ioctl.call_args_list)
            for call in ioctl.call_args_list:
                if len(call.args) == 3:
                    self.assertIsInstance(call.args[2], int)
            ioctl.side_effect = OSError('failure')
            with self.assertRaises(OSError):
                m.create_virtual_xbox()
            close.assert_called_once_with(17)

    def test_short_write_is_failure(self):
        with mock.patch.object(m.os, 'write', return_value=1):
            with self.assertRaises(OSError):
                m.write_exact(17, bytes(24))

    def test_sysfs_multiword_bitmap_and_event_device_directory(self):
        self.assertEqual(m.bitmap('1 0000000000000000 2'), (1 << 128) | 2)
        self.assertEqual(m.bitmap('1 00000000 2', 32), (1 << 64) | 2)
        def fmt(value):
            width = struct.calcsize('@L') * 8
            words = []
            while value:
                words.append(f'{value & ((1 << width) - 1):0{width // 4}x}')
                value >>= width
            return ' '.join(reversed(words)) or '0'
        with fixture_dir() as tmp:
            base = Path(tmp) / 'event3/device'
            for path, text in {'name': 'GO-Super Gamepad', 'id/vendor': '484b',
                               'id/product': '1100', 'capabilities/ev': 'b',
                               'capabilities/key': fmt(KEYS), 'capabilities/abs': '1b'}.items():
                target = base / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(text)
            self.assertEqual(m.physical_devices(tmp), [PAD])
            (base / 'id/vendor').write_text('045e')
            (base / 'id/product').write_text('028e')
            self.assertEqual(m.physical_devices(tmp), [])
        self.assertIsNone(m.choose_pad([PAD[:2] + (0x1234, 0x5678) + PAD[4:]]))
        self.assertEqual(m.choose_pad([PAD]), PAD)

    def test_axis_ioctl_uses_read_request_and_24_byte_buffer(self):
        info = struct.pack('<6i', 511, 0, 1023, 0, 0, 0)
        with mock.patch.object(m.fcntl, 'ioctl', return_value=info) as ioctl:
            self.assertEqual(m.axis_info(7, 3), (511, 0, 1023, 0, 0, 0))
            ioctl.assert_called_once_with(7, 0x80184543, bytes(24))

    def test_translate_every_physical_button_and_release(self):
        keymap, triggers, layout = m.build_keymap(KEYS, ABS)
        self.assertEqual(layout, 'standard')
        out = []
        translator = m.Translator(keymap, triggers, {c: (0, 1023) for c in (0, 1, 3, 4)},
                                  lambda *event: out.append(event))
        for physical, target in {0x131: 0x130, 0x130: 0x131, 0x133: 0x133,
                                 0x134: 0x134, 0x136: 0x136, 0x137: 0x137,
                                 0x2c0: 0x13a, 0x2c1: 0x13b, 0x2c2: 0x13d,
                                 0x2c3: 0x13e, 0x2c4: 0x13c}.items():
            for value in (1, 0):
                translator.process(1, physical, value)
                self.assertEqual(out[-1], (1, target, value))
        for physical, target in ((0x138, 2), (0x139, 5)):
            for value in (1, 0):
                translator.process(1, physical, value)
                self.assertEqual(out[-1], (3, target, value * 255))
        before = len(out)
        translator.process(1, 0x131, 2)  # ignore autorepeat
        self.assertEqual(len(out), before)
        for physical, x, y in ((0x220, 0, -1), (0x221, 0, 1), (0x222, -1, 0), (0x223, 1, 0)):
            translator.process(1, physical, 1)
            self.assertEqual(out[-2:], [(3, 16, x), (3, 17, y)])
            translator.process(1, physical, 0)
            self.assertEqual(out[-2:], [(3, 16, 0), (3, 17, 0)])
        for code in (0, 1, 3, 4):
            translator.process(3, code, 1023)
            self.assertEqual(out[-1], (3, code, 32767))
        translator.process(0, 0, 0)
        self.assertEqual(out[-1], (0, 0, 0))

    def test_user_confirmed_select_start_menu_and_click_snapshot(self):
        keymap, triggers, _ = m.build_keymap(KEYS, ABS)
        # Evidence: photo 0.1.12 showed all five physical passed / XInput not_seen.
        physical = (0x2c0, 0x2c1, 0x2c2, 0x2c3, 0x2c4)
        expected = ('SELECT', 'START', 'THUMBL', 'THUMBR', 'MODE')
        self.assertEqual([keymap[code] for code in physical], list(expected))
        self.assertNotIn(0x13a, keymap)  # Virtual codes must not stand in for physical.
        self.assertNotIn(0x13b, keymap)
        out = []
        translator = m.Translator(keymap, triggers, {}, lambda *e: out.append(e))
        pressed = sum(1 << code for code in physical).to_bytes(96, 'little')
        with mock.patch.object(m.fcntl, 'ioctl', return_value=pressed):
            m.snapshot(9, translator)
        self.assertEqual(sorted((kind, code, value) for kind, code, value in out
                                if kind == m.EV_KEY and value),
                         [(1, code, 1) for code in (0x13a, 0x13b, 0x13c, 0x13d, 0x13e)])
        out.clear()
        for code in physical:
            translator.process(m.EV_KEY, code, 0)
        self.assertEqual(sorted(out),
                         [(1, code, 0) for code in (0x13a, 0x13b, 0x13c, 0x13d, 0x13e)])

    def test_scaling_clamp_deadzone_and_invalid_ranges(self):
        for code in (0, 1, 3, 4):
            for value, expected in ((-100, -32768), (0, -32768), (511, 0), (542, 0), (1023, 32767), (2000, 32767)):
                self.assertEqual(m.scale(code, value, 0, 1023), expected)
        self.assertEqual(m.scale(2, 128, 0, 255), 128)
        with self.assertRaises(ValueError):
            m.scale(0, 5, 5, 5)
        with self.assertRaises(ValueError):
            m.build_keymap(KEYS, ABS | (1 << 2))

    def test_initial_snapshot_includes_held_buttons_and_axes(self):
        out = []
        keys, triggers, _ = m.build_keymap(KEYS, ABS)
        translator = m.Translator(keys, triggers, {3: (0, 1023)}, lambda *e: out.append(e))
        with mock.patch.object(m.fcntl, 'ioctl', return_value=(1 << 0x138).to_bytes(96, 'little')), \
             mock.patch.object(m, 'axis_info', return_value=(1023, 0, 1023, 0, 0, 0)):
            m.snapshot(7, translator)
        self.assertIn((3, 2, 255), out)
        self.assertIn((3, 3, 32767), out)
        self.assertEqual(out[-1], (0, 0, 0))

    def test_stream_dropped_sync_recovers_and_closes_fds(self):
        events = [(0, 3, 0), (1, 0x131, 1), (0, 0, 0), (1, 0x130, 1), (0, 0, 0)]
        data = b''.join(m.EVENT.pack(0, 0, *e) for e in events)
        stdout = io.StringIO()
        emitted = []
        def write(fd, buf):
            emitted.extend(tuple(e[2:]) for e in m.EVENT.iter_unpack(buf))
            return len(buf)
        with mock.patch.object(m.signal, 'signal'), \
             mock.patch.object(m.os, 'O_NONBLOCK', 2048, create=True), \
             mock.patch.object(m, 'physical_devices', return_value=[PAD]), \
             mock.patch.object(m.os, 'open', return_value=16), \
             mock.patch.object(m.os, 'close') as close, \
             mock.patch.object(m, 'axis_info', return_value=(511, 0, 1023, 0, 0, 0)), \
             mock.patch.object(m, 'create_virtual_xbox', return_value=17), \
             mock.patch.object(m.fcntl, 'ioctl', return_value=bytes(96)), \
             mock.patch.object(m.select, 'select', return_value=([16], [], [])), \
             mock.patch.object(m.os, 'read', side_effect=[data, b'']), \
             mock.patch.dict(m.os.environ, {'PD2_CONTROLLER_TEST': '1', 'PD2_WORK': 'private-work'}), \
             mock.patch.object(m, 'ButtonObserver') as observe, \
             mock.patch.object(m.os, 'write', side_effect=write), contextlib.redirect_stdout(stdout):
            self.assertEqual(m.main(), 4)  # EOF is reported, not silent success
        self.assertEqual(observe.call_args.args[0], Path('private-work') / 'ProjectD2')
        observe.return_value.resync.assert_called_once_with(0)
        self.assertIn(mock.call(1, 0x130, 1), observe.return_value.process.call_args_list)
        self.assertNotIn((1, 0x130, 1), emitted)  # discard physical A in dropped frame
        self.assertIn((1, 0x131, 1), emitted)  # physical B after resync
        self.assertEqual(close.call_args_list, [mock.call(17), mock.call(16)])
        statuses = [json.loads(line.removeprefix('PD2_EVENT '))['status']
                    for line in stdout.getvalue().splitlines()]
        self.assertEqual(statuses, ['ready', 'standard', 'invalid'])

    def test_failed_uinput_start_closes_physical_device(self):
        with mock.patch.object(m.signal, 'signal'), \
             mock.patch.object(m.os, 'O_NONBLOCK', 2048, create=True), \
             mock.patch.object(m, 'physical_devices', return_value=[PAD]), \
             mock.patch.object(m.os, 'open', return_value=16), \
             mock.patch.object(m.os, 'close') as close, \
             mock.patch.object(m, 'axis_info', return_value=(511, 0, 1023, 0, 0, 0)), \
             mock.patch.object(m, 'create_virtual_xbox', side_effect=PermissionError()), \
             contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(m.main(), 2)
        close.assert_called_once_with(16)
        self.assertIn('"status":"denied"', output.getvalue())

    def test_missing_pad_safe_log(self):
        stdout = io.StringIO()
        with mock.patch.object(m.signal, 'signal'), mock.patch.object(m, 'physical_devices', return_value=[]), contextlib.redirect_stdout(stdout):
            self.assertEqual(m.main(), 1)
        self.assertEqual(json.loads(stdout.getvalue().removeprefix('PD2_EVENT '))['status'], 'missing')


class ObserverTests(unittest.TestCase):
    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.directory = Path(self.stack.enter_context(fixture_dir()))
        self.request = self.directory / 'pd2-button-step.txt'
        self.report = self.directory / 'pd2-button-physical.txt'
        self.observer = m.ButtonObserver(self.directory)

    def step(self, index):
        self.request.write_bytes(f'{index}\n'.encode())
        self.observer.refresh()

    def rows(self):
        lines = self.report.read_text().splitlines()
        self.assertEqual(lines[0], 'PD2BUTTON1')
        self.assertEqual(len(lines), 18)
        return [tuple(map(int, line.split())) for line in lines[1:]]

    def test_all_17_steps_include_unmapped_keys_without_rebinding(self):
        self.observer.refresh()
        self.assertFalse(self.report.exists())
        for index in range(17):
            self.step(index)
            code = 0x2c0 + index  # Includes previously unknown physical codes.
            self.observer.process(m.EV_KEY, code, 1)
            self.assertEqual(self.rows()[index], (index, 1, code))
            self.observer.process(m.EV_KEY, code, 0)
            self.assertEqual(self.rows()[index], (index, 2, code))
        self.step(-1)
        self.observer.process(m.EV_KEY, 0x130, 1)
        self.assertTrue(all(row[1] == 2 for row in self.rows()))
        self.assertNotIn(0x2cf, m.build_keymap(KEYS, ABS)[0])

    def test_held_at_step_start_and_autorepeat_do_not_pass(self):
        self.observer.held.add(0x131)
        self.step(0)
        for value in (1, 2, 0):
            self.observer.process(m.EV_KEY, 0x131, value)
        self.assertEqual(self.rows()[0], (0, 0, 0))
        self.observer.process(m.EV_KEY, 0x131, 1)
        self.assertEqual(self.rows()[0][1], 1)
        self.observer.process(m.EV_KEY, 0x131, 0)
        self.assertEqual(self.rows()[0][1], 2)

    def test_multiple_keys_and_dropped_events_cannot_pass(self):
        self.step(0)
        for code in (0x131, 0x130):
            self.observer.process(m.EV_KEY, code, 1)
            self.observer.process(m.EV_KEY, code, 0)
        self.assertEqual(self.rows()[0][1], 3)
        self.step(1)
        self.observer.resync(1 << 0x131)
        self.observer.process(m.EV_KEY, 0x131, 0)
        self.assertEqual(self.rows()[1][1], 3)

    def test_only_fresh_keys_not_stick_motion_or_release_pass(self):
        self.step(0)
        for kind, code, value in ((m.EV_ABS, 0, 32767), (m.EV_KEY, 0x130, 0),
                                  (m.EV_KEY, 0x130, 2), (m.EV_KEY, 768, 1)):
            self.observer.process(kind, code, value)
        self.assertEqual(self.rows()[0], (0, 0, 0))

    def test_request_is_bounded_exact_and_never_logged(self):
        with contextlib.redirect_stdout(io.StringIO()) as output:
            for raw in (b'17\n', b'-2\n', b'0\r\n', b'0', b'0\nprivate', b'9' * 4096):
                self.request.write_bytes(raw)
                self.observer.refresh()
                self.assertIsNone(self.observer.step)
                self.assertFalse(self.report.exists())
        self.assertEqual(output.getvalue(), '')

    def test_report_failure_is_isolated_from_mapper(self):
        self.step(0)
        with mock.patch.object(self.observer, 'publish', side_effect=PermissionError()):
            self.observer.process(m.EV_KEY, 0x131, 1)
        self.assertFalse(self.observer.failed)
        self.assertTrue(self.observer.pending)
        self.observer.refresh()  # Retry sharing denial without waiting for another input.
        self.assertFalse(self.observer.pending)
        self.observer.process(m.EV_KEY, 0x131, 0)  # No exception / no mapper failure.
        self.assertEqual(self.rows()[0][1], 2)


if __name__ == '__main__':
    unittest.main()
