import json
import os
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch, MagicMock

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'sdcard/ports/projectdiablo2/scripts'))

import audio_volume


class AudioVolumeTests(unittest.TestCase):
    def setUp(self):
        audio_volume._cached_controls = None

    def tearDown(self):
        audio_volume._cached_controls = None

    @patch('subprocess.run')
    def test_get_system_volume_batocera_cli(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout='75\n')
        vol = audio_volume.get_system_volume()
        self.assertEqual(vol, 75)
        self.assertEqual(mock_run.call_args[0][0], ['batocera-audio', 'getSystemVolume'])

    @patch('subprocess.run')
    def test_get_system_volume_batocera_conf(self, mock_run):
        mock_run.side_effect = FileNotFoundError()
        with tempfile.TemporaryDirectory() as td:
            conf = Path(td) / 'batocera.conf'
            conf.write_text('audio.device=auto\naudio.volume=60\n')
            with patch('audio_volume.Path', side_effect=lambda p: conf if 'batocera.conf' in str(p) else Path(p)):
                vol = audio_volume.get_system_volume()
                self.assertEqual(vol, 60)

    @patch('subprocess.run')
    def test_get_system_volume_missing_returns_none(self, mock_run):
        mock_run.side_effect = FileNotFoundError()
        with patch('pathlib.Path.is_file', return_value=False):
            vol = audio_volume.get_system_volume()
            self.assertIsNone(vol)

    @patch('subprocess.run')
    def test_get_playback_controls_scontrols(self, mock_run):
        # Default card returns Headphone and Line Out
        scontrols_output = (
            "Simple mixer control 'Headphone',0\n"
            "Simple mixer control 'Line Out',0\n"
            "Simple mixer control 'Mic',0\n"
            "Simple mixer control 'Capture',0\n"
        )
        def run_side_effect(cmd, **kwargs):
            if cmd == ['amixer', 'scontrols']:
                return MagicMock(returncode=0, stdout=scontrols_output)
            return MagicMock(returncode=1, stdout='')

        mock_run.side_effect = run_side_effect
        controls = audio_volume.get_playback_controls(force_refresh=True)
        # Should contain Headphone and Line Out, NOT Mic or Capture
        control_names = [c[1] for c in controls]
        self.assertIn('Headphone', control_names)
        self.assertIn('Line Out', control_names)
        self.assertNotIn('Mic', control_names)
        self.assertNotIn('Capture', control_names)

    @patch('subprocess.run')
    def test_set_volume_pct_calls_amixer_and_batocera(self, mock_run):
        audio_volume._cached_controls = [([], 'Line Out', False), ([], 'Headphone', False)]
        mock_run.return_value = MagicMock(returncode=0)

        res = audio_volume.set_volume_pct(65)
        self.assertTrue(res)

        calls = [c[0][0] for c in mock_run.call_args_list]
        self.assertIn(['amixer', 'sset', 'Line Out', '65%', 'unmute'], calls)
        self.assertIn(['amixer', 'sset', 'Headphone', '65%', 'unmute'], calls)
        self.assertIn(['batocera-audio', 'setSystemVolume', '65'], calls)

    @patch('subprocess.run')
    def test_adjust_volume_calls_amixer_and_batocera(self, mock_run):
        audio_volume._cached_controls = [([], 'Line Out', False), ([], 'Headphone', False)]
        def run_side_effect(cmd, **kwargs):
            if cmd == ['batocera-audio', 'getSystemVolume']:
                return MagicMock(returncode=0, stdout='70\n')
            return MagicMock(returncode=0)

        mock_run.side_effect = run_side_effect
        res = audio_volume.adjust_volume(5)
        self.assertTrue(res)

        calls = [c[0][0] for c in mock_run.call_args_list]
        self.assertIn(['amixer', 'sset', 'Line Out', '5%+', 'unmute'], calls)
        self.assertIn(['amixer', 'sset', 'Headphone', '5%+', 'unmute'], calls)
        self.assertIn(['batocera-audio', 'setSystemVolume', '75'], calls)

    @patch('audio_volume.get_system_volume')
    @patch('audio_volume.set_volume_pct')
    def test_init_volume_synced(self, mock_set, mock_get):
        mock_get.return_value = 80
        res = audio_volume.init_volume()
        self.assertTrue(res)
        mock_set.assert_called_once_with(80)

    @patch('audio_volume.get_system_volume')
    @patch('audio_volume.set_volume_pct')
    def test_init_volume_preserved_when_no_system_volume(self, mock_set, mock_get):
        mock_get.return_value = None
        res = audio_volume.init_volume()
        self.assertFalse(res)
        mock_set.assert_not_called()

    def test_find_volume_devices(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ev0 = root / 'event0/device/capabilities'
            ev0.mkdir(parents=True)
            # EV_KEY = 1 (bit 1 = 0x2)
            (ev0 / 'ev').write_text('2\n')
            # KEY_VOLUMEUP = 115, KEY_VOLUMEDOWN = 114
            word_bits = struct.calcsize('@L') * 8
            words_count = (115 // word_bits) + 1
            words = [0] * words_count
            for bit in (114, 115):
                w_idx = bit // word_bits
                b_idx = bit % word_bits
                words[w_idx] |= (1 << b_idx)
            key_text = ' '.join(f'{w:x}' for w in reversed(words))
            (ev0 / 'key').write_text(f'{key_text}\n')

            devs = audio_volume.find_volume_devices(root=root)
            self.assertEqual(devs, ['/dev/input/event0'])

            # Test exclude_path
            devs_ex = audio_volume.find_volume_devices(root=root, exclude_path='/dev/input/event0')
            self.assertEqual(devs_ex, [])

    @patch('audio_volume.get_system_volume', return_value=60)
    @patch('audio_volume.get_playback_controls', return_value=[(['-c', '0'], 'Line Out', False)])
    @patch('subprocess.run')
    def test_save_and_restore_volume_state(self, mock_run, mock_get_controls, mock_get_vol):
        # mock amixer sget output
        mock_run.return_value = MagicMock(returncode=0, stdout="Simple mixer control 'Line Out',0\n  Front Left: Playback 25 [80%] [0.00dB] [on]\n")
        with tempfile.TemporaryDirectory() as td:
            save_path = Path(td) / 'audio_state.json'
            # Save
            res = audio_volume.save_volume_state(save_path)
            self.assertTrue(res)
            self.assertTrue(save_path.is_file())
            content = json.loads(save_path.read_text(encoding='utf-8'))
            self.assertEqual(content['system_volume'], 60)
            self.assertEqual(len(content['controls']), 1)
            self.assertEqual(content['controls'][0]['control'], 'Line Out')
            self.assertEqual(content['controls'][0]['value'], '80%')

            # Restore
            mock_run.reset_mock()
            mock_run.return_value = MagicMock(returncode=0)
            res_restore = audio_volume.restore_volume_state(save_path)
            self.assertTrue(res_restore)
            # File should be removed upon successful restore
            self.assertFalse(save_path.exists())
            calls = [c[0][0] for c in mock_run.call_args_list]
            self.assertIn(['batocera-audio', 'setSystemVolume', '60'], calls)
            self.assertIn(['amixer', '-c', '0', 'sset', 'Line Out', '80%', 'unmute'], calls)


if __name__ == '__main__':
    unittest.main()
