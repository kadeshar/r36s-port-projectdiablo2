"""Pinned 4:3 work-link patch regressions, exclusively synthetic game fixtures."""
import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import unittest
from unittest import mock

import test_layout as layout_tests
from test_layout import SPEC, digest_tree, layout, pe, sgd2_target, write


class ResolutionPatchTests(unittest.TestCase):
    # Reuse setup/helpers, not inheritance: do not run the layout suite twice.
    setUp = layout_tests.LayoutTests.setUp
    prepare = layout_tests.LayoutTests.prepare
    session = layout_tests.LayoutTests.session
    save_path_fixture = layout_tests.LayoutTests.save_path_fixture

    @property
    def cache(self):
        return self.state / 'compat/sgd2-800x600-v1/SGD2FreeRes.dll'

    def settings(self, resolution):
        value = {'schema_version': 1, 'profile': 'gdi', 'swap_ab': False,
                 'game_resolution': resolution}
        return write(self.port, 'config/settings.json', json.dumps(value).encode())

    def assert_closed(self, call):
        with self.assertRaises(layout.LayoutError) as error:
            call()
        self.assertRegex(str(error.exception), r'^[a-z_]+$')
        self.assertNotIn(str(self.root), str(error.exception))
        self.assertNotIn('private', str(error.exception))

    def test_production_pins_and_patch_plan(self):
        production = importlib.util.module_from_spec(SPEC)
        SPEC.loader.exec_module(production)
        self.assertEqual(production.SGD2_SOURCE_SIZE, 307200)
        self.assertEqual(production.SGD2_SOURCE_SHA256, '177242c2afd2df9da93ca1591c4189c6ca014e4ce5e6971e7b26912a146579cf')
        self.assertEqual(production.SGD2_800_SHA256, '2e1142d592e733fad1f595ec50fb3b43b931a9e04c8ab6a357c94b8312e9a80b')
        self.assertEqual(production.SGD2_800_PATCHES, tuple(
            (offset, bytes.fromhex('2c040000'), bytes.fromhex('20030000'))
            for offset in (0x3caa, 0xc6ab)))
        with self.assertRaises(production.LayoutError):
            production.sgd2_800_bytes(self.sgd2_content)

    def test_pure_patch_changes_exactly_four_bytes_without_mutating_source(self):
        source = bytearray(self.sgd2_content)
        before = bytes(source)
        result = layout.sgd2_800_bytes(source)
        self.assertEqual(bytes(source), before)
        self.assertEqual(result, sgd2_target(before))
        self.assertEqual(len(result), 307200)
        self.assertEqual([i for i, (a, b) in enumerate(zip(before, result)) if a != b],
                         [0x3caa, 0x3cab, 0xc6ab, 0xc6ac])
        self.assertEqual(self.sgd2.read_bytes(), before)

    def test_pure_patch_rejects_wrong_size_and_unknown_hash(self):
        unknown = b'private' + self.sgd2_content[7:]
        for content in (b'', self.sgd2_content[:-1], self.sgd2_content + b'!', unknown):
            with self.subTest(size=len(content)):
                self.assert_closed(lambda: layout.sgd2_800_bytes(content))

    def test_pure_patch_checks_both_preimages_even_with_matching_source_pin(self):
        for offset in (0x3caa, 0xc6ab):
            content = bytearray(self.sgd2_content)
            content[offset:offset + 4] = b'FAIL'
            content = bytes(content)
            with mock.patch.object(layout, 'SGD2_SOURCE_SHA256', hashlib.sha256(content).hexdigest()):
                self.assert_closed(lambda: layout.sgd2_800_bytes(content))

    def test_pure_patch_rejects_wrong_target_hash(self):
        with mock.patch.object(layout, 'SGD2_800_SHA256', '0' * 64):
            self.assert_closed(lambda: layout.sgd2_800_bytes(self.sgd2_content))
        self.assertEqual(self.sgd2.read_bytes(), self.sgd2_content)

    def test_file_publishes_atomically_and_reuses_without_touching_mtimes(self):
        before = self.sgd2.stat().st_mtime_ns
        with mock.patch.object(layout, 'atomic_bytes', wraps=layout.atomic_bytes) as atomic:
            result = layout.sgd2_800_file(self.data, self.state)
        self.assertEqual(result, self.cache)
        atomic.assert_called_once_with(self.cache, sgd2_target(self.sgd2_content))
        cache_mtime = self.cache.stat().st_mtime_ns
        with mock.patch.object(layout, 'atomic_bytes', wraps=layout.atomic_bytes) as atomic:
            self.assertEqual(layout.sgd2_800_file(self.data, self.state), self.cache)
        atomic.assert_not_called()
        self.assertEqual(self.cache.stat().st_mtime_ns, cache_mtime)
        self.assertEqual(self.sgd2.stat().st_mtime_ns, before)
        self.assertEqual(digest_tree(self.data), self.original_data)
        self.assertFalse(self.cache.with_name(self.cache.name + '.new').exists())

    def test_valid_cache_never_bypasses_original_size_or_hash_validation(self):
        layout.sgd2_800_file(self.data, self.state)
        cache_before = self.cache.read_bytes()
        cache_mtime = self.cache.stat().st_mtime_ns
        for content in (self.sgd2_content[:-1], b'private' + self.sgd2_content[7:]):
            self.sgd2.write_bytes(content)
            self.assert_closed(lambda: layout.sgd2_800_file(self.data, self.state))
            self.assertEqual(self.sgd2.read_bytes(), content)
            self.assertEqual(self.cache.read_bytes(), cache_before)
            self.assertEqual(self.cache.stat().st_mtime_ns, cache_mtime)

    def test_tampered_cache_is_not_overwritten(self):
        for content in (b'private-cache', sgd2_target(self.sgd2_content)[:-1],
                        b'private' + sgd2_target(self.sgd2_content)[7:]):
            write(self.state, self.cache.relative_to(self.state), content)
            mtime = self.cache.stat().st_mtime_ns
            self.assert_closed(lambda: layout.sgd2_800_file(self.data, self.state))
            self.assertEqual(self.cache.read_bytes(), content)
            self.assertEqual(self.cache.stat().st_mtime_ns, mtime)
            self.assertEqual(digest_tree(self.data), self.original_data)

    def test_bounded_reader_for_unknown_source_and_cache(self):
        real_open = Path.open
        reads = []
        class BoundedStream:
            def __init__(self, stream):
                self.stream = stream
            def __enter__(self):
                self.stream.__enter__()
                return self
            def __exit__(self, *args):
                return self.stream.__exit__(*args)
            def read(self, size=-1):
                reads.append(size)
                if not 0 < size <= 307201:
                    raise AssertionError('unbounded DLL read')
                return self.stream.read(size)
            def __getattr__(self, name):
                return getattr(self.stream, name)
        def bounded_open(path, mode='r', *args, **kwargs):
            stream = real_open(path, mode, *args, **kwargs)
            if mode == 'rb' and path in (self.sgd2, self.cache):
                return BoundedStream(stream)
            return stream
        self.sgd2.write_bytes(b'private' + self.sgd2_content[7:])
        with mock.patch.object(Path, 'open', new=bounded_open):
            self.assert_closed(lambda: layout.sgd2_800_file(self.data, self.state))
        self.assertTrue(reads)
        self.assertFalse(self.cache.exists())
        self.sgd2.write_bytes(self.sgd2_content)
        write(self.state, self.cache.relative_to(self.state), b'private' + sgd2_target(self.sgd2_content)[7:])
        reads.clear()
        with mock.patch.object(Path, 'open', new=bounded_open):
            self.assert_closed(lambda: layout.sgd2_800_file(self.data, self.state))
        self.assertTrue(reads)

    def test_stale_new_is_rejected_with_and_without_valid_cache(self):
        pending = self.cache.with_name(self.cache.name + '.new')
        write(self.state, pending.relative_to(self.state), b'private pending sentinel')
        self.assert_closed(lambda: layout.sgd2_800_file(self.data, self.state))
        self.assertFalse(self.cache.exists())
        write(self.state, self.cache.relative_to(self.state), sgd2_target(self.sgd2_content))
        before = digest_tree(self.state)
        self.assert_closed(lambda: layout.sgd2_800_file(self.data, self.state))
        self.assertEqual(digest_tree(self.state), before)

    def test_source_cache_and_ancestor_symlinks_rejected_without_privileges(self):
        layout.sgd2_800_file(self.data, self.state)
        before = digest_tree(self.state)
        real_lstat = Path.lstat
        for linked in (self.sgd2, self.sgd2.parent, self.cache, self.cache.parent,
                       self.cache.parent.parent, self.cache.with_name(self.cache.name + '.new')):
            def fake_lstat(path, *args, **kwargs):
                if path == linked:
                    return mock.Mock(st_mode=0o120777, st_file_attributes=0)
                return real_lstat(path, *args, **kwargs)
            with self.subTest(linked=linked.name), mock.patch.object(Path, 'lstat', new=fake_lstat):
                self.assert_closed(lambda: layout.sgd2_800_file(self.data, self.state))
            self.assertEqual(digest_tree(self.state), before)
            self.assertEqual(digest_tree(self.data), self.original_data)

    def test_missing_source_fails_even_with_valid_cache(self):
        layout.sgd2_800_file(self.data, self.state)
        self.sgd2.unlink()
        before = digest_tree(self.state)
        self.assert_closed(lambda: layout.sgd2_800_file(self.data, self.state))
        self.assertEqual(digest_tree(self.state), before)

    def test_case_insensitive_unique_source_selection(self):
        interim = self.sgd2.with_name('rename-fixture.tmp')
        self.sgd2.rename(interim)
        self.sgd2 = self.sgd2.with_name('sGd2fReErEs.DlL')
        interim.rename(self.sgd2)
        before = digest_tree(self.data)
        self.settings('800x600')
        self.prepare()
        self.assertEqual(self.links[str(self.state / 'game/ProjectD2' / self.sgd2.name)], str(self.cache))
        self.assertEqual(digest_tree(self.data), before)

    @unittest.skipIf(os.name == 'nt', 'Case-distinct duplicate names need a case-sensitive filesystem')
    def test_duplicate_case_insensitive_source_rejected(self):
        write(self.data, 'ProjectD2/sgd2freeres.DLL', self.sgd2_content)
        # DrvFS (/mnt/c) can collapse case-variant names in enumeration; the
        # precondition must hold for the guard to be testable at all.
        if len([p.name for p in (self.data / 'ProjectD2').iterdir() if p.name.lower() == 'sgd2freeres.dll']) < 2:
            self.skipTest('filesystem enumeration collapses case-variant names')
        before = digest_tree(self.data)
        self.assert_closed(lambda: layout.sgd2_800_file(self.data, self.state))
        self.assertEqual(digest_tree(self.data), before)
        self.assertFalse(self.cache.exists())

    def test_default_new_and_existing_settings_select_640_and_report_session(self):
        result = self.prepare()
        self.assertEqual(result['game_resolution'], '640x480')
        self.assertEqual(self.session()['game_resolution'], '640x480')
        settings = self.port / 'config/settings.json'
        self.assertEqual(json.loads(settings.read_bytes())['game_resolution'], '640x480')
        legacy = b'{"schema_version":1,"profile":"gdi","swap_ab":false}\n'
        settings.write_bytes(legacy)
        self.assertEqual(self.prepare()['game_resolution'], '640x480')
        self.assertEqual(settings.read_bytes(), legacy)
        self.settings('800x600')
        explicit = settings.read_bytes()
        self.assertEqual(self.prepare()['game_resolution'], '800x600')
        self.assertEqual(settings.read_bytes(), explicit)

    def test_invalid_resolution_setting_fails_closed(self):
        for value in ('1280x960', '800X600', '640X480', '640x480 ', '', None, True, 800, [], {}):
            with self.subTest(value=value):
                self.settings(value)
                self.assert_closed(self.prepare)
                self.assertFalse(self.cache.exists())
                self.assertEqual(digest_tree(self.data), self.original_data)

    def test_only_projectd2_resolution_dll_is_redirected_in_both_work_modes(self):
        base = write(self.data, 'SGD2FreeRes.dll', b'base private unknown DLL')
        other = write(self.data, 'ProjectD2/Other.dll', pe() + b'other')
        before = digest_tree(self.data)
        self.settings('800x600')
        for volatile in (True, False):
            self.prepare(volatile=volatile)
            self.assertEqual(self.links[str(self.state / 'game/ProjectD2/SGD2FreeRes.dll')], str(self.cache))
            self.assertEqual(self.links[str(self.state / 'game/SGD2FreeRes.dll')], str(base))
            self.assertEqual(self.links[str(self.state / 'game/ProjectD2/Other.dll')], str(other))
            self.assertEqual(self.links[str(self.state / 'game/ProjectD2/ProjectDiablo.dll')], str(self.data / 'ProjectD2/ProjectDiablo.dll'))
            self.assertEqual(digest_tree(self.data), before)

    def test_native_rollback_retains_cache_original_saves_controllers_and_config(self):
        active = write(self.port, 'config/ProjectDiablo.json', json.dumps(self.save_path_fixture('S:\\')).encode())
        save = write(self.port, 'saves/hero.d2s', b'private synthetic save\x00\xff')
        self.settings('800x600')
        self.prepare()
        self.settings('native')
        config_before = digest_tree(self.port / 'config')
        save_before = digest_tree(save.parent)
        cache_before = self.cache.read_bytes()
        cache_mtime = self.cache.stat().st_mtime_ns
        active_before = active.read_bytes()
        with mock.patch.object(layout, 'sgd2_800_file', side_effect=AssertionError('native must bypass patch')):
            result = self.prepare()
        self.assertEqual(result['game_resolution'], 'native')
        self.assertEqual(self.session()['game_resolution'], 'native')
        self.assertEqual(self.links[str(self.state / 'game/ProjectD2/SGD2FreeRes.dll')], str(self.sgd2))
        self.assertEqual(digest_tree(self.port / 'config'), config_before)
        self.assertEqual(digest_tree(save.parent), save_before)
        self.assertEqual(active.read_bytes(), active_before)
        self.assertEqual(self.cache.read_bytes(), cache_before)
        self.assertEqual(self.cache.stat().st_mtime_ns, cache_mtime)
        self.assertEqual(digest_tree(self.data), self.original_data)

    def test_native_bypasses_unknown_or_missing_resolution_dll_validation(self):
        self.settings('native')
        self.sgd2.write_bytes(b'private unknown release')
        self.assertEqual(self.prepare()['game_resolution'], 'native')
        self.assertFalse(self.cache.exists())
        self.sgd2.unlink()
        self.assertEqual(self.prepare()['game_resolution'], 'native')
        self.assertFalse(self.cache.exists())

    def test_cli_resolution_errors_do_not_disclose_paths_or_content(self):
        self.sgd2.write_bytes(b'private unknown release')
        stdout = io.StringIO()
        # Same privilege-free symlink probe used by the layout fixture.
        def fake_probe(path, target, **kwargs):
            path.touch(exist_ok=False)
        with contextlib.redirect_stdout(stdout), mock.patch.object(Path, 'symlink_to', new=fake_probe), mock.patch.object(layout.shutil, 'disk_usage', return_value=mock.Mock(free=2 * 1024 ** 3)):
            self.assertEqual(layout.main(['--port', str(self.port), '--state', str(self.state)]), 1)
        output = stdout.getvalue()
        self.assertTrue(output.startswith('PD2_EVENT '))
        event = json.loads(output.removeprefix('PD2_EVENT '))
        self.assertEqual(event['event'], 'runtime_error')
        self.assertRegex(event['reason'], r'^[a-z_]+$')
        for private in (str(self.root), 'SGD2FreeRes.dll', 'private', 'unknown release'):
            self.assertNotIn(private, output)


