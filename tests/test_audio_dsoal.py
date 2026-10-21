"""Production DSOAL staging contracts; synthetic files only, no Wine/devices."""
import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import struct
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    'audio_dsoal', ROOT / 'sdcard/ports/projectdiablo2/scripts/audio_dsoal.py')
audio = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audio)

EVIDENCE = (b'[ALSOFT] (II) Initialized backend "winmm"\n'
            b'[ALSOFT] (II) Added "winmm" for playback\n'
            b'[ALSOFT] (II) Added "winmm" for capture\n'
            b'[ALSOFT] (II) Created device 004C2F20, "OpenAL Soft on Out: default"\n')


def fake_pe():
    data = bytearray(128)
    data[:2] = b'MZ'
    struct.pack_into('<I', data, 0x3c, 64)
    data[64:68] = b'PE\0\0'
    struct.pack_into('<H', data, 68, 0x14c)
    struct.pack_into('<H', data, 88, 0x10b)
    return bytes(data)


class EvidenceTests(unittest.TestCase):
    def test_source_exact_startup_and_created_device(self):
        self.assertTrue(audio.winmm_opened(EVIDENCE))

    def test_request_only_not_evidence(self):
        self.assertFalse(audio.winmm_opened(b'ALSOFT_DRIVERS=winmm\ndrivers=winmm'))

    def test_no_device_or_wrong_order_rejected(self):
        self.assertFalse(audio.winmm_opened(EVIDENCE.split(b'Created device')[0]))
        self.assertFalse(audio.winmm_opened(
            b'Created device 1234, "default"\nInitialized backend "winmm"\nAdded "winmm" for playback'))
        self.assertFalse(audio.winmm_opened(
            b'Added "winmm" for playback\nInitialized backend "winmm"\nCreated device 1234, "default"'))

    def test_unknown_or_null_playback_rejected(self):
        for backend in (b'wasapi', b'dsound', b'null', b'untrusted'):
            with self.subTest(backend=backend):
                self.assertFalse(audio.winmm_opened(EVIDENCE.replace(b'winmm', backend)))
                self.assertFalse(audio.winmm_opened(EVIDENCE + b'Added "' + backend + b'" for playback'))

    def test_pe32_only(self):
        self.assertTrue(audio.pe32(fake_pe()))
        for offset, value in ((0, b'xx'), (64, b'BAD!'), (68, b'\x64\x86'), (88, b'\x0b\x02')):
            data = bytearray(fake_pe())
            data[offset:offset + len(value)] = value
            self.assertFalse(audio.pe32(data))
        self.assertFalse(audio.pe32(b'MZ'))
        data = bytearray(fake_pe())
        struct.pack_into('<I', data, 0x3c, 0xffffffff)
        self.assertFalse(audio.pe32(data))

    def test_cli_failures_never_expose_untrusted_arguments(self):
        for args in (['sensitive-path'], ['stage', '--port', 'sensitive-path'],
                     ['collect', '--prefix', 'sensitive-path', '--work', 'sensitive-path']):
            with self.subTest(args=args), contextlib.redirect_stderr(io.StringIO()) as stderr:
                self.assertEqual(audio.main(args), 1)
                text = stderr.getvalue()
                self.assertNotIn('sensitive-path', text)
                event = json.loads(text.removeprefix('PD2_EVENT '))
                self.assertEqual(event['reason'], 'invalid_layout')

    def test_stage_does_not_catch_or_print_untrusted_error_text(self):
        with mock.patch.object(audio, 'stage', side_effect=OSError('secret path')), \
                contextlib.redirect_stderr(io.StringIO()) as stderr:
            self.assertEqual(audio.main(['stage', '--port', 'p', '--prefix', 'x', '--work', 'w']), 1)
        self.assertNotIn('secret', stderr.getvalue())

    def test_root_and_foreign_prefix_owners_rejected(self):
        prefix, drive = mock.Mock(), mock.Mock()
        prefix.stat.return_value.st_uid = drive.stat.return_value.st_uid = 1000
        with mock.patch.object(audio.os, 'getuid', return_value=0, create=True):
            with self.assertRaises(audio.DsoalError):
                audio.verify_owner(prefix, drive)
        with mock.patch.object(audio.os, 'getuid', return_value=1000, create=True):
            audio.verify_owner(prefix, drive)
            drive.stat.return_value.st_uid = 1001
            with self.assertRaises(audio.DsoalError):
                audio.verify_owner(prefix, drive)


