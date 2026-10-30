"""Unit tests for storage_common module and ensure_state_image."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
import uuid
from unittest import mock

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'sdcard/ports/projectdiablo2/storage-tools'))
import storage_common


def fresh_dir(prefix='pd2stc-'):
    """makedirs-based temp dir; mkdtemp's 0o700 DACL blocks nested writes on Windows."""
    path = os.path.join(tempfile.gettempdir(), prefix + uuid.uuid4().hex)
    os.makedirs(path)
    return path


class TestEnsureStateImage(unittest.TestCase):
    def setUp(self):
        self.temp_dir = fresh_dir()
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


class TestVerifyStamp(unittest.TestCase):
    """The write-verified integrity stamp and its trust semantics."""

    def setUp(self):
        self.temp_dir = fresh_dir()
        self.addCleanup(shutil.rmtree, self.temp_dir, ignore_errors=True)

    def _make_port(self):
        port = Path(self.temp_dir) / 'projectdiablo2'
        (port / 'runtime').mkdir(parents=True)
        (port / 'storage').mkdir(parents=True)
        (port / 'logs').mkdir(parents=True)
        wine_data = b'WINE-SQUASHFS-TEST'
        (port / 'runtime' / 'wine-8.0-x86.squashfs').write_bytes(wine_data)
        files = {
            'wine-8.0-x86.tar.xz': b'TAR-XZ',
            'box86': b'BOX86',
            'weston_pkg_0.2.squashfs': b'WESTON',
            'vc_redist.x86.exe': b'VCREDIST',
        }
        artifacts = {}
        for name, data in files.items():
            (port / 'runtime' / name).write_bytes(data)
            artifacts[name] = {
                'file': name,
                'size': len(data),
                'sha256': hashlib.sha256(data).hexdigest(),
            }
        (port / 'runtime-manifest.json').write_text(
            json.dumps({'schema_version': 1, 'artifacts': list(artifacts.values())}))
        # Sparse 1 GiB state image with a valid ext4 magic; never reallocated.
        with open(port / 'storage' / 'state.ext4', 'wb') as stream:
            stream.seek(1024 ** 3 - 1)
            stream.write(b'\0')
            stream.seek(1080)
            stream.write(b'\x53\xef')
        (port / 'storage-manifest.json').write_text(json.dumps({
            'schema_version': 1,
            'wine_file': 'runtime/wine-8.0-x86.squashfs',
            'state_file': 'storage/state.ext4',
            'wine_size': len(wine_data),
            'state_bytes': 1024 ** 3,
            'wine_sha256': hashlib.sha256(wine_data).hexdigest(),
            'source_wine_sha256': artifacts['wine-8.0-x86.tar.xz']['sha256'],
        }))
        return port

    def _stamp(self, port):
        return json.loads((port / 'logs' / storage_common.STAMP_FILE).read_text(encoding='utf-8'))

    def test_full_validation_writes_schema1_stamp(self):
        port = self._make_port()
        result = storage_common.validated(port, write_stamp=True)
        self.assertEqual(result[0], port)
        stamp = self._stamp(port)
        self.assertEqual(stamp['schema_version'], storage_common.STAMP_SCHEMA)
        self.assertEqual(stamp['wine']['size'], len(b'WINE-SQUASHFS-TEST'))
        self.assertEqual(stamp['state_bytes'], 1024 ** 3)
        self.assertEqual(set(stamp['artifacts']),
                         {'wine-8.0-x86.tar.xz', 'box86', 'weston_pkg_0.2.squashfs', 'vc_redist.x86.exe'})
        for item in result[2].values():
            self.assertEqual(stamp['artifacts'][item['file']]['sha256'], item['sha256'])

    def test_trusted_stamp_verifies_without_any_digest(self):
        port = self._make_port()
        storage_common.validated(port, write_stamp=True)
        with mock.patch.object(storage_common, 'digest',
                               side_effect=AssertionError('digest must not run on the trusted path')):
            storage_common.validated(port, trust_stamp=True)

    def test_missing_stamp_fails_closed(self):
        port = self._make_port()
        with self.assertRaises(storage_common.StorageError):
            storage_common.validated(port, trust_stamp=True)

    def test_stale_stamp_fails_closed_without_fallback(self):
        port = self._make_port()
        storage_common.validated(port, write_stamp=True)
        manifest = json.loads((port / 'storage-manifest.json').read_text(encoding='utf-8'))
        manifest['wine_sha256'] = '0' * 64
        (port / 'storage-manifest.json').write_text(json.dumps(manifest))
        with self.assertRaises(storage_common.StorageError):
            storage_common.validated(port, trust_stamp=True)

    def test_trusted_path_detects_runtime_size_change(self):
        port = self._make_port()
        storage_common.validated(port, write_stamp=True)
        with open(port / 'runtime' / 'box86', 'ab') as stream:
            stream.write(b'x')
        with self.assertRaises(storage_common.StorageError):
            storage_common.validated(port, trust_stamp=True)

    def test_full_validation_rejects_same_size_runtime_corruption(self):
        port = self._make_port()
        storage_common.validated(port, write_stamp=True)
        (port / 'runtime' / 'box86').write_bytes(b'BROKE')
        with self.assertRaises(storage_common.StorageError):
            storage_common.validated(port)

    def test_stamp_writes_use_unique_temporary_paths(self):
        port = self._make_port()
        _, info, pins = storage_common.validated(port)
        replacements = []
        with mock.patch.object(storage_common.os, 'replace',
                               side_effect=lambda source, target: replacements.append((source, target))):
            storage_common.write_verify_stamp(port, info, pins, len(b'WINE-SQUASHFS-TEST'))
            storage_common.write_verify_stamp(port, info, pins, len(b'WINE-SQUASHFS-TEST'))
        self.assertEqual(len(replacements), 2)
        self.assertNotEqual(Path(replacements[0][0]).name, Path(replacements[1][0]).name)
        self.assertTrue(all(Path(target).name == storage_common.STAMP_FILE
                            for _, target in replacements))

    def test_fallback_full_rehashes_everything_and_rewrites_stamp(self):
        port = self._make_port()
        (port / 'logs').mkdir(exist_ok=True)
        seen = []
        real_digest = storage_common.digest

        def spy(path):
            seen.append(str(path))
            return real_digest(path)

        with mock.patch.object(storage_common, 'digest', side_effect=spy):
            storage_common.validated(port, trust_stamp=True, trust_fallback_full=True, write_stamp=True)
        # Wine squashfs plus the four runtime artifacts, each hashed exactly once.
        self.assertEqual(len(seen), 5)
        stamp = self._stamp(port)
        self.assertEqual(stamp['schema_version'], storage_common.STAMP_SCHEMA)
        self.assertEqual(stamp['wine']['size'], len(b'WINE-SQUASHFS-TEST'))

    def test_full_validation_rejects_tampered_wine(self):
        port = self._make_port()
        manifest = json.loads((port / 'storage-manifest.json').read_text(encoding='utf-8'))
        manifest['wine_sha256'] = '0' * 64
        (port / 'storage-manifest.json').write_text(json.dumps(manifest))
        with self.assertRaises(storage_common.StorageError):
            storage_common.validated(port)

    def test_read_verify_stamp_rejects_garbage(self):
        port = self._make_port()
        (port / 'logs' / storage_common.STAMP_FILE).write_text('{not json', encoding='utf-8')
        with self.assertRaises(storage_common.StorageError):
            storage_common.read_verify_stamp(port)

    def test_read_verify_stamp_rejects_wrong_schema(self):
        port = self._make_port()
        (port / 'logs' / storage_common.STAMP_FILE).write_text(
            json.dumps({'schema_version': 2, 'wine': {}, 'artifacts': {}}), encoding='utf-8')
        with self.assertRaises(storage_common.StorageError):
            storage_common.read_verify_stamp(port)


if __name__ == '__main__':
    unittest.main()
