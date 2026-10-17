"""GPU variant integration using synthetic Wine; never real game/hardware."""
import json
import os
from pathlib import Path
import subprocess
import signal
import time
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT/'sdcard/ports/projectdiablo2/scripts'
sys.path.insert(0,str(SCRIPTS))
import safe_log

class Schema(unittest.TestCase):
 def test_renderer_and_scope_closed(self):
  e=dict(event='renderer_gl2',stage='frame',status='ready',code=0,gl_major=2,gl_minor=1,bpp=8,width=800,height=600,render_width=640,render_height=480)
  self.assertIsNotNone(safe_log.validate_event(e))
  for bad in [dict(e,code=1),dict(e,path='secret'),dict(e,width=True),dict(e,stage='secret')]:
   self.assertIsNone(safe_log.validate_event(bad))
  for scope in ('verified_subset','partial','unavailable'):
   self.assertIsNotNone(safe_log.validate_event(dict(event='metrics',sample_monotonic_ms=1,game_scope=scope)))
  self.assertIsNone(safe_log.validate_event(dict(event='metrics',sample_monotonic_ms=1,game_scope='unavailable',game_cpu_pct_x100=0)))
 def test_audio_numeric_schema(self):
  e={k:0 for k in safe_log.AUDIO_PCM_FIELDS}
  e.update(event='audio_pcm',schema=1,source=1,stream=1,rate_hz=48000,channels=2)
  self.assertIsNotNone(safe_log.validate_event(e))
  for bad in [dict(e,source=0),dict(e,source=True),dict(e,rate_hz=768001),dict(e,write_frames=10**15+1),dict(e,raw='secret')]:
   self.assertIsNone(safe_log.validate_event(bad))

