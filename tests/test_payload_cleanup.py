"""Single production payload: no removed launcher or renderer dependencies."""
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
PORTS = ROOT / 'sdcard/ports'
PORT = PORTS / 'projectdiablo2'


class PayloadCleanupTests(unittest.TestCase):
    def test_only_production_launcher_is_distributed(self):
        self.assertEqual(sorted(p.name for p in PORTS.glob('*.sh')), ['Project Diablo 2.sh'])
        metadata = json.loads((PORT / 'port.json').read_text())
        self.assertEqual(metadata['items'], ['Project Diablo 2.sh', 'projectdiablo2/'])

    def test_release_manifest_has_no_missing_files(self):
        items = json.loads((ROOT / 'release-files.json').read_text())
        self.assertEqual(len(items), len(set(items)))
        for item in items:
            with self.subTest(item=item):
                self.assertTrue((PORTS / item).is_file())

    def test_retired_renderer_and_cpu_variants_are_absent(self):
        for name in ('compat/gles2-renderer', 'compat/box86-a35',
                     'scripts/gles2_renderer.py', 'scripts/box_variant.py',
                     'scripts/tuning.sh', 'defaults/ddraw-opengl.ini'):
            with self.subTest(name=name):
                self.assertFalse((PORT / name).exists())

    def test_launcher_does_not_forward_retired_variant_flags(self):
        text = (PORTS / 'Project Diablo 2.sh').read_text()
        for key in ('PD2_PERFORMANCE', 'PD2_TUNING', 'PD2_BIGBLOCK',
                    'PD2_RENDERER_VARIANT', 'PD2_BOX_VARIANT', 'tuning.sh'):
            with self.subTest(key=key):
                self.assertNotIn(key, text)


if __name__ == '__main__':
    unittest.main()
