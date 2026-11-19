"""Regression tests for storage launcher validation ordering."""
import contextlib
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import uuid
from unittest import mock

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'sdcard/ports/projectdiablo2/storage-tools'))
import storage_launcher


class StorageLauncherTests(unittest.TestCase):
    def test_launch_full_validates_while_session_lock_is_held(self):
        temp = os.path.join(tempfile.gettempdir(), 'pd2-launcher-' + uuid.uuid4().hex)
        os.makedirs(temp)
        self.addCleanup(shutil.rmtree, temp, ignore_errors=True)
        port = Path(temp) / 'projectdiablo2'
        (port / 'logs').mkdir(parents=True)
        (port / 'runtime').mkdir()
        (port / 'runtime' / 'box86').write_bytes(b'box')
        events = []

        @contextlib.contextmanager
        def fake_lock(path):
            events.append(('lock-enter', Path(path).name))
            try:
                yield
            finally:
                events.append(('lock-exit', Path(path).name))

        def fake_validated(path, **kwargs):
            events.append(('validated', kwargs))
            return Path(path), {}, {'wine-8.0-x86.tar.xz': {'sha256': 'x'}}

        process = mock.Mock(stdout=[], wait=mock.Mock(return_value=0))
        with mock.patch.object(storage_launcher.sys, 'platform', 'linux'), \
             mock.patch.object(storage_launcher.os, 'getuid', return_value=1000, create=True), \
             mock.patch.object(storage_launcher.shutil, 'which', return_value='/bin/tool'), \
             mock.patch.object(storage_launcher, 'lock', side_effect=fake_lock), \
             mock.patch.object(storage_launcher, 'validated', side_effect=fake_validated), \
             mock.patch.object(storage_launcher, 'source_data'), \
             mock.patch.object(storage_launcher.subprocess, 'Popen', return_value=process), \
             mock.patch.object(storage_launcher.os, 'readlink', return_value='mnt:[1]'), \
             mock.patch.object(storage_launcher, 'fixed_message'):
            self.assertEqual(storage_launcher.launch(port, 'check'), 0)

        self.assertEqual(events[0], ('lock-enter', 'session.lock'))
        self.assertEqual(events[1], ('validated', {'write_stamp': True}))
        self.assertEqual(events[-1], ('lock-exit', 'session.lock'))

    def test_launch_root_user_knulli_no_sudo_required(self):
        temp = os.path.join(tempfile.gettempdir(), 'pd2-launcher-root-' + uuid.uuid4().hex)
        os.makedirs(temp)
        self.addCleanup(shutil.rmtree, temp, ignore_errors=True)
        port = Path(temp) / 'projectdiablo2'
        (port / 'logs').mkdir(parents=True)
        (port / 'runtime').mkdir()
        (port / 'runtime' / 'box86').write_bytes(b'box')

        @contextlib.contextmanager
        def fake_lock(path):
            yield

        def fake_validated(path, **kwargs):
            return Path(path), {}, {'wine-8.0-x86.tar.xz': {'sha256': 'x'}}

        spawned_cmd = []
        def fake_popen(cmd, **kwargs):
            spawned_cmd.extend(cmd)
            return mock.Mock(stdout=[], wait=mock.Mock(return_value=0))

        # which returns None for sudo and runuser (missing on Knulli)
        def fake_which(tool):
            if tool in ('sudo', 'runuser'):
                return None
            return '/bin/' + tool

        with mock.patch.object(storage_launcher.sys, 'platform', 'linux'), \
             mock.patch.object(storage_launcher.os, 'getuid', return_value=0, create=True), \
             mock.patch.object(storage_launcher.shutil, 'which', side_effect=fake_which), \
             mock.patch.object(storage_launcher, 'lock', side_effect=fake_lock), \
             mock.patch.object(storage_launcher, 'validated', side_effect=fake_validated), \
             mock.patch.object(storage_launcher.subprocess, 'Popen', side_effect=fake_popen), \
             mock.patch.object(storage_launcher.os, 'readlink', return_value='mnt:[1]'), \
             mock.patch.object(storage_launcher, 'fixed_message'):
            self.assertEqual(storage_launcher.launch(port, 'check'), 0)

        self.assertNotIn('sudo', spawned_cmd)
        self.assertEqual(spawned_cmd[0], 'unshare')
        self.assertIn('--uid', spawned_cmd)
        self.assertEqual(spawned_cmd[spawned_cmd.index('--uid') + 1], '0')

    def test_launch_root_user_knulli_no_unshare_uses_shim(self):
        temp = os.path.join(tempfile.gettempdir(), 'pd2-launcher-root-shim-' + uuid.uuid4().hex)
        os.makedirs(temp)
        self.addCleanup(shutil.rmtree, temp, ignore_errors=True)
        port = Path(temp) / 'projectdiablo2'
        (port / 'logs').mkdir(parents=True)
        (port / 'runtime').mkdir()
        (port / 'runtime' / 'box86').write_bytes(b'box')
        (port / 'storage-tools').mkdir()
        (port / 'storage-tools' / 'unshare_shim.py').write_bytes(b'# shim')

        @contextlib.contextmanager
        def fake_lock(path):
            yield

        def fake_validated(path, **kwargs):
            return Path(path), {}, {'wine-8.0-x86.tar.xz': {'sha256': 'x'}}

        spawned_cmd = []
        def fake_popen(cmd, **kwargs):
            spawned_cmd.extend(cmd)
            return mock.Mock(stdout=[], wait=mock.Mock(return_value=0))

        # which returns None for sudo, runuser, unshare, and losetup (missing on Knulli)
        def fake_which(tool):
            if tool in ('sudo', 'runuser', 'unshare', 'losetup'):
                return None
            return '/bin/' + tool

        with mock.patch.object(storage_launcher.sys, 'platform', 'linux'), \
             mock.patch.object(storage_launcher.os, 'getuid', return_value=0, create=True), \
             mock.patch.object(storage_launcher.shutil, 'which', side_effect=fake_which), \
             mock.patch.object(storage_launcher, 'lock', side_effect=fake_lock), \
             mock.patch.object(storage_launcher, 'validated', side_effect=fake_validated), \
             mock.patch.object(storage_launcher.subprocess, 'Popen', side_effect=fake_popen), \
             mock.patch.object(storage_launcher.os, 'readlink', return_value='mnt:[1]'), \
             mock.patch.object(storage_launcher, 'fixed_message'):
            self.assertEqual(storage_launcher.launch(port, 'check'), 0)

        self.assertNotIn('sudo', spawned_cmd)
        self.assertNotIn('unshare', spawned_cmd)
        self.assertTrue(any('unshare_shim.py' in str(arg) for arg in spawned_cmd))
        self.assertIn('--propagation', spawned_cmd)
        self.assertIn('--uid', spawned_cmd)
        self.assertEqual(spawned_cmd[spawned_cmd.index('--uid') + 1], '0')

    def test_launch_missing_game_files_triggers_screen_message(self):
        temp = os.path.join(tempfile.gettempdir(), 'pd2-launcher-' + uuid.uuid4().hex)
        os.makedirs(temp)
        self.addCleanup(shutil.rmtree, temp, ignore_errors=True)
        port = Path(temp) / 'projectdiablo2'
        (port / 'logs').mkdir(parents=True)
        (port / 'runtime').mkdir()
        (port / 'runtime' / 'box86').write_bytes(b'box')

        @contextlib.contextmanager
        def fake_lock(path):
            yield

        def fake_source_data(p):
            raise storage_launcher.StorageError('Diablo II game files not found. Place Diablo II into gamedata')

        with mock.patch.object(storage_launcher.sys, 'platform', 'linux'), \
             mock.patch.object(storage_launcher.os, 'getuid', return_value=1000, create=True), \
             mock.patch.object(storage_launcher.shutil, 'which', return_value='/bin/tool'), \
             mock.patch.object(storage_launcher, 'lock', side_effect=fake_lock), \
             mock.patch.object(storage_launcher, 'validated', return_value=(port, {}, {})), \
             mock.patch.object(storage_launcher, 'source_data', side_effect=fake_source_data), \
             mock.patch.object(storage_launcher, 'show_missing_game_files') as mock_show:
            with self.assertRaises(storage_launcher.StorageError):
                storage_launcher.launch(port, 'launch')
            mock_show.assert_called_once_with(port)

    def test_show_missing_game_files_formats_screen_message(self):
        temp = os.path.join(tempfile.gettempdir(), 'pd2-launcher-' + uuid.uuid4().hex)
        os.makedirs(temp)
        self.addCleanup(shutil.rmtree, temp, ignore_errors=True)
        port = Path(temp) / 'projectdiablo2'
        written = []

        class FakeFile:
            def write(self, s):
                written.append(s)
            def flush(self):
                pass

        @contextlib.contextmanager
        def fake_open(path, mode='r'):
            yield FakeFile()

        with mock.patch.dict(os.environ, {'PD2_TESTING': '1', 'CUR_TTY': '/dev/fake_tty'}), \
             mock.patch('builtins.open', side_effect=fake_open):
            storage_launcher.show_missing_game_files(port)

        full_output = ''.join(written)
        self.assertIn('\033c', full_output)
        self.assertIn('ERROR: Game files missing from gamedata!', full_output)
        self.assertIn('ProjectD2/Game.exe', full_output)
        self.assertIn('Returning to menu in 7 seconds...', full_output)

    def test_project_diablo_2_launcher_detects_missing_game_files(self):
        if not shutil.which('bash'):
            self.skipTest('bash not found in PATH')
        temp = os.path.join(tempfile.gettempdir(), 'pd2-sh-' + uuid.uuid4().hex)
        os.makedirs(temp)
        self.addCleanup(shutil.rmtree, temp, ignore_errors=True)
        ports_dir = Path(temp) / 'ports'
        ports_dir.mkdir()
        root = Path(__file__).resolve().parents[1]
        sh_script = ports_dir / 'Project Diablo 2.sh'
        shutil.copy2(root / 'sdcard/ports/Project Diablo 2.sh', sh_script)
        pd2_dir = ports_dir / 'projectdiablo2'
        pd2_dir.mkdir()
        (pd2_dir / 'gamedata').mkdir()

        res = subprocess.run(['bash', 'Project Diablo 2.sh'],
                             cwd=str(ports_dir),
                             env=dict(os.environ, WSLENV='PD2_TESTING/u', PD2_TESTING='1'),
                             capture_output=True, errors='replace')
        self.assertEqual(res.returncode, 1)
        log_file = pd2_dir / 'logs/storage-session.log'
        self.assertTrue(log_file.exists())
        self.assertIn('missing_game_files', log_file.read_text(encoding='utf-8'))

    def test_project_diablo_2_launcher_proceeds_when_game_files_present(self):
        if not shutil.which('bash'):
            self.skipTest('bash not found in PATH')
        temp = os.path.join(tempfile.gettempdir(), 'pd2-sh-' + uuid.uuid4().hex)
        os.makedirs(temp)
        self.addCleanup(shutil.rmtree, temp, ignore_errors=True)
        ports_dir = Path(temp) / 'ports'
        ports_dir.mkdir()
        root = Path(__file__).resolve().parents[1]
        sh_script = ports_dir / 'Project Diablo 2.sh'
        shutil.copy2(root / 'sdcard/ports/Project Diablo 2.sh', sh_script)
        pd2_dir = ports_dir / 'projectdiablo2'
        pd2_dir.mkdir()
        (pd2_dir / 'gamedata/Diablo II/ProjectD2').mkdir(parents=True)
        (pd2_dir / 'gamedata/Diablo II/ProjectD2/Game.exe').write_bytes(b'exe')
        (pd2_dir / 'storage-tools').mkdir(parents=True)
        (pd2_dir / 'storage-tools/storage_launcher.py').write_text(
            'import sys\nprint("STORAGE_LAUNCHER_REACHED")\nsys.exit(0)\n', encoding='utf-8'
        )

        res = subprocess.run(['bash', 'Project Diablo 2.sh'],
                             cwd=str(ports_dir),
                             env=dict(os.environ, WSLENV='PD2_TESTING/u', PD2_TESTING='1'),
                             capture_output=True, text=True, errors='replace', timeout=10)
        self.assertEqual(res.returncode, 0)
        self.assertIn("STORAGE_LAUNCHER_REACHED", res.stdout)
        log_file = pd2_dir / 'logs/storage-session.log'
        if log_file.exists():
            self.assertNotIn('missing_game_files', log_file.read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
