"""Private layout regression tests: synthetic files, no ARM/Windows execution."""
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
import tarfile
import tempfile
import unittest
from unittest import mock
import uuid

SCRIPT = Path(__file__).resolve().parents[1] / 'sdcard/ports/projectdiablo2/scripts/layout.py'
SPEC = importlib.util.spec_from_file_location('pd2_layout', SCRIPT)
layout = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(layout)


def write(root, name, content=b'fixture'):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def digest_tree(root):
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file()}


def pe():
    dos = bytearray(64)
    dos[:2] = b'MZ'
    struct.pack_into('<I', dos, 0x3c, 64)
    return bytes(dos) + b'PE\0\0' + struct.pack('<HHIIIHH', 0x14c, 0, 0, 0, 0, 0, 0x102)


def sgd2_fixture():
    """Synthetic release-sized DLL; never reads or copies imported game assets."""
    content = bytearray(307200)
    content[:2] = b'MZ'
    for offset in (0x3caa, 0xc6ab):
        content[offset:offset + 4] = bytes.fromhex('2c040000')
    for offset in (0x3ca1, 0xc6b5):
        content[offset:offset + 4] = bytes.fromhex('58020000')
    return bytes(content)


def sgd2_target(content):
    patched = bytearray(content)
    for offset in (0x3caa, 0xc6ab):
        patched[offset:offset + 4] = bytes.fromhex('20030000')
    return bytes(patched)


def member(name, kind=tarfile.REGTYPE, size=0, target=''):
    entry = tarfile.TarInfo(name)
    entry.type = kind
    entry.size = size
    entry.linkname = target
    entry.mode = 0o755
    return entry


class FakeArchive:
    def __init__(self, members):
        self.members = members

    def getmembers(self):
        return self.members


