"""Automatic HUD selection tests: no game, Wine, pad or screen required."""
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import stat
import struct
import unittest
import uuid
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
PORT = ROOT / 'sdcard/ports/projectdiablo2'
SPEC = importlib.util.spec_from_file_location('fps_renderer', PORT / 'scripts/fps_renderer.py')
fps = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(fps)


class RendererTests(unittest.TestCase):
    def setUp(self):
        self.root = ROOT / '.state' / 'fps-renderer-tests' / uuid.uuid4().hex
        self.root.mkdir(parents=True)
        self.addCleanup(shutil.rmtree, self.root)
        self.port, self.work = self.root / 'port with spaces', self.root / 'work'
        self.source = self.port / 'compat/fps-renderer/ddraw.dll'
        self.source.parent.mkdir(parents=True)
        self.original = self.port / 'compat/cnc-ddraw/ddraw.dll'
        self.original.parent.mkdir(parents=True)
        self.original.write_bytes(b'original upstream bytes')
        self.data = b'MZsynthetic authenticated renderer'
        self.source.write_bytes(self.data)
        self.directory = self.work / 'ProjectD2'
        self.directory.mkdir(parents=True)
        self.target = self.directory / 'ddraw.dll'
        self.addCleanup(mock.patch.stopall)
        mock.patch.object(fps, 'RENDERER_SIZE', len(self.data)).start()
        mock.patch.object(fps, 'RENDERER_SHA256', hashlib.sha256(self.data).hexdigest()).start()

    def link(self, path=None, target=None):
        path = self.target if path is None else path
        target = self.original if target is None else target
        try:
            path.symlink_to(target)
        except OSError as exc:
            if getattr(exc, 'winerror', None) == 1314:
                self.skipTest('Windows symlink privilege unavailable')
            raise

    def test_selects_authenticated_bytes_without_modifying_original(self):
        self.link()
        fps.prepare_renderer(self.port, self.work)
        self.assertFalse(self.target.is_symlink())
        self.assertEqual(self.target.read_bytes(), self.data)
        self.assertEqual(self.original.read_bytes(), b'original upstream bytes')
        self.assertFalse((self.directory / '.pd2-fps-renderer.tmp').exists())
        with self.assertRaises(ValueError):
            fps.prepare_renderer(self.port, self.work)  # Never replace regular files.

    def test_case_insensitive_dll_name(self):
        self.target = self.directory / 'DDraw.DLL'
        self.test_selects_authenticated_bytes_without_modifying_original()

    def test_tampered_truncated_and_oversize_renderer_refused(self):
        for data in (b'', b'x' * len(self.data), self.data + b'x'):
            self.source.write_bytes(data)
            with self.assertRaises(ValueError):
                fps.prepare_renderer(self.port, self.work)
        self.assertEqual(list(self.directory.iterdir()), [])

    def test_hardlinked_source_refused(self):
        os.link(self.source, self.root / 'hardlink.dll')
        with self.assertRaises(ValueError):
            fps.prepare_renderer(self.port, self.work)

    def test_regular_missing_and_foreign_targets_are_preserved(self):
        with self.assertRaises(ValueError):
            fps.prepare_renderer(self.port, self.work)
        self.target.write_bytes(b'user data')
        with self.assertRaises(ValueError):
            fps.prepare_renderer(self.port, self.work)
        self.assertEqual(self.target.read_bytes(), b'user data')
        self.target.unlink()
        self.link(target=self.source)
        with self.assertRaises(ValueError):
            fps.prepare_renderer(self.port, self.work)
        self.assertEqual(os.readlink(self.target), str(self.source))

    def test_source_symlink_and_reparse_ancestors_refused(self):
        original_lstat = Path.lstat
        for suspect in (self.source, self.source.parent, self.port, self.work, self.directory):
            def fake_lstat(path, *args, **kwargs):
                info = original_lstat(path, *args, **kwargs)
                if path == suspect:
                    return mock.Mock(st_mode=info.st_mode, st_file_attributes=0x400)
                return info
            with self.subTest(path=suspect), mock.patch.object(Path, 'lstat', fake_lstat):
                with self.assertRaises(ValueError):
                    fps.prepare_renderer(self.port, self.work)

    def test_changed_source_identity_refused_before_target_write(self):
        original = os.fstat
        def changed(fd):
            info = original(fd)
            return mock.Mock(st_mode=info.st_mode, st_nlink=1, st_dev=info.st_dev,
                             st_ino=info.st_ino + 1, st_size=info.st_size,
                             st_mtime_ns=info.st_mtime_ns)
        with mock.patch.object(os, 'fstat', side_effect=changed):
            with self.assertRaises(ValueError):
                fps.prepare_renderer(self.port, self.work)
        self.assertEqual(list(self.directory.iterdir()), [])

    def test_stale_pending_file_never_overwritten(self):
        self.link()
        pending = self.directory / '.pd2-fps-renderer.tmp'
        pending.write_bytes(b'stale data')
        with self.assertRaises(FileExistsError):
            fps.prepare_renderer(self.port, self.work)
        self.assertTrue(self.target.is_symlink())
        self.assertEqual(pending.read_bytes(), b'stale data')

    def test_replace_failure_preserves_original_and_cleans_only_own_temp(self):
        self.link()
        with mock.patch.object(os, 'replace', side_effect=OSError('private')):
            with self.assertRaises(OSError):
                fps.prepare_renderer(self.port, self.work)
        self.assertTrue(self.target.is_symlink())
        self.assertFalse((self.directory / '.pd2-fps-renderer.tmp').exists())

    def test_dotdot_refused(self):
        with self.assertRaises(ValueError):
            fps.prepare_renderer(self.port / '..' / self.port.name, self.work)

    def test_cli_success_failure_and_timeout_contract(self):
        for failure in (None, OSError('secret path')):
            out = io.StringIO()
            with mock.patch.object(fps, 'prepare_renderer', side_effect=failure):
                result = fps.main(['--port', 'private', '--work', 'private'], out)
            self.assertEqual(result, 1 if failure else 0)
            event = json.loads(out.getvalue()[10:])
            self.assertEqual(event['status'], 'unavailable' if failure else 'renderer')
            self.assertNotIn('private', out.getvalue())
            self.assertNotIn('secret', out.getvalue())
        out = io.StringIO()
        self.assertEqual(fps.main(['--port', 'secret'], out), 1)
        self.assertNotIn('secret', out.getvalue())


