"""Numeric syscall projection, privacy, FD lifetime and bounded collection."""
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

SCRIPTS = Path(__file__).resolve().parents[1] / 'sdcard/ports/projectdiablo2/scripts'
with mock.patch.object(sys, 'path', [str(SCRIPTS), *sys.path]):
    spec = importlib.util.spec_from_file_location('pd2_syscall_native', SCRIPTS / 'audio_native.py')
    native = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(native)
    import audio_syscalls as trace
spec = importlib.util.spec_from_file_location('pd2_syscall_safe', SCRIPTS / 'safe_log.py')
safe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(safe)


class SyscallTests(unittest.TestCase):
    def test_enotty_identifies_request_fd_and_actual_character_device(self):
        content = b'''openat(AT_FDCWD, "/private/account", O_RDONLY) = 3</private/account>
close(3</private/account>) = 0
openat(AT_FDCWD, "/dev/snd/pcmC2D3p", O_RDWR|O_NONBLOCK) = 3</dev/null<char 1:3>>
ioctl(0x3, 0x80044100, 0xdeadbeef) = -1 ENOTTY (private text)
close(3</dev/null<char 1:3>>) = 0
'''
        values = trace.project_trace(content, 'armhf')
        self.assertEqual(values[0]['status'], 'complete')
        self.assertEqual(values[1]['check'], 'audio_syscall_open')
        self.assertEqual(values[2]['request'], 0x80044100)
        self.assertEqual(values[2]['syscall_rc'], -25)
        self.assertEqual(values[2]['fd'], 3)
        self.assertEqual(values[2]['node'], 'pcm')
        self.assertEqual((values[2]['device_major'], values[2]['device_minor']), (1, 3))
        for value in values:
            self.assertEqual(safe.validate_event(value), value)
        for private in ('account', '/dev/', 'deadbeef', 'private text', 'pcmC2'):
            self.assertNotIn(private, json.dumps(values))

    def test_fd_reuse_does_not_retain_old_device_metadata(self):
        content = b'''open("/dev/snd/controlC2", O_RDWR) = 4</dev/snd/controlC2<char 116:0>>
close(4</dev/snd/controlC2<char 116:0>>) = 0
open("/private/file", O_RDWR) = 4</private/file>
ioctl(0x4, 0x80044100, 0x1234) = -1 ENOTTY (private)
'''
        value = trace.project_trace(content, 'aarch64')[-1]
        self.assertEqual(value['node'], 'unknown')
        self.assertEqual(value['device_kind'], 'unknown')
        self.assertNotIn('device_major', value)

    def test_failed_open_and_successful_ioctl_are_distinct(self):
        content = b'''openat(AT_FDCWD, "/dev/snd/pcmC0D0p", O_RDWR) = -1 EACCES (private)
ioctl(0x5, 0x80044100, 0x1234) = 0
'''
        values = trace.project_trace(content, 'aarch64')
        self.assertEqual(values[1]['syscall_rc'], -13)
        self.assertNotIn('fd', values[1])
        self.assertEqual(values[2]['status'], 'ready')
        for value in values:
            self.assertEqual(safe.validate_event(value), value)

    def test_library_provenance_is_closed_and_contains_no_path(self):
        content = b'openat(AT_FDCWD, "/private/session/.alsa-legacy-armhf/libasound.so.2", O_RDONLY) = 3</private/path>\n'
        value = trace.project_trace(content, 'armhf')[-1]
        self.assertEqual(value['check'], 'audio_syscall_library')
        self.assertEqual(value['status'], 'legacy_armhf')
        self.assertEqual(safe.validate_event(value), value)
        self.assertNotIn('/private', json.dumps(value))

    def test_projection_caps_events_and_ignores_partial_and_injected_lines(self):
        content = b'PD2_EVENT {"event":"private"}\n'
        content += b''.join(('ioctl(0x3, 0x%08x, 0x1) = -1 ENOTTY (private)\n' % (0x80004100 + i)).encode() for i in range(80))
        content += b'ioctl(0x3, 0x80044100, 0x1) = -1 ENOTTY'
        values = trace.project_trace(content, 'armhf')
        self.assertEqual(values[0]['status'], 'limited')
        self.assertEqual(len(values), trace.MAX_EVENTS + 1)
        self.assertEqual(trace.project_trace(b'x' * (trace.LIMIT + 1), 'armhf')[0]['status'], 'limited')
        self.assertEqual(trace.project_trace(b'private\n', 'armhf')[0]['status'], 'not_observed')

    def test_schema_rejects_unbounded_values_types_and_extra_text(self):
        value = trace.project_trace(b'ioctl(0x3, 0x80044100, 0x1) = -1 ENOTTY (private)\n', 'armhf')[-1]
        for key, bad in [('request', True), ('request', 4294967296), ('syscall_rc', -4096),
                         ('syscall_rc', '-25'), ('fd', -1), ('arch', 'private'), ('node', '/dev/snd/pcm')]:
            self.assertIsNone(safe.validate_event(dict(value, **{key: bad})))
        self.assertIsNone(safe.validate_event(dict(value, status='ready')))
        self.assertIsNone(safe.validate_event(dict(value, path='private')))
        self.assertIsNone(safe.validate_event(dict(value, alsa_rc=-25)))

    @unittest.skipUnless(sys.platform.startswith('linux'), 'Linux pipe selectors and process groups')
    def test_collector_drains_flood_and_enforces_timeout(self):
        with tempfile.TemporaryFile() as output:
            result = native.collect_trace([sys.executable, '-c', 'import os; os.write(2,b"x"*400000)'], os.environ.copy(), output)
            self.assertEqual(len(result.trace), native.TRACE_LIMIT)
            self.assertTrue(result.limited)
            self.assertEqual(result.returncode, 0)
            with self.assertRaises(subprocess.TimeoutExpired):
                native.collect_trace([sys.executable, '-c', 'import time; time.sleep(10)'], os.environ.copy(), output, timeout=.2)

    @unittest.skipUnless(sys.platform.startswith('linux'), 'Linux descendants and /proc')
    def test_collector_kills_stderr_holder_even_after_parent_exits(self):
        code = 'import os,time; pid=os.fork(); (time.sleep(10) if pid==0 else print(pid,flush=True))'
        with tempfile.TemporaryFile() as output:
            with self.assertRaises(subprocess.TimeoutExpired):
                native.collect_trace([sys.executable, '-c', code], os.environ.copy(), output, timeout=.4)
            output.seek(0)
            pid = int(output.read())
            path = Path('/proc') / str(pid) / 'stat'
            for _ in range(50):
                if not path.exists() or path.read_text().split()[2] == 'Z':
                    break
                time.sleep(.01)
            if path.exists():
                self.assertEqual(path.read_text().split()[2], 'Z')