class ProductionContracts(unittest.TestCase):
    def test_shipped_payload_authenticates(self):
        artifacts = audio.payload(ROOT / 'sdcard/ports/projectdiablo2')
        self.assertEqual(set(artifacts), set(audio.DLLS))
        self.assertTrue(all(audio.pe32(data) for data in artifacts.values()))

    def test_release_includes_binary_and_corresponding_source(self):
        files = json.loads((ROOT / 'release-files.json').read_text())
        folder = ROOT / 'sdcard/ports/projectdiablo2/compat/dsoal'
        for item in folder.rglob('*'):
            if item.is_file():
                self.assertIn(item.relative_to(ROOT / 'sdcard/ports').as_posix(), files)
        self.assertIn('projectdiablo2/scripts/audio_dsoal.py', files)

    def test_logger_accepts_only_closed_audio_output_enums(self):
        spec = importlib.util.spec_from_file_location(
            'dsoal_safe_log', ROOT / 'sdcard/ports/projectdiablo2/scripts/safe_log.py')
        logger = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(logger)
        for status in ('dsoal_winmm', 'winmm_opened', 'unconfirmed'):
            event = dict(event='session_probe', phase='shutdown', check='audio_output', status=status)
            self.assertEqual(logger.validate_event(event), event)
        event['status'] = 'secret/user/path'
        self.assertIsNone(logger.validate_event(event))


class FilesystemTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.port = self.root / 'port'
        self.prefix = self.root / 'normal-prefix'
        self.work = self.root / 'state/game'
        self.incoming = self.port / 'compat/dsoal'
        for directory in (self.incoming, self.prefix / 'drive_c', self.work / 'ProjectD2',
                          self.port / 'config', self.port / 'saves', self.port / 'gamedata/ProjectD2'):
            directory.mkdir(parents=True)
        self.originals = {
            self.prefix / 'user.reg': b'original registry',
            self.port / 'config/ProjectDiablo.json': b'original config',
            self.port / 'saves/hero.d2s': b'original save',
            self.port / 'gamedata/ProjectD2/Game.exe': b'imported game',
        }
        for path, content in self.originals.items():
            path.write_bytes(content)
        # Ownership checks tested separately with exact UID/root cases; fixtures
        # remain portable on Windows and Linux CI running tests as root.
        owner_patch = mock.patch.object(audio, 'verify_owner')
        self.owner = owner_patch.start()
        self.addCleanup(owner_patch.stop)
        self.records = []
        for name in audio.DLLS:
            data = fake_pe()
            (self.incoming / name).write_bytes(data)
            self.records.append({'file': name, 'size': len(data),
                                 'sha256': hashlib.sha256(data).hexdigest()})
        pin_patch = mock.patch.object(audio, 'PAYLOAD_MANIFEST_SHA256', '')
        pin_patch.start()
        self.addCleanup(pin_patch.stop)
        self.manifest = {'schema_version': 1, 'artifacts': self.records}
        self.repin()

    def repin(self):
        raw = (json.dumps(self.manifest) + '\n').encode()
        (self.incoming / 'manifest.json').write_bytes(raw)
        audio.PAYLOAD_MANIFEST_SHA256 = hashlib.sha256(raw).hexdigest()

    def assert_originals(self):
        self.assertEqual(self.originals, {path: path.read_bytes() for path in self.originals})
        self.assertFalse((self.prefix / 'drive_c/ProjectD2').exists())
        for name in audio.DLLS:
            self.assertFalse((self.prefix / 'drive_c' / name).exists())
            self.assertFalse((self.port / 'gamedata/ProjectD2' / name).exists())

    def staged(self):
        with contextlib.redirect_stdout(io.StringIO()) as stdout:
            session = audio.stage(self.port, self.prefix, self.work)
        self.assertRegex(session, '^[0-9a-f]{32}$')
        self.assertEqual(stdout.getvalue(), session + '\n')
        return self.prefix / 'drive_c/pd2-audio' / session

    def assert_unstaged(self):
        self.assertFalse((self.prefix / 'drive_c/pd2-audio').exists())
        self.assertFalse((self.work / audio.MARKER).exists())
        for name in audio.DLLS:
            self.assertFalse((self.work / 'ProjectD2' / name).exists())
        self.assert_originals()

    def test_stage_normal_prefix_and_work_only(self):
        logdir = self.staged()
        self.assertEqual((logdir / 'openal.ini').read_bytes(), audio.OPENAL_INI)
        marker = json.loads((self.work / audio.MARKER).read_text())
        self.assertEqual(marker['prefix'], str(self.prefix))
        self.assertEqual(marker['work'], str(self.work))
        for name in audio.DLLS:
            self.assertEqual((self.work / 'ProjectD2' / name).read_bytes(), fake_pe())
            self.assertFalse((self.work / 'ProjectD2' / name).is_symlink())
        self.owner.assert_called_once_with(self.prefix, self.prefix / 'drive_c')
        self.assert_originals()

    def test_manifest_tamper_rejected_before_any_write(self):
        (self.incoming / 'manifest.json').write_bytes(b'{"schema_version":1}')
        with self.assertRaises(audio.DsoalError):
            audio.stage(self.port, self.prefix, self.work)
        self.assert_unstaged()

    def test_artifact_tamper_rejected_before_any_write(self):
        (self.incoming / 'dsoal-aldrv.dll').write_bytes(b'corrupt')
        with self.assertRaises(audio.DsoalError):
            audio.stage(self.port, self.prefix, self.work)
        self.assert_unstaged()

    def test_wrong_size_rejected(self):
        self.records[0]['size'] += 1
        self.repin()
        with self.assertRaises(audio.DsoalError):
            audio.stage(self.port, self.prefix, self.work)
        self.assert_unstaged()

    def test_wrong_machine_with_matching_hash_rejected(self):
        data = bytearray(fake_pe())
        struct.pack_into('<H', data, 68, 0x8664)
        (self.incoming / 'dsound.dll').write_bytes(data)
        self.records[0]['sha256'] = hashlib.sha256(data).hexdigest()
        self.repin()
        with self.assertRaises(audio.DsoalError):
            audio.stage(self.port, self.prefix, self.work)
        self.assert_unstaged()

    def test_manifest_requires_exact_two_artifacts(self):
        for records in (self.records[:1], self.records * 2, [self.records[0], self.records[0]],
                        [{'file': '../dsound.dll'}, self.records[1]]):
            with self.subTest(records=records):
                self.manifest['artifacts'] = records
                self.repin()
                with self.assertRaises(audio.DsoalError):
                    audio.stage(self.port, self.prefix, self.work)
                self.assert_unstaged()

    def test_casefold_collision_rejects_before_either_copy(self):
        collision = self.work / 'ProjectD2/DSOUND.DLL'
        collision.write_bytes(b'existing imported bytes')
        with self.assertRaises(audio.DsoalError):
            audio.stage(self.port, self.prefix, self.work)
        self.assertEqual(collision.read_bytes(), b'existing imported bytes')
        self.assertFalse((self.work / 'ProjectD2/dsoal-aldrv.dll').exists())
        self.assertFalse((self.prefix / 'drive_c/pd2-audio').exists())
        self.assert_originals()

    def test_repeat_stage_refused_without_overwrite(self):
        self.staged()
        before = (self.work / audio.MARKER).read_bytes()
        with self.assertRaises(audio.DsoalError):
            audio.stage(self.port, self.prefix, self.work)
        self.assertEqual((self.work / audio.MARKER).read_bytes(), before)
        self.assert_originals()

    def test_refuse_work_under_game_data_or_prefix(self):
        for bad in (self.port / 'gamedata', self.prefix / 'drive_c'):
            with self.subTest(work=bad), self.assertRaises(audio.DsoalError):
                audio.stage(self.port, self.prefix, bad)
        self.assert_unstaged()

    def test_collect_confirmed_bounded_logs_and_safe_result(self):
        logdir = self.staged()
        (logdir / 'openal.log').write_bytes(EVIDENCE + b'x' * audio.LOG_LIMIT)
        (logdir / 'dsoal.log').write_bytes(b'private path player-name ' + b'x' * audio.LOG_LIMIT)
        with contextlib.redirect_stdout(io.StringIO()) as stdout:
            self.assertEqual(audio.collect(self.prefix, self.work), 'winmm_opened')
        self.assertEqual((logdir / 'openal.log').stat().st_size, audio.LOG_LIMIT)
        self.assertEqual((logdir / 'dsoal.log').stat().st_size, audio.LOG_LIMIT)
        result = json.loads((logdir / 'result.json').read_text())
        self.assertEqual(result, {'schema_version': 1, 'mode': 'dsoal', 'backend_evidence': 'winmm_opened'})
        self.assertNotIn('player-name', stdout.getvalue())
        event = json.loads(stdout.getvalue().removeprefix('PD2_EVENT '))
        self.assertEqual(event['check'], 'audio_output')
        self.assert_originals()

    def test_collect_unconfirmed_records_result_and_cli_fails(self):
        logdir = self.staged()
        (logdir / 'openal.log').write_bytes(b'ALSOFT_DRIVERS=winmm')
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()) as stderr:
            self.assertEqual(audio.main(['collect', '--prefix', str(self.prefix), '--work', str(self.work)]), 1)
        self.assertEqual(json.loads((logdir / 'result.json').read_text())['backend_evidence'], 'unconfirmed')
        self.assertEqual(json.loads(stderr.getvalue().removeprefix('PD2_EVENT '))['reason'], 'invalid_layout')
        self.assert_originals()

    def test_collect_wrong_prefix_or_marker_does_not_mutate_logs(self):
        logdir = self.staged()
        log = logdir / 'openal.log'
        log.write_bytes(EVIDENCE)
        marker = json.loads((self.work / audio.MARKER).read_text())
        marker['prefix'] = 'untrusted-prefix'
        (self.work / audio.MARKER).write_text(json.dumps(marker))
        with self.assertRaises(audio.DsoalError):
            audio.collect(self.prefix, self.work)
        self.assertEqual(log.read_bytes(), EVIDENCE)
        self.assertFalse((logdir / 'result.json').exists())
        self.assert_originals()

    def test_collect_rejects_missing_log_directory(self):
        logdir = self.staged()
        marker = json.loads((self.work / audio.MARKER).read_text())
        marker['session'] = '0' * 32
        (self.work / audio.MARKER).write_text(json.dumps(marker))
        with self.assertRaises((audio.DsoalError, OSError)):
            audio.collect(self.prefix, self.work)
        self.assertTrue(logdir.is_dir())

    @unittest.skipIf(os.name == 'nt', 'Unix symlinks required')
    def test_casefold_symlink_collision_never_follows_target(self):
        (self.work / 'ProjectD2/DSOAL-ALDRV.DLL').symlink_to(self.port / 'saves/hero.d2s')
        with self.assertRaises(audio.DsoalError):
            audio.stage(self.port, self.prefix, self.work)
        self.assertFalse((self.work / 'ProjectD2/dsound.dll').exists())
        self.assert_originals()

    @unittest.skipIf(os.name == 'nt', 'Unix symlinks required')
    def test_work_ancestor_symlink_refused(self):
        alias = self.root / 'work-alias'
        alias.symlink_to(self.work.parent, target_is_directory=True)
        with self.assertRaises(audio.DsoalError):
            audio.stage(self.port, self.prefix, alias / 'game')
        self.assert_unstaged()

    @unittest.skipIf(os.name == 'nt', 'Unix symlinks required')
    def test_projectd2_symlink_refused(self):
        (self.work / 'ProjectD2').rmdir()
        (self.work / 'ProjectD2').symlink_to(self.port / 'gamedata/ProjectD2', target_is_directory=True)
        with self.assertRaises(audio.DsoalError):
            audio.stage(self.port, self.prefix, self.work)
        self.assert_originals()

    @unittest.skipIf(os.name == 'nt', 'Unix symlinks required')
    def test_log_symlink_refused_before_any_truncation(self):
        logdir = self.staged()
        original = self.port / 'saves/hero.d2s'
        (logdir / 'openal.log').write_bytes(EVIDENCE + b'x' * audio.LOG_LIMIT)
        (logdir / 'dsoal.log').symlink_to(original)
        with self.assertRaises(audio.DsoalError):
            audio.collect(self.prefix, self.work)
        self.assertGreater((logdir / 'openal.log').stat().st_size, audio.LOG_LIMIT)
        self.assert_originals()

    @unittest.skipIf(os.name == 'nt', 'Unix hardlinks required')
    def test_log_hardlink_refused_without_touching_save(self):
        logdir = self.staged()
        os.link(self.port / 'saves/hero.d2s', logdir / 'openal.log')
        with self.assertRaises(audio.DsoalError):
            audio.collect(self.prefix, self.work)
        self.assert_originals()


if __name__ == '__main__':
    unittest.main()
