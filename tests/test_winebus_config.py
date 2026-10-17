"""Synthetic Wine registry fixtures only; never call Wine or read game assets."""
import contextlib
import importlib.util
import io
import os
from pathlib import Path
import stat
import shutil
import tempfile
import unittest
import uuid
from unittest import mock

SCRIPT = Path(__file__).resolve().parents[1] / 'sdcard/ports/projectdiablo2/scripts/winebus_config.py'
SPEC = importlib.util.spec_from_file_location('pd2_winebus_config', SCRIPT)
winebus = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(winebus)


def exported(body='', section=winebus.SECTION, utf8=False):
    text = winebus.HEADER + '\r\n\r\n[' + section + ']\r\n' + body
    return text.encode('utf-8') if utf8 else b'\xff\xfe' + text.encode('utf-16-le')


class ParserTests(unittest.TestCase):
    def test_all_missing_are_explicit_deletions(self):
        values = winebus.parse_export(exported())
        self.assertEqual(values, dict.fromkeys(winebus.FLAGS))
        expected = (winebus.HEADER + '\r\n\r\n[' + winebus.SECTION + ']\r\n'
                    '"Enable SDL"=-\r\n"DisableInput"=-\r\n"DisableUdevd"=-\r\n')
        self.assertEqual(winebus.restore_bytes(values), b'\xff\xfe' + expected.encode('utf-16-le'))
        self.assertEqual(winebus.validate_restore(winebus.restore_bytes(values)), values)

    def test_case_insensitive_section_and_flags(self):
        values = winebus.parse_export(exported(
            '"eNaBlE SdL"=DWORD:FFFFFFFF\r\n"DISABLEINPUT"=dword:00000000\r\n'
            '"disableudevd"=dword:1\r\n', section=winebus.SECTION.swapcase()))
        self.assertEqual(values, {'Enable SDL': 0xffffffff, 'DisableInput': 0, 'DisableUdevd': 1})
        marker = winebus.restore_bytes(values)
        self.assertIn('"DisableUdevd"=dword:00000001'.encode('utf-16-le'), marker)
        self.assertEqual(winebus.validate_restore(marker), values)

    def test_utf8_header_with_and_without_bom(self):
        content = exported('"Enable SDL"=dword:00000001\n', utf8=True)
        for data in (content, b'\xef\xbb\xbf' + content):
            self.assertEqual(winebus.parse_export(data)['Enable SDL'], 1)

    def test_foreign_child_sections_and_unknown_values_ignored(self):
        body = ('"Other secret"="private data"\r\n"Enable SDL"=dword:00000002\r\n'
                '[' + winebus.SECTION + '\\Child]\r\n'
                '"Enable SDL"="not a DWORD"\r\n"DisableInput"=dword:00000009\r\n'
                '[HKEY_CURRENT_USER\\Other]\r\n"DisableUdevd"=hex:01\r\n')
        values = winebus.parse_export(exported(body))
        self.assertEqual(values, {'Enable SDL': 2, 'DisableInput': None, 'DisableUdevd': None})
        self.assertNotIn('private'.encode('utf-16-le'), winebus.restore_bytes(values))

    def test_foreign_sections_before_target(self):
        content = exported('"Enable SDL"="foreign"\r\n[' + winebus.SECTION + ']\r\n',
                           section='HKEY_CURRENT_USER\\Other')
        self.assertEqual(winebus.parse_export(content), dict.fromkeys(winebus.FLAGS))

    def test_reject_missing_duplicate_and_nonexact_target_sections(self):
        for content in (exported(section=winebus.SECTION + '\\Child'),
                        exported(section=winebus.SECTION + 'Extra'),
                        exported(section='-' + winebus.SECTION),
                        exported('[' + winebus.SECTION.swapcase() + ']\r\n')):
            with self.subTest(content=content), self.assertRaises(ValueError):
                winebus.parse_export(content)

    def test_duplicate_flags_even_with_case_changes(self):
        with self.assertRaises(ValueError):
            winebus.parse_export(exported('"Enable SDL"=dword:1\n"ENABLE SDL"=dword:1\n'))

    def test_selected_non_dword_and_invalid_dword_rejected(self):
        for name in winebus.FLAGS:
            for value in ('"1"', 'hex:01,00,00,00', 'hex(4):01,00,00,00', '-',
                          'dword:-1', 'dword:100000000', 'dword:', 'dword:zzzzzzzz',
                          'dword:00000001 ; comment'):
                with self.subTest(name=name, value=value), self.assertRaises(ValueError):
                    winebus.parse_export(exported('"' + name + '"=' + value + '\n'))

    def test_malformed_encoding_header_and_oversize(self):
        for content in (b'\xff\xfe\x00', b'\xfe\xff\x00W', b'\xff',
                        exported().replace(b'\xff\xfe', b'', 1),
                        exported(utf8=True).replace(b'Version 5.00', b'Version 4.00'),
                        exported('\x00'), b'x' * (winebus.MAX_BYTES + 1)):
            with self.subTest(content=content[:30]), self.assertRaises((ValueError, UnicodeError)):
                winebus.parse_export(content)

    def test_export_size_limit_is_inclusive(self):
        base = exported(utf8=True)
        content = base + b';' + b'x' * (winebus.MAX_BYTES - len(base) - 1)
        self.assertEqual(len(content), winebus.MAX_BYTES)
        self.assertEqual(winebus.parse_export(content), dict.fromkeys(winebus.FLAGS))
        with self.assertRaises(ValueError):
            winebus.parse_export(content + b'x')

    def test_restore_only_exact_three_flags_and_bounded_ints(self):
        valid = dict.fromkeys(winebus.FLAGS)
        for values in ({}, {**valid, 'Arbitrary': 1}, {**valid, 'Enable SDL': -1},
                       {**valid, 'Enable SDL': 0x100000000}, {**valid, 'Enable SDL': True},
                       {**valid, 'Enable SDL': '1'}):
            with self.subTest(values=values), self.assertRaises(ValueError):
                winebus.restore_bytes(values)

    def test_validate_rejects_every_noncanonical_marker(self):
        marker = winebus.restore_bytes({'Enable SDL': 1, 'DisableInput': None, 'DisableUdevd': None})
        text = marker[2:].decode('utf-16-le')
        variants = [text + '\r\n', text + '[HKEY_CURRENT_USER\\Other]\r\n',
                    text + '"Other"=dword:00000001\r\n',
                    text + '"Enable SDL"=dword:00000001\r\n',
                    text.replace('"Enable SDL"', '"enable sdl"'),
                    text.replace('dword:00000001', 'dword:1'),
                    text.replace('dword:00000001', '"1"'),
                    text.replace('dword:00000001', 'dword:FFFFFFFF'),
                    text.replace('"DisableInput"=-\r\n', ''), text.replace('\r\n', '\n')]
        for variant in variants:
            with self.subTest(variant=variant), self.assertRaises(ValueError):
                winebus.validate_restore(b'\xff\xfe' + variant.encode('utf-16-le'))
        for data in (text.encode('utf-8'), marker[2:], marker + b'\x00',
                     b'x' * (winebus.MAX_BYTES + 1)):
            with self.assertRaises((ValueError, UnicodeError)):
                winebus.validate_restore(data)


