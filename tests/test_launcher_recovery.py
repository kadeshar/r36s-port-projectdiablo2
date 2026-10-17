"""Cross-platform checks for the 0.1.13 native/audio recovery path."""
import json
from pathlib import Path
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PORTS = ROOT / 'sdcard/ports'
PORT = PORTS / 'projectdiablo2'


class RecoveryTests(unittest.TestCase):
    def test_controller_implementation_matches_013(self):
        with zipfile.ZipFile(ROOT / 'dist/projectdiablo2-port-update-0.1.13-rollback.zip') as old:
            for relative in ('projectdiablo2/scripts/xbox_mapper.py',
                             'projectdiablo2/scripts/winebus_config.py',
                             'projectdiablo2/compat/xinput-probe/xinput-probe.exe'):
                with self.subTest(relative=relative):
                    self.assertEqual((PORTS / relative).read_bytes(), old.read(relative))

    def test_default_is_native_without_fps_and_restorable_audio_enabled(self):
        source = (PORTS / 'Project Diablo 2.sh').read_text(encoding='utf-8')
        self.assertIn('PD2_INPUT_MODE="${PD2_INPUT_MODE:-native}"', source)
        self.assertIn('PD2_FPS="${PD2_FPS:-0}"', source)
        self.assertIn('PD2_AUDIO_TEST="${PD2_AUDIO_TEST:-1}"', source)
        self.assertIn('PD2_AUDIO_TEST="$PD2_AUDIO_TEST"', source)
        self.assertIn('PD2_FPS="$PD2_FPS"', source)
        self.assertIn('PD2_GAME_RESOLUTION="$PD2_GAME_RESOLUTION"', source)

    def test_audio_experiment_is_gated_and_restorable(self):
        source = (PORT / 'scripts/run-game.sh').read_text(encoding='utf-8')
        start = source.index('if [[ "$audio_test" == 1 ]]; then')
        end = source.index('if [[ "$input_mode" == native ]]; then', start)
        block = source[start:end]
        self.assertIn('audio_test="${PD2_AUDIO_TEST:-1}"', source)
        for flag in ('--prepare-export', '--snapshot', '--route', 'ALSA_CONFIG_PATH='):
            self.assertIn(flag, block)
        self.assertLess(block.index('--snapshot'), block.index('/v Audio'))
        self.assertLess(block.index('/v Audio'), block.index('stop_wine'))
        for forbidden in ('PULSE_SERVER=', 'PIPEWIRE_RUNTIME_DIR=', 'amixer '):
            self.assertNotIn(forbidden, source)
        self.assertIn('audio_result.py" --prepare', source)
        self.assertIn('pd2-audio-probe.exe', source)
        self.assertEqual(source.count('/v Audio /t REG_SZ /d alsa /f'), 2)
        self.assertIn('SDL_AUDIODRIVER=alsa', source)
        self.assertIn('pd2-audio-restore.reg', source)
        self.assertIn('--validate', source)
        self.assertIn('--retire', source)

    def test_menu_is_packaged_and_old_audio_entry_cannot_run_audio(self):
        files = json.loads((ROOT / 'release-files.json').read_text(encoding='utf-8'))
        for relative in ('Project Diablo 2.sh', 'projectdiablo2/scripts/start_menu.py'):
            self.assertIn(relative, files)
        expected = {p for p in files if '/' not in p and p.endswith('.sh')}
        self.assertIn('Project Diablo 2.sh', expected)
        self.assertEqual(len([p for p in expected if ' - Diag ' in p]), 6)
        self.assertEqual({p.name for p in PORTS.glob('*.sh')}, expected)
        self.assertEqual({p for p in files if '/' not in p and p.endswith('.sh')}, expected)
        metadata = json.loads((PORT / 'port.json').read_text(encoding='utf-8'))
        self.assertEqual({p for p in metadata['items'] if p.endswith('.sh')}, expected)



if __name__ == '__main__':
    unittest.main()