class LayoutTests(unittest.TestCase):
    def setUp(self):
        parent = Path(__file__).resolve().parent
        if os.name == 'nt':
            self.root = parent / ('.layout-fixture-' + uuid.uuid4().hex)
            self.root.mkdir(mode=0o755)
        else:
            self.root = Path(tempfile.mkdtemp(prefix='.layout-fixture-', dir=parent))
        self.addCleanup(shutil.rmtree, self.root)
        self.port = self.root / 'port'
        self.state = self.root / 'state'
        self.data = self.port / 'gamedata/Diablo II'
        self.links = {}
        self.link_calls = []
        self.port.mkdir()
        self.state.mkdir()
        for name in ('d2data.mpq', 'd2exp.mpq', 'd2char.mpq', 'ProjectD2/pd2data.mpq', 'ProjectD2/pd2monchars.mpq'):
            write(self.data, name, b'MPQ\x1a' + b'\0' * 28)
        for name in ('ProjectD2/Game.exe', 'ProjectD2/ProjectDiablo.dll', 'ProjectD2/ddraw.dll'):
            write(self.data, name, pe())
        self.sgd2_content = sgd2_fixture()
        self.sgd2 = write(self.data, 'ProjectD2/SGD2FreeRes.dll', self.sgd2_content)
        write(self.data, 'D2.LNG', b'ENG')
        write(self.data, 'ProjectD2/ProjectDiablo.cfg', b'immutable donor config')
        write(self.data, 'ProjectD2/default.filter', b'immutable donor filter')
        for name in layout.JSON_CONFIGS:
            write(self.port, 'defaults/' + name, b'{"fixture": true}\n')
        write(self.port, 'defaults/ProjectDiablo.json', json.dumps({
            'classic_game_settings': {'other': {'save_path': 'S:\\'}},
            'fixture': True,
        }).encode())
        for name in ('ProjectDiablo.cfg', 'default.filter'):
            write(self.port, 'defaults/' + name, ('default ' + name + '\n').encode())
        for profile in ('gdi',):
            content = '[ddraw]\nrenderer=' + profile + '\n' + ''.join(key + '=' + value + '\n' for key, value in layout.DISPLAY_KEYS.items())
            write(self.port, 'defaults/ddraw-' + profile + '.ini', content.encode())
        self.wrapper = write(self.port, 'compat/cnc-ddraw/ddraw.dll', pe() + b'new companion')
        self.wrapper_hash = hashlib.sha256(self.wrapper.read_bytes()).hexdigest()
        self.wrapper_manifest = {'version': layout.CNC_DDRAW_VERSION, 'file': 'ddraw.dll',
                                 'size': self.wrapper.stat().st_size, 'sha256': self.wrapper_hash}
        write(self.port, 'compat/cnc-ddraw/manifest.json', json.dumps(self.wrapper_manifest).encode())
        # Fixture authenticates real bytes with synthetic release pins; production
        # pins are checked separately without changing the checked-in constants.
        self.addCleanup(mock.patch.stopall)
        mock.patch.object(layout, 'CNC_DDRAW_SIZE', self.wrapper.stat().st_size).start()
        mock.patch.object(layout, 'CNC_DDRAW_SHA256', self.wrapper_hash).start()
        mock.patch.object(layout, 'SGD2_SOURCE_SHA256', hashlib.sha256(self.sgd2_content).hexdigest()).start()
        mock.patch.object(layout, 'SGD2_800_SHA256', hashlib.sha256(sgd2_target(self.sgd2_content)).hexdigest()).start()
        target640 = bytearray(self.sgd2_content)
        for offset, previous, replacement in layout.SGD2_640_PATCHES:
            target640[offset:offset + len(previous)] = replacement
        mock.patch.object(layout, 'SGD2_640_SHA256', hashlib.sha256(target640).hexdigest()).start()
        runtime = self.port / 'runtime'
        runtime.mkdir()
        with tarfile.open(runtime / 'wine-8.0-x86.tar.xz', 'w:xz') as archive:
            for name in ('wine-8.0-x86', 'wine-8.0-x86/bin'):
                archive.addfile(member(name, tarfile.DIRTYPE))
            for name in ('wine', 'wineserver'):
                content = b'\x7fELFsynthetic only not executable'
                archive.addfile(member('wine-8.0-x86/bin/' + name, size=len(content)), io.BytesIO(content))
        write(runtime, 'box86', b'\x7fELFfake ARM fixture never executed')
        write(runtime, 'weston_pkg_0.2.squashfs', b'opaque fake squashfs')
        write(runtime, 'vc_redist.x86.exe', pe())
        artifacts = [{'file': name, 'size': (runtime / name).stat().st_size, 'sha256': hashlib.sha256((runtime / name).read_bytes()).hexdigest()} for name in layout.ARTIFACTS]
        write(self.port, 'runtime-manifest.json', json.dumps({'artifacts': artifacts}).encode())
        self.original_data = digest_tree(self.data)

    def prepare(self, volatile=True, data_override=None):
        # Mock *only* symlink creation on Windows/Linux alike. Assets remain
        # recorded references, not fake copies; config I/O and tar extraction run.
        def fake_link(path, target):
            layout.no_links(path.parent)
            self.links[str(path)] = str(target)
            self.link_calls.append((path, target))
        def fake_probe(path, target, **kwargs):
            path.touch(exist_ok=False)
        with mock.patch.object(layout, 'link', side_effect=fake_link), mock.patch.object(Path, 'symlink_to', new=fake_probe), mock.patch.object(layout.shutil, 'disk_usage', return_value=mock.Mock(free=2 * 1024 ** 3)):
            return layout.prepare(self.port, self.state, data_override, volatile)

    def session(self):
        return json.loads((self.state / 'session-layout.json').read_text())

    def test_session_state_recovers_after_interrupted_write(self):
        self.prepare()
        stale = write(self.state, 'session-layout.json.new', b'{"volatile_work":')
        orphan = write(self.state, 'session-layout.json.interrupted.tmp', b'partial')
        self.prepare(volatile=False)
        self.assertFalse(self.session()['volatile_work'])
        self.assertEqual(stale.read_bytes(), b'{"volatile_work":')
        self.assertEqual(orphan.read_bytes(), b'partial')
        self.assertEqual(list(self.state.glob('session-layout.json.*.tmp')), [orphan])
        self.assertEqual(digest_tree(self.data), self.original_data)

    def test_session_write_failure_preserves_previous_state_and_cleans_temp(self):
        path = write(self.state, 'session-layout.json', b'{"previous": true}\n')
        original = path.read_bytes()
        for operation in ('fsync', 'replace'):
            with self.subTest(operation=operation):
                target = mock.patch.object(layout.os, 'fsync', side_effect=OSError('interrupted')) if operation == 'fsync' else mock.patch.object(Path, 'replace', side_effect=OSError('interrupted'))
                with target, self.assertRaises(OSError):
                    layout.atomic_session_json(path, {'next': True})
                self.assertEqual(path.read_bytes(), original)
                self.assertEqual(list(self.state.glob('session-layout.json.*.tmp')), [])

    def test_session_state_rejects_link_destination(self):
        path = self.state / 'session-layout.json'
        with mock.patch.object(layout, 'no_links', side_effect=layout.LayoutError('invalid_layout')):
            with self.assertRaises(layout.LayoutError):
                layout.atomic_session_json(path, {'next': True})
        self.assertEqual(list(self.state.iterdir()), [])

    def test_production_gdi_template_is_session_only_and_sync_preserves_ini(self):
        self.prepare()
        settings = self.port / 'config/settings.json'
        original_settings = settings.read_bytes()
        before = digest_tree(self.port / 'config')
        result = self.prepare()
        self.assertEqual(result['profile'], 'gdi')
        self.assertNotIn('performance', result)
        content = (self.state / 'game/ProjectD2/ddraw.ini').read_text()
        for value in ('renderer=gdi', 'shader=Nearest neighbor', 'inject_resolution=640x480',
                      'maxfps=30', 'minfps=0', 'vsync=false', 'singlecpu=false', 'maxgameticks=-1'):
            self.assertIn(value, content)
        (self.state / 'game/ProjectD2/ddraw.ini').write_text('[ddraw]\nrenderer=opengl\n')
        self.assertEqual(layout.sync_config(self.port, self.state), 0)
        self.assertEqual(before, digest_tree(self.port / 'config'))
        self.assertEqual(settings.read_bytes(), original_settings)
        self.assertEqual(self.original_data, digest_tree(self.data))

    def test_production_template_ignores_user_renderer_sections_without_rewriting_them(self):
        self.prepare()
        active = self.port / 'config/ddraw-gdi.ini'
        custom = b'[ddraw]\nrenderer=opengl\nmaxfps=7\n[Game.exe]\nrenderer=opengl\n'
        active.write_bytes(custom)
        self.prepare()
        work = (self.state / 'game/ProjectD2/ddraw.ini').read_bytes()
        self.assertIn(b'renderer=gdi', work)
        self.assertIn(b'maxfps=30', work)
        self.assertNotIn(b'[Game.exe]', work)
        self.assertEqual(active.read_bytes(), custom)
        self.assertEqual(layout.sync_config(self.port, self.state), 0)
        self.assertEqual(active.read_bytes(), custom)

    def test_gdi_still_syncs_other_user_changes(self):
        self.prepare()
        (self.state / 'game/ProjectD2/default.filter').write_bytes(b'user change\n')
        self.assertEqual(layout.sync_config(self.port, self.state), 1)
        self.assertEqual((self.port / 'config/default.filter').read_bytes(), b'user change\n')

    def test_volatile_copies_only_tiny_configs_and_never_game_assets(self):
        with mock.patch.object(layout.shutil, 'copyfile', wraps=shutil.copyfile) as copies:
            result = self.prepare()
        self.assertTrue(result['volatile_work'])
        self.assertEqual(Path(result['work']), self.state / 'game')
        self.assertEqual(len(copies.call_args_list), 1)  # box86, never gamedata
        self.assertEqual(Path(copies.call_args.args[0]), self.port / 'runtime/box86')
        for name in layout.WORK_CONFIGS:
            path = self.state / 'game/ProjectD2' / name
            self.assertTrue(path.is_file())
            self.assertFalse(path.is_symlink())
            active = 'ddraw-gdi.ini' if name == 'ddraw.ini' else name
            if name != 'ddraw.ini':
                self.assertEqual(path.read_bytes(), (self.port / 'config' / active).read_bytes())
            else:
                self.assertIn(b'renderer=gdi', path.read_bytes())
            self.assertNotIn(str(path), self.links)
        self.assertEqual(self.links[str(self.state / 'game/d2data.mpq')], str(self.data / 'd2data.mpq'))
        self.assertFalse((self.port / 'config/game-state').exists())
        self.assertNotIn(str(self.state / 'game/ProjectD2/BnetLog.txt'), self.links)
        self.assertNotIn(str(self.state / 'game/ProjectD2/bncache.dat'), self.links)
        self.assertEqual(self.original_data, digest_tree(self.data))

    def check_imported_engine_files_are_not_linked(self, volatile):
        names = ('bncache.dat', 'BnetLog.txt', 'BnCaChE.DaT', 'bNeTlOg.TxT')
        for index, name in enumerate(names):
            with self.subTest(volatile=volatile, name=name):
                # Separate imports avoid case-only duplicate names on Windows.
                data = self.root / ('engine-import-' + str(index))
                shutil.copytree(self.data, data)
                content = b'imported engine output must stay private\x00\xff'
                imported = write(data, 'ProjectD2/' + name, content)
                before = digest_tree(data)
                tree = sorted(path.relative_to(data).as_posix() for path in data.rglob('*'))
                self.links.clear()
                self.link_calls.clear()
                result = self.prepare(volatile=volatile, data_override=data)
                self.assertEqual(result['volatile_work'], volatile)
                work = Path(result['work']) / 'ProjectD2'
                self.assertFalse(any(target == imported for _, target in self.link_calls))
                self.assertFalse(imported.is_symlink())
                self.assertTrue(imported.is_file())
                self.assertEqual(imported.read_bytes(), content)
                self.assertEqual(before, digest_tree(data))
                self.assertEqual(tree, sorted(path.relative_to(data).as_posix() for path in data.rglob('*')))
                mutable = self.port / 'config/game-state'
                for canonical in ('bncache.dat', 'BnetLog.txt'):
                    destination = work / canonical
                    if volatile:
                        self.assertFalse(destination.exists())
                        self.assertNotIn(str(destination), self.links)
                    else:
                        active = mutable / canonical
                        self.assertEqual(self.links[str(destination)], str(active))
                        self.assertTrue(active.is_file())
                        self.assertFalse(active.is_symlink())
                        self.assertEqual(active.read_bytes(), b'')
                if volatile:
                    self.assertFalse(mutable.exists())
                    self.assertFalse((work / name).exists())
                    self.assertNotIn(str(work / name), self.links)
                elif name not in ('bncache.dat', 'BnetLog.txt'):
                    self.assertNotIn(str(work / name), self.links)
                for path in (self.port / 'config').rglob('*'):
                    if path.is_file():
                        self.assertNotIn(content, path.read_bytes())
                self.assertEqual(self.original_data, digest_tree(self.data))

    def test_volatile_ignores_imported_engine_cache_and_log_case_insensitively(self):
        self.check_imported_engine_files_are_not_linked(volatile=True)

    def test_nonvolatile_links_empty_game_state_not_imported_engine_files(self):
        self.check_imported_engine_files_are_not_linked(volatile=False)

    def test_imported_dsoal_dlls_are_not_linked(self):
        for index, name in enumerate(('dsound.dll', 'dsoal-aldrv.dll', 'DSOUND.DLL', 'DSOAL-ALDRV.DLL')):
            with self.subTest(name=name):
                data = self.root / ('dsoal-import-' + str(index))
                shutil.copytree(self.data, data)
                imported = write(data, 'ProjectD2/' + name, b'custom sound wrapper')
                self.links.clear()
                self.link_calls.clear()
                result = self.prepare(volatile=True, data_override=data)
                work = Path(result['work']) / 'ProjectD2'
                self.assertFalse(any(target == imported for _, target in self.link_calls))
                self.assertNotIn(str(work / name), self.links)
                self.assertFalse((work / name).exists())

    def test_repeated_updates_preserve_user_configs_and_runtime(self):
        self.prepare()
        user = self.port / 'config/ProjectDiablo.cfg'
        user.write_bytes(b'user configuration\n')
        write(self.port, 'defaults/ProjectDiablo.cfg', b'new release defaults\n')
        settings = self.port / 'config/settings.json'
        settings.write_text(json.dumps({'schema_version': 1, 'profile': 'opengl', 'swap_ab': True}))
        before = digest_tree(self.port / 'config')
        with mock.patch.object(layout.shutil, 'copyfile', wraps=shutil.copyfile) as copies, mock.patch.object(layout.tarfile, 'open', wraps=tarfile.open) as tar:
            result = self.prepare()
            copies.assert_not_called()
            tar.assert_not_called()
        self.assertEqual(before, digest_tree(self.port / 'config'))
        self.assertEqual(result['profile'], 'gdi')
        self.assertTrue(result['swap_ab'])
        self.assertEqual((self.state / 'game/ProjectD2/ProjectDiablo.cfg').read_bytes(), b'user configuration\n')
        self.assertEqual(self.original_data, digest_tree(self.data))

    def test_normal_preflight_retains_legacy_config_and_log_links(self):
        result = self.prepare(volatile=False)
        self.assertFalse(result['volatile_work'])
        for name in layout.WORK_CONFIGS:
            target = 'ddraw-gdi.ini' if name == 'ddraw.ini' else name
            self.assertEqual(self.links[str(self.state / 'game/ProjectD2' / name)], str(self.port / 'config' / target))
        self.assertEqual(self.links[str(self.state / 'game/ProjectD2/BnetLog.txt')], str(self.port / 'config/game-state/BnetLog.txt'))
        self.assertEqual(self.original_data, digest_tree(self.data))

    def test_sync_atomically_updates_changed_configs_and_one_previous_backup(self):
        self.prepare()
        work = self.state / 'game/ProjectD2'
        active = self.port / 'config/default.filter'
        first = active.read_bytes()
        (work / 'default.filter').write_bytes(b'user filter one\n')
        self.assertEqual(layout.sync_config(self.port, self.state), 1)
        backup = self.port / 'config/backups/default.filter'
        self.assertEqual(backup.read_bytes(), first)
        self.assertEqual(active.read_bytes(), b'user filter one\n')
        before = digest_tree(self.port / 'config')
        self.assertEqual(layout.sync_config(self.port, self.state), 0)
        self.assertEqual(before, digest_tree(self.port / 'config'))
        (work / 'default.filter').write_bytes(b'user filter two\n')
        self.assertEqual(layout.sync_config(self.port, self.state), 1)
        self.assertEqual(backup.read_bytes(), b'user filter one\n')
        self.assertEqual(list((self.port / 'config/backups').iterdir()), [backup])
        self.assertFalse(list((self.port / 'config').rglob('*.new')))
        self.assertEqual(self.original_data, digest_tree(self.data))

    def test_sync_never_persists_session_renderer_even_if_settings_change(self):
        self.prepare()
        before = (self.port / 'config/ddraw-gdi.ini').read_bytes()
        (self.port / 'config/settings.json').write_text(json.dumps({'schema_version': 1, 'profile': 'opengl', 'swap_ab': False}))
        (self.state / 'game/ProjectD2/ddraw.ini').write_bytes(b'new session gdi configuration\n')
        self.assertEqual(layout.sync_config(self.port, self.state), 0)
        self.assertEqual((self.port / 'config/ddraw-gdi.ini').read_bytes(), before)
        self.assertFalse((self.port / 'config/ddraw-opengl.ini').exists())
        self.assertFalse((self.port / 'config/backups/ddraw-gdi.ini').exists())

    def test_sync_ignores_engine_logs_data_saves_and_unknown_files(self):
        self.prepare()
        before = digest_tree(self.port / 'config')
        for name in ('BnetLog.txt', 'bncache.dat', 'hero.d2s', 'new-data.mpq', 'account.json', 'unknown.ini'):
            write(self.state, 'game/ProjectD2/' + name, b'invalid engine output\0' * 30000)
        self.assertEqual(layout.sync_config(self.port, self.state), 0)
        self.assertEqual(before, digest_tree(self.port / 'config'))
        self.assertFalse((self.port / 'config/game-state').exists())
        self.assertFalse((self.port / 'config/backups').exists())
        self.assertEqual(self.original_data, digest_tree(self.data))

    def test_sync_prevalidates_all_no_partial_changes_for_bad_json_utf8_or_oversize(self):
        self.prepare()
        work = self.state / 'game/ProjectD2'
        (work / 'default.filter').write_bytes(b'pending valid change')
        active_before = digest_tree(self.port / 'config')
        good = (work / 'BH.json').read_bytes()
        for invalid in (b'{bad JSON', b'[]', b'null', b'42', b'{"bad": NaN}', b'\xff', b'{"padding":"' + b'x' * layout.CONFIG_LIMIT + b'"}'):
            (work / 'BH.json').write_bytes(invalid)
            with self.assertRaises(layout.LayoutError):
                layout.sync_config(self.port, self.state)
            self.assertEqual(active_before, digest_tree(self.port / 'config'))
        (work / 'BH.json').write_bytes(good)
        for invalid in (b'\xff', b'text\x00', b'x' * (layout.CONFIG_LIMIT + 1)):
            (work / 'ProjectDiablo.cfg').write_bytes(invalid)
            with self.assertRaises(layout.LayoutError):
                layout.sync_config(self.port, self.state)
            self.assertEqual(active_before, digest_tree(self.port / 'config'))

    def test_sync_rejects_work_config_symlink_and_parent_link_without_privilege(self):
        self.prepare()
        real_lstat = Path.lstat
        before = digest_tree(self.port / 'config')
        for symlink in (self.state / 'game/ProjectD2/BH.json', self.state / 'game/ProjectD2', self.port / 'config'):
            def fake_lstat(path, *args, **kwargs):
                if path == symlink:
                    return mock.Mock(st_mode=0o120777, st_file_attributes=0)
                return real_lstat(path, *args, **kwargs)
            with mock.patch.object(Path, 'lstat', new=fake_lstat):
                with self.assertRaises(layout.LayoutError):
                    layout.sync_config(self.port, self.state)
            self.assertEqual(before, digest_tree(self.port / 'config'))

    def test_sync_rejects_forged_session_work_profile_and_nonvolatile(self):
        self.prepare()
        good = self.session()
        before = digest_tree(self.port / 'config')
        for field, value in (('work', str(self.root / 'outside')), ('work', str(self.state / 'game/../other')), ('profile', '../outside'), ('volatile_work', False)):
            session = dict(good)
            session[field] = value
            (self.state / 'session-layout.json').write_text(json.dumps(session))
            with self.assertRaises(layout.LayoutError):
                layout.sync_config(self.port, self.state)
            self.assertEqual(before, digest_tree(self.port / 'config'))

    def test_prepare_rejects_asset_directory_or_config_ancestor_symlink(self):
        real_lstat = Path.lstat
        for symlink in (self.data / 'ProjectD2', self.port / 'config', self.port / 'defaults'):
            def fake_lstat(path, *args, **kwargs):
                if path == symlink:
                    return mock.Mock(st_mode=0o120777, st_file_attributes=0)
                return real_lstat(path, *args, **kwargs)
            with mock.patch.object(Path, 'lstat', new=fake_lstat):
                with self.assertRaises(layout.LayoutError):
                    self.prepare()
            self.assertEqual(self.original_data, digest_tree(self.data))

    def test_volatile_refuses_leftover_persistent_engine_log_link(self):
        self.prepare()
        target = self.state / 'game/ProjectD2/BnetLog.txt'
        real_lstat = Path.lstat
        def fake_lstat(path, *args, **kwargs):
            if path == target:
                return mock.Mock(st_mode=0o120777, st_file_attributes=0)
            return real_lstat(path, *args, **kwargs)
        with mock.patch.object(Path, 'lstat', new=fake_lstat):
            with self.assertRaises(layout.LayoutError):
                self.prepare()
        self.assertFalse((self.port / 'config/game-state').exists())
        self.assertEqual(self.original_data, digest_tree(self.data))

    def test_data_override_is_used_only_as_reference_without_copy(self):
        override = self.root / 'readonly-bind-alias'
        shutil.copytree(self.data, override)  # tiny fixture, never real game
        original = digest_tree(override)
        self.prepare(data_override=override)
        self.assertEqual(self.links[str(self.state / 'game/ProjectD2/Game.exe')], str(override / 'ProjectD2/Game.exe'))
        self.assertEqual(original, digest_tree(override))
        self.assertEqual(self.original_data, digest_tree(self.data))

    def test_runtime_manifest_mismatch_and_missing_fail_closed(self):
        (self.port / 'runtime/box86').write_bytes(b'corrupt')
        with self.assertRaisesRegex(layout.LayoutError, 'unsupported_runtime'):
            self.prepare()
        self.assertFalse((self.state / 'game').exists())

    def test_tar_rejects_oversize_duplicates_ancestor_collision_special_and_escapes(self):
        cases = [
            [member('wine-8.0-x86')],
            [member('wine-8.0-x86/a', size=layout.RUNTIME_LIMIT + 1)],
            [member('wine-8.0-x86/a', size=layout.RUNTIME_LIMIT), member('wine-8.0-x86/b', size=1)],
            [member('wine-8.0-x86/a'), member('wine-8.0-x86/./a')],
            [member('wine-8.0-x86/a'), member('wine-8.0-x86/a/child')],
            [member('wine-8.0-x86/a', tarfile.SYMTYPE, target='b'), member('wine-8.0-x86/a/child')],
            [member('../outside')], [member('/absolute')], [member('C:/outside')],
            [member('wine-8.0-x86/a\\..\\outside')],
            [member('wine-8.0-x86/.. /outside')],
            [member('wine-8.0-x86/a', tarfile.LNKTYPE, target='wine-8.0-x86/b')],
            [member('wine-8.0-x86/a', tarfile.CHRTYPE)], [member('wine-8.0-x86/a', tarfile.FIFOTYPE)],
            [member('wine-8.0-x86/a', tarfile.SYMTYPE, target='/absolute')],
            [member('wine-8.0-x86/a', tarfile.SYMTYPE, target='../outside')],
            [member('wine-8.0-x86/a', tarfile.SYMTYPE, target='b'), member('wine-8.0-x86/b', tarfile.SYMTYPE, target='a')],
            [member('wine-8.0-x86/dir', tarfile.SYMTYPE, target='.'), member('wine-8.0-x86/a', tarfile.SYMTYPE, target='dir/../outside')],
        ]
        for entries in cases:
            with self.subTest(entries=[m.name for m in entries]):
                with self.assertRaisesRegex(layout.LayoutError, 'unsupported_runtime'):
                    layout.validate_tar(FakeArchive(entries))

    def test_tar_accepts_realistic_contained_relative_symlinks(self):
        entries = [
            member('wine-8.0-x86', tarfile.DIRTYPE),
            member('wine-8.0-x86/bin', tarfile.DIRTYPE),
            member('wine-8.0-x86/root-alias', tarfile.SYMTYPE, target='.'),
            member('wine-8.0-x86/lib', tarfile.DIRTYPE),
            member('wine-8.0-x86/lib/wine', tarfile.DIRTYPE),
            member('wine-8.0-x86/lib/wine/libwine.so.1.0'),
            member('wine-8.0-x86/lib/wine/libwine.so.1', tarfile.SYMTYPE, target='libwine.so.1.0'),
            member('wine-8.0-x86/lib/libwine.so', tarfile.SYMTYPE, target='wine/libwine.so.1'),
            member('wine-8.0-x86/bin/wine', tarfile.SYMTYPE, target='../lib/wine/libwine.so.1.0'),
        ]
        self.assertEqual(layout.validate_tar(FakeArchive(entries)), entries)

    def test_partial_extraction_requires_explicit_repair(self):
        manifest = json.loads((self.port / 'runtime-manifest.json').read_text())
        key = next(a['sha256'] for a in manifest['artifacts'] if a['file'] == 'wine-8.0-x86.tar.xz')[:12]
        stage = self.state / ('runtime-' + key) / 'extracting'
        stage.mkdir(parents=True)
        (stage / 'partial').write_bytes(b'leave untouched')
        with self.assertRaises(layout.LayoutError):
            self.prepare()
        self.assertEqual((stage / 'partial').read_bytes(), b'leave untouched')

    def test_json_parser_recursion_failure_is_closed_without_input(self):
        self.prepare()
        with mock.patch.object(layout.json, 'loads', side_effect=RecursionError('private input')):
            with self.assertRaisesRegex(layout.LayoutError, '^invalid_layout$'):
                layout.sync_config(self.port, self.state)

    def test_cli_sync_and_safe_closed_error_output(self):
        self.prepare()
        args = ['--port', str(self.port), '--state', str(self.state), '--sync-config']
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            self.assertEqual(layout.main(args), 0)
        self.assertEqual(stdout.getvalue(), '')
        (self.state / 'game/ProjectD2/BH.json').write_bytes(b'private-file-content-not-valid-json')
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            self.assertEqual(layout.main(args), 1)
        self.assertEqual(stdout.getvalue().strip(), 'PD2_EVENT ' + json.dumps({'event': 'runtime_error', 'reason': 'invalid_layout', 'phase': 'preflight'}))
        self.assertNotIn(str(self.root), stdout.getvalue())
        self.assertNotIn('BH.json', stdout.getvalue())
        self.assertNotIn('private-file-content', stdout.getvalue())

    def test_resolution_defaults_and_legacy_migration(self):
        real_default_path = Path(__file__).resolve().parents[1] / 'sdcard/ports/projectdiablo2/defaults/SGD2FreeResolution.json'
        res_default = json.loads(real_default_path.read_text(encoding='utf-8'))
        cfg = res_default['SlashGaming Diablo II Free Resolution']
        self.assertEqual(cfg['Main Menu Resolution'], '1024x768')
        self.assertEqual(cfg['Ingame Resolutions'], ['1024x768', '800x600'])
        self.assertTrue(cfg['Use 800 Interface Bar?'])

        (self.port / 'config').mkdir(parents=True, exist_ok=True)
        legacy_cfg = {
            'SlashGaming Diablo II Free Resolution': {
                '!!!Metadata (Do not modify)!!!': {'Major Version A': 3, 'Major Version B': 0, 'Minor Version A': 1, 'Minor Version B': 0},
                'Ingame Resolutions': ['800x600'],
                'Ingame Resolution Mode': 1,
                'Main Menu Resolution': '800x600',
                'Custom MPQ File': 'SGD2FreeRes.mpq',
                'Enable Screen Border Frame?': False,
                'Use Original Screen Border Frame?': False,
                'Use 800 Interface Bar?': False
            },
            '!!!Globals!!!': {'Config Tab Width': 4}
        }
        (self.port / 'config/SGD2FreeResolution.json').write_text(json.dumps(legacy_cfg), encoding='utf-8')
        legacy_ddraw = "[ddraw]\nwidth=640\nheight=480\nfullscreen=true\nwindowed=true\nmaintas=true\nhook=2\nadjmouse=true\n"
        (self.port / 'config/ddraw-gdi.ini').write_text(legacy_ddraw, encoding='utf-8')
        (self.data / 'D2.LNG').write_bytes(b'dummy-lng-data')
        self.prepare()
        migrated = json.loads((self.port / 'config/SGD2FreeResolution.json').read_text(encoding='utf-8'))
        migrated_cfg = migrated['SlashGaming Diablo II Free Resolution']
        self.assertEqual(migrated_cfg['Main Menu Resolution'], '1024x768')
        self.assertEqual(migrated_cfg['Ingame Resolutions'], ['1024x768', '800x600'])
        self.assertTrue(migrated_cfg['Use 800 Interface Bar?'])
        migrated_ddraw = (self.port / 'config/ddraw-gdi.ini').read_text(encoding='utf-8')
        for key, value in layout.DISPLAY_KEYS.items():
            self.assertIn(key + '=' + value + '\n', migrated_ddraw)
        self.assertEqual(migrated['!!!Globals!!!'], legacy_cfg['!!!Globals!!!'])
        self.assertEqual(migrated_cfg['Custom MPQ File'], 'SGD2FreeRes.mpq')
        self.assertEqual((self.port / 'config/backups/SGD2FreeResolution.json.display-640-v1.bak').read_bytes(), json.dumps(legacy_cfg).encode())
        migrated_cfg['Main Menu Resolution'] = '1280x720'
        migrated_cfg['Ingame Resolutions'] = ['1280x720']
        migrated_cfg['Use 800 Interface Bar?'] = False
        (self.port / 'config/SGD2FreeResolution.json').write_text(json.dumps(migrated), encoding='utf-8')
        before = digest_tree(self.port / 'config')
        self.prepare()
        self.assertEqual(before, digest_tree(self.port / 'config'))
        self.assertEqual(self.links[str(self.state / 'game/ProjectD2/D2.LNG')], str(self.data / 'D2.LNG'))

    def test_display_migration_preserves_comments_sections_renderer_and_custom_keys(self):
        originals = {}
        untouched = '; width=800 height=600 fullscreen=false hook=2\r\n[custom]\r\nwidth=8000\r\nheight=6000\r\nfullscreen=false\r\nhook=2\r\n'
        for profile in ('gdi',):
            originals[profile] = ('; width=640 not a setting\r\n[ddraw]\r\n'
                                  ' WIDTH = 1024 ; custom width comment\r\nheight=768\r\n'
                                  'fullscreen=false\r\nmaintas=false\r\nadjmouse=false\r\n'
                                  'renderer=' + profile + '\r\ncustomwidth=8000\r\n'
                                  'customheight=6000\r\nmaxfps=35\r\n' + untouched).encode()
            write(self.port, 'config/ddraw-' + profile + '.ini', originals[profile])
        self.prepare()
        for profile in originals:
            active = self.port / ('config/ddraw-' + profile + '.ini')
            content = active.read_bytes()
            self.assertIn(b' WIDTH = 640 ; custom width comment\r\n', content)
            self.assertIn(('renderer=' + profile + '\r\n').encode(), content)
            self.assertIn(b'customwidth=8000\r\ncustomheight=6000\r\nmaxfps=35\r\n', content)
            comment, custom_section = untouched.split('[custom]', 1)
            self.assertIn(comment.encode(), content)
            self.assertTrue(content.endswith(('[custom]' + custom_section).encode()))
            self.assertIn(b'; width=640 not a setting\r\n', content)
            for key, value in layout.DISPLAY_KEYS.items():
                if key != 'width':
                    self.assertIn((key + '=' + value + '\r\n').encode(), content)
            backup = self.port / ('config/backups/ddraw-' + profile + '.ini.display-640-v1.bak')
            self.assertEqual(backup.read_bytes(), originals[profile])
            active.write_bytes(content.replace(b'height=480', b'height=900'))
        before = digest_tree(self.port / 'config')
        mtimes = {p: p.stat().st_mtime_ns for p in (self.port / 'config').rglob('*') if p.is_file()}
        self.prepare()
        self.assertEqual(before, digest_tree(self.port / 'config'))
        self.assertEqual(mtimes, {p: p.stat().st_mtime_ns for p in mtimes})
        self.assertEqual(self.original_data, digest_tree(self.data))

    def test_migration_prevalidates_gdi_without_partial_rewrite(self):
        original = b'[ddraw]\nwidth=1024\nheight=768\n'
        write(self.port, 'config/ddraw-gdi.ini', original)
        invalids = (b'\xff', b'[other]\nwidth=800\n', b'[ddraw]\n[ddraw]\n', b'[ddraw]\n[malformed\n')
        for invalid in invalids:
            write(self.port, 'config/ddraw-gdi.ini', invalid)
            with self.assertRaises(layout.LayoutError):
                self.prepare()
            self.assertEqual((self.port / 'config/ddraw-gdi.ini').read_bytes(), invalid)
            self.assertFalse((self.port / 'config/backups').exists())
            self.assertFalse((self.port / 'config' / layout.DISPLAY_MARKER).exists())
        self.assertEqual(self.original_data, digest_tree(self.data))

    def test_interrupted_migration_retains_original_backups_on_retry(self):
        originals = {}
        for profile in ('gdi',):
            originals[profile] = ('[ddraw]\nrenderer=' + profile + '\nwidth=1024\nheight=768\n').encode()
            write(self.port, 'config/ddraw-' + profile + '.ini', originals[profile])
        real_atomic = layout.atomic_bytes
        def interrupt(path, content):
            if path == self.port / 'config' / layout.DISPLAY_MARKER:
                raise OSError('simulated interruption')
            return real_atomic(path, content)
        with mock.patch.object(layout, 'atomic_bytes', side_effect=interrupt):
            with self.assertRaises(OSError):
                self.prepare()
        self.assertFalse((self.port / 'config' / layout.DISPLAY_MARKER).exists())
        self.prepare()
        self.assertTrue((self.port / 'config' / layout.DISPLAY_MARKER).is_file())
        for profile in originals:
            saved = self.port / ('config/backups/ddraw-' + profile + '.ini.display-640-v1.bak')
            self.assertEqual(saved.read_bytes(), originals[profile])
            self.assertIn(b'width=640\n', (self.port / ('config/ddraw-' + profile + '.ini')).read_bytes())
        self.assertEqual(self.original_data, digest_tree(self.data))

    def test_initial_custom_resolution_json_is_not_overridden(self):
        custom = b'{ "SlashGaming Diablo II Free Resolution": {"Main Menu Resolution": "1280x720", "Ingame Resolutions": ["1280x720"], "Use 800 Interface Bar?": false}, "custom": 42 }\n'
        write(self.port, 'config/SGD2FreeResolution.json', custom)
        self.prepare()
        self.assertEqual((self.port / 'config/SGD2FreeResolution.json').read_bytes(), custom)
        self.assertFalse((self.port / 'config/backups/SGD2FreeResolution.json.display-640-v1.bak').exists())

    def save_path_fixture(self, path='C:\\Diablo II\\Save'):
        return {'classic_game_settings': {
            'other': {'save_path': path, 'custom': ['retained', 17]},
            'input': {'wasd': True, 'controller': False}},
            'controller': {'enabled': False, 'bindings': {'a': 'attack'}},
            'WASD': True, 'unrelated': {'save_path': 'leave this alone'}}

    def test_save_path_legacy_migration_preserves_all_other_values_and_saves(self):
        obj = self.save_path_fixture()
        previous = (json.dumps(obj, indent=4) + '\n').encode()
        active = write(self.port, 'config/ProjectDiablo.json', previous)
        sentinel = write(self.port, 'saves/hero.d2s', b'synthetic save sentinel\x00\xff')
        before_saves = digest_tree(sentinel.parent)
        self.prepare()
        expected = self.save_path_fixture('S:\\')
        self.assertEqual(json.loads(active.read_bytes()), expected)
        self.assertEqual(json.loads((self.state / 'game/ProjectD2/ProjectDiablo.json').read_bytes()), expected)
        backup = self.port / 'config/backups/ProjectDiablo.json.save-path-v1.bak'
        self.assertEqual(backup.read_bytes(), previous)
        marker = self.port / 'config/.save-path-v1.json'
        self.assertEqual(json.loads(marker.read_bytes()), {'schema_version': 1, 'migration': 'save-path-v1'})
        self.assertEqual(self.links[str(self.state / 'wineprefix/dosdevices/s:')], str(self.port / 'saves'))
        self.assertEqual(before_saves, digest_tree(sentinel.parent))
        self.assertEqual(self.original_data, digest_tree(self.data))
        changed = json.loads(active.read_bytes())
        changed['controller']['bindings']['a'] = 'user attack'
        changed['classic_game_settings']['other']['custom'].append('user value')
        active.write_text(json.dumps(changed), encoding='utf-8')
        before = digest_tree(self.port / 'config')
        self.prepare()
        self.prepare()
        self.assertEqual(before, digest_tree(self.port / 'config'))
        self.assertEqual(backup.read_bytes(), previous)
        self.assertEqual(before_saves, digest_tree(sentinel.parent))

    def test_save_path_canonical_does_not_rewrite_json_or_create_backup(self):
        previous = (json.dumps(self.save_path_fixture('S:\\'), indent=4) + '  \n').encode()
        active = write(self.port, 'config/ProjectDiablo.json', previous)
        before_mtime = active.stat().st_mtime_ns
        self.prepare()
        self.assertEqual(active.read_bytes(), previous)
        self.assertEqual(active.stat().st_mtime_ns, before_mtime)
        self.assertFalse((self.port / 'config/backups/ProjectDiablo.json.save-path-v1.bak').exists())
        self.assertTrue((self.port / 'config' / layout.SAVE_PATH_MARKER).exists())

    def test_save_path_missing_leaf_sets_only_leaf(self):
        obj = self.save_path_fixture()
        del obj['classic_game_settings']['other']['save_path']
        previous = json.dumps(obj).encode()
        active = write(self.port, 'config/ProjectDiablo.json', previous)
        layout.migrate_save_path(active.parent)
        obj['classic_game_settings']['other']['save_path'] = 'S:\\'
        self.assertEqual(json.loads(active.read_bytes()), obj)
        self.assertEqual((active.parent / 'backups/ProjectDiablo.json.save-path-v1.bak').read_bytes(), previous)

    def test_save_path_malformed_dictionaries_and_leaf_fail_closed(self):
        invalids = [{}, {'classic_game_settings': None}, {'classic_game_settings': []},
                    {'classic_game_settings': {}}, {'classic_game_settings': {'other': []}},
                    {'classic_game_settings': {'other': None}}]
        invalids.extend(self.save_path_fixture(value) for value in (None, 1, True, [], {}))
        for obj in invalids:
            with self.subTest(obj=obj):
                previous = json.dumps(obj).encode()
                active = write(self.port, 'config/ProjectDiablo.json', previous)
                before = digest_tree(active.parent)
                with self.assertRaisesRegex(layout.LayoutError, '^invalid_layout$'):
                    layout.migrate_save_path(active.parent)
                self.assertEqual(before, digest_tree(active.parent))

    def test_save_path_rejects_symlink_backup_and_pending_paths_before_writes(self):
        active = write(self.port, 'config/ProjectDiablo.json', json.dumps(self.save_path_fixture()).encode())
        config = active.parent
        saved = config / 'backups/ProjectDiablo.json.save-path-v1.bak'
        marker = config / layout.SAVE_PATH_MARKER
        real_lstat = Path.lstat
        for linked in (saved, saved.parent, marker, active,
                       saved.with_name(saved.name + '.new'),
                       active.with_name(active.name + '.new'),
                       marker.with_name(marker.name + '.new')):
            def fake_lstat(path, *args, **kwargs):
                if path == linked:
                    return mock.Mock(st_mode=0o120777, st_file_attributes=0)
                return real_lstat(path, *args, **kwargs)
            before = digest_tree(config)
            with mock.patch.object(Path, 'lstat', new=fake_lstat):
                with self.assertRaisesRegex(layout.LayoutError, '^invalid_layout$'):
                    layout.migrate_save_path(config)
            self.assertEqual(before, digest_tree(config))
        for pending in (saved.with_name(saved.name + '.new'),
                        active.with_name(active.name + '.new'), marker.with_name(marker.name + '.new')):
            pending.parent.mkdir(parents=True, exist_ok=True)
            pending.write_bytes(b'pending sentinel')
            before = digest_tree(config)
            with self.assertRaisesRegex(layout.LayoutError, '^invalid_layout$'):
                layout.migrate_save_path(config)
            self.assertEqual(before, digest_tree(config))
            pending.unlink()

    def test_save_path_marker_schema_is_strict_and_later_rewrites_are_not_enforced(self):
        active = write(self.port, 'config/ProjectDiablo.json', json.dumps(self.save_path_fixture()).encode())
        marker = active.parent / layout.SAVE_PATH_MARKER
        for value in ({}, {'schema_version': True, 'migration': 'save-path-v1'},
                      {'schema_version': 1.0, 'migration': 'save-path-v1'},
                      {'schema_version': 2, 'migration': 'save-path-v1'},
                      {'schema_version': 1, 'migration': 'other'},
                      {'schema_version': 1, 'migration': 'save-path-v1', 'extra': True}):
            marker.write_text(json.dumps(value), encoding='utf-8')
            before = digest_tree(active.parent)
            with self.assertRaisesRegex(layout.LayoutError, '^invalid_layout$'):
                layout.migrate_save_path(active.parent)
            self.assertEqual(before, digest_tree(active.parent))
        marker.write_text(json.dumps({'schema_version': 1, 'migration': 'save-path-v1'}), encoding='utf-8')
        # Deliberate one-time policy: a later wrong string remains untouched.
        before = digest_tree(active.parent)
        self.prepare()
        self.assertEqual(active.read_bytes(), json.dumps(self.save_path_fixture()).encode())
        for name, digest in before.items():
            self.assertEqual(digest_tree(active.parent)[name], digest)
        self.assertFalse((active.parent / 'backups/ProjectDiablo.json.save-path-v1.bak').exists())

    def test_save_path_interrupted_marker_write_retains_immutable_original_backup(self):
        previous = json.dumps(self.save_path_fixture()).encode()
        active = write(self.port, 'config/ProjectDiablo.json', previous)
        real_atomic = layout.atomic_bytes
        def interrupt(path, content):
            if path == active.parent / layout.SAVE_PATH_MARKER:
                raise OSError('simulated interruption')
            return real_atomic(path, content)
        with mock.patch.object(layout, 'atomic_bytes', side_effect=interrupt):
            with self.assertRaises(OSError):
                layout.migrate_save_path(active.parent)
        backup = active.parent / 'backups/ProjectDiablo.json.save-path-v1.bak'
        self.assertEqual(backup.read_bytes(), previous)
        self.assertFalse((active.parent / layout.SAVE_PATH_MARKER).exists())
        layout.migrate_save_path(active.parent)
        self.assertEqual(backup.read_bytes(), previous)
        self.assertEqual(json.loads(active.read_bytes()), self.save_path_fixture('S:\\'))
        manifest = json.loads((SCRIPT.parents[1] / 'runtime-manifest.json').read_text())
        self.assertEqual(layout.VERSION, manifest['port_version'])

    def test_companion_link_redirects_only_projectd2_wrapper_in_both_modes(self):
        base_wrapper = write(self.data, 'ddraw.dll', pe() + b'base game wrapper')
        self.original_data = digest_tree(self.data)
        for volatile in (True, False):
            self.prepare(volatile=volatile)
            self.assertEqual(self.links[str(self.state / 'game/ProjectD2/ddraw.dll')], str(self.wrapper))
            self.assertEqual(self.links[str(self.state / 'game/ddraw.dll')], str(base_wrapper))
            self.assertEqual(self.links[str(self.state / 'game/ProjectD2/Game.exe')], str(self.data / 'ProjectD2/Game.exe'))
            self.assertEqual(self.original_data, digest_tree(self.data))

    def test_companion_redirect_is_case_insensitive(self):
        # On Windows a differently cased name denotes the same leaf; rename via
        # an intermediate fixture name to force the directory spelling too.
        original = self.data / 'ProjectD2/ddraw.dll'
        interim = original.with_name('wrapper-fixture.tmp')
        original.rename(interim)
        interim.rename(original.with_name('DDRAW.DLL'))
        self.original_data = digest_tree(self.data)
        self.prepare(volatile=False)
        self.assertEqual(self.links[str(self.state / 'game/ProjectD2/DDRAW.DLL')], str(self.wrapper))
        self.assertEqual(self.original_data, digest_tree(self.data))

    def test_companion_missing_tampered_or_forged_manifest_fails_before_mutation(self):
        manifest_path = self.port / 'compat/cnc-ddraw/manifest.json'
        good_wrapper = self.wrapper.read_bytes()
        for missing in (self.wrapper, manifest_path):
            previous = missing.read_bytes()
            missing.unlink()
            with self.assertRaises(layout.LayoutError):
                self.prepare()
            self.assertEqual(list(self.state.iterdir()), [])
            self.assertFalse((self.port / 'config').exists())
            missing.write_bytes(previous)
        self.wrapper.write_bytes(good_wrapper[:-1] + b'!')  # same size, wrong hash
        with self.assertRaisesRegex(layout.LayoutError, 'unsupported_runtime'):
            self.prepare()
        self.assertEqual(list(self.state.iterdir()), [])
        self.wrapper.write_bytes(good_wrapper)
        for field, value in (('version', 'old'), ('file', '../ddraw.dll'), ('size', True),
                             ('size', len(good_wrapper) + 1), ('sha256', '0' * 64)):
            manifest = dict(self.wrapper_manifest)
            manifest[field] = value
            manifest_path.write_text(json.dumps(manifest))
            with self.assertRaisesRegex(layout.LayoutError, 'unsupported_runtime'):
                self.prepare()
            self.assertEqual(list(self.state.iterdir()), [])
        self.assertEqual(self.original_data, digest_tree(self.data))

    def test_companion_production_pins_and_regular_file_checks(self):
        production = importlib.util.module_from_spec(SPEC)
        SPEC.loader.exec_module(production)
        self.assertEqual(production.CNC_DDRAW_VERSION, '7.1.0.0')
        self.assertEqual(production.CNC_DDRAW_SIZE, 411648)
        self.assertEqual(production.CNC_DDRAW_SHA256, '85e0f7d530dfda134793a57cb3e76b0287dcc96892ee57162dd68f47283b03a9')
        # A self-consistent local manifest is not enough to bypass release pins.
        with self.assertRaisesRegex(production.LayoutError, 'unsupported_runtime'):
            production.companion_file(self.port)
        real_lstat = Path.lstat
        for symlink in (self.wrapper, self.wrapper.parent, self.wrapper.parent / 'manifest.json'):
            def fake_lstat(path, *args, **kwargs):
                if path == symlink:
                    return mock.Mock(st_mode=0o120777, st_file_attributes=0)
                return real_lstat(path, *args, **kwargs)
            with mock.patch.object(Path, 'lstat', new=fake_lstat):
                with self.assertRaises(layout.LayoutError):
                    self.prepare()
            self.assertEqual(list(self.state.iterdir()), [])

    def test_stale_regular_work_config_unlinked_on_preflight(self):
        self.prepare(volatile=False)
        stale_file = self.state / 'game/ProjectD2/ddraw.ini'
        stale_file.write_text('stale content')
        self.assertTrue(stale_file.exists())
        self.prepare(volatile=False)
        self.assertFalse(stale_file.exists())
        self.assertEqual(self.links[str(stale_file)], str(self.port / 'config/ddraw-gdi.ini'))

    def prepare_filter(self, loot_filter, volatile=True):
        """prepare() with an explicit session loot-filter override (menu path)."""
        def fake_link(path, target):
            layout.no_links(path.parent)
            self.links[str(path)] = str(target)
            self.link_calls.append((path, target))
        def fake_probe(path, target, **kwargs):
            path.touch(exist_ok=False)
        with mock.patch.object(layout, 'link', side_effect=fake_link), mock.patch.object(Path, 'symlink_to', new=fake_probe), mock.patch.object(layout.shutil, 'disk_usage', return_value=mock.Mock(free=2 * 1024 ** 3)):
            return layout.prepare(self.port, self.state, None, volatile, loot_filter=loot_filter)

    def test_filter_content_allows_ansi_above_config_limit_but_bounds_size(self):
        scratch = self.root / 'scratch'
        scratch.mkdir()
        ansi = b'Name: Test \xa9\r\nLevel: 1\x02\xff\r\n'
        big_ok = write(scratch, 'big-ok.filter', b'x' * (600 * 1024) + ansi)
        self.assertEqual(layout.filter_content(big_ok), b'x' * (600 * 1024) + ansi)
        exact = write(scratch, 'exact.filter', b'f' * layout.FILTER_LIMIT)
        self.assertEqual(layout.filter_content(exact), b'f' * layout.FILTER_LIMIT)
        oversize = write(scratch, 'oversize.filter', b'f' * (layout.FILTER_LIMIT + 1))
        with self.assertRaises(layout.LayoutError):
            layout.filter_content(oversize)
        nul = write(scratch, 'nul.filter', b'ok\x00bytes')
        with self.assertRaises(layout.LayoutError):
            layout.filter_content(nul)
        with self.assertRaises(layout.LayoutError):
            layout.filter_content(scratch / 'missing.filter')
        # CONFIG_LIMIT still applies to the other configs, only filters are exempt.
        self.assertEqual(layout.CONFIG_LIMIT, 512 * 1024)
        self.assertGreater(layout.FILTER_LIMIT, layout.CONFIG_LIMIT)

    def test_filter_listing_is_flat_sorted_safe_names_only(self):
        self.assertEqual(layout.filter_listing(self.port), [])
        filters = self.port / 'filters'
        write(filters, 'alpha.filter', b'a')
        write(filters, 'Beta.filter', b'b')
        write(filters, 'not-a-filter.txt', b'x')
        write(filters, '.hidden.filter', b'x')
        write(filters, 'bad name.filter', b'x')
        write(filters / 'dir.filter', 'inner.filter', b'x')  # directory
        max_name = 'n' * 128 + '.filter'  # exactly the maximum allowed length (135)
        write(filters, max_name, b'x')
        too_long = 'n' * 129 + '.filter'  # one byte beyond the maximum
        write(filters, too_long, b'x')
        oversize = write(filters, 'big.filter', b'f' * (layout.FILTER_LIMIT + 1))
        expected = sorted(['Beta.filter', 'alpha.filter', max_name])
        self.assertEqual(layout.filter_listing(self.port), expected)
        # Symlinks are never listed (best effort: Windows may refuse creation).
        try:
            (filters / 'link.filter').symlink_to('alpha.filter')
        except (OSError, ValueError):
            pass
        else:
            self.assertEqual(layout.filter_listing(self.port), expected)
            (filters / 'link.filter').unlink()
        self.assertTrue(oversize.exists())

    def test_apply_loot_filter_publishes_selected_default_and_missing_fallback(self):
        self.prepare()
        config = self.port / 'config'
        good = write(self.port / 'filters', 'Good.filter', b'ANSI \xa9 filter body')
        default_bytes = (self.port / 'defaults' / 'default.filter').read_bytes()
        stderr = io.StringIO()
        with mock.patch.object(sys, 'stderr', stderr):
            self.assertEqual(layout.apply_loot_filter(self.port, config, 'Good.filter'), 'Good.filter')
        self.assertEqual((config / 'default.filter').read_bytes(), good.read_bytes())
        self.assertEqual(stderr.getvalue(), '')  # no announce: silent
        stderr = io.StringIO()
        with mock.patch.object(sys, 'stderr', stderr):
            self.assertEqual(layout.apply_loot_filter(self.port, config, 'Good.filter', announce=True), 'Good.filter')
        self.assertEqual(stderr.getvalue(),
                         'PD2_EVENT {"event":"session_probe","phase":"preflight","check":"loot_filter","status":"selected"}\n')
        stderr = io.StringIO()
        with mock.patch.object(sys, 'stderr', stderr):
            self.assertEqual(layout.apply_loot_filter(self.port, config, 'default', announce=True), 'default')
        self.assertEqual((config / 'default.filter').read_bytes(), default_bytes)
        self.assertIn('"status":"default"', stderr.getvalue())
        # Missing or non-file names always report and fall back to the shipped default,
        # replacing any stale published filter bytes.
        write(self.port / 'filters', 'Ghost.filter', b'x')
        (self.port / 'filters' / 'Ghost.filter').unlink()
        (self.port / 'filters' / 'Dir.filter').mkdir()
        for missing in ('Ghost.filter', 'Dir.filter'):
            stderr = io.StringIO()
            with mock.patch.object(sys, 'stderr', stderr):
                self.assertEqual(layout.apply_loot_filter(self.port, config, missing), 'default')
            self.assertEqual(stderr.getvalue(),
                             'PD2_EVENT {"event":"session_probe","phase":"preflight","check":"loot_filter","status":"missing"}\n')
            self.assertEqual((config / 'default.filter').read_bytes(), default_bytes)
        with self.assertRaises(layout.LayoutError):
            layout.apply_loot_filter(self.port, config, '../../evil')

    def test_prepare_loot_filter_override_persists_and_plain_prepare_stays_silent(self):
        settings = self.port / 'config' / 'settings.json'
        stderr = io.StringIO()
        with mock.patch.object(sys, 'stderr', stderr):
            result = self.prepare()
        self.assertEqual(result['loot_filter'], 'default')
        fresh_settings = settings.read_bytes()
        self.assertNotIn('loot_filter', json.loads(fresh_settings))
        self.assertEqual(stderr.getvalue(), '')  # plain prepare: no filter events
        self.prepare()
        self.assertEqual(settings.read_bytes(), fresh_settings)  # byte-identical
        good = write(self.port / 'filters', 'Good.filter', b'ANSI \xa9 body')
        result = self.prepare_filter('Good.filter')
        self.assertEqual(result['loot_filter'], 'Good.filter')
        stored = json.loads(settings.read_bytes())
        self.assertEqual(stored['loot_filter'], 'Good.filter')
        self.assertEqual(self.session()['loot_filter'], 'Good.filter')
        self.assertEqual((self.port / 'config' / 'default.filter').read_bytes(), good.read_bytes())
        # The stored choice wins on later plain prepares and re-announces.
        after_override = settings.read_bytes()
        stderr = io.StringIO()
        with mock.patch.object(sys, 'stderr', stderr):
            result = self.prepare()
        self.assertEqual(result['loot_filter'], 'Good.filter')
        self.assertIn('"status":"selected"', stderr.getvalue())
        self.assertEqual(settings.read_bytes(), after_override)  # no rewrite
        # A missing override falls back to default and persists that fallback.
        result = self.prepare_filter('Ghost.filter')
        self.assertEqual(result['loot_filter'], 'default')
        self.assertEqual(json.loads(settings.read_bytes())['loot_filter'], 'default')
        self.assertEqual((self.port / 'config' / 'default.filter').read_bytes(),
                         (self.port / 'defaults' / 'default.filter').read_bytes())
        with self.assertRaises(layout.LayoutError):
            self.prepare_filter('../../evil')

    def test_prepare_rejects_invalid_loot_filter_parameter(self):
        for bad in ('../../evil', 'bad name.filter', 'UPPER.DIR\\..', 7, b'bytes'):
            with self.subTest(bad=bad), self.assertRaises(layout.LayoutError):
                layout.prepare(self.port, self.state, None, False, loot_filter=bad)
        # A valid regex name that does not exist is accepted (fallback inside prepare).
        self.assertEqual(self.prepare_filter('Nope.filter')['loot_filter'], 'default')

    def test_main_get_reports_stored_loot_filter(self):
        write(self.port / 'filters', 'Good.filter', b'x')
        self.prepare_filter('Good.filter')
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            self.assertEqual(layout.main(['--port', str(self.port), '--state', str(self.state),
                                          '--get', 'loot_filter']), 0)
        self.assertEqual(stdout.getvalue(), 'Good.filter\n')


if __name__ == '__main__':
    unittest.main()
