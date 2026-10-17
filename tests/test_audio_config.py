"""Synthetic bounded registry/proc fixtures; no Wine or real audio hardware."""
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
SPEC = importlib.util.spec_from_file_location('pd2_audio_config', SCRIPTS / 'audio_config.py')
audio = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audio)


def exported(body='', section=audio.SECTION, utf8=False):
    text = audio.HEADER + '\r\n\r\n[' + section + ']\r\n' + body
    return text.encode('utf-8') if utf8 else b'\xff\xfe' + text.encode('utf-16-le')


def hex_value(kind, text):
    return 'hex(%d):%s' % (kind, ','.join('%02x' % b for b in text.encode('utf-16-le')))


class RegistryParserTests(unittest.TestCase):
    def test_missing_restores_only_Audio_deletion(self):
        values = audio.parse_export(exported('"Unrelated"="secret"\r\n'))
        self.assertEqual(values, {'Audio': None})
        marker = audio.restore_bytes(values)
        self.assertEqual(marker, exported('"Audio"=-\r\n'))
        self.assertEqual(audio.validate_restore(marker), values)
        self.assertNotIn('secret'.encode('utf-16-le'), marker)

    def test_strings_empty_unicode_and_escaped_preserve_exact_bytes(self):
        cases = [('alsa', 'alsa'), ('', ''), ('pulse,alsa', 'pulse,alsa'),
                 ('zażółć', 'zażółć'), (r'back\\slash\"quote', 'back\\slash"quote'),
                 (r'first\r\nsecond', 'first\r\nsecond'), ('tab\there', 'tab\there')]
        for encoded, expected in cases:
            with self.subTest(encoded=encoded):
                values = audio.parse_export(exported('"Audio"="' + encoded + '"\r\n'))
                self.assertEqual(values, {'Audio': {'type': 1, 'data': (expected + '\0').encode('utf-16-le')}})
                self.assertEqual(audio.validate_restore(audio.restore_bytes(values)), values)
                self.assertIn('"Audio"=hex(1):'.encode('utf-16-le'), audio.restore_bytes(values))

    def test_utf8_bom_and_case_insensitive_names(self):
        payload = exported('"aUdIo"="alsa"\n', section=audio.SECTION.swapcase(), utf8=True)
        for content in (payload, b'\xef\xbb\xbf' + payload):
            self.assertEqual(audio.parse_export(content)['Audio']['data'], b'a\x00l\x00s\x00a\x00\x00\x00')

    def test_hex_types_and_multiline_preserve_exact(self):
        for kind, text in ((1, 'pulse\0'), (1, '\0'), (2, '%AUDIO%\r\nnext\0'),
                           (7, 'pulse\0alsa\0\0'), (7, '\0'), (7, '\0\0')):
            with self.subTest(kind=kind, text=text):
                encoded = hex_value(kind, text)
                colon = encoded.index(':') + 1
                split = colon + 3
                encoded = encoded[:split] + '\\\r\n  ' + encoded[split:]
                values = audio.parse_export(exported('"Audio"=' + encoded + '\r\n'))
                self.assertEqual(values, {'Audio': {'type': kind, 'data': text.encode('utf-16-le')}})
                self.assertEqual(audio.validate_restore(audio.restore_bytes(values)), values)

    def test_successful_parent_export_proves_missing_target(self):
        content = exported('"Version"="win10"\r\n[' + audio.PARENT_SECTION + '\\AppDefaults]\r\n'
                           '"Audio"="ignored"\r\n', section=audio.PARENT_SECTION)
        self.assertEqual(audio.parse_export(content), {'Audio': None})
        content += ('[' + audio.SECTION + ']\r\n"Audio"="alsa"\r\n').encode('utf-16-le')
        self.assertEqual(audio.parse_export(content)['Audio']['data'], 'alsa\0'.encode('utf-16-le'))

    def test_child_and_foreign_values_never_in_restore(self):
        content = exported('"Audio"="alsa"\r\n[' + audio.SECTION + '\\winealsa.drv]\r\n'
                           '"Audio"="secret"\r\n[HKEY_CURRENT_USER\\Other]\r\n"Audio"=dword:1\r\n')
        marker = audio.restore_bytes(audio.parse_export(content))
        self.assertNotIn('secret'.encode('utf-16-le'), marker)
        self.assertEqual(audio.validate_restore(marker)['Audio']['type'], 1)

    def test_missing_foreign_only_duplicate_and_malformed_sections(self):
        cases = [exported(section='HKEY_CURRENT_USER\\Other'),
                 exported(section=audio.SECTION + '\\Child'),
                 exported('[' + audio.SECTION.swapcase() + ']\r\n'),
                 exported('[' + audio.PARENT_SECTION + ']\r\n[' + audio.PARENT_SECTION + ']\r\n'),
                 exported('[broken\r\n'), exported('"Audio"="alsa"\n"AUDIO"="pulse"\n')]
        for content in cases:
            with self.subTest(content=content), self.assertRaises(ValueError):
                audio.parse_export(content)

    def test_invalid_values_escapes_hex_lengths_and_terminators(self):
        cases = ['dword:1', 'hex:00,00', 'hex(4):00,00', 'hex(9):00,00', '-',
                 '"bad\\q"', '"unterminated', '"alsa" junk', 'hex(1):',
                 'hex(1):00,', 'hex(1):0,00', 'hex(1):gg,00', 'hex(1):00',
                 'hex(1):61,00', 'hex(1):00,00,61,00,00,00',
                 'hex(7):61,00,00,00', 'hex(2):00,d8,00,00',
                 'hex(1):00,\\\r\n[HKEY_CURRENT_USER\\Other]',
                 'hex(1):00,\\', 'hex(1):00,\\\r\n"Other"="secret"']
        for encoded in cases:
            with self.subTest(encoded=encoded), self.assertRaises((ValueError, UnicodeError)):
                audio.parse_export(exported('"Audio"=' + encoded + '\r\n'))

    def test_bounded_inputs_and_value_inclusive_limit(self):
        raw = ('a' * (audio.MAX_VALUE_BYTES // 2 - 1) + '\0').encode('utf-16-le')
        value = {'Audio': {'type': 1, 'data': raw}}
        self.assertEqual(audio.validate_restore(audio.restore_bytes(value)), value)
        with self.assertRaises(ValueError):
            audio.restore_bytes({'Audio': {'type': 1, 'data': raw + b'\0\0'}})
        for content in (b'x' * (audio.MAX_BYTES + 1), b'\xff\xfe\x00',
                        exported('\x00'), exported().replace(b'\xff\xfe', b'', 1)):
            with self.assertRaises((ValueError, UnicodeError)):
                audio.parse_export(content)

    def test_restore_rejects_unknown_fields_and_noncanonical_bytes(self):
        for value in ({}, {'Audio': None, 'Other': None}, {'Audio': 1},
                      {'Audio': {'type': True, 'data': b'\0\0'}},
                      {'Audio': {'type': 1, 'data': b'\0\0', 'extra': 0}}):
            with self.assertRaises(ValueError):
                audio.restore_bytes(value)
        canonical = audio.restore_bytes({'Audio': {'type': 1, 'data': 'alsa\0'.encode('utf-16-le')}})
        text = canonical[2:].decode('utf-16-le')
        variants = [canonical[2:], text.encode('utf-8'), canonical + b'\0',
                    exported('"Audio"="alsa"\r\n'),
                    exported('"Audio"=hex(1):61,00,6C,00,73,00,61,00,00,00\r\n'),
                    exported('"Audio"=-\r\n"Other"=-\r\n'),
                    exported('"Audio"=-\r\n[HKEY_CURRENT_USER\\Other]\r\n'),
                    exported(section=audio.PARENT_SECTION),
                    b'\xff\xfe' + text.replace('\r\n', '\n').encode('utf-16-le')]
        for content in variants:
            with self.subTest(content=content), self.assertRaises((ValueError, UnicodeError)):
                audio.validate_restore(content)


class FixtureTests(unittest.TestCase):
    def setUp(self):
        if os.name == 'posix':
            temporary = tempfile.TemporaryDirectory(dir='/tmp')
            self.addCleanup(temporary.cleanup)
            self.root = Path(temporary.name)
        else:
            self.root = Path(tempfile.gettempdir()) / ('pd2-audio-test-' + uuid.uuid4().hex)
            self.root.mkdir()
            self.addCleanup(shutil.rmtree, self.root)
        self.drive = self.root / 'prefix/drive_c'
        self.drive.mkdir(parents=True)
        self.export = self.drive / audio.EXPORT_NAME
        self.marker = self.drive / audio.RESTORE_NAME
        self.run = self.root / 'run'
        self.run.mkdir(mode=0o700 if os.name == 'posix' else 0o777)
        self.proc = self.root / 'proc'
        self.proc.mkdir()
        self.snd = self.root / 'snd'
        self.snd.mkdir()
        self.base = self.root / 'alsa.conf'
        self.base.write_bytes(b'# system ALSA fixture\n')
        self.write_proc()

    def write_proc(self, cards=b' 2 [rk817          ]: rk817-codec - rk817-codec\n',
                   pcm=b'02-03: rk817 : rk817 codec : playback 1 : capture 1\n'):
        (self.proc / 'cards').write_bytes(cards)
        (self.proc / 'pcm').write_bytes(pcm)

    def call(self, operation, expected=0):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            status = audio.main(['--prefix', str(self.drive.parent), operation])
        self.assertEqual(status, expected)
        self.assertEqual(stdout.getvalue(), '' if expected == 0 else audio.ERROR_EVENT + '\n')
        self.assertEqual(stderr.getvalue(), '')

    def route(self, access='ready'):
        return audio.route(self.run, self.proc, self.snd, self.base, lambda path: access)

    def test_registry_lifecycle_present_empty_and_missing(self):
        for body in ('"Audio"="pulse"\r\n', '"Audio"=""\r\n', ''):
            with self.subTest(body=body):
                self.call('--prepare-export')
                self.assertEqual(self.export.read_bytes(), exported())
                if os.name == 'posix':
                    self.assertEqual(stat.S_IMODE(self.export.stat().st_mode), 0o600)
                self.export.write_bytes(exported(body))
                expected = audio.parse_export(self.export.read_bytes())
                self.call('--snapshot')
                self.assertFalse(self.export.exists())
                self.assertEqual(audio.validate_restore(self.marker.read_bytes()), expected)
                if os.name == 'posix':
                    self.assertEqual(stat.S_IMODE(self.marker.stat().st_mode), 0o600)
                self.call('--validate')
                self.call('--retire')
                self.assertFalse(self.marker.exists())

    def test_snapshot_parent_export_and_explicit_missing(self):
        self.call('--prepare-export')
        self.export.write_bytes(exported(section=audio.PARENT_SECTION))
        self.call('--snapshot')
        self.assertEqual(audio.validate_restore(self.marker.read_bytes()), {'Audio': None})
        self.call('--retire')
        self.call('--prepare-export')
        self.call('--snapshot-missing')
        self.assertEqual(audio.validate_restore(self.marker.read_bytes()), {'Audio': None})

    def test_snapshot_missing_never_infers_stale_export_or_missing_file(self):
        self.call('--snapshot-missing', 1)
        self.export.write_bytes(exported('"Audio"="pulse"\r\n'))
        before = self.export.read_bytes()
        self.call('--snapshot-missing', 1)
        self.assertEqual(self.export.read_bytes(), before)
        self.assertFalse(self.marker.exists())

    def test_prepare_retry_preserves_valid_stale_export_and_recovery_marker(self):
        self.export.write_bytes(exported('"Audio"="pulse"\r\n'))
        before = self.export.read_bytes()
        self.call('--prepare-export')
        self.assertEqual(self.export.read_bytes(), before)
        self.call('--snapshot')
        marker = self.marker.read_bytes()
        self.call('--prepare-export', 1)
        self.call('--snapshot', 1)
        self.assertEqual(self.marker.read_bytes(), marker)

    def test_invalid_export_existing_files_and_marker_never_overwritten(self):
        self.export.write_bytes(b'private arbitrary data')
        self.call('--prepare-export', 1)
        self.call('--snapshot', 1)
        self.assertEqual(self.export.read_bytes(), b'private arbitrary data')
        self.assertFalse(self.marker.exists())
        self.marker.write_bytes(b'private marker')
        self.call('--validate', 1)
        self.call('--retire', 1)
        self.assertEqual(self.marker.read_bytes(), b'private marker')
        self.assertEqual(self.export.read_bytes(), b'private arbitrary data')

    def test_persist_marker_before_export_removal_and_recover_after_sync_error(self):
        self.export.write_bytes(exported('"Audio"="pulse"\r\n'))
        with mock.patch.object(audio.wb, '_sync_directory', side_effect=OSError('secret error')):
            self.call('--snapshot', 1)
        self.assertTrue(self.export.exists())
        audio.validate_restore(self.marker.read_bytes())
        self.assertFalse(list(self.drive.glob('.pd2-audio-*.tmp')))
        self.call('--validate')
        self.call('--retire')
        self.assertFalse(self.export.exists())
        self.assertFalse(self.marker.exists())

    def test_retire_sync_failure_preserves_recovery(self):
        self.export.write_bytes(exported())
        self.call('--snapshot')
        marker = self.marker.read_bytes()
        with mock.patch.object(audio.wb, '_sync_directory', side_effect=OSError('secret error')):
            self.call('--retire', 1)
        self.assertEqual(self.marker.read_bytes(), marker)

    def test_hardlinked_export_and_marker_refused_without_touching_other_link(self):
        victim = self.root / 'hardlink-victim'
        victim.write_bytes(exported('"Audio"="pulse"\r\n'))
        os.link(victim, self.export)
        self.call('--prepare-export', 1)
        self.call('--snapshot', 1)
        self.assertEqual(victim.read_bytes(), self.export.read_bytes())
        self.export.unlink()
        victim.write_bytes(audio.restore_bytes({'Audio': None}))
        os.link(victim, self.marker)
        self.call('--validate', 1)
        self.call('--retire', 1)
        self.assertEqual(victim.read_bytes(), self.marker.read_bytes())

    def test_atomic_publication_race_refuses_replacement(self):
        real_link = os.link
        def racing_link(source, destination, *args, **kwargs):
            Path(destination).write_bytes(b'concurrent private data')
            return real_link(source, destination, *args, **kwargs)
        with mock.patch.object(audio.os, 'link', side_effect=racing_link):
            self.call('--prepare-export', 1)
        self.assertEqual(self.export.read_bytes(), b'concurrent private data')
        self.assertFalse(list(self.drive.glob('.pd2-audio-*.tmp')))

    def test_route_known_stable_id_and_nonzero_device_no_global_changes(self):
        before = self.base.read_bytes()
        result = self.route()
        self.assertEqual(result, {'audio_route': 'rk817', 'audio_device': 'ready', 'audio_control': 'ready'})
        config = self.run / audio.CONFIG_NAME
        self.assertEqual(config.read_bytes(), b'</usr/share/alsa/alsa.conf>\npcm.!default {\n type plug\n slave.pcm "hw:CARD=rk817,DEV=3"\n}\nctl.!default {\n type hw\n card "rk817"\n}\n')
        self.assertEqual(self.base.read_bytes(), before)
        if os.name == 'posix':
            self.assertEqual(stat.S_IMODE(config.stat().st_mode), 0o600)
        self.assertEqual(list(self.run.iterdir()), [config])

    def test_route_reports_control_node_access_separately_from_pcm(self):
        def access(path):
            return 'denied' if path.name.startswith('controlC') else 'ready'
        self.assertEqual(audio.route(self.run, self.proc, self.snd, self.base, access),
                         {'audio_route': 'rk817', 'audio_device': 'ready', 'audio_control': 'denied'})
        # The control hint never blocks a working PCM route or changes files.
        self.assertTrue((self.run / audio.CONFIG_NAME).is_file())

    def test_route_known_id_case_insensitive_hdmi_not_selected(self):
        self.write_proc(b' 0 [HDMI]: HDMI - HDMI\n 5 [RK817_codec]: codec - rk817\n',
                        b'00-00: HDMI : playback 1\n05-01: codec : playback 1\n')
        self.assertEqual(self.route()['audio_route'], 'rk817')
        self.assertIn(b'hw:CARD=RK817_codec,DEV=1', (self.run / audio.CONFIG_NAME).read_bytes())

    def test_no_fix_unknown_hdmi_missing_ambiguous_and_invalid_ids(self):
        cases = [
            (b' 0 [HDMI]: HDMI - HDMI\n', b'00-00: HDMI : playback 1\n', 'default'),
            (b' 0 [hdmi-rk817]: HDMI - HDMI\n', b'00-00: HDMI : playback 1\n', 'default'),
            (b'--- no soundcards ---\n', b'', 'missing'),
            (b' 0 [rk817]: codec\n', b'00-00: codec : capture 1\n', 'missing'),
            (b' 0 [rk817]: codec\n', b'00-00: codec : playback 1\n00-01: codec : playback 1\n', 'ambiguous'),
            (b' 0 [rk817]: codec\n 1 [rk817b]: codec\n', b'00-00: codec : playback 1\n', 'ambiguous'),
            (b' 0 [rk817/evil]: codec\n', b'00-00: codec : playback 1\n', 'ambiguous'),
            (b' 0 [rk817"evil]: codec\n', b'00-00: codec : playback 1\n', 'ambiguous'),
            (b' 0 [rk817]: codec\n', b'03-00: codec : playback 1\n', 'ambiguous'),
        ]
        for cards, pcm, expected in cases:
            with self.subTest(cards=cards, pcm=pcm):
                self.write_proc(cards, pcm)
                self.assertEqual(self.route()['audio_route'], expected)
                self.assertFalse((self.run / audio.CONFIG_NAME).exists())

    def test_no_fix_missing_or_denied_device_and_base(self):
        for status in ('missing', 'denied'):
            self.assertEqual(self.route(status), {'audio_route': status, 'audio_device': status, 'audio_control': status})
            self.assertFalse((self.run / audio.CONFIG_NAME).exists())
        self.base.unlink()
        self.assertEqual(self.route(), {'audio_route': 'default', 'audio_device': 'ready', 'audio_control': 'ready'})
        self.assertFalse((self.run / audio.CONFIG_NAME).exists())

    def test_busy_status_prevents_override_closed_or_missing_not_proof_of_pcm_open(self):
        path = self.proc / 'card2/pcm3p/sub0/status'
        path.parent.mkdir(parents=True)
        for content in (b'state: RUNNING\nowner_pid: 123\n', b'state: PREPARED\n', b'state: OPEN\n', b''):
            path.write_bytes(content)
            self.assertEqual(self.route(), {'audio_route': 'busy', 'audio_device': 'ready', 'audio_control': 'ready'})
            self.assertFalse((self.run / audio.CONFIG_NAME).exists())
        path.write_bytes(b'closed\n')
        self.assertEqual(self.route()['audio_route'], 'rk817')

    def test_proc_errors_classified_without_writes(self):
        for error, expected in ((FileNotFoundError('private'), 'missing'),
                                (PermissionError('private'), 'denied'),
                                (ValueError('private'), 'ambiguous')):
            with mock.patch.object(audio, '_proc_bytes', side_effect=error):
                self.assertEqual(self.route()['audio_route'], expected)
            self.assertFalse((self.run / audio.CONFIG_NAME).exists())

    def test_existing_route_file_refused_even_if_bytes_valid(self):
        path = self.run / audio.CONFIG_NAME
        for content in (b'private', audio.config_bytes('rk817', 3)):
            path.write_bytes(content)
            with self.assertRaises(ValueError):
                self.route()
            self.assertEqual(path.read_bytes(), content)

    def test_device_status_rejects_regular_file_and_respects_node_access(self):
        path = self.snd / 'pcmC2D3p'
        self.assertEqual(audio._device_status(path), 'missing')
        path.write_bytes(b'not a character device')
        self.assertEqual(audio._device_status(path), 'missing')
        with mock.patch.object(audio.stat, 'S_ISCHR', return_value=True), \
                mock.patch.object(audio.os, 'access', return_value=False):
            self.assertEqual(audio._device_status(path), 'denied')
        with mock.patch.object(audio.stat, 'S_ISCHR', return_value=True), \
                mock.patch.object(audio.os, 'access', return_value=True):
            self.assertEqual(audio._device_status(path), 'ready')

    def test_cli_only_fixed_events_no_paths_ids_or_errors(self):
        for check, status in (('audio_route', 'rk817'), ('audio_device', 'ready')):
            self.assertNotIn('private', status)
        stdout, stderr = io.StringIO(), io.StringIO()
        with mock.patch.object(audio, 'route', return_value={'audio_route': 'rk817', 'audio_device': 'ready', 'audio_control': 'ready'}), \
                contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            self.assertEqual(audio.main(['--route', '--run', str(self.run)]), 0)
        self.assertEqual(stdout.getvalue(),
                         'PD2_EVENT {"event":"session_probe","phase":"launch","check":"audio_route","status":"rk817"}\n'
                         'PD2_EVENT {"event":"session_probe","phase":"launch","check":"audio_device","status":"ready"}\n'
                         'PD2_EVENT {"event":"session_probe","phase":"launch","check":"audio_control","status":"ready"}\n')
        self.assertEqual(stderr.getvalue(), '')
        for arguments in ([], ['--route'], ['--route', '--run', 'secret', '--proc-root', 'private'],
                          ['--route', '--run', 'secret', '--prefix', 'private'],
                          ['--snapshot', '--run', 'secret'], ['--prefix', 'private', '--validate']):
            stdout, stderr = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                self.assertEqual(audio.main(arguments), 1)
            self.assertEqual(stdout.getvalue(), audio.ERROR_EVENT + '\n')
            self.assertEqual(stderr.getvalue(), '')

    @unittest.skipUnless(os.name == 'posix', 'POSIX links/permissions')
    def test_symlink_and_hardlink_files_and_ancestors_refused(self):
        victim = self.root / 'victim'
        victim.write_bytes(b'private victim')
        for path in (self.export, self.marker, self.run / audio.CONFIG_NAME):
            for mode in ('symlink', 'hardlink'):
                if mode == 'symlink':
                    path.symlink_to(victim)
                else:
                    os.link(victim, path)
                if path == self.export:
                    self.call('--prepare-export', 1)
                    self.call('--snapshot', 1)
                elif path == self.marker:
                    self.call('--validate', 1)
                    self.call('--retire', 1)
                else:
                    with self.assertRaises(ValueError):
                        self.route()
                self.assertEqual(victim.read_bytes(), b'private victim')
                path.unlink()
        alias = self.root / 'run-alias'
        alias.symlink_to(self.run, target_is_directory=True)
        with self.assertRaises(ValueError):
            audio.route(alias, self.proc, self.snd, self.base, lambda path: 'ready')
        self.run.chmod(0o755)
        with self.assertRaises(ValueError):
            self.route()


class ProcParserTests(unittest.TestCase):
    def test_bounded_duplicate_invalid_and_nonascii_cards(self):
        for content in (b'x' * (audio.PROC_LIMIT + 1), b' 0 [rk817]: codec\n 0 [other]: codec\n',
                        b' 0 [rk817]: codec\n 1 [rk817]: codec\n', b' 999 [rk817]: codec\n',
                        b' 0 [' + b'a' * 33 + b']: codec\n', b' 0 [rk817\xff]: codec\n'):
            with self.subTest(content=content[:60]), self.assertRaises((ValueError, UnicodeError)):
                audio.parse_cards(content)

    def test_bounded_duplicate_invalid_and_capture_pcm(self):
        self.assertEqual(audio.parse_pcm(b'00-01: capture : capture 1\n'), [])
        for content in (b'x' * (audio.PROC_LIMIT + 1), b'junk\n', b'999-00: playback 1\n',
                        b'00-999: playback 1\n', b'00-00: playback 0\n',
                        b'00-00: playback 999\n', b'00-00: playback nope\n',
                        b'00-00: playback 1 : playback 2\n',
                        b'00-00: playback 1\n00-00: playback 1\n'):
            with self.subTest(content=content[:60]), self.assertRaises(ValueError):
                audio.parse_pcm(content)

    def test_config_injection_and_types_rejected(self):
        for stable, device in (('rk817";evil', 0), ('rk817\n', 0), ('', 0),
                               ('rk817', -1), ('rk817', 256), ('rk817', True), ('rk817', '0')):
            with self.assertRaises(ValueError):
                audio.config_bytes(stable, device)


if __name__ == '__main__':
    unittest.main()
