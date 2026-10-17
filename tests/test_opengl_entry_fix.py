"""Regression guards for headless OpenGL startup; no ARM hardware implied."""
from pathlib import Path
import unittest

PORTS = Path(__file__).resolve().parents[1] / 'sdcard' / 'ports'

class OpenGLEntryTests(unittest.TestCase):
    def test_headless_entry_explicitly_skips_invisible_menu(self):
        text = (PORTS / 'Project Diablo 2 - Performance OpenGL.sh').read_text()
        self.assertIn('export PD2_START_MENU=0', text)
        self.assertLess(text.index('export PD2_START_MENU=0'), text.index('exec bash'))
        self.assertIn('PD2_FPS="${PD2_FPS:-0}"', text)

    def test_regular_entry_keeps_visible_menu(self):
        text = (PORTS / 'Project Diablo 2.sh').read_text()
        self.assertIn('export PD2_START_MENU="${PD2_START_MENU:-1}"', text)
        text = (PORTS / 'Project Diablo 2 - Performance GDI.sh').read_text()
        self.assertNotIn('PD2_START_MENU=0', text)

if __name__ == '__main__':
    unittest.main()
