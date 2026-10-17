"""Opt-in GL2 security, wire schema, failure contracts and artifact tests."""
import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import struct
import sys
import unittest
import uuid
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
PORT = ROOT / 'sdcard/ports/projectdiablo2'
sys.path.insert(0, str(PORT / 'scripts'))
SPEC = importlib.util.spec_from_file_location('gles2_renderer', PORT / 'scripts/gles2_renderer.py')
r = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(r)


def wire(stage=6, code=0, **kwargs):
    value = dict(stage=stage, code=code, gl_major=2, gl_minor=1, bpp=8,
                 width=800, height=600, render_width=640, render_height=480)
    value.update(kwargs)
    return json.dumps(value, separators=(',', ':')).encode() + b'\n'


class Files(unittest.TestCase):
    def setUp(self):
        self.root = ROOT / '.state/gles2-tests' / uuid.uuid4().hex
        self.root.mkdir(parents=True)
        self.addCleanup(shutil.rmtree, self.root)
        self.port = self.root / 'port with spaces'
        self.work = self.root / 'work'
        self.directory = self.work / 'ProjectD2'
        self.directory.mkdir(parents=True)
        self.source = self.port / 'compat/gles2-renderer/ddraw.dll'
        self.source.parent.mkdir(parents=True)
        self.original = self.port / 'compat/cnc-ddraw/ddraw.dll'
        self.original.parent.mkdir(parents=True)
        self.original.write_bytes(b'original bytes')
        self.data = b'MZsynthetic test bytes'
        self.source.write_bytes(self.data)
        self.target = self.directory / 'ddraw.dll'
        self.status = self.directory / r.TELEMETRY_FILE
        self.addCleanup(mock.patch.stopall)
        mock.patch.object(r, 'RENDERER_SIZE', len(self.data)).start()
        mock.patch.object(r, 'RENDERER_SHA256', hashlib.sha256(self.data).hexdigest()).start()

    def link(self, target=None):
        try:
            self.target.symlink_to(self.original if target is None else target)
        except OSError as exc:
            if getattr(exc, 'winerror', None) == 1314:
                self.skipTest('Windows symlink privilege unavailable')
            raise

    def test_selection_preserves_stock(self):
        self.link()
        r.prepare_renderer(self.port, self.work)
        self.assertEqual(self.target.read_bytes(), self.data)
        self.assertFalse(self.target.is_symlink())
        self.assertEqual(self.original.read_bytes(), b'original bytes')
        self.assertFalse((self.directory / '.pd2-gles2-renderer.tmp').exists())
        with self.assertRaises(ValueError):
            r.prepare_renderer(self.port, self.work)

    def test_case_insensitive(self):
        self.target = self.directory / 'DDraw.DLL'
        self.test_selection_preserves_stock()

    def test_missing_regular_foreign_targets_not_replaced(self):
        with self.assertRaises(ValueError):
            r.prepare_renderer(self.port, self.work)
        self.target.write_bytes(b'user bytes')
        with self.assertRaises(ValueError):
            r.prepare_renderer(self.port, self.work)
        self.assertEqual(self.target.read_bytes(), b'user bytes')
        self.target.unlink()
        self.link(self.source)
        with self.assertRaises(ValueError):
            r.prepare_renderer(self.port, self.work)
        self.assertTrue(self.target.is_symlink())

    def test_source_tamper_and_truncation(self):
        for blob in (b'', b'x' * len(self.data), self.data + b'x'):
            self.source.write_bytes(blob)
            with self.assertRaises(ValueError):
                r.prepare_renderer(self.port, self.work)
        self.assertEqual(list(self.directory.iterdir()), [])

    def test_source_hardlink(self):
        os.link(self.source, self.root / 'source-copy')
        with self.assertRaises(ValueError):
            r.prepare_renderer(self.port, self.work)

    def test_reparse_ancestors_refused(self):
        original = Path.lstat
        for suspect in (self.source, self.source.parent, self.port, self.work, self.directory):
            def fake(path, *args, **kwargs):
                info = original(path, *args, **kwargs)
                return mock.Mock(st_mode=info.st_mode, st_file_attributes=0x400) if path == suspect else info
            with self.subTest(path=suspect), mock.patch.object(Path, 'lstat', fake):
                with self.assertRaises(ValueError):
                    r.prepare_renderer(self.port, self.work)

    def test_source_identity_change(self):
        original = os.fstat
        def changed(fd):
            info = original(fd)
            return mock.Mock(st_mode=info.st_mode, st_nlink=1, st_dev=info.st_dev, st_ino=info.st_ino + 1, st_size=info.st_size, st_mtime_ns=info.st_mtime_ns)
        with mock.patch.object(os, 'fstat', side_effect=changed), self.assertRaises(ValueError):
            r.prepare_renderer(self.port, self.work)
        self.assertEqual(list(self.directory.iterdir()), [])

    def test_stale_temp_preserved(self):
        self.link()
        pending = self.directory / '.pd2-gles2-renderer.tmp'
        pending.write_bytes(b'stale')
        with self.assertRaises(FileExistsError):
            r.prepare_renderer(self.port, self.work)
        self.assertEqual(pending.read_bytes(), b'stale')
        self.assertTrue(self.target.is_symlink())

    def test_replace_failure_cleans_only_owned_temp(self):
        self.link()
        with mock.patch.object(os, 'replace', side_effect=OSError('secret')), self.assertRaises(OSError):
            r.prepare_renderer(self.port, self.work)
        self.assertFalse((self.directory / '.pd2-gles2-renderer.tmp').exists())
        self.assertTrue(self.target.is_symlink())

    def test_dotdot_refused(self):
        with self.assertRaises(ValueError):
            r.prepare_renderer(self.port / '..' / self.port.name, self.work)

    def present(self, backend=2):
        (self.directory / 'pd2-present.jsonl').write_text(json.dumps(dict(event=3, backend=backend, frames=1, duration_ms=0, width=640, height=480)) + '\n')

    def test_result_ready_requires_both_channels(self):
        self.status.write_bytes(wire())
        self.assertEqual(r.main(['--result', '--work', str(self.work)]), 1)
        self.present(1)
        self.assertEqual(r.result(self.work), 1)
        self.present(2)
        self.assertEqual(r.result(self.work), 0)

    def test_every_failure_is_authoritative(self):
        self.present()
        for code in range(1, 17):
            self.status.write_bytes(wire() + wire(code=code))
            self.assertEqual(r.result(self.work), 86)

    def test_no_frame_not_success(self):
        self.present()
        self.status.write_bytes(wire(stage=5))
        self.assertEqual(r.result(self.work), 1)

    def test_invalid_or_missing_not_success(self):
        for data in (b'private text', wire()[:-1], wire() * 129, b'X' * 32769):
            self.status.write_bytes(data)
            self.assertEqual(r.main(['--result', '--work', str(self.work)]), 1)

    def test_status_hardlink_refused(self):
        self.status.write_bytes(wire())
        os.link(self.status, self.root / 'status-copy')
        with self.assertRaises(ValueError):
            r.result(self.work)

    def test_watch_final_drain_after_host_exit(self):
        self.status.write_bytes(wire(stage=1) + wire(code=11))
        out = io.StringIO()
        with mock.patch.object(r, '_pid_identity', side_effect=['123', None]), contextlib.redirect_stdout(out):
            self.assertEqual(r.watch(self.work, 123), 86)
        events = [json.loads(line.removeprefix('PD2_EVENT ')) for line in out.getvalue().splitlines()]
        self.assertEqual([v['status'] for v in events], ['ready', 'failed'])
        self.assertNotIn(str(self.root), out.getvalue())

    def test_watch_never_signals_host(self):
        self.status.write_bytes(wire())
        with mock.patch.object(r, '_pid_identity', side_effect=['123', None]), mock.patch.object(os, 'kill') as kill, mock.patch.object(r, 'emit'):
            self.assertEqual(r.watch(self.work, 123), 0)
        kill.assert_not_called()

    def test_watch_rewrite_refused(self):
        self.status.write_bytes(wire(stage=1))
        def changed(_):
            self.status.write_bytes(wire(stage=2))
        with mock.patch.object(r, '_pid_identity', return_value='123'), mock.patch.object(r.time, 'sleep', side_effect=changed), mock.patch.object(r, 'emit'):
            self.assertEqual(r.watch(self.work, 123), 1)

    def test_cli_no_raw_errors(self):
        out = io.StringIO()
        with mock.patch.object(r, 'prepare_renderer', side_effect=OSError('secret')), contextlib.redirect_stdout(out):
            self.assertEqual(r.main(['--port', 'private', '--work', 'private']), 1)
        self.assertEqual(out.getvalue(), '')
        for args in ([], ['--watch', '--work', 'private', '--pid', '1'], ['--result', '--port', 'private', '--work', 'private'], ['--work', 'private']):
            self.assertEqual(r.main(args), 1)


