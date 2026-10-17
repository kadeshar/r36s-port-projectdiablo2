"""Independent renderer selection/security tests; no GUI/game/Wine required."""
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
SPEC = importlib.util.spec_from_file_location('present_renderer', PORT / 'scripts/present_renderer.py')
renderer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(renderer)


class RendererTests(unittest.TestCase):
    def setUp(self):
        self.root = ROOT / '.state/present-renderer-tests' / uuid.uuid4().hex
        self.root.mkdir(parents=True)
        self.addCleanup(shutil.rmtree, self.root)
        self.port, self.work = self.root / 'port with spaces', self.root / 'work'
        self.source = self.port / 'compat/present-renderer/ddraw.dll'
        self.source.parent.mkdir(parents=True)
        self.original = self.port / 'compat/cnc-ddraw/ddraw.dll'
        self.original.parent.mkdir(parents=True)
        self.original.write_bytes(b'original upstream bytes')
        self.data = b'MZsynthetic authenticated diagnostic renderer'
        self.source.write_bytes(self.data)
        self.directory = self.work / 'ProjectD2'
        self.directory.mkdir(parents=True)
        self.target = self.directory / 'ddraw.dll'
        self.addCleanup(mock.patch.stopall)
        mock.patch.object(renderer, 'RENDERER_SIZE', len(self.data)).start()
        mock.patch.object(renderer, 'RENDERER_SHA256', hashlib.sha256(self.data).hexdigest()).start()

    def link(self, target=None):
        try:
            self.target.symlink_to(self.original if target is None else target)
        except OSError as exc:
            if getattr(exc, 'winerror', None) == 1314:
                self.skipTest('Windows symlink privilege unavailable')
            raise

    def test_authenticated_selection_preserves_original(self):
        self.link()
        renderer.prepare_renderer(self.port, self.work)
        self.assertFalse(self.target.is_symlink())
        self.assertEqual(self.target.read_bytes(), self.data)
        self.assertEqual(self.original.read_bytes(), b'original upstream bytes')
        self.assertFalse((self.directory / '.pd2-present-renderer.tmp').exists())
        with self.assertRaises(ValueError):
            renderer.prepare_renderer(self.port, self.work)

    def test_case_insensitive_dll_name(self):
        self.target = self.directory / 'DDraw.DLL'
        self.test_authenticated_selection_preserves_original()

    def test_tampered_truncated_oversize_source(self):
        for data in (b'', b'x' * len(self.data), self.data + b'x'):
            self.source.write_bytes(data)
            with self.assertRaises(ValueError):
                renderer.prepare_renderer(self.port, self.work)
        self.assertEqual(list(self.directory.iterdir()), [])

    def test_hardlinked_source(self):
        os.link(self.source, self.root / 'hardlink.dll')
        with self.assertRaises(ValueError):
            renderer.prepare_renderer(self.port, self.work)

    def test_missing_regular_and_foreign_targets_preserved(self):
        with self.assertRaises(ValueError):
            renderer.prepare_renderer(self.port, self.work)
        self.target.write_bytes(b'user data')
        with self.assertRaises(ValueError):
            renderer.prepare_renderer(self.port, self.work)
        self.assertEqual(self.target.read_bytes(), b'user data')
        self.target.unlink()
        self.link(self.source)
        with self.assertRaises(ValueError):
            renderer.prepare_renderer(self.port, self.work)
        self.assertEqual(os.readlink(self.target), str(self.source))

    def test_fps_renderer_link_is_never_replaced(self):
        fps = self.port / 'compat/fps-renderer/ddraw.dll'
        fps.parent.mkdir(parents=True)
        fps.write_bytes(b'FPS bytes')
        self.link(fps)
        with self.assertRaises(ValueError):
            renderer.prepare_renderer(self.port, self.work)
        self.assertEqual(fps.read_bytes(), b'FPS bytes')
        self.assertEqual(os.readlink(self.target), str(fps))

    def test_source_symlink_reparse_and_ancestor_links(self):
        original = Path.lstat
        for suspect in (self.source, self.source.parent, self.port, self.work, self.directory):
            def fake(path, *args, **kwargs):
                info = original(path, *args, **kwargs)
                if path == suspect:
                    return mock.Mock(st_mode=info.st_mode, st_file_attributes=0x400)
                return info
            with self.subTest(path=suspect), mock.patch.object(Path, 'lstat', fake):
                with self.assertRaises(ValueError):
                    renderer.prepare_renderer(self.port, self.work)

    def test_changed_source_identity_before_write(self):
        original = os.fstat
        def changed(fd):
            info = original(fd)
            return mock.Mock(st_mode=info.st_mode, st_nlink=1, st_dev=info.st_dev,
                             st_ino=info.st_ino + 1, st_size=info.st_size,
                             st_mtime_ns=info.st_mtime_ns)
        with mock.patch.object(os, 'fstat', side_effect=changed):
            with self.assertRaises(ValueError):
                renderer.prepare_renderer(self.port, self.work)
        self.assertEqual(list(self.directory.iterdir()), [])

    def test_stale_pending_preserved(self):
        self.link()
        pending = self.directory / '.pd2-present-renderer.tmp'
        pending.write_bytes(b'stale')
        with self.assertRaises(FileExistsError):
            renderer.prepare_renderer(self.port, self.work)
        self.assertTrue(self.target.is_symlink())
        self.assertEqual(pending.read_bytes(), b'stale')

    def test_replace_failure_preserves_original_cleans_own_temp(self):
        self.link()
        with mock.patch.object(os, 'replace', side_effect=OSError('secret')):
            with self.assertRaises(OSError):
                renderer.prepare_renderer(self.port, self.work)
        self.assertTrue(self.target.is_symlink())
        self.assertFalse((self.directory / '.pd2-present-renderer.tmp').exists())

    def test_dotdot_refused(self):
        with self.assertRaises(ValueError):
            renderer.prepare_renderer(self.port / '..' / self.port.name, self.work)

    def test_cli_numeric_status_no_private_data(self):
        for failure in (None, OSError('secret path')):
            out = io.StringIO()
            with mock.patch.object(renderer, 'prepare_renderer', side_effect=failure):
                rc = renderer.main(['--port', 'private', '--work', 'private'], out)
            self.assertEqual(rc, 1 if failure else 0)
            self.assertEqual(json.loads(out.getvalue()), {'status': rc})
            self.assertNotIn('secret', out.getvalue())
            self.assertNotIn('private', out.getvalue())
        out = io.StringIO()
        self.assertEqual(renderer.main(['--port', 'secret'], out), 1)
        self.assertEqual(json.loads(out.getvalue()), {'status': 1})