class Resolution1024Tests(unittest.TestCase):
    # Reuse only fixture methods: no inherited regression-suite duplication.
    prepare = layout_tests.LayoutTests.prepare
    session = layout_tests.LayoutTests.session
    save_path_fixture = layout_tests.LayoutTests.save_path_fixture
    settings = ResolutionPatchTests.settings
    assert_closed = ResolutionPatchTests.assert_closed

    def setUp(self):
        layout_tests.LayoutTests.setUp(self)
        content = bytearray(self.sgd2_content)
        for offset in (0x3ca1, 0xc6b5):
            content[offset:offset + 4] = bytes.fromhex('58020000')
        self.sgd2_content = bytes(content)
        self.sgd2.write_bytes(self.sgd2_content)
        mock.patch.object(layout, 'SGD2_SOURCE_SHA256', hashlib.sha256(content).hexdigest()).start()
        mock.patch.object(layout, 'SGD2_800_SHA256', hashlib.sha256(sgd2_target(content)).hexdigest()).start()
        mock.patch.object(layout, 'SGD2_1024_SHA256', hashlib.sha256(self.target(content)).hexdigest()).start()
        self.original_data = digest_tree(self.data)

    @staticmethod
    def target(content):
        result = bytearray(content)
        for offset in (0x3ca1, 0xc6b5):
            result[offset:offset + 4] = bytes.fromhex('00030000')
        for offset in (0x3caa, 0xc6ab):
            result[offset:offset + 4] = bytes.fromhex('00040000')
        return bytes(result)

    @property
    def cache(self):
        return self.state / 'compat/sgd2-1024x768-v1/SGD2FreeRes.dll'

    def test_production_plan_and_hash(self):
        production = importlib.util.module_from_spec(SPEC)
        SPEC.loader.exec_module(production)
        self.assertEqual(production.SGD2_1024_SHA256,
                         'f79829ab958440aab43a789d4aad43bf2eeaa657642589aee6cb6b6e6cb5656e')
        self.assertEqual(production.SGD2_1024_PATCHES, (
            (0x3ca1, bytes.fromhex('58020000'), bytes.fromhex('00030000')),
            (0x3caa, bytes.fromhex('2c040000'), bytes.fromhex('00040000')),
            (0xc6ab, bytes.fromhex('2c040000'), bytes.fromhex('00040000')),
            (0xc6b5, bytes.fromhex('58020000'), bytes.fromhex('00030000'))))
        with self.assertRaises(production.LayoutError):
            production.sgd2_1024_bytes(self.sgd2_content)

    def test_patch_changes_only_verified_immediates_and_keeps_source(self):
        content = bytearray(self.sgd2_content)
        result = layout.sgd2_1024_bytes(content)
        self.assertEqual(result, self.target(content))
        self.assertEqual(bytes(content), self.sgd2_content)
        self.assertEqual([i for i, (a, b) in enumerate(zip(content, result)) if a != b],
                         [0x3ca1, 0x3ca2, 0x3caa, 0xc6ab, 0xc6b5, 0xc6b6])

    def test_all_preimages_and_final_hash_are_checked(self):
        for offset in (0x3ca1, 0x3caa, 0xc6ab, 0xc6b5):
            content = bytearray(self.sgd2_content)
            content[offset:offset + 4] = b'FAIL'
            with self.subTest(offset=offset), mock.patch.object(layout, 'SGD2_SOURCE_SHA256', hashlib.sha256(content).hexdigest()):
                self.assert_closed(lambda: layout.sgd2_1024_bytes(content))
        with mock.patch.object(layout, 'SGD2_1024_SHA256', '0' * 64):
            self.assert_closed(lambda: layout.sgd2_1024_bytes(self.sgd2_content))
        for content in (b'', self.sgd2_content[:-1], self.sgd2_content + b'!', b'private' + self.sgd2_content[7:]):
            self.assert_closed(lambda: layout.sgd2_1024_bytes(content))

    def test_cache_publication_reuse_and_source_validation(self):
        original_mtime = self.sgd2.stat().st_mtime_ns
        self.assertEqual(layout.sgd2_1024_file(self.data, self.state), self.cache)
        self.assertEqual(self.cache.read_bytes(), self.target(self.sgd2_content))
        cache_mtime = self.cache.stat().st_mtime_ns
        with mock.patch.object(layout, 'atomic_bytes', wraps=layout.atomic_bytes) as atomic:
            layout.sgd2_1024_file(self.data, self.state)
            atomic.assert_not_called()
        self.assertEqual(self.cache.stat().st_mtime_ns, cache_mtime)
        self.assertEqual(self.sgd2.stat().st_mtime_ns, original_mtime)
        for content in (self.sgd2_content[:-1], b'private' + self.sgd2_content[7:]):
            self.sgd2.write_bytes(content)
            self.assert_closed(lambda: layout.sgd2_1024_file(self.data, self.state))
            self.assertEqual(self.cache.stat().st_mtime_ns, cache_mtime)
        self.sgd2.unlink()
        self.assert_closed(lambda: layout.sgd2_1024_file(self.data, self.state))

    def test_bad_cache_and_stale_pending_fail_without_repair(self):
        for content in (b'private', self.target(self.sgd2_content)[:-1],
                        sgd2_target(self.sgd2_content), b'private' + self.target(self.sgd2_content)[7:]):
            write(self.state, self.cache.relative_to(self.state), content)
            before = digest_tree(self.state)
            self.assert_closed(lambda: layout.sgd2_1024_file(self.data, self.state))
            self.assertEqual(digest_tree(self.state), before)
        write(self.state, self.cache.relative_to(self.state), self.target(self.sgd2_content))
        write(self.state, self.cache.relative_to(self.state).as_posix() + '.new', b'pending')
        before = digest_tree(self.state)
        self.assert_closed(lambda: layout.sgd2_1024_file(self.data, self.state))
        self.assertEqual(digest_tree(self.state), before)
        self.assertEqual(digest_tree(self.data), self.original_data)

    def test_cache_source_and_ancestor_links_rejected(self):
        layout.sgd2_1024_file(self.data, self.state)
        real_lstat = Path.lstat
        before = digest_tree(self.state)
        for linked in (self.sgd2, self.sgd2.parent, self.cache, self.cache.parent,
                       self.cache.parent.parent, self.cache.with_name(self.cache.name + '.new')):
            def fake_lstat(path, *args, **kwargs):
                if path == linked:
                    return mock.Mock(st_mode=0o120777, st_file_attributes=0)
                return real_lstat(path, *args, **kwargs)
            with self.subTest(linked=linked.name), mock.patch.object(Path, 'lstat', new=fake_lstat):
                self.assert_closed(lambda: layout.sgd2_1024_file(self.data, self.state))
            self.assertEqual(digest_tree(self.state), before)

    def test_persisted_1024_and_session_override_roundtrip_are_scoped(self):
        self.settings('1024x768')
        self.assertEqual(self.prepare()['game_resolution'], '1024x768')
        self.assertEqual(self.links[str(self.state / 'game/ProjectD2/SGD2FreeRes.dll')], str(self.cache))
        self.settings('800x600')
        active = self.port / 'config/ProjectDiablo.json'
        obj = json.loads(active.read_bytes())
        obj['pd2_game_settings'] = {'wasd_movement': False, 'controller_movement': True,
                                    'unrelated_user_flag': 'retain'}
        active.write_text(json.dumps(obj))
        write(self.port, 'saves/hero.d2s', b'private save')
        original_configs = digest_tree(self.port / 'config')
        original_saves = digest_tree(self.port / 'saves')
        cache800 = self.state / 'compat/sgd2-800x600-v1/SGD2FreeRes.dll'
        initial_links = None
        retained = {}
        real_prepare = layout.prepare
        for resolution, target in (('800x600', cache800), ('1024x768', self.cache), ('800x600', cache800)):
            # Helper supplies filesystem mocks; inject only the session argument.
            def prepare_override(*args, **kwargs):
                return real_prepare(*args, **kwargs, game_resolution=resolution)
            with self.subTest(resolution=resolution), mock.patch.object(layout, 'prepare', side_effect=prepare_override):
                result = self.prepare()
            self.assertEqual(result['game_resolution'], resolution)
            self.assertEqual(self.session()['game_resolution'], resolution)
            links = self.links.copy()
            self.assertEqual(links.pop(str(self.state / 'game/ProjectD2/SGD2FreeRes.dll')), str(target))
            if initial_links is None:
                initial_links = links
            self.assertEqual(links, initial_links)
            self.assertEqual(layout.sync_config(self.port, self.state), 0)
            self.assertEqual(digest_tree(self.port / 'config'), original_configs)
            self.assertEqual(digest_tree(self.port / 'saves'), original_saves)
            self.assertEqual(digest_tree(self.data), self.original_data)
            for path, (content, mtime) in retained.items():
                self.assertEqual(path.read_bytes(), content)
                self.assertEqual(path.stat().st_mtime_ns, mtime)
            retained[target] = (target.read_bytes(), target.stat().st_mtime_ns)

    def test_invalid_session_overrides_fail_before_any_mutation(self):
        before = digest_tree(self.root)
        for resolution in ('', '1024X768', '1280x960', '640X480', '1024x768 ', True, 1024, [], {}):
            with self.subTest(resolution=resolution):
                self.assert_closed(lambda: layout.prepare(self.port, self.state, game_resolution=resolution))
                self.assertEqual(digest_tree(self.root), before)

    def test_cli_forwards_session_override_without_persisting_it(self):
        for resolution in ('800x600', '1024x768', 'native', '640x480'):
            with mock.patch.dict(os.environ, {'PD2_GAME_RESOLUTION': resolution}), mock.patch.object(layout, 'prepare') as prepare:
                self.assertEqual(layout.main(['--port', str(self.port), '--state', str(self.state)]), 0)
                self.assertEqual(prepare.call_args.kwargs['game_resolution'], resolution)
        for resolution in ('', '1024X768', 'private invalid'):
            before = digest_tree(self.root)
            stdout = io.StringIO()
            with mock.patch.dict(os.environ, {'PD2_GAME_RESOLUTION': resolution}), contextlib.redirect_stdout(stdout):
                self.assertEqual(layout.main(['--port', str(self.port), '--state', str(self.state)]), 1)
            self.assertEqual(digest_tree(self.root), before)
            self.assertEqual(json.loads(stdout.getvalue().removeprefix('PD2_EVENT '))['reason'], 'invalid_profile')
            self.assertNotIn('private', stdout.getvalue())


