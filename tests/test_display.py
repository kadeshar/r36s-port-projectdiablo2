"""Static display contract and pinned companion; no Wine/game/ARM execution."""
import configparser
import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import unittest

ROOT = Path(__file__).resolve().parents[1]
PORT = ROOT / 'sdcard/ports/projectdiablo2'


class DisplayTests(unittest.TestCase):
    def test_borderless_downscale_and_mouse_for_both_profiles(self):
        for renderer in ('gdi', 'opengl'):
            cfg = configparser.ConfigParser()
            cfg.read(PORT / ('defaults/ddraw-' + renderer + '.ini'))
            values = cfg['ddraw']
            self.assertEqual(values.getint('width'), 640)
            self.assertEqual(values.getint('height'), 480)
            for key in ('fullscreen', 'windowed', 'maintas', 'adjmouse', 'handlemouse'):
                self.assertTrue(values.getboolean(key), key)
            for key in ('boxing', 'border', 'resizable'):
                self.assertFalse(values.getboolean(key), key)
            self.assertEqual(values['inject_resolution'], '1024x768')
            self.assertEqual(values['renderer'], renderer)
            self.assertEqual(values.getint('savesettings'), 0)

    def test_game_logical_resolution_stays_1024(self):
        data = json.loads((PORT / 'defaults/SGD2FreeResolution.json').read_text())
        cfg = data['SlashGaming Diablo II Free Resolution']
        self.assertEqual(cfg['Main Menu Resolution'], '1024x768')
        self.assertIn('1024x768', cfg['Ingame Resolutions'])

    def test_wine_and_compositor_are_native_not_fake_downscalers(self):
        source = (PORT / 'scripts/weston-session.sh').read_text()
        self.assertIn('CRUSTY_RESOLUTION=640x480 WESTON_HEADLESS_WIDTH=640 WESTON_HEADLESS_HEIGHT=480', source)
        self.assertNotIn('CRUSTY_RESOLUTION=1024x768', source)
        game = (PORT / 'scripts/run-game.sh').read_text()
        desktop = next(line for line in game.splitlines() if '/v Default /t REG_SZ' in line)
        self.assertIn("/d '640x480'", desktop)
        self.assertNotIn('|| true', desktop)

    def test_bundled_companion_is_pinned_x86_and_not_imported_asset(self):
        spec = importlib.util.spec_from_file_location('ddraw_fetch', ROOT / 'tools/fetch_ddraw.py')
        tool = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(tool)
        companion = PORT / 'compat/cnc-ddraw'
        metadata = json.loads((companion / 'manifest.json').read_text())
        dll = (companion / 'ddraw.dll').read_bytes()
        self.assertEqual(metadata['version'], tool.VERSION)
        self.assertEqual(metadata['archive_sha256'], tool.ARCHIVE_SHA256)
        self.assertEqual(len(dll), tool.DLL_SIZE)
        self.assertEqual(metadata['size'], tool.DLL_SIZE)
        self.assertEqual(hashlib.sha256(dll).hexdigest(), tool.DLL_SHA256)
        self.assertEqual(metadata['sha256'], tool.DLL_SHA256)
        pe = struct.unpack_from('<I', dll, 60)[0]
        self.assertEqual(dll[:2], b'MZ')
        self.assertEqual(dll[pe:pe+4], b'PE\0\0')
        self.assertEqual(struct.unpack_from('<H', dll, pe+4)[0], 0x14c)
        # The approved companion is a separate distributable, not replacement data.
        original = PORT / 'gamedata/Diablo II/ProjectD2/ddraw.dll'
        if original.exists():
            self.assertNotEqual(hashlib.sha256(original.read_bytes()).hexdigest(), tool.DLL_SHA256)


if __name__ == '__main__':
    unittest.main()
