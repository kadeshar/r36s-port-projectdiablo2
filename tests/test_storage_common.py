"""Unit tests for storage_common module and ensure_state_image."""
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest import mock

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'sdcard/ports/projectdiablo2/storage-tools'))
import storage_common


class TestEnsureStateImage(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.port = Path(self.temp_dir)
        self.info = {
            'state_file': 'storage/state.ext4',
            'state_bytes': 4096,
        }
        (self.port / 'storage').mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _write_valid_mock_ext4(self, path, size):
        with open(path, 'wb') as f:
            f.seek(size - 1)
            f.write(b'\0')
            f.seek(1080)
            f.write(b'\x53\xef')

    def test_ensure_state_image_skips_when_valid(self):
        state_file = self.port / self.info['state_file']
        self._write_valid_mock_ext4(state_file, 4096)
        mtime_before = state_file.stat().st_mtime

        with mock.patch('subprocess.run') as mock_run:
            storage_common.ensure_state_image(self.port, self.info)
            mock_run.assert_not_called()

        self.assertTrue(state_file.exists())
        self.assertEqual(state_file.stat().st_size, 4096)

    def test_ensure_state_image_recreates_corrupt_zeroed_file(self):
        # Scenario from Issue #6: 0-byte or zero-filled file created during crash
        state_file = self.port / self.info['state_file']
        with open(state_file, 'wb') as f:
            f.seek(4095)
            f.write(b'\0')  # No magic at 1080

        def fake_mke2fs(cmd, **kwargs):
            target = cmd[-1]
            self._write_valid_mock_ext4(target, 4096)
            res = mock.MagicMock()
            res.returncode = 0
            return res

        with mock.patch('subprocess.run', side_effect=fake_mke2fs), \
             mock.patch('shutil.which', return_value='/sbin/mke2fs'):
            storage_common.ensure_state_image(self.port, self.info)

        self.assertTrue(state_file.exists())
        with open(state_file, 'rb') as f:
            f.seek(1080)
            self.assertEqual(f.read(2), b'\x53\xef')

    def test_ensure_state_image_creates_when_missing(self):
        state_file = self.port / self.info['state_file']
        self.assertFalse(state_file.exists())

        def fake_mke2fs(cmd, **kwargs):
            target = cmd[-1]
            self._write_valid_mock_ext4(target, 4096)
            res = mock.MagicMock()
            res.returncode = 0
            return res

        with mock.patch('subprocess.run', side_effect=fake_mke2fs), \
             mock.patch('shutil.which', return_value='/sbin/mke2fs'):
            storage_common.ensure_state_image(self.port, self.info)

        self.assertTrue(state_file.exists())
        with open(state_file, 'rb') as f:
            f.seek(1080)
            self.assertEqual(f.read(2), b'\x53\xef')

    def test_ensure_state_image_cleans_tmp_on_failure(self):
        state_file = self.port / self.info['state_file']
        tmp_file = state_file.with_name(state_file.name + '.tmp')

        def failing_mke2fs(cmd, **kwargs):
            res = mock.MagicMock()
            res.returncode = 1
            res.stderr = "device full"
            return res

        with mock.patch('subprocess.run', side_effect=failing_mke2fs), \
             mock.patch('shutil.which', return_value='/sbin/mke2fs'):
            with self.assertRaises(storage_common.StorageError) as ctx:
                storage_common.ensure_state_image(self.port, self.info)
            self.assertIn("device full", str(ctx.exception))

        self.assertFalse(state_file.exists())
        self.assertFalse(tmp_file.exists())

    def test_ensure_state_image_fallbacks_when_option_unsupported(self):
        # Scenario on ArkOS: mke2fs 1.45.3 rejects ^orphan_file with "Invalid filesystem option set"
        state_file = self.port / self.info['state_file']
        self.assertFalse(state_file.exists())

        calls = []

        def fallback_mke2fs(cmd, **kwargs):
            calls.append(cmd)
            res = mock.MagicMock()
            # If orphan_file in args, reject
            if any('orphan_file' in str(arg) for arg in cmd):
                res.returncode = 1
                res.stderr = "Invalid filesystem option set: ^64bit,^metadata_csum,^metadata_csum_seed,^orphan_file"
                return res
            # Otherwise succeed
            target = cmd[-1]
            self._write_valid_mock_ext4(target, 4096)
            res.returncode = 0
            return res

        with mock.patch('subprocess.run', side_effect=fallback_mke2fs), \
             mock.patch('shutil.which', return_value='/sbin/mke2fs'):
            storage_common.ensure_state_image(self.port, self.info)

        self.assertTrue(state_file.exists())
        self.assertEqual(len(calls), 2)
        # First call attempted orphan_file
        self.assertIn('^orphan_file', calls[0][calls[0].index('-O') + 1])
        # Second call omitted orphan_file
        self.assertNotIn('^orphan_file', calls[1][calls[1].index('-O') + 1])
        with open(state_file, 'rb') as f:
            f.seek(1080)
            self.assertEqual(f.read(2), b'\x53\xef')

    def test_ensure_state_image_stops_on_unrelated_error_without_fallback(self):
        calls = []

        def failing_mke2fs(cmd, **kwargs):
            calls.append(cmd)
            res = mock.MagicMock()
            res.returncode = 1
            res.stderr = "mke2fs: Permission denied when trying to open /tmp/state.ext4.tmp"
            return res

        with mock.patch('subprocess.run', side_effect=failing_mke2fs), \
             mock.patch('shutil.which', return_value='/sbin/mke2fs'):
            with self.assertRaises(storage_common.StorageError) as ctx:
                storage_common.ensure_state_image(self.port, self.info)
            self.assertIn("Permission denied", str(ctx.exception))

        # Should NOT try other candidates if the failure wasn't invalid option
        self.assertEqual(len(calls), 1)


if __name__ == '__main__':
    unittest.main()
