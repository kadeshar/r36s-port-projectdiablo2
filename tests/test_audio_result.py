"""Explicit audio diagnostic: closed results and authenticated own PE, no sound."""
import copy
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
SCRIPTS = ROOT / 'sdcard/ports/projectdiablo2/scripts'
with mock.patch.object(sys, 'path', [str(SCRIPTS), *sys.path]):
    spec = importlib.util.spec_from_file_location('pd2_audio_result', SCRIPTS / 'audio_result.py')
    audio = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(audio)
spec = importlib.util.spec_from_file_location('pd2_audio_safe_log', SCRIPTS / 'safe_log.py')
safe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(safe)
GOOD = dict(schema_version=1, devices=1, open='ready', write='ready', tone='completed', directsound='ready')


class AudioResultTests(unittest.TestCase):
    def setUp(self):
        self.base = ROOT / '.state' / ('.audio-result-' + uuid.uuid4().hex)
        self.base.mkdir(parents=True)
        self.work = self.base / 'game'
        self.directory = self.work / 'ProjectD2'
        self.directory.mkdir(parents=True)
        self.report = self.directory / 'pd2-audio-result.json'
        self.port = self.base / 'port'
        self.source = self.port / 'compat/audio-probe/audio-probe.exe'
        self.source.parent.mkdir(parents=True)
        self.source.write_bytes((SCRIPTS.parent / 'compat/audio-probe/audio-probe.exe').read_bytes())

    def tearDown(self):
        self.assertEqual(self.base.parent, ROOT / '.state')
        self.assertTrue(self.base.name.startswith('.audio-result-'))
        shutil.rmtree(self.base)

    def save(self, value=GOOD):
        self.report.write_text(json.dumps(value), encoding='utf-8')

    def test_exact_schema_and_all_finite_failure_states(self):
        self.assertEqual(audio.validate(GOOD), GOOD)
        self.assertTrue(audio.playback_ready(GOOD))
        self.assertFalse(audio.playback_ready(dict(GOOD, tone='error')))
        for status in audio.STATUSES:
            value = dict(GOOD, open=status, write='not_run', tone='not_run')
            self.assertEqual(audio.validate(value), value)
        self.assertEqual(audio.validate(dict(GOOD, devices=0, open='missing', write='not_run', tone='not_run'))['devices'], 0)

    def test_unknown_fields_types_enums_and_inconsistent_buffers_refused(self):
        variants = [dict(GOOD, extra='private'), dict(GOOD, devices=True), dict(GOOD, devices=257),
                    dict(GOOD, devices=-1), dict(GOOD, schema_version=True), dict(GOOD, open='private'),
                    dict(GOOD, tone='completed', write='error'), dict(GOOD, open='missing'),
                    dict(GOOD, directsound=['ready']), dict(GOOD, tone=None)]
        for value in variants:
            with self.subTest(value=value), self.assertRaises(ValueError): audio.validate(value)
        value = dict(GOOD); del value['tone']
        with self.assertRaises(ValueError): audio.validate(value)

    def test_bounded_strict_json_duplicate_and_non_utf8(self):
        for content in [b'{}' * 3000, b'\xff', b'{"schema_version":1,"schema_version":1}', b'[]']:
            self.report.write_bytes(content)
            with self.assertRaises((ValueError, OSError)): audio.read_summary(self.work)
        self.save(); self.assertEqual(audio.read_summary(self.work), GOOD)

    def test_report_hardlink_refused(self):
        self.save(); os.link(self.report, self.directory / 'other')
        with self.assertRaises(ValueError): audio.read_summary(self.work)

    def test_cli_only_safe_fixed_events(self):
        self.save(); output = io.StringIO()
        self.assertEqual(audio.main(['--work', str(self.work)], output), 0)
        lines = [json.loads(line.removeprefix('PD2_EVENT ')) for line in output.getvalue().splitlines()]
        self.assertEqual(len(lines), 5)
        self.assertTrue(all(safe.validate_event(item) == item for item in lines))
        self.report.write_text('private-account-secret', encoding='utf-8')
        output = io.StringIO(); self.assertEqual(audio.main(['--work', str(self.work)], output), 1)
        self.assertNotIn('private', output.getvalue())
        self.assertEqual(len(output.getvalue().splitlines()), 1)
        self.assertIn('"status":"invalid"', output.getvalue())

    def test_cli_usable_requires_complete_playback(self):
        self.save(); output = io.StringIO()
        self.assertEqual(audio.main(['--work', str(self.work), '--usable'], output), 0)
        self.save(dict(GOOD, tone='error')); output = io.StringIO()
        self.assertEqual(audio.main(['--work', str(self.work), '--usable'], output), 1)
        self.assertIn('"check":"audio_tone","status":"error"', output.getvalue())

    def test_cli_arguments_no_paths_or_exceptions(self):
        for args in [[], ['--work', 'private-path', '--bad'], ['--work', str(self.work), '--prepare'],
                     ['--work', str(self.work), '--port', 'private-path']]:
            output = io.StringIO()
            self.assertEqual(audio.main(args, output), 1)
            self.assertNotIn('private-path', output.getvalue())
            self.assertNotIn('Traceback', output.getvalue())

    def test_prepare_authenticates_and_exclusive_link(self):
        with mock.patch.object(Path, 'symlink_to') as create:
            audio.prepare_probe(self.port, self.work)
            create.assert_called_once_with(self.source)
        for path in [self.directory / 'pd2-audio-probe.exe', self.report]:
            with self.subTest(path=path):
                path.write_bytes(b'old')
                with self.assertRaises(ValueError): audio.prepare_probe(self.port, self.work)
                path.unlink()

    def test_prepare_tamper_hardlink_and_size(self):
        original = self.source.read_bytes()
        for content in [original[:-1], b'MZ' + bytes(len(original) - 2)]:
            self.source.write_bytes(content)
            with self.assertRaises(ValueError): audio.prepare_probe(self.port, self.work)
        self.source.write_bytes(original)
        os.link(self.source, self.source.with_suffix('.alias'))
        with self.assertRaises(ValueError): audio.prepare_probe(self.port, self.work)

    def test_own_probe_pins_and_x86_gui_pe(self):
        content = self.source.read_bytes()
        self.assertEqual(len(content), audio.AUDIO_SIZE)
        self.assertEqual(hashlib.sha256(content).hexdigest(), audio.AUDIO_SHA256)
        offset = struct.unpack_from('<I', content, 0x3c)[0]
        self.assertEqual(content[offset:offset + 4], b'PE\x00\x00')
        self.assertEqual(struct.unpack_from('<H', content, offset + 4)[0], 0x14c)
        self.assertEqual(struct.unpack_from('<H', content, offset + 24 + 68)[0], 2)
        package_spec = importlib.util.spec_from_file_location('pd2_audio_prepare', ROOT / 'tools/prepare.py')
        package = importlib.util.module_from_spec(package_spec); package_spec.loader.exec_module(package)
        allowed = json.loads((ROOT / 'release-files.json').read_text())
        for name in ('audio-probe', 'fps-hotkey'):
            path = 'projectdiablo2/compat/' + name + '/' + name + '.exe'
            self.assertIn(path, allowed); package.validate_release_path(path)
        for path in ('projectdiablo2/compat/audio-probe/other.exe', 'projectdiablo2/compat/fps-hotkey/Game.exe',
                     'Project Diablo 2 - arbitrary.sh', 'projectdiablo2/compat/Game.exe'):
            with self.assertRaises(package.PrepareError): package.validate_release_path(path)

    def test_audio_fps_render_log_allowlist_and_extra_secret_rejection(self):
        states = {'audio_route': ('rk817', 'default', 'missing', 'denied', 'ambiguous', 'busy'),
                  'audio_device': ('ready', 'missing', 'denied'), 'audio_backend': ('alsa', 'restored'),
                  'audio_open': audio.STATUSES, 'audio_directsound': audio.STATUSES + ('not_run',),
                  'audio_write': ('ready', 'error', 'not_run'), 'audio_tone': ('completed', 'error', 'not_run'),
                  'audio_fallback': ('attempted', 'skipped'), 'audio_control': ('ready', 'denied', 'missing'),
                  'audio_diagnostics': ('capture_v2', 'enum_v3', 'errno_v4', 'native_v5', 'syscalls_v6', 'legacy_v7'),
                  'audio_library': ('legacy_armhf', 'unavailable'),
                  'audio_test': ('invalid',), 'fps_counter': ('hotkey', 'renderer', 'disabled', 'unavailable'),
                  'render_resolution': ('640x480', '800x600', '1024x768', 'native')}
        for check, statuses in states.items():
            for status in statuses:
                value = dict(event='session_probe', phase='launch', check=check, status=status)
                self.assertEqual(safe.validate_event(value), value)
                self.assertIsNone(safe.validate_event(dict(value, secret='private')))
            self.assertIsNone(safe.validate_event(dict(event='session_probe', phase='launch', check=check, status='private')))
        for count, status in [(0, 'missing'), (1, 'ready'), (256, 'ready')]:
            value = dict(event='session_probe', phase='launch', check='audio_endpoints', status=status, count=count)
            self.assertEqual(safe.validate_event(value), value)
        for count, status in [(False, 'missing'), (0, 'ready'), (1, 'missing'), (257, 'ready')]:
            self.assertIsNone(safe.validate_event(dict(event='session_probe', phase='launch', check='audio_endpoints', status=status, count=count)))
        for detail in ('no_log', 'silent', 'libasound', 'load_error', 'alsa_error', 'unknown', 'capture_error', 'capture_timeout'):
            value = dict(event='session_probe', phase='launch', check='audio_driver', status='failed', detail=detail)
            self.assertEqual(safe.validate_event(value), value)
        loaded = dict(event='session_probe', phase='launch', check='audio_driver', status='loaded')
        self.assertEqual(safe.validate_event(loaded), loaded)
        for detail in ('loaded', 'private', 'libasound.so.2'):
            self.assertIsNone(safe.validate_event(dict(event='session_probe', phase='launch', check='audio_driver', status='failed', detail=detail)))
        self.assertIsNone(safe.validate_event(dict(event='session_probe', phase='launch', check='audio_driver', status='loaded', detail='no_log')))
        self.assertIsNone(safe.validate_event(dict(event='session_probe', phase='launch', check='audio_driver', status='failed')))

    def test_wine8_enumeration_warnings_keep_each_stage_and_discard_private_text(self):
        # Format strings verified in the shipped winealsa.so, not invented
        # probe messages. Device labels and free-form ALSA strerror stay private.
        content = b'''pd2-capture-marker
0024:trace:alsa:alsa_try_open devnode: default, flow: 0
0024:warn:alsa:alsa_try_open The device "default" failed to open: -16 (private busy detail).
0024:warn:alsa:alsa_try_open The device "default" failed to open: -13 (private permission detail).
0024:trace:alsa:alsa_try_open devnode: plughw:2,3, flow: 0
0024:warn:alsa:alsa_try_open The device "plughw:2,3" failed to open: -22 (private invalid detail).
0024:warn:alsa:alsa_get_endpoint_ids Unable to open ctl for ALSA device hw:2: -13 (private).
0024:warn:alsa:alsa_get_endpoint_ids Got a failure during card enumeration: -19 (private).
0024:warn:alsa:alsa_get_card_devices Failed to get info for card 2, device 3: -5 (private)
0024:warn:alsa:alsa_open_device Unable to open PCM "private-pcm": -2 (private)
0024:warn:alsa:alsa_probe_num_speakers snd_pcm_hw_params_any failed for "private-pcm": -38 (private).
0024:err:alsa:alsa_get_mix_format Didn't recognize any available ALSA formats
PD2_EVENT {"event":"session_probe","check":"audio_alsa_endpoint","status":"render_seen"}
'''
        events = audio.driver_events(content)
        pairs = {(v['check'], v['status']) for v in events}
        self.assertTrue({('audio_alsa_default', 'busy'), ('audio_alsa_default', 'denied'),
                         ('audio_alsa_plughw', 'invalid'), ('audio_alsa_control', 'denied'),
                         ('audio_alsa_cards', 'missing'), ('audio_alsa_devices', 'other_error'),
                         ('audio_alsa_stream', 'missing'), ('audio_alsa_params', 'unsupported'),
                         ('audio_alsa_endpoint', 'not_observed')} <= pairs)
        for value in events:
            self.assertEqual(safe.validate_event(value), value)
            self.assertIsNone(safe.validate_event(dict(value, detail='private')))
        self.assertNotIn('private', json.dumps(events))
        self.assertNotIn('hw:2', json.dumps(events))

    def test_enumeration_observations_never_infer_missing_cards_from_silence(self):
        events = audio.driver_events(b'pd2-capture-marker\n')
        self.assertTrue(all(e['status'] == 'not_observed' for e in events[1:]))
        for prefix, expected in [('In:', 'capture_only'), ('Out:', 'render_seen')]:
            content = ('pd2-capture-marker\n0024:trace:alsa:construct_device_id Enumerated device: L"' + prefix + ' private"\n').encode()
            self.assertEqual(audio.driver_events(content)[-1]['status'], expected)
        limited = b'pd2-capture-marker\n' + b'x' * audio.DRIVER_LIMIT
        self.assertEqual(audio.driver_events(limited[:audio.DRIVER_LIMIT])[0]['status'], 'limited')
        self.assertEqual(audio.driver_events(b'trace:alsa:fake no marker\n')[0]['status'], 'unavailable')

    def test_alsa_numeric_errors_survive_mapping_and_deduplication(self):
        content = b'pd2-capture-marker\n'
        for code in (-5, -6, -5, -2147483648):
            content += ('0024:warn:alsa:alsa_try_open The device "default" failed to open: %d (private).\n' % code).encode()
        events = [e for e in audio.driver_events(content) if e['check'] == 'audio_alsa_default']
        self.assertEqual({e['alsa_rc'] for e in events}, {-5, -6, -2147483648})
        self.assertEqual(len(events), 3)
        for event in events:
            self.assertEqual(event['status'], 'other_error')
            self.assertEqual(safe.validate_event(event), event)
        for code in ('-2147483649', '-999999999999999999999', '-0'):
            content = ('pd2-capture-marker\n0024:warn:alsa:alsa_try_open The device "default" failed to open: ' + code + ' (private).\n').encode()
            self.assertTrue(all('alsa_rc' not in e for e in audio.driver_events(content)))

    def test_logger_numeric_alsa_codes_are_typed_bounded_and_stage_specific(self):
        value = dict(event='session_probe', phase='launch', check='audio_alsa_default', status='other_error', alsa_rc=-5)
        self.assertEqual(safe.validate_event(value), value)
        for code in (True, False, None, '-5', -5.0, 0, 1, -2147483649):
            self.assertIsNone(safe.validate_event(dict(value, alsa_rc=code)))
        self.assertIsNone(safe.validate_event(dict(value, alsa_rc=-16)))
        self.assertIsNone(safe.validate_event(dict(value, status='attempted')))
        self.assertIsNone(safe.validate_event(dict(value, check='audio_driver', status='loaded')))
        self.assertIsNone(safe.validate_event(dict(value, check='audio_alsa_endpoint', status='render_seen')))

    def test_driver_log_cli_emits_only_closed_observations(self):
        path = self.base / 'audio-driver.log'
        path.write_bytes(b'pd2-capture-marker\n0024:trace:alsa:alsa_try_open devnode: default, flow: 0\n')
        output = io.StringIO()
        self.assertEqual(audio.main(['--driver-log', '--work', str(self.base)], stdout=output), 0)
        self.assertIn('"check":"audio_alsa_default","status":"attempted"', output.getvalue())
        self.assertNotIn(str(self.base), output.getvalue())
        path.write_bytes(b'x' * (audio.DRIVER_LIMIT + 1))
        output = io.StringIO()
        audio.main(['--driver-log', '--work', str(self.base)], stdout=output)
        self.assertIn('"status":"unavailable"', output.getvalue())


if __name__ == '__main__': unittest.main()
