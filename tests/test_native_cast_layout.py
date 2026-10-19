"""Private native-cast cache integration; synthetic assets only, no game run."""

import hashlib
import os
from pathlib import Path
import sys
import types
import unittest
from unittest import mock

import test_layout as fixtures
from test_layout import digest_tree, layout, write


class NativeCastLayoutTests(unittest.TestCase):
    # Reuse fixture, not its test class: avoid rerunning the entire layout suite.
    prepare = fixtures.LayoutTests.prepare
    session = fixtures.LayoutTests.session
    save_path_fixture = fixtures.LayoutTests.save_path_fixture

    def setUp(self):
        fixtures.LayoutTests.setUp(self)
        self.source = self.data / 'ProjectD2/ProjectDiablo.dll'
        self.source_bytes = self.source.read_bytes()
        self.target_bytes = self.source_bytes + b'private synthetic native-cast target'
        self.builder = mock.Mock(return_value=self.target_bytes)
        stub = types.SimpleNamespace(
            SOURCE_SIZE=len(self.source_bytes),
            SOURCE_SHA256=hashlib.sha256(self.source_bytes).hexdigest(),
            TARGET_SIZE=len(self.target_bytes),
            TARGET_SHA256=hashlib.sha256(self.target_bytes).hexdigest(),
            native_cast_bytes=self.builder)
        modules = mock.patch.dict(sys.modules, {'native_cast': stub})
        modules.start()
        self.addCleanup(modules.stop)
        # Exercise real resolution preflight for 1024 too; only its hash is fake.
        target1024 = bytearray(self.sgd2_content)
        for offset, old, new in layout.SGD2_1024_PATCHES:
            self.assertEqual(target1024[offset:offset + len(old)], old)
            target1024[offset:offset + len(old)] = new
        pin = mock.patch.object(layout, 'SGD2_1024_SHA256',
                                hashlib.sha256(target1024).hexdigest())
        pin.start()
        self.addCleanup(pin.stop)

    @property
    def cache(self):
        return self.state / 'compat/pd2-native-cast-640-v1/ProjectDiablo.dll'

    @property
    def work_dll(self):
        return self.state / 'game/ProjectD2' / self.source.name

    def prepare_mode(self, input_mode='native', resolution='640x480', volatile=True):
        real_prepare = layout.prepare

        def with_mode(*args, **kwargs):
            return real_prepare(*args, **kwargs, input_mode=input_mode,
                                game_resolution=resolution)

        with mock.patch.object(layout, 'prepare', side_effect=with_mode):
            return self.prepare(volatile=volatile)

    def assert_closed(self, call):
        with self.assertRaises(layout.LayoutError) as error:
            call()
        self.assertRegex(str(error.exception), r'^[a-z_]+$')
        self.assertNotIn(str(self.root), str(error.exception))
        self.assertNotIn('private', str(error.exception))

    def test_native_640_redirects_only_project_dll_and_preserves_imports(self):
        for volatile in (True, False):
            with self.subTest(volatile=volatile):
                result = self.prepare_mode(volatile=volatile)
                self.assertEqual(result['input_mode'], 'native')
                self.assertEqual(result['game_resolution'], '640x480')
                self.assertEqual(self.links[str(self.work_dll)], str(self.cache))
                self.assertEqual(self.cache.read_bytes(), self.target_bytes)
                self.assertEqual(self.source.read_bytes(), self.source_bytes)
                self.assertEqual(digest_tree(self.data), self.original_data)
                self.assertEqual(self.links[str(self.state / 'game/ProjectD2/Game.exe')],
                                 str(self.data / 'ProjectD2/Game.exe'))
                self.assertFalse(self.cache.with_name(self.cache.name + '.new').exists())
        self.assertEqual(self.session()['input_mode'], 'native')

    def test_cache_published_atomically_and_reused_without_rewrite(self):
        source_mtime = self.source.stat().st_mtime_ns
        with mock.patch.object(layout, 'atomic_bytes', wraps=layout.atomic_bytes) as atomic:
            self.assertEqual(layout.native_cast_file(self.data, self.state), self.cache)
        atomic.assert_called_once_with(self.cache, self.target_bytes)
        cache_mtime = self.cache.stat().st_mtime_ns
        with mock.patch.object(layout, 'atomic_bytes', wraps=layout.atomic_bytes) as atomic:
            self.assertEqual(layout.native_cast_file(self.data, self.state), self.cache)
        atomic.assert_not_called()
        self.assertEqual(self.cache.stat().st_mtime_ns, cache_mtime)
        self.assertEqual(self.source.stat().st_mtime_ns, source_mtime)
        self.assertEqual(digest_tree(self.data), self.original_data)
        self.assertEqual(self.builder.call_args_list,
                         [mock.call(self.source_bytes), mock.call(self.source_bytes)])

    def test_tampered_cache_fails_without_repair_or_work_links(self):
        for content in (self.target_bytes[:-1], b'X' + self.target_bytes[1:]):
            with self.subTest(size=len(content)):
                write(self.state, self.cache.relative_to(self.state), content)
                mtime = self.cache.stat().st_mtime_ns
                with mock.patch.object(layout, 'atomic_bytes', wraps=layout.atomic_bytes) as atomic:
                    self.assert_closed(lambda: layout.native_cast_file(self.data, self.state))
                atomic.assert_not_called()
                self.assertEqual(self.cache.read_bytes(), content)
                self.assertEqual(self.cache.stat().st_mtime_ns, mtime)
                self.assert_closed(self.prepare_mode)
                self.assertEqual(self.links, {})
                self.assertEqual(digest_tree(self.data), self.original_data)

    def test_valid_cache_revalidates_original_size_and_hash(self):
        layout.native_cast_file(self.data, self.state)
        cache_mtime = self.cache.stat().st_mtime_ns
        for content in (self.source_bytes[:-1], b'X' + self.source_bytes[1:]):
            self.source.write_bytes(content)
            self.builder.reset_mock()
            self.assert_closed(lambda: layout.native_cast_file(self.data, self.state))
            self.builder.assert_not_called()
            self.assertEqual(self.source.read_bytes(), content)
            self.assertEqual(self.cache.read_bytes(), self.target_bytes)
            self.assertEqual(self.cache.stat().st_mtime_ns, cache_mtime)

    def test_valid_cache_does_not_hide_missing_source(self):
        layout.native_cast_file(self.data, self.state)
        self.source.unlink()
        self.builder.reset_mock()
        before = digest_tree(self.state)
        self.assert_closed(lambda: layout.native_cast_file(self.data, self.state))
        self.builder.assert_not_called()
        self.assertEqual(digest_tree(self.state), before)

    def test_pending_file_fails_with_and_without_valid_cache(self):
        pending = self.cache.with_name(self.cache.name + '.new')
        write(self.state, pending.relative_to(self.state), b'private pending sentinel')
        before = digest_tree(self.state)
        self.assert_closed(lambda: layout.native_cast_file(self.data, self.state))
        self.assertFalse(self.cache.exists())
        self.assertEqual(digest_tree(self.state), before)
        write(self.state, self.cache.relative_to(self.state), self.target_bytes)
        before = digest_tree(self.state)
        self.assert_closed(lambda: layout.native_cast_file(self.data, self.state))
        self.assertEqual(digest_tree(self.state), before)
        self.assert_closed(self.prepare_mode)
        self.assertEqual(self.links, {})
        self.assertEqual(pending.read_bytes(), b'private pending sentinel')
        self.assertEqual(self.cache.read_bytes(), self.target_bytes)
        self.assertEqual(digest_tree(self.data), self.original_data)

    def test_source_cache_pending_and_ancestor_symlinks_fail_closed(self):
        layout.native_cast_file(self.data, self.state)
        before = digest_tree(self.state)
        real_lstat = Path.lstat
        for linked in (self.source, self.source.parent, self.cache, self.cache.parent,
                       self.cache.parent.parent, self.cache.with_name(self.cache.name + '.new')):
            def fake_lstat(path, *args, **kwargs):
                if path == linked:
                    return mock.Mock(st_mode=0o120777, st_file_attributes=0)
                return real_lstat(path, *args, **kwargs)
            with self.subTest(linked=linked.name), mock.patch.object(Path, 'lstat', new=fake_lstat):
                self.assert_closed(lambda: layout.native_cast_file(self.data, self.state))
            self.assertEqual(digest_tree(self.state), before)
            self.assertEqual(digest_tree(self.data), self.original_data)

    def test_nonregular_source_and_cache_fail_closed(self):
        for invalid in (self.source, self.cache):
            real_is_file = Path.is_file

            def not_file(path):
                return False if path == invalid else real_is_file(path)

            if invalid == self.cache:
                layout.native_cast_file(self.data, self.state)
            with self.subTest(invalid=invalid.name), mock.patch.object(Path, 'is_file', new=not_file):
                self.assert_closed(lambda: layout.native_cast_file(self.data, self.state))
            self.assertEqual(digest_tree(self.data), self.original_data)

    def test_non_native_640_and_all_other_resolutions_keep_original_and_skip_builder(self):
        cases = [('mapper', '640x480'), (None, '640x480')]
        cases += [(mode, resolution) for mode in ('mapper', 'native')
                  for resolution in ('800x600', '1024x768', 'native')]
        for mode, resolution in cases:
            with self.subTest(mode=mode, resolution=resolution):
                self.builder.reset_mock()
                result = self.prepare_mode(mode, resolution)
                self.assertEqual(result['game_resolution'], resolution)
                self.assertEqual(self.links[str(self.work_dll)], str(self.source))
                self.builder.assert_not_called()
                self.assertFalse(self.cache.exists())
                self.assertEqual(digest_tree(self.data), self.original_data)

    def test_native_640_unknown_source_rejected_before_work_links(self):
        for content in (self.source_bytes[:-1], b'X' + self.source_bytes[1:]):
            self.source.write_bytes(content)
            self.builder.reset_mock()
            self.assert_closed(self.prepare_mode)
            self.builder.assert_not_called()
            self.assertEqual(self.links, {})
            self.assertFalse(self.cache.exists())
            self.assertEqual(self.source.read_bytes(), content)

    def test_builder_rejection_becomes_closed_layout_error(self):
        self.builder.side_effect = ValueError('private details must not escape')
        self.assert_closed(self.prepare_mode)
        self.assertEqual(self.links, {})
        self.assertFalse(self.cache.exists())
        self.assertEqual(digest_tree(self.data), self.original_data)

    def test_case_insensitive_unique_source_selection(self):
        interim = self.source.with_name('case-rename-fixture.tmp')
        self.source.rename(interim)
        self.source = self.source.with_name('pRoJeCtDiAbLo.DlL')
        interim.rename(self.source)
        before = digest_tree(self.data)
        self.prepare_mode()
        self.assertEqual(self.links[str(self.work_dll)], str(self.cache))
        self.assertEqual(digest_tree(self.data), before)

    @unittest.skipIf(os.name == 'nt', 'Case-distinct names need case-sensitive filesystem')
    def test_case_insensitive_duplicate_sources_rejected(self):
        write(self.data, 'ProjectD2/projectdiablo.DLL', self.source_bytes)
        matches = [p for p in self.source.parent.iterdir()
                   if p.name.lower() == 'projectdiablo.dll']
        if len(matches) != 2:
            self.skipTest('filesystem enumeration collapses case-variant names')
        before = digest_tree(self.data)
        self.assert_closed(self.prepare_mode)
        self.builder.assert_not_called()
        self.assertEqual(self.links, {})
        self.assertFalse(self.cache.exists())
        self.assertEqual(digest_tree(self.data), before)


if __name__ == '__main__':
    unittest.main()