class Resolution640Tests(unittest.TestCase):
    prepare = layout_tests.LayoutTests.prepare
    session = layout_tests.LayoutTests.session
    save_path_fixture = layout_tests.LayoutTests.save_path_fixture
    settings = ResolutionPatchTests.settings
    assert_closed = ResolutionPatchTests.assert_closed

    def setUp(self):
        layout_tests.LayoutTests.setUp(self)
        content = bytearray(self.sgd2_content)
        for offset in (0x3ca1, 0xc6b5):
            content[offset:offset + 4] = bytes.fromhex('58020000')
        self.sgd2_content = bytes(content)
        self.sgd2.write_bytes(self.sgd2_content)
        mock.patch.object(layout, 'SGD2_SOURCE_SHA256', hashlib.sha256(content).hexdigest()).start()
        mock.patch.object(layout, 'SGD2_800_SHA256', hashlib.sha256(sgd2_target(content)).hexdigest()).start()
        mock.patch.object(layout, 'SGD2_640_SHA256', hashlib.sha256(self.target(content)).hexdigest()).start()
        self.original_data = digest_tree(self.data)

    @staticmethod
    def target(content):
        result = bytearray(content)
        for offset in (0x3ca1, 0xc6b5):
            result[offset:offset + 4] = bytes.fromhex('e0010000')
        for offset in (0x3caa, 0xc6ab):
            result[offset:offset + 4] = bytes.fromhex('80020000')
        return bytes(result)

    @property
    def cache(self):
        return self.state / 'compat/sgd2-640x480-v1/SGD2FreeRes.dll'

    def test_production_plan_and_hash(self):
        production = importlib.util.module_from_spec(SPEC)
        SPEC.loader.exec_module(production)
        self.assertEqual(production.SGD2_640_SHA256,
                         'b582f3018b75ff1010ce811924f146d7bd8b67b5693c2f338f782695b1b14cec')
        self.assertEqual(production.SGD2_640_PATCHES, (
            (0x3ca1, bytes.fromhex('58020000'), bytes.fromhex('e0010000')),
            (0x3caa, bytes.fromhex('2c040000'), bytes.fromhex('80020000')),
            (0xc6ab, bytes.fromhex('2c040000'), bytes.fromhex('80020000')),
            (0xc6b5, bytes.fromhex('58020000'), bytes.fromhex('e0010000'))))
        with self.assertRaises(production.LayoutError):
            production.sgd2_640_bytes(self.sgd2_content)

    def test_patch_changes_only_verified_immediates_and_keeps_source(self):
        content = bytearray(self.sgd2_content)
        result = layout.sgd2_640_bytes(content)
        self.assertEqual(result, self.target(content))
        self.assertEqual(bytes(content), self.sgd2_content)
        self.assertEqual([i for i, (a, b) in enumerate(zip(content, result)) if a != b],
                         [0x3ca1, 0x3ca2, 0x3caa, 0x3cab, 0xc6ab, 0xc6ac, 0xc6b5, 0xc6b6])

    def test_all_preimages_and_final_hash_are_checked(self):
        for offset in (0x3ca1, 0x3caa, 0xc6ab, 0xc6b5):
            content = bytearray(self.sgd2_content)
            content[offset:offset + 4] = b'FAIL'
            with self.subTest(offset=offset), mock.patch.object(layout, 'SGD2_SOURCE_SHA256', hashlib.sha256(content).hexdigest()):
                self.assert_closed(lambda: layout.sgd2_640_bytes(content))
        with mock.patch.object(layout, 'SGD2_640_SHA256', '0' * 64):
            self.assert_closed(lambda: layout.sgd2_640_bytes(self.sgd2_content))
        for content in (b'', self.sgd2_content[:-1], self.sgd2_content + b'!', b'private' + self.sgd2_content[7:]):
            self.assert_closed(lambda: layout.sgd2_640_bytes(content))

    def test_cache_publication_reuse_and_source_validation(self):
        original_mtime = self.sgd2.stat().st_mtime_ns
        self.assertEqual(layout.sgd2_640_file(self.data, self.state), self.cache)
        self.assertEqual(self.cache.read_bytes(), self.target(self.sgd2_content))
        cache_mtime = self.cache.stat().st_mtime_ns
        with mock.patch.object(layout, 'atomic_bytes', wraps=layout.atomic_bytes) as atomic:
            layout.sgd2_640_file(self.data, self.state)
            atomic.assert_not_called()
        self.assertEqual(self.cache.stat().st_mtime_ns, cache_mtime)
        self.assertEqual(self.sgd2.stat().st_mtime_ns, original_mtime)
        for content in (self.sgd2_content[:-1], b'private' + self.sgd2_content[7:]):
            self.sgd2.write_bytes(content)
            self.assert_closed(lambda: layout.sgd2_640_file(self.data, self.state))
            self.assertEqual(self.cache.stat().st_mtime_ns, cache_mtime)
        self.sgd2.unlink()
        self.assert_closed(lambda: layout.sgd2_640_file(self.data, self.state))

    def test_bad_cache_and_stale_pending_fail_without_repair(self):
        for content in (b'private', self.target(self.sgd2_content)[:-1],
                        sgd2_target(self.sgd2_content), b'private' + self.target(self.sgd2_content)[7:]):
            write(self.state, self.cache.relative_to(self.state), content)
            before = digest_tree(self.state)
            self.assert_closed(lambda: layout.sgd2_640_file(self.data, self.state))
            self.assertEqual(digest_tree(self.state), before)
        write(self.state, self.cache.relative_to(self.state), self.target(self.sgd2_content))
        write(self.state, self.cache.relative_to(self.state).as_posix() + '.new', b'pending')
        before = digest_tree(self.state)
        self.assert_closed(lambda: layout.sgd2_640_file(self.data, self.state))
        self.assertEqual(digest_tree(self.state), before)
        self.assertEqual(digest_tree(self.data), self.original_data)

    def test_cache_source_and_ancestor_links_rejected(self):
        layout.sgd2_640_file(self.data, self.state)
        real_lstat = Path.lstat
        before = digest_tree(self.state)
        for linked in (self.sgd2, self.sgd2.parent, self.cache, self.cache.parent,
                       self.cache.parent.parent, self.cache.with_name(self.cache.name + '.new')):
            def fake_lstat(path, *args, **kwargs):
                if path == linked:
                    return mock.Mock(st_mode=0o120777, st_file_attributes=0)
                return real_lstat(path, *args, **kwargs)
            with self.subTest(linked=linked.name), mock.patch.object(Path, 'lstat', new=fake_lstat):
                self.assert_closed(lambda: layout.sgd2_640_file(self.data, self.state))
            self.assertEqual(digest_tree(self.state), before)

    def test_persisted_640_and_session_override_roundtrip_are_scoped(self):
        self.settings('640x480')
        self.assertEqual(self.prepare()['game_resolution'], '640x480')
        self.assertEqual(self.links[str(self.state / 'game/ProjectD2/SGD2FreeRes.dll')], str(self.cache))
        self.settings('800x600')
        active = self.port / 'config/ProjectDiablo.json'
        obj = json.loads(active.read_bytes())
        obj['pd2_game_settings'] = {'wasd_movement': False, 'controller_movement': True,
                                    'unrelated_user_flag': 'retain'}
        active.write_text(json.dumps(obj))
        write(self.port, 'saves/hero.d2s', b'private save')
        original_configs = digest_tree(self.port / 'config')
        original_saves = digest_tree(self.port / 'saves')
        cache800 = self.state / 'compat/sgd2-800x600-v1/SGD2FreeRes.dll'
        initial_links = None
        retained = {}
        real_prepare = layout.prepare
        for resolution, target in (('800x600', cache800), ('640x480', self.cache), ('800x600', cache800)):
            def prepare_override(*args, **kwargs):
                return real_prepare(*args, **kwargs, game_resolution=resolution)
            with self.subTest(resolution=resolution), mock.patch.object(layout, 'prepare', side_effect=prepare_override):
                result = self.prepare()
            self.assertEqual(result['game_resolution'], resolution)
            self.assertEqual(self.session()['game_resolution'], resolution)
            links = self.links.copy()
            self.assertEqual(links.pop(str(self.state / 'game/ProjectD2/SGD2FreeRes.dll')), str(target))
            if initial_links is None:
                initial_links = links
            self.assertEqual(links, initial_links)
            self.assertEqual(layout.sync_config(self.port, self.state), 0)
            self.assertEqual(digest_tree(self.port / 'config'), original_configs)
            self.assertEqual(digest_tree(self.port / 'saves'), original_saves)
            self.assertEqual(digest_tree(self.data), self.original_data)
            for path, (content, mtime) in retained.items():
                self.assertEqual(path.read_bytes(), content)
                self.assertEqual(path.stat().st_mtime_ns, mtime)
            retained[target] = (target.read_bytes(), target.stat().st_mtime_ns)


if __name__ == '__main__':
    unittest.main()