class PidIdentity(unittest.TestCase):
    @staticmethod
    def proc_record():
        return '123 (synthetic name) ' + ' '.join(['S'] + ['0'] * 18 + ['456'] + ['0'] * 2)

    def test_starttime_read_is_ascii_and_bounded(self):
        stream = mock.MagicMock()
        stream.__enter__.return_value = stream
        stream.read.return_value = self.proc_record().ljust(8192)
        with mock.patch.object(Path, 'open', return_value=stream) as opened:
            self.assertEqual(r._pid_identity(123), '456')
        opened.assert_called_once_with('r', encoding='ascii')
        stream.read.assert_called_once_with(8193)

    def test_oversized_proc_record_refused_without_signal_probe(self):
        stream = mock.MagicMock()
        stream.__enter__.return_value = stream
        stream.read.return_value = self.proc_record().ljust(8193)
        with mock.patch.object(Path, 'open', return_value=stream), mock.patch.object(os, 'kill') as kill:
            self.assertIsNone(r._pid_identity(123))
        stream.read.assert_called_once_with(8193)
        kill.assert_not_called()

    def test_nonascii_proc_record_refused(self):
        error = UnicodeDecodeError('ascii', b'\xff', 0, 1, 'invalid')
        with mock.patch.object(Path, 'open', side_effect=error), mock.patch.object(os, 'kill') as kill:
            self.assertIsNone(r._pid_identity(123))
        kill.assert_not_called()


