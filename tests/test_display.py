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
    def test_borderless_downscale_and_mouse_for_production_profile(self):
        for renderer in ('gdi',):
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
        self.assertIn('display_res="${PD2_DISPLAY_RESOLUTION:-640x480}"', source)
        self.assertIn('export CRUSTY_RESOLUTION="$display_res"', source)
        self.assertIn('weston_args=(-B drm --drm-device card0 --renderer=gl)', source)
        self.assertNotIn('WESTON_HEADLESS_', source)
        self.assertNotIn('-B headless', source)
        self.assertNotIn('CRUSTY_RESOLUTION=1024x768', source)
        game = (PORT / 'scripts/run-game.sh').read_text()
        desktop = next(line for line in game.splitlines() if 'Explorer\\\\Desktops' in line)
        self.assertIn('"$display_res"', desktop)
        self.assertIn('/desktop="PD2Native,$display_res"', game)
        self.assertNotIn('|| true', desktop)

    def test_bundled_companion_is_pinned_x86_and_not_imported_asset(self):
        layout_spec = importlib.util.spec_from_file_location('pd2_layout', PORT / 'scripts/layout.py')
        layout = importlib.util.module_from_spec(layout_spec)
        layout_spec.loader.exec_module(layout)
        build_spec = importlib.util.spec_from_file_location('cnc_ddraw_build', ROOT / 'tools/cnc_ddraw_build.py')
        cnc_build = importlib.util.module_from_spec(build_spec)
        build_spec.loader.exec_module(cnc_build)
        companion = PORT / 'compat/cnc-ddraw'
        metadata = json.loads((companion / 'manifest.json').read_text())
        dll = (companion / 'ddraw.dll').read_bytes()
        self.assertEqual(metadata['version'], layout.CNC_DDRAW_VERSION)
        self.assertEqual(metadata['upstream']['source_sha256'], cnc_build.SOURCE_SHA)
        self.assertEqual(len(dll), layout.CNC_DDRAW_SIZE)
        self.assertEqual(metadata['size'], layout.CNC_DDRAW_SIZE)
        self.assertEqual(hashlib.sha256(dll).hexdigest(), layout.CNC_DDRAW_SHA256)
        self.assertEqual(metadata['sha256'], layout.CNC_DDRAW_SHA256)
        for name, digest in metadata['build']['inputs_sha256'].items():
            self.assertEqual(hashlib.sha256((ROOT / 'tools' / name).read_bytes()).hexdigest(), digest)
        self.assertEqual(
            hashlib.sha256((companion / 'source.patch').read_bytes()).hexdigest(),
            metadata['build']['source_patch_sha256'],
        )
        pe = struct.unpack_from('<I', dll, 60)[0]
        self.assertEqual(dll[:2], b'MZ')
        self.assertEqual(dll[pe:pe+4], b'PE\0\0')
        self.assertEqual(struct.unpack_from('<H', dll, pe+4)[0], 0x14c)
        # The approved companion is a separate distributable, not replacement data.
        original = PORT / 'gamedata/Diablo II/ProjectD2/ddraw.dll'
        if original.exists():
            self.assertNotEqual(hashlib.sha256(original.read_bytes()).hexdigest(), layout.CNC_DDRAW_SHA256)

    def test_cnc_ddraw_and_present_renderer_share_scaler_header(self):
        cnc_manifest = json.loads((PORT / 'compat/cnc-ddraw/manifest.json').read_text())
        pres_manifest = json.loads((PORT / 'compat/present-renderer/manifest.json').read_text())
        hdr_sha = hashlib.sha256((ROOT / 'tools/pd2_gdi_scaler.h').read_bytes()).hexdigest()
        self.assertEqual(cnc_manifest['build']['inputs_sha256']['pd2_gdi_scaler.h'], hdr_sha)
        self.assertEqual(pres_manifest['build']['inputs_sha256']['pd2_gdi_scaler.h'], hdr_sha)


if __name__ == '__main__':
    unittest.main()
