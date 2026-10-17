"""Verify our diagnostic executable, its session link, and closed log schema."""
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import struct
import tempfile
import unittest
import uuid
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
PORT = ROOT / 'sdcard/ports/projectdiablo2'
SPEC = importlib.util.spec_from_file_location('artifact_result', PORT / 'scripts/xinput_result.py')
result = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(result)


class ArtifactTests(unittest.TestCase):
    def setUp(self):
        if os.name == 'posix':
            self.root = Path(tempfile.mkdtemp(prefix='pd2-artifact-'))
        else:
            self.root = ROOT / 'tests' / ('.artifact-' + uuid.uuid4().hex)
            self.root.mkdir()
        self.addCleanup(shutil.rmtree, self.root)
        self.port = self.root / 'port'
        self.work = self.root / 'work'
        self.source = self.port / 'compat/xinput-probe/xinput-probe.exe'
        self.source.parent.mkdir(parents=True)
        (self.work / 'ProjectD2').mkdir(parents=True)
        self.source.write_bytes((PORT / 'compat/xinput-probe/xinput-probe.exe').read_bytes())

    def test_authentic_pe_is_x86_and_self_contained(self):
        blob = self.source.read_bytes()
        self.assertEqual(len(blob), result.PROBE_SIZE)
        self.assertEqual(hashlib.sha256(blob).hexdigest(), result.PROBE_SHA256)
        self.assertEqual(blob[:2], b'MZ')
        pe = struct.unpack_from('<I', blob, 0x3c)[0]
        self.assertEqual(blob[pe:pe+4], b'PE\0\0')
        machine, sections = struct.unpack_from('<HH', blob, pe+4)
        self.assertEqual(machine, 0x14c)
        optional_size = struct.unpack_from('<H', blob, pe+20)[0]
        optional = pe+24
        self.assertEqual(struct.unpack_from('<H', blob, optional)[0], 0x10b)
        table = optional+optional_size
        def offset(rva):
            for i in range(sections):
                base = table+i*40
                vsize, va, rawsize, raw = struct.unpack_from('<IIII', blob, base+8)
                if va <= rva < va+max(vsize, rawsize):
                    return raw+rva-va
            raise AssertionError('invalid RVA')
        imports_rva = struct.unpack_from('<I', blob, optional+104)[0]
        index = offset(imports_rva)
        libraries = set()
        while any(blob[index:index+20]):
            name = offset(struct.unpack_from('<I', blob, index+12)[0])
            libraries.add(blob[name:blob.index(b'\0', name)].decode().lower())
            index += 20
        self.assertTrue({'kernel32.dll','user32.dll','gdi32.dll'} <= libraries)
        self.assertTrue(libraries <= {'kernel32.dll','user32.dll','gdi32.dll'}, libraries)

    def test_prepare_authenticates_then_links_only_expected_executable(self):
        with mock.patch.object(Path, 'symlink_to') as link:
            result.prepare_probe(self.port, self.work)
        link.assert_called_once_with(self.source)

    def test_tampered_or_stale_files_rejected_without_link(self):
        for stale in ('pd2-xinput-probe.exe', 'pd2-xinput-result.json',
                      'pd2-button-step.txt', 'pd2-button-physical.txt'):
            path = self.work / 'ProjectD2' / stale
            path.write_text('unrelated')
            with mock.patch.object(Path, 'symlink_to') as link:
                with self.assertRaises(ValueError):
                    result.prepare_probe(self.port, self.work)
            link.assert_not_called()
            self.assertEqual(path.read_text(), 'unrelated')
            path.unlink()
        self.source.write_bytes(b'unknown executable')
        with mock.patch.object(Path, 'symlink_to') as link:
            with self.assertRaises(ValueError):
                result.prepare_probe(self.port, self.work)
        link.assert_not_called()

    def test_prepare_cli_silent_success_and_safe_failure(self):
        output = io.StringIO()
        with mock.patch.object(result, 'prepare_probe') as prepare:
            self.assertEqual(result.main(['--prepare','--work',str(self.work),'--port',str(self.port)], output),0)
        prepare.assert_called_once_with(str(self.port),str(self.work))
        self.assertEqual(output.getvalue(), '')
        self.assertEqual(result.main(['--prepare','--work',str(self.work)],output),1)
        self.assertNotIn(str(self.work),output.getvalue())

    def test_builder_allows_only_this_probe_not_arbitrary_executables(self):
        import test_prepare
        builder = test_prepare.prepare
        builder.validate_release_path('projectdiablo2/compat/xinput-probe/xinput-probe.exe')
        for path in ('projectdiablo2/compat/xinput-probe/other.exe',
                     'projectdiablo2/scripts/game.exe', 'projectdiablo2/gamedata/Game.exe'):
            with self.assertRaises(builder.PrepareError):
                builder.validate_release_path(path)
        files = json.loads((ROOT/'release-files.json').read_text())
        self.assertIn('projectdiablo2/compat/xinput-probe/xinput-probe.exe', files)

    def test_logger_accepts_enums_not_raw_input(self):
        spec = importlib.util.spec_from_file_location('artifact_log', PORT/'scripts/safe_log.py')
        logger = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(logger)
        allowed = dict(result.FIELDS, winebus_backend=('udev','restored'))
        for check, statuses in allowed.items():
            check = check if check == 'winebus_backend' else 'xinput_'+check
            for status in statuses:
                event = dict(event='session_probe',phase='launch',check=check,status=status)
                self.assertEqual(logger.validate_event(event),event)
                for field in ('buttons','axes','path','name','values'):
                    self.assertIsNone(logger.validate_event(dict(event,**{field:'private'})))
                self.assertIsNone(logger.validate_event(dict(event,status='arbitrary text')))


if __name__ == '__main__':
    unittest.main()
