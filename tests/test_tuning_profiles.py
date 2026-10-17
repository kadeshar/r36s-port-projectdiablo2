"""Real Bash tests where available; pure checks run everywhere. No Wine/ARM."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'sdcard/ports/projectdiablo2/scripts'
sys.path.insert(0, str(SCRIPTS))
import safe_log
import client_graphics_probe
from unittest.mock import patch

MODES = {'baseline': 'gdi', 'forward512': 'gdi', 'callret': 'gdi',
         'fastflags': 'gdi', 'gl-kms': 'opengl', 'gl-auto': 'opengl'}

class StaticTuningTests(unittest.TestCase):
    def test_packaged_entries_and_helpers(self):
        names = json.loads((ROOT/'release-files.json').read_text())
        for name in ('tuning.sh', 'client_graphics_probe.py'):
            self.assertIn('projectdiablo2/scripts/'+name, names)
        entries = sorted((ROOT/'sdcard/ports').glob('Project Diablo 2 - Test [1-6]*.sh'))
        self.assertEqual(len(entries), 6)
        for entry in entries:
            text=entry.read_text()
            self.assertIn(entry.name, names)
            self.assertIn('PD2_START_MENU=0', text)
            self.assertIn('PD2_BIGBLOCK=1', text)
            self.assertIn('PD2_FPS="${PD2_FPS:-1}"', text)
            self.assertNotIn(b'\r', entry.read_bytes())

    def test_safe_telemetry_closed_schema(self):
        for mode in ['off', *MODES]:
            self.assertIsNotNone(safe_log.validate_event(dict(event='session_probe',phase='launch',check='tuning_profile',status=mode)))
        self.assertIsNone(safe_log.validate_event(dict(event='session_probe',phase='launch',check='tuning_profile',status='private/path')))
        for field, maximum in safe_log.FREQUENCY_RANGES.items():
            for value in [1, maximum]:
                self.assertIsNotNone(safe_log.validate_event({'event':'metrics',field:value}))
            for value in [0,-1,maximum+1,True,'private',1.5]:
                self.assertIsNone(safe_log.validate_event({'event':'metrics',field:value}))
        self.assertIsNotNone(safe_log.validate_event(dict(event='graphics_probe',arch='armhf',role='gles',status='ready')))

    def test_drm_probe_does_not_report_paths(self):
        with patch.object(client_graphics_probe.os, 'stat', side_effect=PermissionError('private')):
            self.assertEqual(client_graphics_probe.drm_access(), 'denied')
        with patch.object(client_graphics_probe.os, 'stat', side_effect=FileNotFoundError('private')):
            self.assertEqual(client_graphics_probe.drm_access(), 'missing')

@unittest.skipUnless(sys.platform.startswith('linux'), 'Requires Linux Bash')
class BashTuningTests(unittest.TestCase):
    def invoke(self, mode, profile, script):
        env={k:v for k,v in os.environ.items() if not k.startswith(('BOX86_', 'PD2_'))}
        env.update(PD2_TUNING=mode, PD2_PERFORMANCE=profile, SDL_VIDEODRIVER='x11', DISPLAY=':0',
                   PD2_CRUSTY_EGL='/real/armhf/egl.so')
        return subprocess.run(['bash','-c','source "$1"; pd2_validate_tuning || exit 23; '+script,'test',str(SCRIPTS/'tuning.sh')],env=env,text=True,capture_output=True,timeout=5)

    def test_effective_environment_and_native_parent_isolation(self):
        code='''PD2_GAME_TUNING_ACTIVE=1; box_env=(env LD_LIBRARY_PATH=/test); pd2_tune_box_env
"${box_env[@]}" python3 -c 'import os,json; print(json.dumps({k:os.getenv(k) for k in ["BOX86_DYNAREC_FORWARD","BOX86_DYNAREC_CALLRET","BOX86_DYNAREC_SAFEFLAGS","SDL_VIDEODRIVER","DISPLAY","SDL_VIDEO_EGL_DRIVER","XDG_SESSION_TYPE"]}))'
[[ $SDL_VIDEODRIVER == x11 ]]
'''
        for mode,profile in MODES.items():
            with self.subTest(mode=mode):
                result=self.invoke(mode,profile,code)
                self.assertEqual(result.returncode,0,result.stderr)
                got=json.loads(result.stdout)
                self.assertEqual(got['DISPLAY'],':0')
                if profile=='gdi':
                    self.assertEqual(got['SDL_VIDEODRIVER'],'x11')
                    self.assertEqual(got['BOX86_DYNAREC_FORWARD'],'512' if mode=='forward512' else '128')
                    self.assertEqual(got['BOX86_DYNAREC_CALLRET'],'1' if mode=='callret' else '0')
                    self.assertEqual(got['BOX86_DYNAREC_SAFEFLAGS'],'0' if mode=='fastflags' else '1')
                else:
                    self.assertEqual(got['SDL_VIDEODRIVER'],'kmsdrm' if mode=='gl-kms' else None)
                    self.assertEqual(got['SDL_VIDEO_EGL_DRIVER'],'/real/armhf/egl.so')
                    self.assertEqual(got['XDG_SESSION_TYPE'],'x11')

    def test_reject_invalid_or_mismatched_profiles(self):
        for mode,profile in [('private','gdi'),('callret','opengl'),('gl-kms','gdi')]:
            result=self.invoke(mode,profile,'echo unsafe')
            self.assertEqual(result.returncode,23)
            self.assertNotIn('unsafe',result.stdout)

    def test_off_does_not_change_box_environment(self):
        result=self.invoke('off','off','box_env=(env LD_LIBRARY_PATH=/test); pd2_tune_box_env; declare -p box_env')
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertNotIn('BOX86_',result.stdout)
        self.assertNotIn('SDL_',result.stdout)

if __name__ == '__main__':
    unittest.main()