@unittest.skipUnless(sys.platform.startswith('linux'),'Linux process groups required')
class Integration(unittest.TestCase):
 def setUp(self):
  # Compose existing fixture without inheriting/re-running its unrelated tests.
  import test_shell
  self.f=test_shell.ShellTests(methodName='runTest');self.f.setUp()
  self.addCleanup(self.f.tearDown)
  self.f.env.update(PD2_RENDERER_VARIANT='gles2',PD2_BOX_VARIANT='stock',PD2_TUNING='gl-kms',PD2_PERFORMANCE='opengl',PD2_PROFILE='opengl')
  self.record=self.f.base/'gpu-helpers.jsonl'
  shared='''import json,os,pathlib,sys,time
with open(os.environ['GPU_RECORD'],'a') as f:f.write(json.dumps({'helper':pathlib.Path(__file__).name,'args':sys.argv[1:],'libs':os.environ.get('PD2_NATIVE_LIBS',''),'time':time.monotonic_ns(),'pid':os.getpid(),'pgid':os.getpgrp()})+'\\n')
'''
  (self.f.port/'scripts/gles2_renderer.py').write_text(shared+'''if '--watch' in sys.argv:
 time.sleep(120)
if '--result' in sys.argv:raise SystemExit(int(os.environ.get('GPU_RESULT','0')))
raise SystemExit(int(os.environ.get('GPU_PREPARE','0')))
''')
  (self.f.port/'scripts/presentation_watch.py').write_text(shared+'time.sleep(120)\n')
  (self.f.port/'scripts/audio_metrics.py').write_text(shared+'''if sys.argv[1]=='prepare':raise SystemExit(int(os.environ.get('GPU_AUDIO_PREPARE','0')))
if sys.argv[1]=='run':
 args=sys.argv[3:]
 os.execvp(args[0],args)
raise SystemExit(1)
''')
  (self.f.port/'scripts/metrics.py').write_text(shared+'time.sleep(120)\n')
  self.f.env['GPU_RECORD']=str(self.record)
  box=self.f.base/'bin/box'
  box.write_text(box.read_text().replace("call['dynarec']=", "call['gl']={k:os.getenv(k) for k in ('LIBGL_ES','LIBGL_GL','LIBGL_VABGRA','LIBGL_NOERROR','LIBGL_NOTEST','LIBGL_NOPSA','LIBGL_VERSION','LIBGL_SHRINK')}\ncall['dynarec']="))
 def helpers(self):return [json.loads(l) for l in self.record.read_text().splitlines()]
 def execute(self,extra=None):
  r,_=self.f.execute(extra)
  return r
 def test_gpu_selects_no_hud_and_authenticates_scope(self):
  r=self.execute({'MOCK_GAME_DELAY':'.4'});self.assertEqual(r.returncode,0,r.stdout)
  h=self.helpers()
  renderer=[e for e in h if e['helper']=='gles2_renderer.py']
  self.assertTrue(any('--watch' in e['args'] for e in renderer))
  self.assertTrue(any('--result' in e['args'] for e in renderer))
  self.assertTrue(any('--port' in e['args'] for e in renderer))
  audio=[e for e in h if e['helper']=='audio_metrics.py']
  self.assertEqual([e['args'][0] for e in audio],['prepare','run'])
  game=[e for e in self.f.records() if any(a.endswith('Game.exe') for a in e['args'])][0]
  self.assertTrue(game['libraries'].startswith(str(self.f.work/'.alsa-audio-metrics')))
  scope=[e for e in h if e['helper']=='metrics.py' and '--wine-prefix' in e['args']]
  self.assertEqual(len(scope),1);self.assertIn('--wine-exe',scope[0]['args']);self.assertIn('--uid',scope[0]['args'])
  for e in h:
   if '--watch' in e['args'] or e['helper'] in ('presentation_watch.py','metrics.py'):self.f.assert_dead(e['pid'])
 def test_gl2_environment_rejects_inherited_capability_spoofing(self):
  r=self.execute({'LIBGL_VERSION':'1.1 private','LIBGL_SHRINK':'11','LIBGL_NOERROR':'1','LIBGL_NOTEST':'1','LIBGL_VABGRA':'1'})
  self.assertEqual(r.returncode,0,r.stdout)
  game=[e for e in self.f.records() if any(a.endswith('Game.exe') for a in e['args'])][0]
  self.assertEqual(game['gl'],dict(LIBGL_ES='2',LIBGL_GL='21',LIBGL_VABGRA='0',LIBGL_NOERROR='0',LIBGL_NOTEST='0',LIBGL_NOPSA='1',LIBGL_VERSION=None,LIBGL_SHRINK=None))
 def test_failed_backend_overrides_masked_success(self):
  r=self.execute({'GPU_RESULT':'86','MOCK_GAME_DELAY':'.2'})
  self.assertEqual(r.returncode,86,r.stdout)
  self.assertIn('gl_context_failed',r.stdout)
 def test_no_presentation_not_silent_success(self):
  r=self.execute({'GPU_RESULT':'1'});self.assertEqual(r.returncode,1,r.stdout)
 def test_renderer_auth_failure_prevents_game(self):
  r=self.execute({'GPU_PREPARE':'1'});self.assertNotEqual(r.returncode,0)
  self.assertFalse(any(any(a.endswith('Game.exe') for a in e['args']) for e in self.f.records()))
 def test_audio_observer_unavailable_keeps_stock(self):
  r=self.execute({'GPU_AUDIO_PREPARE':'1'});self.assertEqual(r.returncode,0,r.stdout)
  self.assertFalse(any(e['helper']=='audio_metrics.py' and e['args'][0]=='run' for e in self.helpers()))
 def test_cancellation_stops_owned_watchers_and_game_group(self):
  env=dict(self.f.env,MOCK_GAME_SLEEP='1')
  process=subprocess.Popen(['bash',str(SCRIPTS/'run-game.sh')],env=env,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
  try:
   deadline=time.monotonic()+8
   while time.monotonic()<deadline:
    if self.f.calls.exists() and any(any(a.endswith('Game.exe') for a in e['args']) for e in self.f.records()):break
    time.sleep(.05)
   else:self.fail('Synthetic game did not launch')
   process.send_signal(signal.SIGTERM);out,_=process.communicate(timeout=15)
   self.assertEqual(process.returncode,143,out)
   for e in self.helpers():
    if '--watch' in e['args'] or e['helper'] in ('presentation_watch.py','metrics.py'):self.f.assert_dead(e['pid'])
   for e in self.f.records():
    if any(a.endswith('Game.exe') for a in e['args']):self.f.assert_dead(e['pid'])
  finally:
   if process.poll() is None:process.kill();process.communicate()
 def test_incompatible_modes_fail_before_setup(self):
  for extra in ({'PD2_FPS':'1'},{'PD2_TUNING':'fastflags'},{'PD2_BOX_VARIANT':'private/path'},{'PD2_DIAGNOSTIC':'present'}):
   r=self.execute(extra);self.assertNotEqual(r.returncode,0)

if __name__=='__main__':unittest.main()