class ArtifactTests(unittest.TestCase):
    def test_pinned_x86_release_hud_and_original_are_distinct(self):
        blob = (PORT / 'compat/fps-renderer/ddraw.dll').read_bytes()
        self.assertEqual(len(blob), fps.RENDERER_SIZE)
        self.assertEqual(hashlib.sha256(blob).hexdigest(), fps.RENDERER_SHA256)
        pe = struct.unpack_from('<I', blob, 0x3c)[0]
        self.assertEqual(blob[pe:pe + 4], b'PE\0\0')
        self.assertEqual(struct.unpack_from('<H', blob, pe + 4)[0], 0x14c)
        upstream = (PORT / 'compat/cnc-ddraw/ddraw.dll').read_bytes()
        self.assertEqual(hashlib.sha256(upstream).hexdigest(),
                         '85e0f7d530dfda134793a57cb3e76b0287dcc96892ee57162dd68f47283b03a9')
        manifest = json.loads((PORT / 'compat/fps-renderer/manifest.json').read_text())
        self.assertEqual((manifest['size'], manifest['sha256']),
                         (fps.RENDERER_SIZE, fps.RENDERER_SHA256))

    def test_shell_uses_hud_before_game_without_hotkey_sidecar(self):
        script = (PORT / 'scripts/run-game.sh').read_text()
        prepare = script.index('"$PD2_PORT/scripts/fps_renderer.py"')
        game = script.index("/exec 'C:\\Diablo II\\ProjectD2\\Game.exe'")
        self.assertLess(prepare, game)
        self.assertIn('timeout --kill-after=2 10 python3 -B', script[:prepare])
        self.assertNotIn('pd2-fps-hotkey.exe', script)
        self.assertNotIn('fps_counter.py', script)


if __name__ == '__main__':
    unittest.main()
