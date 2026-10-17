"""Pinned PE and synthetic filesystem safety tests; no real input/game needed."""
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import struct
import unittest
import uuid
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
PORT = ROOT / 'sdcard/ports/projectdiablo2'
SPEC = importlib.util.spec_from_file_location('fps_artifact', PORT / 'scripts/fps_counter.py')
fps = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(fps)


class FpsTests(unittest.TestCase):
    def setUp(self):
        self.root = ROOT / '.state' / 'fps-python-tests' / uuid.uuid4().hex
        self.root.mkdir(parents=True)
        self.addCleanup(shutil.rmtree, self.root)
        self.port, self.work = self.root / 'port', self.root / 'work'
        self.source = self.port / 'compat/fps-hotkey/fps-hotkey.exe'
        self.source.parent.mkdir(parents=True)
        self.directory = self.work / 'ProjectD2'
        self.directory.mkdir(parents=True)
        self.target = self.directory / 'pd2-fps-hotkey.exe'
        self.source.write_bytes((PORT / 'compat/fps-hotkey/fps-hotkey.exe').read_bytes())

    def assert_refused(self):
        with mock.patch.object(Path, 'symlink_to') as link:
            with self.assertRaises((OSError, ValueError)):
                fps.prepare_counter(self.port, self.work)
        link.assert_not_called()

    def make_symlink(self, path, target, directory=False):
        try:
            path.symlink_to(target, target_is_directory=directory)
        except OSError as error:
            self.skipTest('symlink unavailable: ' + str(error.errno))

    def test_pinned_x86_static_crt_pe(self):
        blob = self.source.read_bytes()
        self.assertEqual(len(blob), fps.FPS_SIZE)
        self.assertEqual(hashlib.sha256(blob).hexdigest(), fps.FPS_SHA256)
        self.assertEqual(blob[:2], b'MZ')
        pe = struct.unpack_from('<I', blob, 0x3c)[0]
        self.assertEqual(blob[pe:pe+4], b'PE\0\0')
        machine, sections = struct.unpack_from('<HH', blob, pe+4)
        self.assertEqual(machine, 0x14c)
        optional = pe+24
        self.assertEqual(struct.unpack_from('<H', blob, optional)[0], 0x10b)
        self.assertEqual(struct.unpack_from('<H', blob, optional+68)[0], 2)  # no console
        table = optional + struct.unpack_from('<H', blob, pe+20)[0]
        def offset(rva):
            for i in range(sections):
                vsize, va, rawsize, raw = struct.unpack_from('<IIII', blob, table+i*40+8)
                if va <= rva < va+max(vsize, rawsize):
                    return raw+rva-va
            raise AssertionError('invalid RVA')
        index = offset(struct.unpack_from('<I', blob, optional+104)[0])
        libraries = set()
        symbols = set()
        while any(blob[index:index+20]):
            thunk, _, _, name_rva, first = struct.unpack_from('<IIIII', blob, index)
            name = offset(name_rva)
            libraries.add(blob[name:blob.index(b'\0', name)].decode().lower())
            cursor = offset(thunk or first)
            while True:
                value = struct.unpack_from('<I', blob, cursor)[0]
                if not value:
                    break
                if not value & 0x80000000:
                    pos = offset(value)+2
                    symbols.add(blob[pos:blob.index(b'\0', pos)].decode())
                cursor += 4
            index += 20
        self.assertEqual(libraries, {'kernel32.dll', 'user32.dll'})
        self.assertTrue({'QueryFullProcessImageNameW', 'SendMessageTimeoutW',
                         'GetWindowThreadProcessId', 'GetForegroundWindow'} <= symbols)
        self.assertFalse({'SendInput', 'keybd_event', 'SetWindowsHookExW',
                          'ReadProcessMemory', 'WriteProcessMemory'} & symbols)

    def test_valid_link_request(self):
        with mock.patch.object(Path, 'symlink_to') as link:
            fps.prepare_counter(self.port, self.work)
        link.assert_called_once_with(self.source)
        self.assertEqual(list(self.directory.iterdir()), [])

    def test_actual_link_and_stale_refusal(self):
        try:
            fps.prepare_counter(self.port, self.work)
        except OSError as error:
            if getattr(error, 'winerror', None) == 1314:
                self.skipTest('Windows symlink privilege unavailable')
            raise
        self.assertTrue(self.target.is_symlink())
        self.assertEqual(self.target.read_bytes(), self.source.read_bytes())
        self.assert_refused()

    def test_tampered_same_size(self):
        data = bytearray(self.source.read_bytes())
        data[-1] ^= 1
        self.source.write_bytes(data)
        self.assert_refused()

    def test_truncated_or_oversize(self):
        for data in (b'', b'x' * (fps.FPS_SIZE+1)):
            self.source.write_bytes(data)
            self.assert_refused()

    def test_stale_regular_target_preserved(self):
        self.target.write_text('private stale data')
        self.assert_refused()
        self.assertEqual(self.target.read_text(), 'private stale data')

    def test_stale_dangling_target_preserved(self):
        self.make_symlink(self.target, self.root / 'missing')
        self.assert_refused()
        self.assertTrue(self.target.is_symlink())

    def test_source_leaf_symlink_rejected(self):
        other = self.root / 'original.exe'
        self.source.rename(other)
        self.make_symlink(self.source, other)
        self.assert_refused()

    def test_source_hardlink_rejected(self):
        other = self.root / 'second.exe'
        os.link(self.source, other)
        self.assert_refused()

    def test_source_ancestor_symlink_rejected(self):
        original = self.root / 'actual-source'
        self.source.parent.rename(original)
        self.make_symlink(self.source.parent, original, True)
        self.assert_refused()

    def test_work_ancestor_symlink_rejected(self):
        original = self.root / 'actual-work'
        self.work.rename(original)
        self.make_symlink(self.work, original, True)
        self.assert_refused()

    def test_work_directory_symlink_rejected(self):
        original = self.root / 'actual-projectd2'
        self.directory.rename(original)
        self.make_symlink(self.directory, original, True)
        self.assert_refused()

    def test_synthetic_reparse_entries_refused_without_symlink_privilege(self):
        original = Path.lstat
        # Exercise Windows junction/reparse checks even on hosts without symlink privilege.
        for suspect in (self.source, self.source.parent, self.port, self.work, self.directory):
            def fake_lstat(path, *args, **kwargs):
                info = original(path, *args, **kwargs)
                if path == suspect:
                    return mock.Mock(st_mode=info.st_mode, st_file_attributes=0x400)
                return info
            with self.subTest(path=suspect), mock.patch.object(Path, 'lstat', fake_lstat):
                self.assert_refused()

    def test_synthetic_dangling_target_refused(self):
        with mock.patch.object(os.path, 'lexists', return_value=True):
            self.assert_refused()

    def test_source_replaced_between_stat_and_open_refused(self):
        actual = os.fstat
        def replaced(fd):
            info = actual(fd)
            return mock.Mock(st_mode=info.st_mode, st_nlink=1, st_dev=info.st_dev,
                             st_ino=info.st_ino+1, st_size=info.st_size,
                             st_mtime_ns=info.st_mtime_ns)
        with mock.patch.object(os, 'fstat', replaced):
            self.assert_refused()

    def test_dotdot_layout_rejected(self):
        with self.assertRaises(ValueError):
            fps.prepare_counter(self.port / '..' / 'port', self.work)

    def test_missing_source_or_work_rejected(self):
        with self.assertRaises(OSError):
            fps.prepare_counter(self.port, self.root / 'nonexistent')
        self.source.unlink()
        self.assert_refused()

    def test_launch_delays_checks_game_and_bounds_prepare_before_exec(self):
        command = ['env', 'LD_PRELOAD=armhf.so', 'box86', 'wine', 'explorer.exe']
        with mock.patch.object(fps.time, 'sleep') as sleep, \
             mock.patch.object(fps.os, 'kill') as kill, \
             mock.patch.object(fps.subprocess, 'run') as run, \
             mock.patch.object(fps.os, 'execvpe') as execute, \
             mock.patch('builtins.print'):
            timeline = mock.Mock()
            for name, method in [('sleep', sleep), ('kill', kill),
                                 ('prepare', run), ('execute', execute)]:
                timeline.attach_mock(method, name)
            fps.launch_counter(self.port, self.work, 4321, command)
        self.assertEqual([call[0] for call in timeline.mock_calls],
                         ['sleep', 'kill', 'prepare', 'kill', 'execute'])
        sleep.assert_called_once_with(10)
        self.assertEqual(kill.call_args_list, [mock.call(4321, 0)] * 2)
        self.assertEqual(run.call_args.kwargs, dict(
            timeout=10, check=True, stdout=fps.subprocess.DEVNULL,
            stderr=fps.subprocess.DEVNULL))
        self.assertIn('--prepare', run.call_args.args[0])
        execute.assert_called_once_with('env', command, fps.os.environ)

    def test_dead_game_before_or_after_prepare_never_starts_wine(self):
        for effects in ([ProcessLookupError()], [None, ProcessLookupError()]):
            with self.subTest(effects=len(effects)), \
                 mock.patch.object(fps.time, 'sleep'), \
                 mock.patch.object(fps.os, 'kill', side_effect=effects), \
                 mock.patch.object(fps.subprocess, 'run') as run, \
                 mock.patch.object(fps.os, 'execvpe') as execute:
                with self.assertRaises(ProcessLookupError):
                    fps.launch_counter(self.port, self.work, 4321, ['wine'])
                execute.assert_not_called()
                self.assertEqual(run.call_count, len(effects) - 1)

    def test_prepare_timeout_failure_and_exec_failure_are_fixed_nonfatal_events(self):
        args = ['--launch', '--game-pid', '4321', '--port', 'private',
                '--work', 'private', '--', 'wine']
        for error in (fps.subprocess.TimeoutExpired('private', 10),
                      fps.subprocess.CalledProcessError(1, 'private'),
                      OSError('private')):
            with mock.patch.object(fps, 'launch_counter', side_effect=error):
                output = io.StringIO()
                self.assertEqual(fps.main(args, output), 1)
                self.assertEqual(json.loads(output.getvalue()[10:])['status'], 'unavailable')
                self.assertNotIn('private', output.getvalue())
        with mock.patch.object(fps.time, 'sleep'), \
             mock.patch.object(fps.os, 'kill'), \
             mock.patch.object(fps.subprocess, 'run',
                               side_effect=fps.subprocess.TimeoutExpired('private', 10)), \
             mock.patch.object(fps.os, 'execvpe') as execute:
            with self.assertRaises(fps.subprocess.TimeoutExpired):
                fps.launch_counter(self.port, self.work, 4321, ['wine'])
            execute.assert_not_called()

    def test_launch_rejects_missing_command_or_unsafe_pid_without_wait(self):
        for pid, command in ((0, ['wine']), (1, ['wine']), (-1, ['wine']), (4321, [])):
            with mock.patch.object(fps.time, 'sleep') as sleep:
                with self.assertRaises(ValueError):
                    fps.launch_counter(self.port, self.work, pid, command)
                sleep.assert_not_called()

    def test_legacy_hotkey_helper_is_not_started_by_game(self):
        script = (PORT / 'scripts/run-game.sh').read_text()
        self.assertNotIn('fps_counter.py', script)
        self.assertNotIn('pd2-fps-hotkey.exe', script)
        self.assertIn('fps_renderer.py', script)

    def test_cli_silent_success(self):
        output = io.StringIO()
        with mock.patch.object(fps, 'prepare_counter') as prepare:
            self.assertEqual(fps.main(['--prepare', '--port', str(self.port),
                                       '--work', str(self.work)], output), 0)
        prepare.assert_called_once_with(str(self.port), str(self.work))
        self.assertEqual(output.getvalue(), '')

    def test_cli_failure_closed_fixed_event(self):
        for args in ([], ['--prepare', '--port', 'secret/path'],
                     ['--work', 'private', '--port', 'private'],
                     ['--prepare', '--port', 'private', '--work', 'private', '--fps', '60']):
            output = io.StringIO()
            self.assertEqual(fps.main(args, output), 1)
            self.assertEqual(json.loads(output.getvalue()[10:]), dict(
                event='session_probe', phase='launch', check='fps_counter', status='unavailable'))
        output = io.StringIO()
        with mock.patch.object(fps, 'prepare_counter', side_effect=OSError('secret/path')):
            self.assertEqual(fps.main(['--prepare', '--port', 'private', '--work', 'private'], output), 1)
        self.assertNotIn('private', output.getvalue())
        self.assertNotIn('secret', output.getvalue())


if __name__ == '__main__':
    unittest.main()
