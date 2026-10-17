# SPDX-License-Identifier: MIT
"""Static/unit checks; optional native Linux compile and failure-path smoke test.
Run: python -m unittest discover -s tests -p test_graphics_layers.py -v
Build validation: python tools/build_graphics_layers.py --target all
Never interprets host test results as physical R36S hardware success.
"""
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / 'sdcard/ports/projectdiablo2/compat/graphics-probe'


def builder():
    spec = importlib.util.spec_from_file_location('graphics_build', ROOT / 'tools/build_graphics_layers.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class GraphicsLayersTests(unittest.TestCase):
    def test_headerless_and_real_sdl(self):
        text = (ROOT / 'tools/graphics_layers.c').read_text()
        self.assertNotIn('#include <SDL', text)
        self.assertNotIn('#include <GL', text)
        self.assertNotIn('#include <X11', text)
        for value in ('getenv("CRUSTY_LIBSDL")', 'dlopen(path, RTLD_NOW | RTLD_LOCAL)',
                      'libGL.so.1', 'libX11.so.6', 'SDL_GL_SetAttribute(21,4)',
                      'SDL_GL_SetAttribute(17,2)', 'glXMakeCurrent', 'glXChooseVisual'):
            self.assertIn(value, text)
        self.assertIn('-ldl', builder().ARM_COMMAND)
        self.assertNotIn('-lSDL', builder().ARM_COMMAND)

    def test_fixed_bounded_events(self):
        for name in ('graphics_layers.c', 'graphics_layers_win.c'):
            text = (ROOT / 'tools' / name).read_text()
            self.assertIn('\\"event\\":\\"graphics_layer\\"', text)
            self.assertIn('PD2_EVENT ', text)
            self.assertNotIn('GetLastError', text)
            self.assertNotIn('SDL_GetError', text)
            self.assertNotIn('dlerror', text)
            self.assertNotIn('fopen', text)
            self.assertNotIn('system(', text)
        example = {'event': 'graphics_layer', 'schema': 1, 'probe': 'sdl',
                   'stage': 'context', 'status': 'ok', 'backend': 'unknown',
                   'renderer': 'unknown', 'frame': 0, 'code': 0}
        self.assertLess(7 * len('PD2_EVENT ' + json.dumps(example) + '\n'), 4096)

    def test_win32_synthetic_only(self):
        text = (ROOT / 'tools/graphics_layers_win.c').read_text()
        for value in ('LoadLibraryA("ddraw.dll")', 'GetCurrentDirectoryA', '_stricmp(expected,loaded)',
                      'DDPCAPS_8BIT', 'DDBLT_COLORFILL', 'IDirectDraw_RestoreDisplayMode'):
            self.assertIn(value, text)
        self.assertNotIn('RegSetValue', text)
        self.assertNotIn('CreateFile', text)

    def test_manifest_hashes_if_built(self):
        path = DEST / 'manifest.json'
        if not path.exists():
            self.skipTest('build manifest not generated')
        manifest = json.loads(path.read_text())
        self.assertEqual(manifest['license'], 'MIT')
        for name, info in manifest['artifacts'].items():
            data = (DEST / name).read_bytes()
            self.assertEqual(len(data), info['size'])
            self.assertEqual(hashlib.sha256(data).hexdigest(), info['sha256'])
        for name, digest in manifest['inputs_sha256'].items():
            self.assertEqual(hashlib.sha256((ROOT / name).read_bytes()).hexdigest(), digest)

    @unittest.skipUnless(shutil.which('cc'), 'native Linux C compiler unavailable')
    def test_native_compile_failure_paths(self):
        # This test is useful on Linux; compiler target, not host GPU validation.
        import os
        if os.name != 'posix':
            self.skipTest('POSIX dynamic loading required')
        with tempfile.TemporaryDirectory() as folder:
            exe = str(Path(folder) / 'graphics-layers')
            subprocess.run(['cc', '-std=c99', '-Wall', '-Wextra', '-Werror',
                            str(ROOT / 'tools/graphics_layers.c'), '-ldl', '-o', exe], check=True)
            env = dict(os.environ, CRUSTY_LIBSDL='/nonexistent/pd2-test-library')
            for args, code in [([], 20), (['--mode', 'sdl'], 1), (['--mode', 'invalid'], 20)]:
                result = subprocess.run([exe] + args, env=env, capture_output=True, text=True, timeout=3)
                self.assertEqual(result.returncode, code)
                for line in result.stdout.splitlines():
                    self.assertTrue(line.startswith('PD2_EVENT '))
                    item = json.loads(line[len('PD2_EVENT '):])
                    self.assertEqual(item['event'], 'graphics_layer')
                    self.assertIn(item['renderer'], ('gpu', 'software', 'unknown'))
                    self.assertLessEqual(item['frame'], 3)
                    self.assertLessEqual(item['code'], 20)


if __name__ == '__main__':
    unittest.main()