class ArtifactTests(unittest.TestCase):
    def test_authenticated_x86_release_and_isolation(self):
        blob = (PORT / 'compat/present-renderer/ddraw.dll').read_bytes()
        self.assertEqual(len(blob), renderer.RENDERER_SIZE)
        self.assertEqual(hashlib.sha256(blob).hexdigest(), renderer.RENDERER_SHA256)
        pe = struct.unpack_from('<I', blob, 0x3c)[0]
        self.assertEqual(blob[pe:pe + 4], b'PE\0\0')
        self.assertEqual(struct.unpack_from('<H', blob, pe + 4)[0], 0x14c)
        untouched = {
            'cnc-ddraw': '85e0f7d530dfda134793a57cb3e76b0287dcc96892ee57162dd68f47283b03a9',
            'fps-renderer': 'acb44f73f3ee0b2aa4ac98ed860b40e0d9389162eaa7de9ec0028affc778ba5a',
        }
        for name, digest in untouched.items():
            other = (PORT / 'compat' / name / 'ddraw.dll').read_bytes()
            self.assertNotEqual(blob, other)
            self.assertEqual(hashlib.sha256(other).hexdigest(), digest)
        manifest = json.loads((PORT / 'compat/present-renderer/manifest.json').read_text())
        self.assertEqual((manifest['size'], manifest['sha256']),
                         (renderer.RENDERER_SIZE, renderer.RENDERER_SHA256))
        for name, digest in manifest['build']['inputs_sha256'].items():
            self.assertEqual(hashlib.sha256((ROOT / 'tools' / name).read_bytes()).hexdigest(), digest)
        patch = PORT / 'compat/present-renderer/source.patch'
        self.assertEqual(hashlib.sha256(patch.read_bytes()).hexdigest(), manifest['build']['source_patch_sha256'])
        self.assertEqual(manifest['telemetry']['max_bytes'], renderer.MAX_TELEMETRY)
        self.assertEqual(manifest['telemetry']['file'], renderer.TELEMETRY_FILE)
        self.assertEqual(set(manifest['telemetry']['event']), {'1', '2', '3'})
        self.assertIn('once per backend per process', manifest['telemetry']['event']['3'])
        self.assertIn(b'p\x00d\x002\x00-\x00p\x00r\x00e\x00s\x00e\x00n\x00t\x00.\x00j\x00s\x00o\x00n\x00l\x00', blob)

    def test_source_patch_no_added_surface_manipulation_or_hud(self):
        patch = (PORT / 'compat/present-renderer/source.patch').read_text()
        added = '\n'.join(line[1:] for line in patch.splitlines() if line.startswith('+') and not line.startswith('+++'))
        for forbidden in ('primary->surface', 'DrawText(', 'memcpy(', 'pd2_pixels', 'SendInput(', 'WinHttp', 'urlretrieve'):
            self.assertNotIn(forbidden, added)
        self.assertIn('IsWindow(g_ddraw.hwnd)', added)
        self.assertIn('SwapBuffers(g_ogl.hdc) != 0', added)
        self.assertIn('lines_copied = real_SetDIBitsToDevice(', added)
        self.assertIn('CREATE_NEW', added)
        self.assertIn('PD2_PRESENT_LIMIT - pd2_present_bytes', added)


if __name__ == '__main__':
    unittest.main()