class Schema(unittest.TestCase):
    def test_every_stage_and_code(self):
        for stage in range(1, 9):
            for code in range(17):
                value = r.decode_record(wire(stage, code))
                self.assertEqual(value['event'], 'renderer_gl2')
                self.assertEqual(value['status'], 'failed' if code else 'ready')
                self.assertEqual(value['stage'], r.STAGES[stage])

    def test_invalid_types_keys_ranges_duplicates(self):
        for key, value in [('stage', 0), ('stage', 9), ('code', 17), ('bpp', 24), ('gl_major', 10), ('width', 16385), ('height', -1), ('render_width', True), ('code', 'secret'), ('width', 1.0)]:
            self.assertIsNone(r.decode_record(wire(**{key: value})))
        raw = wire().decode()
        self.assertIsNone(r.decode_record(raw.replace('{', '{"code":0,', 1)))
        self.assertIsNone(r.decode_record(raw.replace('"bpp":8,', '')))
        self.assertIsNone(r.decode_record(b'X' * 257))
        self.assertIsNone(r.decode_record(b'[]'))

    def test_partial_and_caps(self):
        self.assertEqual(len(r.records(wire() * 128)), 128)
        for raw in (wire() * 129, b'X' * 257, wire()[:-1]):
            with self.assertRaises(ValueError):
                r.records(raw)
        self.assertEqual(len(r.records(wire() + wire()[:12], partial=True)), 1)