class FilesystemTests(unittest.TestCase):
    def setUp(self):
        # POSIX mode/link checks belong on /tmp, not mounted Windows/DrvFS.
        if os.name == 'posix':
            self.temp = tempfile.TemporaryDirectory(dir='/tmp')
            self.addCleanup(self.temp.cleanup)
            self.root = Path(self.temp.name)
        else:
            # TemporaryDirectory/mkdtemp request 0700, which creates restrictive
            # Windows ACLs in Python 3.13+; use ordinary mkdir instead.
            self.root = Path(tempfile.gettempdir()) / ('pd2-winebus-test-' + uuid.uuid4().hex)
            self.root.mkdir()
            self.addCleanup(shutil.rmtree, self.root)
        self.prefix = self.root / 'prefix'
        self.drive = self.prefix / 'drive_c'
        # Do not request POSIX-style 0700 mkdir ACLs on Windows.
        self.drive.mkdir(parents=True)
        self.export = self.drive / winebus.EXPORT_NAME
        self.marker = self.drive / winebus.RESTORE_NAME

    def call(self, operation, expected=0, prefix=None):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            status = winebus.main(['--prefix', str(prefix or self.prefix), operation])
        self.assertEqual(status, expected)
        self.assertEqual(stdout.getvalue(), '' if not expected else winebus.ERROR_EVENT + '\n')
        self.assertEqual(stderr.getvalue(), '')

    def make_export(self):
        self.export.write_bytes(exported('"Enable SDL"=dword:00000002\r\n"Private"="secret"\r\n'))

    def test_prepare_export_reserves_minimal_private_export(self):
        self.call('--prepare-export')
        self.assertEqual(self.export.read_bytes(), exported())
        self.assertEqual(winebus.parse_export(self.export.read_bytes()), dict.fromkeys(winebus.FLAGS))
        self.assertFalse(self.marker.exists())
        if os.name == 'posix':
            self.assertEqual(stat.S_IMODE(self.export.stat().st_mode), 0o600)
        # A retry leaves the reservation inode and bytes untouched.
        before = self.export.stat()
        self.call('--prepare-export')
        self.assertTrue(winebus._same(before, self.export.stat()))
        self.assertEqual(self.export.read_bytes(), exported())

    def test_prepare_export_existing_arbitrary_file_never_overwritten(self):
        for payload in (b'private arbitrary data', b'', b'x' * (winebus.MAX_BYTES + 1)):
            self.export.write_bytes(payload)
            before = self.export.stat()
            self.call('--prepare-export', 1)
            self.assertTrue(winebus._same(before, self.export.stat()))
            self.assertEqual(self.export.read_bytes(), payload)
        self.export.unlink()
        self.export.mkdir()
        self.call('--prepare-export', 1)
        self.assertTrue(self.export.is_dir())

    def test_prepare_export_accepts_valid_stale_export_unchanged(self):
        self.make_export()
        before, payload = self.export.stat(), self.export.read_bytes()
        self.call('--prepare-export')
        self.assertTrue(winebus._same(before, self.export.stat()))
        self.assertEqual(self.export.read_bytes(), payload)

    def test_prepare_export_refuses_pending_restore(self):
        self.marker.write_bytes(winebus.restore_bytes(dict.fromkeys(winebus.FLAGS)))
        self.call('--prepare-export', 1)
        self.assertFalse(self.export.exists())
        self.make_export()
        payload = self.export.read_bytes()
        self.call('--prepare-export', 1)
        self.assertEqual(self.export.read_bytes(), payload)

    def test_prepare_export_refuses_missing_drive(self):
        self.drive.rmdir()
        self.call('--prepare-export', 1)
        self.assertFalse(self.drive.exists())

    def test_prepare_export_exclusive_creation_preserves_racing_file(self):
        real_open = os.open

        def racing_open(path, flags, mode=0o777):
            if Path(path) == self.export:
                self.export.write_bytes(b'concurrent private data')
            return real_open(path, flags, mode)

        with mock.patch.object(winebus.os, 'open', side_effect=racing_open):
            self.call('--prepare-export', 1)
        self.assertEqual(self.export.read_bytes(), b'concurrent private data')

    def test_snapshot_directory_sync_failure_preserves_source_and_marker(self):
        self.make_export()
        with mock.patch.object(winebus, '_sync_directory', side_effect=OSError('private details')):
            self.call('--snapshot', 1)
        self.assertTrue(self.export.exists())
        winebus.validate_restore(self.marker.read_bytes())
        self.assertFalse(list(self.drive.glob('.pd2-winebus-*.tmp')))

    def test_snapshot_persists_marker_before_removing_export(self):
        self.make_export()
        real_unlink = winebus._unlink_checked
        events = []

        def sync(directory):
            self.assertEqual(directory, self.drive)
            winebus.validate_restore(self.marker.read_bytes())
            events.append('sync')

        def unlink(path, expected):
            events.append('unlink')
            return real_unlink(path, expected)

        with mock.patch.object(winebus, '_sync_directory', side_effect=sync), \
                mock.patch.object(winebus, '_unlink_checked', side_effect=unlink):
            self.call('--snapshot')
        self.assertEqual(events, ['sync', 'unlink', 'sync'])

    def test_retire_directory_sync_failure_preserves_both_files(self):
        self.make_export()
        self.marker.write_bytes(winebus.restore_bytes(dict.fromkeys(winebus.FLAGS)))
        with mock.patch.object(winebus, '_sync_directory', side_effect=OSError('private details')):
            self.call('--retire', 1)
        self.assertTrue(self.export.exists())
        self.assertTrue(self.marker.exists())

    def test_retire_syncs_directory_after_unlink(self):
        self.marker.write_bytes(winebus.restore_bytes(dict.fromkeys(winebus.FLAGS)))
        existed = []
        with mock.patch.object(winebus, '_sync_directory', side_effect=lambda directory: existed.append(self.marker.exists())):
            self.call('--retire')
        self.assertEqual(existed, [True, False])

    def test_snapshot_validate_retire_silent_and_scoped(self):
        self.make_export()
        other = self.drive / 'unrelated.reg'
        other.write_bytes(b'untouched')
        self.call('--snapshot')
        self.assertFalse(self.export.exists())
        values = winebus.validate_restore(self.marker.read_bytes())
        self.assertEqual(values, {'Enable SDL': 2, 'DisableInput': None, 'DisableUdevd': None})
        self.assertEqual(sorted(p.name for p in self.drive.iterdir()), [winebus.RESTORE_NAME, 'unrelated.reg'])
        if os.name == 'posix':
            self.assertEqual(stat.S_IMODE(self.marker.stat().st_mode), 0o600)
        self.call('--validate')
        self.call('--retire')
        self.assertFalse(self.marker.exists())
        self.assertEqual(other.read_bytes(), b'untouched')

    def test_refuse_existing_marker_leaves_export_intact(self):
        self.make_export()
        self.marker.write_bytes(b'prior recovery')
        self.call('--snapshot', 1)
        self.assertEqual(self.marker.read_bytes(), b'prior recovery')
        self.assertIn('secret'.encode('utf-16-le'), self.export.read_bytes())

    def test_invalid_snapshot_and_oversize_leave_source_and_no_marker(self):
        for content in (b'invalid private data', b'x' * (winebus.MAX_BYTES + 1)):
            self.export.write_bytes(content)
            self.call('--snapshot', 1)
            self.assertEqual(self.export.read_bytes(), content)
            self.assertFalse(self.marker.exists())

    def test_missing_files_directories_and_bad_restore(self):
        for operation in ('--snapshot', '--validate', '--retire'):
            self.call(operation, 1)
        self.export.mkdir()
        self.call('--snapshot', 1)
        self.marker.write_bytes(exported('"Unknown"="secret"\r\n'))
        self.call('--validate', 1)
        self.call('--retire', 1)
        self.assertTrue(self.marker.exists())

    def test_retire_optional_export_checked_before_any_unlink(self):
        self.marker.write_bytes(winebus.restore_bytes(dict.fromkeys(winebus.FLAGS)))
        self.export.mkdir()
        self.call('--retire', 1)
        self.assertTrue(self.marker.exists())
        self.export.rmdir()
        self.make_export()
        self.call('--retire')
        self.assertFalse(self.export.exists())
        self.assertFalse(self.marker.exists())

    def symlink(self, source, target, directory=False):
        try:
            source.symlink_to(target, target_is_directory=directory)
        except (OSError, NotImplementedError):
            self.skipTest('symlinks unavailable')

    def test_symlink_export_rejected(self):
        target = self.root / 'private.reg'
        target.write_bytes(exported())
        self.symlink(self.export, target)
        self.call('--prepare-export', 1)
        self.call('--snapshot', 1)
        self.assertTrue(self.export.is_symlink())
        self.assertFalse(self.marker.exists())

    def test_symlink_ancestor_rejected(self):
        self.make_export()
        alias = self.root / 'alias'
        self.symlink(alias, self.prefix, directory=True)
        self.call('--prepare-export', 1, prefix=alias)
        self.call('--snapshot', 1, prefix=alias)
        self.assertTrue(self.export.exists())
        self.assertFalse(self.marker.exists())

    def test_symlink_marker_and_retire_export_rejected(self):
        target = self.root / 'marker.reg'
        target.write_bytes(winebus.restore_bytes(dict.fromkeys(winebus.FLAGS)))
        self.symlink(self.marker, target)
        self.call('--validate', 1)
        self.call('--retire', 1)
        self.make_export()
        self.call('--snapshot', 1)
        self.marker.unlink()
        self.marker.write_bytes(target.read_bytes())
        self.export.unlink()
        self.symlink(self.export, target)
        self.call('--retire', 1)
        self.assertTrue(self.marker.exists())
        self.assertTrue(target.exists())

    def test_dangling_marker_link_refuses_snapshot(self):
        self.make_export()
        self.symlink(self.marker, self.root / 'missing')
        self.call('--snapshot', 1)
        self.assertTrue(self.export.exists())

    def test_hardlinked_files_rejected(self):
        self.make_export()
        alias = self.root / 'alias.reg'
        try:
            os.link(self.export, alias)
        except (OSError, NotImplementedError):
            self.skipTest('hardlinks unavailable')
        self.call('--prepare-export', 1)
        self.call('--snapshot', 1)
        self.assertTrue(alias.exists())
        self.assertFalse(self.marker.exists())

    def test_hardlinked_marker_retirement_refused(self):
        self.marker.write_bytes(winebus.restore_bytes(dict.fromkeys(winebus.FLAGS)))
        alias = self.root / 'marker-alias.reg'
        try:
            os.link(self.marker, alias)
        except (OSError, NotImplementedError):
            self.skipTest('hardlinks unavailable')
        self.make_export()
        self.call('--validate', 1)
        self.call('--retire', 1)
        self.assertTrue(self.marker.exists())
        self.assertTrue(self.export.exists())
        self.assertTrue(alias.exists())

    def test_publish_failure_preserves_export_and_cleans_only_temp(self):
        self.make_export()
        with mock.patch.object(winebus.os, 'link', side_effect=OSError('private error')):
            self.call('--snapshot', 1)
        self.assertEqual([p.name for p in self.drive.iterdir()], [winebus.EXPORT_NAME])

    def test_publish_race_does_not_replace_recovery_marker(self):
        self.make_export()
        real_link = os.link

        def concurrent_marker(source, target):
            self.marker.write_bytes(b'concurrent recovery')
            return real_link(source, target)

        with mock.patch.object(winebus.os, 'link', side_effect=concurrent_marker):
            self.call('--snapshot', 1)
        self.assertEqual(self.marker.read_bytes(), b'concurrent recovery')
        self.assertTrue(self.export.exists())
        self.assertFalse(list(self.drive.glob('.pd2-winebus-*.tmp')))

    def test_bad_arguments_fixed_event_without_usage_or_private_paths(self):
        for arguments in ([], ['--help'], ['--prefix', 'secret'],
                          ['--prefix', 'secret', '--discard-export'],
                          ['--prefix', 'secret', '--snapshot', '--retire'],
                          ['--prefix', 'secret', '--prepare-export', '--snapshot'],
                          ['--prefix', 'secret', '--prepare']):
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                self.assertEqual(winebus.main(arguments), 1)
            self.assertEqual(out.getvalue(), winebus.ERROR_EVENT + '\n')
            self.assertEqual(err.getvalue(), '')


if __name__ == '__main__':
    unittest.main()
