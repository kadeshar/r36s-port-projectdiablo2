"""Local ALSA selection is authenticated, volatile and non-overwriting."""
import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import struct
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'sdcard/ports/projectdiablo2/scripts'
with mock.patch.object(sys, 'path', [str(SCRIPTS), *sys.path]):
    spec = importlib.util.spec_from_file_location('pd2_audio_compat', SCRIPTS / 'audio_compat.py')
    compat = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(compat)
spec = importlib.util.spec_from_file_location('pd2_compat_safe', SCRIPTS / 'safe_log.py')
safe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(safe)


class CompatTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='pd2-compat-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.port = self.root / 'port'
        self.source = self.port / compat.LIBRARY_PATH
        self.source.parent.mkdir(parents=True)
        self.content = (ROOT / 'sdcard/ports/projectdiablo2' / compat.LIBRARY_PATH).read_bytes()
        self.source.write_bytes(self.content)
        self.work = self.root / 'work'
        self.work.mkdir()

    def test_library_pin_abi_and_private_copy(self):
        self.assertEqual(hashlib.sha256(self.content).hexdigest(), compat.LIBRARY_SHA256)
        self.assertEqual(self.content[:6], b'\x7fELF\x01\x01')
        self.assertEqual(struct.unpack_from('<H', self.content, 18)[0], 40)
        self.assertTrue(struct.unpack_from('<I', self.content, 36)[0] & 0x400)
        self.assertIn(b'ALSA_0.9.0rc4\0', self.content)
        self.assertNotIn(b'GLIBC_2.34', self.content)
        destination = compat.prepare(self.port, self.work)
        self.assertEqual((destination / 'libasound.so.2').read_bytes(), self.content)
        self.assertEqual(self.source.read_bytes(), self.content)
        self.assertEqual(list(self.work.iterdir()), [destination])
        if os.name == 'posix':
            self.assertEqual(stat.S_IMODE(destination.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE((destination / 'libasound.so.2').stat().st_mode), 0o400)
        with self.assertRaises(ValueError):
            compat.prepare(self.port, self.work)
        self.assertEqual((destination / 'libasound.so.2').read_bytes(), self.content)

    def test_tampering_fails_before_publication_without_raw_error(self):
        self.source.write_bytes(b'private broken library')
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(compat.main(['--port', str(self.port), '--work', str(self.work)]), 1)
        value = json.loads(output.getvalue().removeprefix('PD2_EVENT '))
        self.assertEqual(value['status'], 'unavailable')
        self.assertEqual(safe.validate_event(value), value)
        self.assertNotIn(str(self.root), output.getvalue())
        self.assertEqual(list(self.work.iterdir()), [])

    def test_unrelated_stale_directory_is_preserved(self):
        target = self.work / compat.DIRECTORY
        target.mkdir()
        (target / 'user-file').write_bytes(b'keep')
        with self.assertRaises(ValueError):
            compat.prepare(self.port, self.work)
        self.assertEqual((target / 'user-file').read_bytes(), b'keep')

    def test_release_allows_only_the_named_local_library_and_source(self):
        spec = importlib.util.spec_from_file_location('pd2_compat_prepare', ROOT / 'tools/prepare.py')
        package = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(package)
        relative = 'projectdiablo2/' + compat.LIBRARY_PATH
        self.assertIn(relative, json.loads((ROOT / 'release-files.json').read_text()))
        package.validate_release_path(relative)
        with self.assertRaises(package.PrepareError):
            package.validate_release_path('projectdiablo2/compat/alsa-legacy-armhf/arbitrary.so.2')
