"""Regression tests for storage launcher validation ordering."""
import contextlib
import os
from pathlib import Path
import shutil
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


if __name__ == '__main__':
    unittest.main()
