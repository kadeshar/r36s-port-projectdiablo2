"""Aggregate diagnostics never read saves or disclose paths/settings/names."""
import hashlib
import io
import zipfile
import importlib.util
import json
import shutil
import uuid
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'sdcard/ports/projectdiablo2/scripts'

def load(name):
    spec = importlib.util.spec_from_file_location('probe_' + name, SCRIPTS / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

probe = load('session_probe')
logger = load('safe_log')

class SessionProbeTests(unittest.TestCase):
    def setUp(self):
        # As in test_layout: Python 3.14's Windows mkdir(0700) deliberately
        # creates a private directory inaccessible to the confined test token.
        # Fixtures need ordinary inherited workspace permissions, not ACL repair.
        if os.name == 'nt':
            self.root = ROOT / 'tests' / ('.session-probe-' + uuid.uuid4().hex)
            self.root.mkdir(mode=0o755)
            def cleanup():
                assert self.root.parent.resolve() == (ROOT / 'tests').resolve()
                shutil.rmtree(self.root)
            self.addCleanup(cleanup)
        else:
            self.temp = tempfile.TemporaryDirectory(prefix='.session-probe-', dir=ROOT / 'tests')
            self.addCleanup(self.temp.cleanup)
            self.root = Path(self.temp.name).absolute()
        self.port = self.root / 'port'
        self.state = self.root / 'state'
        self.saves = self.port / 'saves'
        self.saves.mkdir(parents=True)
        self.cfg = self.state / 'game/ProjectD2/ProjectDiablo.json'
        self.cfg.parent.mkdir(parents=True)
        self.mapping = self.state / 'wineprefix/dosdevices/s:'
        self.mapping.parent.mkdir(parents=True)
        self.config = {'classic_game_settings': {'other': {'save_path': 'S:\\'}},
                       'pd2_game_settings': {'wasd_movement': True, 'controller_movement': False},
                       'private': 'SECRET-ACCOUNT-DO-NOT-LOG'}
        self.write_config()

    def write_config(self):
        self.cfg.write_text(json.dumps(self.config), encoding='utf-8')

    def test_counts_only_root_regular_saves_without_opening_or_mutation(self):
        for name in ('SECRET-PLAYER.d2s', 'other.D2S', 'stash.d2x'):
            (self.saves / name).write_bytes(b'PRIVATE SAVE BYTES')
        (self.saves / 'nested').mkdir()
        (self.saves / 'nested/third.d2s').write_bytes(b'PRIVATE')
        before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in self.saves.rglob('*') if p.is_file()}
        with mock.patch.object(Path, 'open', side_effect=AssertionError('Save must not be opened')):
            event = probe.save_directory(self.saves)
        self.assertEqual(event['status'], 'ready')
        self.assertEqual(event['count'], 2)
        self.assertIsNotNone(logger.validate_event(event))
        self.assertNotIn('SECRET', json.dumps(event))
        self.assertEqual(before, {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in before})

    def test_probe_config_is_enum_projection_not_raw_values(self):
        for wasd, controller, expected in ((True,False,'emulated'), (False,True,'native'), (True,True,'mixed'), (False,False,'disabled'), (None,False,'unknown')):
            self.config['pd2_game_settings'].update(wasd_movement=wasd, controller_movement=controller)
            self.write_config()
            events = probe.config_events(self.cfg)
            self.assertEqual(events[-1]['status'], expected)
            self.assertEqual(events[1]['status'], 'canonical')
            self.assertTrue(all(logger.validate_event(e) for e in events))
            self.assertNotIn('SECRET', json.dumps(events))
        self.config['classic_game_settings']['other']['save_path'] = 'C:\\PRIVATE-ACCOUNT\\Save'
        self.write_config()
        events = probe.config_events(self.cfg)
        self.assertEqual(events[1]['status'], 'other')
        self.assertNotIn('PRIVATE', json.dumps(events))

    def test_missing_invalid_and_oversized_configs_are_closed(self):
        for content in (b'not json SECRET', b'[]', b'{"classic_game_settings":null}', b'\xff', b' ' * (probe.CONFIG_LIMIT + 1)):
            self.cfg.write_bytes(content)
            events = probe.config_events(self.cfg)
            self.assertEqual(events[0]['status'], 'invalid')
            self.assertTrue(all(logger.validate_event(e) for e in events))
            self.assertNotIn('SECRET', json.dumps(events))
        self.assertEqual(probe.config_events(self.cfg.with_name('absent.json'))[0]['status'], 'missing')

    def test_missing_directory_and_bounded_enumeration(self):
        self.assertEqual(probe.save_directory(self.root / 'absent')['status'], 'missing')
        for i in range(3):
            (self.saves / (str(i) + '.d2s')).touch()
        with mock.patch.object(probe, 'LIMIT', 2):
            event = probe.save_directory(self.saves)
        self.assertEqual(event['status'], 'limit')
        self.assertNotIn('count', event)
        self.assertIsNotNone(logger.validate_event(event))

    def test_mapping_and_symlink_config(self):
        try:
            self.mapping.symlink_to(self.saves, target_is_directory=True)
        except OSError:
            self.skipTest('OS does not permit symlink creation')
        self.assertEqual(probe.mapping(self.mapping, self.saves)['status'], 'ready')
        self.assertEqual(probe.mapping(self.mapping, self.cfg.parent)['status'], 'invalid')
        leaf = self.cfg.with_name('link.json')
        leaf.symlink_to(self.cfg)
        self.assertEqual(probe.config_events(leaf)[0]['status'], 'invalid')

    @unittest.skipUnless(sys.platform.startswith('linux'), 'Linux FIFO')
    def test_nonregular_config_is_rejected_before_open(self):
        # WSL /mnt/c (DrvFS) does not support FIFOs; use native Linux /tmp.
        with tempfile.TemporaryDirectory(prefix='pd2-probe-fifo-') as directory:
            fifo = Path(directory) / 'fifo.json'
            os.mkfifo(fifo)
            self.assertEqual(probe.config_events(fifo)[0]['status'], 'invalid')

    def test_cli_outputs_only_safe_events(self):
        result = subprocess.run([sys.executable, '-B', str(SCRIPTS / 'session_probe.py'), '--port', str(self.port), '--state', str(self.state)], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stderr, '')
        self.assertNotIn(str(self.root), result.stdout)
        self.assertNotIn('SECRET', result.stdout)
        lines = result.stdout.splitlines()
        self.assertEqual(len(lines), 5)
        for line in lines:
            self.assertTrue(line.startswith('PD2_EVENT '))
            self.assertIsNotNone(logger.validate_event(json.loads(line[len('PD2_EVENT '):])))

    def test_stream_and_export_roundtrip_keeps_probes_not_private_fields(self):
        logs = self.root / 'logs'
        logs.mkdir(mode=0o755)
        events = probe.snapshot(self.port, self.state)
        injected = dict(events[0], path='SECRET-PRIVATE-PATH')
        payload = ''.join('PD2_EVENT ' + json.dumps(e) + '\n' for e in [*events, injected])
        self.assertEqual(logger.stream_log(logs, 'probe', io.StringIO(payload)), 0)
        self.assertEqual(logger.export_logs(logs), 0)
        with zipfile.ZipFile(logs / 'diagnostic-export.zip') as archive:
            exported = b''.join(archive.read(name) for name in archive.namelist())
        self.assertNotIn(b'SECRET', exported)
        self.assertNotIn(str(self.root).encode(), exported)
        rows = [json.loads(line) for line in exported.splitlines()]
        self.assertEqual([row for row in rows if row['event'] == 'session_probe'], events)

    def test_closed_schema_rejects_dynamic_fields_and_bad_combinations(self):
        valid = probe.event('saves_directory', 'ready', count=2)
        self.assertIsNotNone(logger.validate_event(valid))
        for value in (True, -1, 4097, 1.5, '2'):
            self.assertIsNone(logger.validate_event(dict(valid, count=value)))
        for invalid in (dict(valid, path='SECRET'), dict(valid, name='SECRET'), dict(valid, status='SECRET'), dict(valid, check='SECRET'), dict(valid, phase='game'), probe.event('saves_directory', 'ready'), probe.event('save_mapping', 'ready', count=1)):
            self.assertIsNone(logger.validate_event(invalid))
        for check, status in (('save_mapping','ready'), ('game_config','invalid'), ('save_path','other'), ('movement_mode','mixed')):
            self.assertIsNotNone(logger.validate_event(probe.event(check, status)))

if __name__ == '__main__':
    unittest.main()