class Artifact(unittest.TestCase):
    def test_pin_manifest_pe_and_sources(self):
        directory = PORT / 'compat/gles2-renderer'
        blob = (directory / 'ddraw.dll').read_bytes()
        self.assertEqual(len(blob), r.RENDERER_SIZE)
        self.assertEqual(hashlib.sha256(blob).hexdigest(), r.RENDERER_SHA256)
        pe = struct.unpack_from('<I', blob, 0x3c)[0]
        self.assertEqual(blob[pe:pe + 4], b'PE\0\0')
        self.assertEqual(struct.unpack_from('<H', blob, pe + 4)[0], 0x14c)
        manifest = json.loads((directory / 'manifest.json').read_text())
        self.assertEqual((manifest['size'], manifest['sha256']), (r.RENDERER_SIZE, r.RENDERER_SHA256))
        for name, digest in manifest['build']['inputs_sha256'].items():
            self.assertEqual(hashlib.sha256((ROOT / 'tools' / name).read_bytes()).hexdigest(), digest)
        self.assertEqual(hashlib.sha256((directory / 'source.patch').read_bytes()).hexdigest(), manifest['build']['source_patch_sha256'])
        for name, digest in [('cnc-ddraw', '85e0f7d530dfda134793a57cb3e76b0287dcc96892ee57162dd68f47283b03a9'), ('fps-renderer', 'acb44f73f3ee0b2aa4ac98ed860b40e0d9389162eaa7de9ec0028affc778ba5a')]:
            self.assertEqual(hashlib.sha256((PORT / 'compat' / name / 'ddraw.dll').read_bytes()).hexdigest(), digest)

    def test_pipeline_no_ignored_errors_fake_tests_or_gl3(self):
        pipeline = (ROOT / 'tools/gles2_pipeline.h').read_text()
        backend = (ROOT / 'tools/gles2_backend.c').read_text()
        self.assertNotIn('while (glGetError()', pipeline + backend)
        self.assertNotIn('GL_INVALID_FRAMEBUFFER_OPERATION', pipeline + backend)
        self.assertNotIn('glGetTexImage(', pipeline + backend)
        self.assertNotIn('CreateContextAttribs', backend)
        self.assertIn('#version 110', pipeline)
        self.assertIn('a->ReadPixels(0,0,2,2', pipeline)
        self.assertIn('pd2_gl_upload_palette', pipeline)
        self.assertIn('PD2_GL_VALIDATION', pipeline)
        self.assertIn('ExitProcess(PD2_GL_EXIT_CODE)', backend)
        for forbidden in ('TerminateProcess', 'CreateProcess', 'ShellExecute', 'gdi_render_main()', 'minfps_tick_len', 'GL_RGBA8', 'GL_RGB565'):
            self.assertNotIn(forbidden, backend + pipeline)

    def test_adapter_failure_and_normal_release_contracts(self):
        text = (ROOT / 'tools/gles2_backend.c').read_text()
        for needle in ('PD2_GL_CONTEXT', 'PD2_GL_API_MISSING', 'PD2_GL_VERSION', 'PD2_GL_STATE', 'PD2_GL_WAIT', 'PD2_GL_UPLOAD', 'PD2_GL_DRAW', 'PD2_GL_SWAP', 'PD2_GL_RELEASE'):
            self.assertIn('pd2_gles2_fatal(', text)
            self.assertIn(needle, text + (ROOT / 'tools/gles2_pipeline.h').read_text())
        self.assertIn('code=pd2_gl_upload(&pd2_api', text)
        self.assertIn('code=pd2_gl_upload_palette(&pd2_api', text)
        self.assertIn('if (code) pd2_gles2_fatal(6,code);', text)
        self.assertIn('if (!g_ddraw.render.run) break;', text)
        self.assertIn('if (wait_result==WAIT_TIMEOUT && ready) continue;', text)
        self.assertIn('pd2_status(7,0);\n return 0;', text)
        self.assertIn('EnterCriticalSection(&g_ddraw.cs)', text)
        self.assertIn('EnterCriticalSection(&g_ddraw.primary->cs)', text)
        self.assertIn('if (first_frame) { pd2_status(6,0)', text)
        self.assertIn('AcquireSRWLockShared(&pd2_gles2_palette_gate)', text)
        self.assertLess(text.index('ReleaseSRWLockShared(&pd2_gles2_palette_gate)'), text.index('code=pd2_gl_upload(&pd2_api'))
        self.assertIn('pd2_gl_validate(&pd2_api,g_ddraw.bpp,g_config.rgb555)', text)
        self.assertNotIn('!xwglMakeCurrent(NULL,NULL) || !xwglDeleteContext', text)
        self.assertIn('if (!xwglDeleteContext(pd2_context))', text)

    def test_patch_forces_gl2_and_no_silent_gdi(self):
        patch = (PORT / 'compat/gles2-renderer/source.patch').read_text()
        self.assertIn('+        if (!oglu_load_dll()) pd2_gles2_fatal(2, 2);', patch)
        self.assertIn('+        g_config.minfps = 0;', patch)
        self.assertIn('+DWORD WINAPI gdi_render_main(void) { pd2_gles2_fatal(8, 15); return 0; }', patch)
        self.assertIn('+    pd2_gles2_fatal(8, 15);', patch)
        self.assertIn('+        g_ddraw.renderer = ogl_render_main;', patch)
        self.assertIn('+    AcquireSRWLockExclusive(&pd2_gles2_palette_gate);', patch)
        self.assertEqual(patch.count('+            ReleaseSRWLockExclusive(&pd2_gles2_palette_gate);'), 1)
        self.assertEqual(patch.count('+    ReleaseSRWLockExclusive(&pd2_gles2_palette_gate);'), 1)


if __name__ == '__main__':
    unittest.main()
