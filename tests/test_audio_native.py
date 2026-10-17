"""Native PCM comparison: authenticated ELF, exact environment, closed results."""
import hashlib
import contextlib
import io
import importlib.util
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'sdcard/ports/projectdiablo2/scripts'
with mock.patch.object(sys, 'path', [str(SCRIPTS), *sys.path]):
    spec = importlib.util.spec_from_file_location('pd2_audio_native', SCRIPTS / 'audio_native.py')
    native = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(native)
spec = importlib.util.spec_from_file_location('pd2_native_safe', SCRIPTS / 'safe_log.py')
safe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(safe)


class NativeAudioTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='pd2-native-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.port = self.root / 'port'
        target = self.port / native.HELPER_PATH
        target.parent.mkdir(parents=True)
        self.source = ROOT / 'sdcard/ports/projectdiablo2' / native.HELPER_PATH
        target.write_bytes(self.source.read_bytes())
        for name in (native.HELPER64_PATH, native.TRACE_PATH):
            destination = self.port / name
            destination.write_bytes((ROOT / 'sdcard/ports/projectdiablo2' / name).read_bytes())
        self.work = self.root / 'work'
        self.work.mkdir()
        self.proc = self.root / 'proc'
        self.proc.mkdir()
        (self.proc / 'cards').write_bytes(b' 2 [rk817]: codec\n')
        (self.proc / 'pcm').write_bytes(b'02-03: codec : playback 1\n')

    def run_native(self, runner, env=None):
        return native.native_events(self.port, self.work, environ=env or {}, runner=runner,
                                    machine='aarch64', proc_root=self.proc)

    def test_artifact_is_pinned_arm32_hard_float_with_old_glibc_abi(self):
        data = native.helper_bytes(self.port)
        self.assertEqual(hashlib.sha256(data).hexdigest(), native.HELPER_SHA256)
        self.assertEqual(data[:6], b'\x7fELF\x01\x01')
        self.assertEqual(struct.unpack_from('<H', data, 18)[0], 40)
        self.assertTrue(struct.unpack_from('<I', data, 36)[0] & 0x400)
        self.assertIn(b'/lib/ld-linux-armhf.so.3\0', data)
        self.assertIn(b'GLIBC_2.4\0', data)
        self.assertNotIn(b'GLIBC_2.34', data)
        package_spec = importlib.util.spec_from_file_location('pd2_native_prepare', ROOT / 'tools/prepare.py')
        package = importlib.util.module_from_spec(package_spec)
        package_spec.loader.exec_module(package)
        relative = 'projectdiablo2/' + native.HELPER_PATH
        self.assertIn(relative, json.loads((ROOT / 'release-files.json').read_text()))
        package.validate_release_path(relative)
        with self.assertRaises(package.PrepareError):
            package.validate_release_path('projectdiablo2/compat/alsa-native/arbitrary.armhf')

    def test_direct_execution_uses_same_library_environment_and_session_alsa_config(self):
        env = {'PD2_NATIVE_LIBS': '/private/armhf', 'PD2_NATIVE_PRELOAD': '/private/preload',
               'PD2_CRUSTY_SDL': '/private/sdl', 'ALSA_CONFIG_PATH': '/private/alsa.conf'}
        def runner(command, **options):
            self.assertEqual(command[1:], ['plughw:2,3'])
            self.assertEqual(Path(command[0]).name, 'alsa-native.armhf')
            self.assertEqual(Path(command[0]).read_bytes(), self.source.read_bytes())
            self.assertEqual(options['env']['LD_LIBRARY_PATH'], env['PD2_NATIVE_LIBS'])
            self.assertEqual(options['env']['LD_PRELOAD'], env['PD2_NATIVE_PRELOAD'])
            self.assertEqual(options['env']['ALSA_CONFIG_PATH'], env['ALSA_CONFIG_PATH'])
            self.assertEqual(options['env']['CRUSTY_LIBSDL'], env['PD2_CRUSTY_SDL'])
            self.assertEqual(options['stderr'], subprocess.DEVNULL)
            self.assertEqual(options['timeout'], 8)
            options['stdout'].write(b'{"schema_version":1,"status":"ready","default_rc":-25,"plughw_rc":0}')
            return subprocess.CompletedProcess(command, 0)
        events = self.run_native(runner, env)
        self.assertEqual(events[1], native.event('audio_native_default', 'other_error', -25))
        self.assertEqual(events[2], native.event('audio_native_plughw', 'ready'))
        for event in events:
            self.assertEqual(safe.validate_event(event), event)
        self.assertEqual(list(self.work.iterdir()), [])
        self.assertNotIn('/private', json.dumps(events))

    def test_timeout_and_tampering_never_run_box86_or_leak_exceptions(self):
        runner = mock.Mock(side_effect=subprocess.TimeoutExpired('private command', 8))
        self.assertEqual(self.run_native(runner), [native.event('audio_native_armhf', 'timeout')])
        self.assertEqual(list(self.work.iterdir()), [])
        (self.port / native.HELPER_PATH).write_bytes(b'tampered')
        runner.reset_mock()
        self.assertEqual(self.run_native(runner), [native.event('audio_native_armhf', 'tampered')])
        runner.assert_not_called()

    def test_aarch64_uses_64_bit_libraries_without_armhf_preload(self):
        env = {'PD2_NATIVE_LIBS': '/arm32', 'PD2_NATIVE_PRELOAD': '/arm32/preload',
               'PD2_NATIVE64_LIBS': '/arm64', 'ALSA_CONFIG_PATH': '/private/alsa.conf'}
        def runner(command, **options):
            self.assertEqual(Path(command[0]).read_bytes()[:5], b'\x7fELF\x02')
            self.assertEqual(options['env']['LD_LIBRARY_PATH'], '/arm64')
            self.assertEqual(options['env']['LD_PRELOAD'], '')
            self.assertEqual(options['env']['ALSA_CONFIG_PATH'], env['ALSA_CONFIG_PATH'])
            options['stdout'].write(b'{"schema_version":1,"status":"ready","default_rc":0,"plughw_rc":0}')
            return subprocess.CompletedProcess(command, 0)
        events = native.native_events(self.port, self.work, environ=env, runner=runner,
                                      machine='aarch64', proc_root=self.proc, arch='aarch64')
        self.assertEqual(events[0]['check'], 'audio_native_aarch64')
        self.assertEqual(events[1]['check'], 'audio_native64_default')
        for value in events:
            self.assertEqual(safe.validate_event(value), value)
        self.assertEqual(list(self.work.iterdir()), [])

    def test_aarch64_artifacts_and_main_schedule_both_baselines_and_traces(self):
        data = native.helper_bytes(self.port, 'aarch64')
        self.assertEqual(data[:5], b'\x7fELF\x02')
        self.assertEqual(struct.unpack_from('<H', data, 18)[0], 183)
        self.assertIn(b'GLIBC_2.17\0', data)
        tracer = native.artifact_bytes(self.port, native.TRACE_PATH, native.TRACE_SIZE, native.TRACE_SHA256)
        self.assertEqual(struct.unpack_from('<H', tracer, 18)[0], 183)
        output = io.StringIO()
        with mock.patch.object(native, 'native_events', return_value=[]) as baseline, \
                mock.patch.object(native, 'trace_native_events', return_value=[]) as traced, contextlib.redirect_stdout(output):
            self.assertEqual(native.main(['--port', str(self.port), '--work', str(self.work)]), 0)
        self.assertEqual([call.kwargs['arch'] for call in baseline.call_args_list], ['armhf', 'aarch64'])
        self.assertEqual([call.args[2] for call in traced.call_args_list], ['armhf', 'aarch64'])

    def test_trace_parent_and_armhf_child_have_separate_library_environments(self):
        env = {'PD2_NATIVE_LIBS': '/arm32', 'PD2_NATIVE_PRELOAD': '/arm32/preload', 'PD2_NATIVE64_LIBS': '/arm64'}
        def runner(command, **options):
            self.assertEqual(Path(command[0]).read_bytes()[:5], b'\x7fELF\x02')
            self.assertEqual(options['env']['LD_LIBRARY_PATH'], '/arm64')
            self.assertEqual(options['env']['LD_PRELOAD'], '')
            self.assertIn('LD_LIBRARY_PATH=/arm32', command)
            self.assertIn('LD_PRELOAD=/arm32/preload', command)
            child = command[command.index('--') + 1]
            self.assertEqual(Path(child).read_bytes()[:5], b'\x7fELF\x01')
            options['stdout'].write(b'{"schema_version":1,"status":"ready","default_rc":-25,"plughw_rc":-25}')
            return native.SimpleNamespace(returncode=0, limited=False, trace=b'ioctl(0x3, 0x80044100, 0x1234) = -1 ENOTTY (private)\n')
        values = native.trace_native_events(self.port, self.work, 'armhf', environ=env,
                                           runner=runner, machine='aarch64', proc_root=self.proc)
        self.assertEqual(values[0]['status'], 'complete')
        self.assertEqual(values[1]['request'], 0x80044100)
        self.assertEqual(values[1]['syscall_rc'], -25)
        for value in values:
            self.assertEqual(safe.validate_event(value), value)
        self.assertEqual(list(self.work.iterdir()), [])

    def test_ptrace_denial_and_timeout_do_not_claim_device_failure(self):
        runner = mock.Mock(return_value=native.SimpleNamespace(returncode=1, limited=False,
                          trace=b'strace: ptrace(PTRACE_TRACEME): Operation not permitted\n'))
        for expected in ('denied', 'timeout'):
            if expected == 'timeout':
                runner.side_effect = subprocess.TimeoutExpired('private', 8)
            values = native.trace_native_events(self.port, self.work, 'armhf', runner=runner,
                                               machine='aarch64', proc_root=self.proc)
            self.assertEqual(values, [native.trace_event('armhf', expected)])
            self.assertEqual(list(self.work.iterdir()), [])

    def test_ambiguous_card_skips_plughw_instead_of_guessing(self):
        (self.proc / 'pcm').write_bytes(b'02-03: codec : playback 1\n02-04: codec : playback 1\n')
        self.assertIsNone(native.plughw_node(self.proc))
        events = native.project_report(b'{"schema_version":1,"status":"ready","default_rc":0,"plughw_rc":null}', False)
        self.assertEqual(events[-1], native.event('audio_native_plughw', 'not_run'))

    def test_closed_report_and_logger_reject_bad_codes_and_extra_fields(self):
        for value in ({'schema_version': 1, 'status': 'ready', 'default_rc': True, 'plughw_rc': 0},
                      {'schema_version': 1, 'status': 'library_missing', 'path': 'private'},
                      {'schema_version': 1, 'status': 'ready', 'default_rc': 1, 'plughw_rc': 0}):
            with self.assertRaises(ValueError):
                native.project_report(json.dumps(value).encode(), True)
        for check in ('audio_native_default', 'audio_native_plughw'):
            value = native.event(check, 'other_error', -25)
            self.assertEqual(safe.validate_event(value), value)
            self.assertIsNone(safe.validate_event(dict(value, alsa_rc='-25')))
            self.assertIsNone(safe.validate_event(dict(value, status='ready')))
