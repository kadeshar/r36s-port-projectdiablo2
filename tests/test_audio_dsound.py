"""Synthetic bounded DirectSound fixtures; no Wine or real audio hardware."""
import contextlib
import importlib.util
import io
import os
from pathlib import Path
import shutil
import stat
import sys
import tempfile
import unittest
import uuid
from unittest import mock

SCRIPTS = Path(__file__).resolve().parents[1] / 'sdcard/ports/projectdiablo2/scripts'
# Normal sibling import in production; explicit module registration in tests.
if 'winebus_config' not in sys.modules:
    spec = importlib.util.spec_from_file_location('winebus_config', SCRIPTS / 'winebus_config.py')
    dependency = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(dependency)
    sys.modules['winebus_config'] = dependency
SPEC = importlib.util.spec_from_file_location('pd2_audio_dsound', SCRIPTS / 'audio_dsound.py')
dsound = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(dsound)


def exported(body='', section=dsound.SECTION, utf8=False):
    text = dsound.HEADER + '\r\n\r\n[' + section + ']\r\n' + body
    return text.encode('utf-8') if utf8 else b'\xff\xfe' + text.encode('utf-16-le')


def values(**overrides):
    result = dict.fromkeys(dsound.VALUES)
    result.update(overrides)
    return result


class ParserTests(unittest.TestCase):
    def test_missing_restores_only_named_deletions(self):
        parsed = dsound.parse_export(exported('"Unrelated"="secret"\r\n'))
        self.assertEqual(parsed, values())
        marker = dsound.restore_bytes(parsed)
        self.assertEqual(dsound.validate_restore(marker), parsed)
        self.assertNotIn('secret'.encode('utf-16-le'), marker)
        for name in dsound.VALUES:
            self.assertIn('"%s"=-' % name, marker.decode('utf-16-le'))

    def test_string_values_preserved_exactly(self):
        body = '"HelBuflen"="8192"\r\n"MaxHardwareChannels"="16"\r\n'
        parsed = dsound.parse_export(exported(body))
        self.assertEqual(parsed, values(HelBuflen='8192', MaxHardwareChannels='16'))
        self.assertEqual(dsound.validate_restore(dsound.restore_bytes(parsed)), parsed)

    def test_parent_section_without_target_returns_empty_values(self):
        content = exported(section=dsound.PARENT_SECTION)
        self.assertEqual(dsound.parse_export(content), values())

    def test_parent_and_target_sections_present(self):
        text = dsound.HEADER + '\r\n\r\n[' + dsound.PARENT_SECTION + ']\r\n"Version"="win10"\r\n\r\n[' + dsound.SECTION + ']\r\n"HelBuflen"="8192"\r\n'
        content = b'\xff\xfe' + text.encode('utf-16-le')
        self.assertEqual(dsound.parse_export(content), values(HelBuflen='8192'))

    def test_duplicate_parent_section_rejected(self):
        text = dsound.HEADER + '\r\n\r\n[' + dsound.PARENT_SECTION + ']\r\n[' + dsound.PARENT_SECTION + ']\r\n[' + dsound.SECTION + ']\r\n'
        content = b'\xff\xfe' + text.encode('utf-16-le')
        with self.assertRaises(ValueError):
            dsound.parse_export(content)

    def test_utf8_bom_case_insensitive_and_empty_value(self):
        payload = exported('"helbuflen"=""\n', section=dsound.SECTION.swapcase(), utf8=True)
        for content in (payload, b'\xef\xbb\xbf' + payload):
            self.assertEqual(dsound.parse_export(content), values(HelBuflen=''))

    def test_foreign_child_and_unrelated_values_ignored(self):
        content = exported('"HelBuflen"="8192"\r\n[' + dsound.SECTION + '\\child]\r\n'
                           '"HelBuflen"="secret"\r\n[HKEY_CURRENT_USER\\Other]\r\n"HelBuflen"="x"\r\n')
        marker = dsound.restore_bytes(dsound.parse_export(content))
        self.assertNotIn('secret'.encode('utf-16-le'), marker)

    def test_duplicate_malformed_and_missing_sections_rejected(self):
        cases = [exported(section='HKEY_CURRENT_USER\\Other'),
                 exported('[' + dsound.SECTION.swapcase() + ']\r\n'),
                 exported('[' + dsound.SECTION + ']\r\n[' + dsound.SECTION + ']\r\n'),
                 exported('[broken\r\n'),
                 exported('"HelBuflen"="1"\r\n"HELBUFLEN"="2"\r\n')]
        for content in cases:
            with self.subTest(content=content), self.assertRaises(ValueError):
                dsound.parse_export(content)

    def test_non_string_dword_and_malformed_values_rejected(self):
        cases = ['dword:00002000', 'hex(1):38,00', '1', '"unterminated', '"ok" junk',
                 '"bad\\q"', '"" ,']
        for encoded in cases:
            with self.subTest(encoded=encoded), self.assertRaises((ValueError, UnicodeError)):
                dsound.parse_export(exported('"HelBuflen"=' + encoded + '\r\n'))

    def test_control_and_quote_characters_refused(self):
        for text in ('line\r\nbreak', 'quote"here', 'back\\slash'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                dsound.parse_export(exported('"HelBuflen"="' + text + '"\r\n'))

    def test_bounded_inputs(self):
        for content in (b'x' * (dsound.MAX_BYTES + 1), b'\xff\xfe\x00',
                        exported().replace(b'\xff\xfe', b'', 1),
                        exported('"HelBuflen"="' + 'a' * (dsound.MAX_TEXT + 1) + '"\r\n')):
            with self.subTest(content=content[:40]), self.assertRaises((ValueError, UnicodeError)):
                dsound.parse_export(content)

    def test_restore_rejects_unknown_fields_and_duplicate_names(self):
        for value in ({}, dict(values(), Extra='x')):
            with self.assertRaises(ValueError):
                dsound.restore_bytes(value)
        canonical = dsound.restore_bytes(values(HelBuflen='8192'))
        text = canonical[2:].decode('utf-16-le')
        variants = [canonical[2:], text.encode('utf-8'), canonical + b'\0',
                    exported('"HelBuflen"="8192"\r\n'),
                    b'\xff\xfe' + text.replace('\r\n', '\n').encode('utf-16-le')]
        for content in variants:
            with self.subTest(content=content[:40]), self.assertRaises((ValueError, UnicodeError)):
                dsound.validate_restore(content)


class FixtureTests(unittest.TestCase):
    def setUp(self):
        if os.name == 'posix':
            temporary = tempfile.TemporaryDirectory(dir='/tmp')
            self.addCleanup(temporary.cleanup)
            self.root = Path(temporary.name)
        else:
            self.root = Path(tempfile.gettempdir()) / ('pd2-dsound-test-' + uuid.uuid4().hex)
            self.root.mkdir()
            self.addCleanup(shutil.rmtree, self.root)
        self.drive = self.root / 'prefix/drive_c'
        self.drive.mkdir(parents=True)
        self.export = self.drive / dsound.EXPORT_NAME
        self.marker = self.drive / dsound.RESTORE_NAME
        self.verify = self.drive / dsound.VERIFY_NAME

    def call(self, operation, expected=0, extra_args=None):
        stdout, stderr = io.StringIO(), io.StringIO()
        args = ['--prefix', str(self.drive.parent), operation]
        if extra_args:
            args.extend(extra_args)
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            status = dsound.main(args)
        self.assertEqual(status, expected)
        self.assertEqual(stderr.getvalue(), '')
        return stdout.getvalue()

    def test_registry_lifecycle_present_and_reservation(self):
        for body in ('"HelBuflen"="8192"\r\n', '"HelBuflen"=""\r\n', ''):
            with self.subTest(body=body):
                self.call('--prepare-export')
                self.assertEqual(self.export.read_bytes(), exported())
                if os.name == 'posix':
                    self.assertEqual(stat.S_IMODE(self.export.stat().st_mode), 0o600)
                self.export.write_bytes(exported(body))
                expected = dsound.parse_export(self.export.read_bytes())
                self.call('--snapshot')
                self.assertFalse(self.export.exists())
                self.assertEqual(dsound.validate_restore(self.marker.read_bytes()), expected)
                if os.name == 'posix':
                    self.assertEqual(stat.S_IMODE(self.marker.stat().st_mode), 0o600)
                self.call('--validate')
                self.call('--retire')
                self.assertFalse(self.marker.exists())

    def test_snapshot_missing_never_infers_stale_export(self):
        self.call('--snapshot-missing', 1)
        self.export.write_bytes(exported('"HelBuflen"="8192"\r\n'))
        before = self.export.read_bytes()
        self.call('--snapshot-missing', 1)
        self.assertEqual(self.export.read_bytes(), before)
        self.assertFalse(self.marker.exists())
        self.export.unlink()
        self.call('--prepare-export')
        self.call('--snapshot-missing')
        self.assertEqual(dsound.validate_restore(self.marker.read_bytes()), values())

    def test_prepare_retry_preserves_valid_stale_export_and_recovery_marker(self):
        self.export.write_bytes(exported('"HelBuflen"="8192"\r\n'))
        before = self.export.read_bytes()
        self.call('--prepare-export')
        self.assertEqual(self.export.read_bytes(), before)
        self.call('--snapshot')
        marker = self.marker.read_bytes()
        self.call('--prepare-export', 1)
        self.call('--snapshot', 1)
        self.assertEqual(self.marker.read_bytes(), marker)

    def test_invalid_existing_files_and_marker_never_overwritten(self):
        self.export.write_bytes(b'private arbitrary data')
        self.call('--prepare-export', 1)
        self.call('--snapshot', 1)
        self.assertEqual(self.export.read_bytes(), b'private arbitrary data')
        self.assertFalse(self.marker.exists())
        self.marker.write_bytes(b'private marker')
        self.call('--validate', 1)
        self.call('--retire', 1)
        self.assertEqual(self.marker.read_bytes(), b'private marker')

    def test_persist_marker_before_export_removal_and_recover_after_sync_error(self):
        self.export.write_bytes(exported('"HelBuflen"="8192"\r\n'))
        with mock.patch.object(dsound.wb, '_sync_directory', side_effect=OSError('secret error')):
            self.call('--snapshot', 1)
        self.assertTrue(self.export.exists())
        dsound.validate_restore(self.marker.read_bytes())
        self.assertFalse(list(self.drive.glob('.pd2-dsound-*.tmp')))
        self.call('--validate')
        self.call('--retire')
        self.assertFalse(self.export.exists())
        self.assertFalse(self.marker.exists())

    def test_retire_sync_failure_preserves_recovery(self):
        self.export.write_bytes(exported())
        self.call('--snapshot')
        marker = self.marker.read_bytes()
        with mock.patch.object(dsound.wb, '_sync_directory', side_effect=OSError('secret error')):
            self.call('--retire', 1)
        self.assertEqual(self.marker.read_bytes(), marker)

    def test_hardlinked_export_and_marker_refused(self):
        victim = self.root / 'hardlink-victim'
        victim.write_bytes(exported('"HelBuflen"="8192"\r\n'))
        os.link(victim, self.export)
        self.call('--prepare-export', 1)
        self.call('--snapshot', 1)
        self.assertEqual(victim.read_bytes(), self.export.read_bytes())
        self.export.unlink()
        victim.write_bytes(dsound.restore_bytes(values()))
        os.link(victim, self.marker)
        self.call('--validate', 1)
        self.call('--retire', 1)
        self.assertEqual(victim.read_bytes(), self.marker.read_bytes())

    def test_cli_only_fixed_events_no_paths(self):
        for arguments in ([], ['--snapshot'], ['--snapshot', '--prefix', 'private'],
                          ['--prefix', 'private'], ['--prefix', 'private', '--prepare-export', '--retire']):
            stdout, stderr = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                self.assertEqual(dsound.main(arguments), 1)
            self.assertEqual(stdout.getvalue(), dsound.ERROR_EVENT + '\n')
            self.assertEqual(stderr.getvalue(), '')
            self.assertNotIn('private', stdout.getvalue())

    def test_verify_applied_ver2_success(self):
        body = ('"HelBuflen"="8192"\r\n"MaxHardwareChannels"="16"\r\n"SndQueueMax"="28"\r\n'
                '"DefaultSampleRate"="44100"\r\n"DefaultBitsPerSample"="16"\r\n')
        self.verify.write_bytes(exported(body))
        out = self.call('--verify-applied', 0, ['ver2'])
        self.assertIn('"check":"dsound_helbuflen","status":"8192"', out)
        self.assertFalse(self.verify.exists())

    def test_verify_applied_wine_success(self):
        body = '"HelBuflen"="65536"\r\n'
        self.verify.write_bytes(exported(body))
        out = self.call('--verify-applied', 0, ['wine'])
        self.assertIn('"check":"dsound_helbuflen","status":"65536"', out)
        self.assertFalse(self.verify.exists())

    def test_verify_applied_mismatch_aborts(self):
        body = '"HelBuflen"="1234"\r\n'
        self.verify.write_bytes(exported(body))
        out = self.call('--verify-applied', 1, ['wine'])
        self.assertEqual(out, dsound.ERROR_EVENT + '\n')
        self.assertFalse(self.verify.exists())

    def test_verify_applied_missing_file_fails(self):
        out = self.call('--verify-applied', 1, ['ver2'])
        self.assertEqual(out, dsound.ERROR_EVENT + '\n')

    def test_verify_applied_non_numeric_aborts(self):
        body = '"HelBuflen"="broken"\r\n'
        self.verify.write_bytes(exported(body))
        out = self.call('--verify-applied', 1, ['wine'])
        self.assertEqual(out, dsound.ERROR_EVENT + '\n')
        self.assertFalse(self.verify.exists())


if __name__ == '__main__':
    unittest.main()
