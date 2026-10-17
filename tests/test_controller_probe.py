"""Synthetic sysfs and mocked character-device syscalls; no controller required."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import shutil
import tempfile
import uuid
from types import SimpleNamespace
import unittest
from unittest import mock

SCRIPT = Path(__file__).resolve().parents[1] / 'sdcard/ports/projectdiablo2/scripts/controller_probe.py'
spec = importlib.util.spec_from_file_location('controller_probe', SCRIPT)
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


class ControllerProbeTests(unittest.TestCase):
    def setUp(self):
        # Python 3.14's Windows 0700 temp ACL excludes sandbox tokens.
        if os.name == 'posix':
            # Use a POSIX filesystem, not WSL drvfs (/mnt/c), for mode checks.
            self.root = Path(tempfile.mkdtemp(prefix='pd2-controller-test-'))
        else:
            self.root = Path(__file__).resolve().parent / ('.controller-test-' + uuid.uuid4().hex)
            self.root.mkdir(mode=0o777)
        self.addCleanup(shutil.rmtree, self.root)
        self.run = self.root / 'run'
        self.run.mkdir(mode=0o700 if os.name == 'posix' else 0o777)
        self.virtual = self.root / 'virtual/input'
        self.sys = self.virtual / 'class'
        self.sys.mkdir(parents=True)
        self.dev = self.root / 'dev'
        self.dev.mkdir()
        self.baseline = self.run / 'controller.json'
        self.elapsed = 0.0

    def event(self, name='event1', vendor='045e', product='028e'):
        ids = self.sys / name / 'device/id'
        ids.mkdir(parents=True)
        (ids / 'vendor').write_text(vendor + '\n', encoding='ascii')
        (ids / 'product').write_text(product + '\n', encoding='ascii')
        (self.dev / name).touch()

    def snapshot(self):
        return probe.snapshot(self.baseline, run_dir=self.run, sys_root=self.sys)

    def sleep(self, duration):
        self.elapsed += duration

    def wait(self, **kwargs):
        options = dict(run_dir=self.run, sys_root=self.sys, virtual_root=self.virtual,
                       dev_root=self.dev, clock=lambda: self.elapsed, sleep=self.sleep)
        options.update(kwargs)
        return probe.wait(self.baseline, **options)

    @contextlib.contextmanager
    def character_device(self, denied=False):
        """Only device-node calls are fake; snapshot and ID reads stay real."""
        original_stat = Path.stat
        original_open, original_close = os.open, os.close
        original_fstat, original_read = os.fstat, os.read
        opens, reads, closes = [], [], []
        fake_fd = 987654
        dev = self.dev

        def node_stat(path, *args, **kwargs):
            if path.parent == dev:
                return SimpleNamespace(st_mode=stat.S_IFCHR | 0o600)
            return original_stat(path, *args, **kwargs)

        def open_node(path, flags, *args, **kwargs):
            if Path(path).parent == dev:
                opens.append((Path(path).name, flags))
                if denied:
                    raise PermissionError()
                return fake_fd
            return original_open(path, flags, *args, **kwargs)

        def fstat(fd):
            if fd == fake_fd:
                return SimpleNamespace(st_mode=stat.S_IFCHR | 0o600)
            return original_fstat(fd)

        def close(fd):
            if fd == fake_fd:
                closes.append(fd)
                return
            return original_close(fd)

        def read(fd, count):
            reads.append(fd)
            self.assertNotEqual(fd, fake_fd, 'must never read event data')
            return original_read(fd, count)

        with mock.patch.object(Path, 'stat', node_stat), \
                mock.patch.object(os, 'open', open_node), \
                mock.patch.object(os, 'fstat', fstat), \
                mock.patch.object(os, 'close', close), \
                mock.patch.object(os, 'read', read):
            yield opens, reads, closes

    def test_old_virtual_xbox_ignored(self):
        self.event()
        self.assertEqual(self.snapshot(), 'ready')
        with self.character_device() as (opens, _, _):
            self.assertEqual(self.wait(), 'missing')
        self.assertEqual(opens, [])
        self.assertLessEqual(self.elapsed, 5.0)

    def test_physical_xbox_ignored(self):
        self.assertEqual(self.snapshot(), 'ready')
        self.event()
        other = self.root / 'different_virtual_root'
        other.mkdir()
        with self.character_device() as (opens, _, _):
            self.assertEqual(self.wait(virtual_root=other), 'missing')
        self.assertEqual(opens, [])

    def test_new_virtual_ready_opens_readwrite_without_reading(self):
        self.assertEqual(self.snapshot(), 'ready')
        self.event()
        with self.character_device() as (opens, _, closes):
            self.assertEqual(self.wait(), 'ready')
        self.assertEqual(len(opens), 1)
        self.assertEqual(opens[0][1] & os.O_RDWR, os.O_RDWR)
        nonblock = getattr(os, 'O_NONBLOCK', 0)
        self.assertEqual(opens[0][1] & nonblock, nonblock)
        self.assertEqual(len(closes), 1)

    def test_mapper_can_appear_during_poll(self):
        self.assertEqual(self.snapshot(), 'ready')
        def start_mapper(duration):
            self.sleep(duration)
            if not (self.sys / 'event1').exists():
                self.event()
        with self.character_device():
            self.assertEqual(self.wait(sleep=start_mapper), 'ready')
        self.assertGreater(self.elapsed, 0)

    def test_denied_timeout(self):
        self.snapshot()
        self.event()
        with self.character_device(denied=True) as (opens, _, _):
            self.assertEqual(self.wait(), 'denied')
        self.assertLessEqual(len(opens), probe.MAX_POLLS)
        self.assertLessEqual(self.elapsed, 5.0)

    def test_missing_timeout_and_frozen_clock_bound(self):
        self.snapshot()
        sleeps = []
        self.assertEqual(self.wait(clock=lambda: 0, sleep=sleeps.append), 'missing')
        self.assertEqual(len(sleeps), probe.MAX_POLLS - 1)
        self.assertLessEqual(sum(sleeps), 5.000001)

    def test_wrong_ids_and_regular_nodes_not_ready(self):
        self.snapshot()
        self.event(vendor='1234')
        with self.character_device() as (opens, _, _):
            self.assertEqual(self.wait(), 'missing')
        self.assertFalse(opens)
        (self.sys / 'event1/device/id/vendor').write_text('045e\n')
        self.assertEqual(self.wait(), 'missing')  # Real node is a regular file.

    def test_malformed_and_oversized_baselines(self):
        for data in (b'{}', b'["event../secret"]', b'["event1", "event1"]',
                     b'[1]', b'null', b'\xff', b'[' * 2000,
                     b' ' * (probe.MAX_BYTES + 1),
                     json.dumps(['event' + str(i) for i in range(probe.MAX_ITEMS + 1)]).encode()):
            with self.subTest(data=data[:25]):
                self.baseline.write_bytes(data)
                self.assertEqual(self.wait(), 'invalid')

    def test_symlink_snapshot_rejected_without_following(self):
        target = self.run / 'target'
        target.write_text('[]')
        real_lstat = Path.lstat
        def lstat(path, *args, **kwargs):
            if path == self.baseline:
                return SimpleNamespace(st_mode=stat.S_IFLNK | 0o777)
            return real_lstat(path, *args, **kwargs)
        with mock.patch.object(Path, 'lstat', lstat):
            self.assertEqual(self.snapshot(), 'invalid')
            self.assertEqual(self.wait(), 'invalid')
        self.assertEqual(target.read_text(), '[]')

    def test_requires_run_directory_and_bounds_enumeration(self):
        self.assertEqual(probe.snapshot(self.root / 'outside', run_dir=self.run,
                                        sys_root=self.sys), 'invalid')
        for i in range(probe.MAX_ITEMS + 1):
            (self.sys / ('event' + str(i))).mkdir()
        self.assertEqual(self.snapshot(), 'invalid')
        self.assertFalse(self.baseline.exists())

    def test_baseline_contains_only_event_identifiers_and_atomic_replace(self):
        self.event('event23')
        for name in ('mouse0', 'event1-name', 'event１２', 'event12345678901'):
            (self.sys / name).mkdir()
        self.assertEqual(self.snapshot(), 'ready')
        self.assertEqual(json.loads(self.baseline.read_text()), ['event23'])
        before = self.baseline.read_bytes()
        with mock.patch.object(probe.os, 'replace', side_effect=PermissionError()):
            self.assertEqual(self.snapshot(), 'denied')
        self.assertEqual(self.baseline.read_bytes(), before)
        self.assertEqual(list(self.run.iterdir()), [self.baseline])

    def test_unavailable_sysfs_and_bounded_ids(self):
        self.snapshot()
        self.assertEqual(self.wait(sys_root=self.root / 'not-present'), 'unavailable')
        self.event()
        (self.sys / 'event1/device/id/vendor').write_bytes(b'045e' + b' ' * 100)
        with self.character_device() as (opens, _, _):
            self.assertEqual(self.wait(), 'unavailable')
        self.assertEqual(opens, [])

    def test_snapshot_is_private_on_posix(self):
        if os.name != 'posix':
            return
        self.snapshot()
        self.assertEqual(self.baseline.stat().st_mode & 0o777, 0o600)
        original = Path.stat
        def public_directory(path, *args, **kwargs):
            info = original(path, *args, **kwargs)
            if path == self.run:
                return SimpleNamespace(st_mode=stat.S_IFDIR | 0o755, st_uid=info.st_uid)
            return info
        with mock.patch.object(Path, 'stat', public_directory):
            self.assertEqual(self.wait(), 'invalid')

    def test_logger_accepts_only_closed_statuses_without_input_data(self):
        log_spec = importlib.util.spec_from_file_location('probe_safe_log', SCRIPT.with_name('safe_log.py'))
        logger = importlib.util.module_from_spec(log_spec)
        log_spec.loader.exec_module(logger)
        for status in ('ready', 'missing', 'denied', 'invalid', 'unavailable'):
            event = dict(event='session_probe', phase='launch', check='virtual_gamepad', status=status)
            self.assertEqual(logger.validate_event(event), event)
            for field in ('path', 'name', 'buttons', 'axes', 'count'):
                self.assertIsNone(logger.validate_event(dict(event, **{field: 'private'})))
        self.assertIsNone(logger.validate_event(dict(event='session_probe', phase='launch',
                                                     check='virtual_gamepad', status='XInput confirmed')))

    def test_safe_single_event_and_exit_codes(self):
        for status in ('ready', 'missing', 'denied', 'invalid', 'unavailable'):
            for mode in ('--snapshot', '--wait'):
                with self.subTest(status=status, mode=mode):
                    output = io.StringIO()
                    function = 'snapshot' if mode == '--snapshot' else 'wait'
                    with mock.patch.object(probe, function, return_value=status), \
                            contextlib.redirect_stdout(output):
                        code = probe.main([mode, str(self.baseline)])
                    self.assertEqual(code, 0 if status == 'ready' else 1)
                    if mode == '--snapshot' and status == 'ready':
                        self.assertEqual(output.getvalue(), '')
                    else:
                        lines = output.getvalue().splitlines()
                        self.assertEqual(len(lines), 1)
                        self.assertTrue(lines[0].startswith('PD2_EVENT '))
                        self.assertEqual(json.loads(lines[0][10:]), dict(event='session_probe',
                                         check='virtual_gamepad', phase='launch', status=status))
                        self.assertNotIn(str(self.root), lines[0])


if __name__ == '__main__':
    unittest.main()
