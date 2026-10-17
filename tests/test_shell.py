"""Linux Bash integration on synthetic Wine/Box86/controller processes only."""
import json, os, pathlib, signal, subprocess, sys, tempfile, time, unittest
ROOT=pathlib.Path(__file__).resolve().parents[1]
SCRIPTS=ROOT/'sdcard/ports/projectdiablo2/scripts'
@unittest.skipUnless(sys.platform.startswith('linux'), 'Native Linux needed for process groups')
class ShellTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory(prefix='.shell-');self.base=pathlib.Path(self.temp.name)
  self.port=self.base/'port with spaces';self.state=self.base/'state';self.prefix=self.state/'wineprefix';self.work=self.state/'game'
  for p in [self.port/'scripts',self.port/'defaults',self.port/'runtime',self.work/'ProjectD2',self.prefix/'dosdevices',self.prefix/'drive_c',self.port/'compat/xinput-probe',self.base/'run',self.base/'bin']:
   p.mkdir(parents=True,exist_ok=True)
  self.mock_proc=self.base/'mock-proc';self.mock_proc.mkdir()
  (self.mock_proc/'cards').write_bytes(b' 2 [rk817          ]: rk817-codec - rk817-codec\n')
  (self.mock_proc/'pcm').write_bytes(b'02-03: rk817 : rk817 codec : playback 1 : capture 1\n')
  self.mock_snd=self.base/'mock-snd';self.mock_snd.mkdir()
  (self.base/'mock-alsa.conf').write_bytes(b'# synthetic system ALSA fixture\n')
  (self.prefix/'.initialized').touch()
  (self.port/'scripts/layout.py').write_text('import sys\n# Synthetic config sync is covered separately by test_layout.\nraise SystemExit(0)\n')
  (self.port/'scripts/session_probe.py').write_text((SCRIPTS/'session_probe.py').read_text())
  (self.port/'scripts/audio_compat.py').write_text('''import json,os,pathlib,sys
failed=bool(os.environ.get('MOCK_COMPAT_FAIL'))
if not failed:
 directory=pathlib.Path(os.environ['PD2_WORK'])/'.alsa-legacy-armhf'
 directory.mkdir(exist_ok=True)
 (directory/'libasound.so.2').write_bytes(b'synthetic-only')
print('PD2_EVENT '+json.dumps(dict(event='session_probe',phase='launch',check='audio_library',status='unavailable' if failed else 'legacy_armhf'),separators=(',',':')))
raise SystemExit(1 if failed else 0)
''')
  (self.port/'scripts/audio_native.py').write_text('''import json,os,pathlib,time
with open(pathlib.Path(os.environ['PD2_RUN'])/'native-calls.jsonl','a') as f:
 f.write(json.dumps({'private':bool(os.environ.get('ALSA_CONFIG_PATH')),'time':time.monotonic_ns(),'libraries':os.environ.get('PD2_NATIVE_LIBS','')})+'\\n')
print('PD2_EVENT '+json.dumps(dict(event='session_probe',phase='launch',check='audio_native_armhf',status='ready'),separators=(',',':')))
code=int(os.environ.get('MOCK_NATIVE_RC','0'))
v=dict(event='session_probe',phase='launch',check='audio_native_default',status='ready' if code==0 else 'other_error')
if code:v['alsa_rc']=code
print('PD2_EVENT '+json.dumps(v,separators=(',',':')))
''')
  for helper in ('tuning.sh','winebus_config.py','xinput_result.py','audio_config.py','audio_result.py','fps_counter.py','fps_renderer.py'):
   code=(SCRIPTS/helper).read_text()
   if helper=='audio_config.py':
    route_call=('route(args.run, proc_root=Path(%r), snd_root=Path(%r), alsa_base=Path(%r), device_status=lambda p: "ready").items()' % (str(self.mock_proc),str(self.mock_snd),str(self.base/'mock-alsa.conf')))
    code=code.replace('route(args.run).items()', route_call)
   (self.port/'scripts'/helper).write_text(code)
  (self.port/'scripts/client_graphics_probe.py').write_text('# synthetic-only probe\n')
  (self.port/'scripts/metrics.py').write_text('# synthetic-only metrics\n')
  (self.base/'run').chmod(0o700)
  for name in ('audio-probe','fps-hotkey'):
   folder=self.port/'compat'/name;folder.mkdir(parents=True)
   (folder/(name+'.exe')).write_bytes((SCRIPTS.parent/'compat'/name/(name+'.exe')).read_bytes())
  (self.port/'compat/xinput-probe/xinput-probe.exe').write_bytes((SCRIPTS.parent/'compat/xinput-probe/xinput-probe.exe').read_bytes())
  hud=self.port/'compat/fps-renderer/ddraw.dll';hud.parent.mkdir(parents=True)
  hud.write_bytes((SCRIPTS.parent/'compat/fps-renderer/ddraw.dll').read_bytes())
  original=self.port/'compat/cnc-ddraw/ddraw.dll';original.parent.mkdir(parents=True)
  original.write_bytes(b'synthetic upstream renderer')
  (self.work/'ProjectD2/ddraw.dll').symlink_to(original)
  (self.port/'defaults/controls.gptk').write_text('a = mouse_left\n')
  (self.port/'scripts/controller_probe.py').write_text('''import json,os,pathlib,sys,time
with open(os.environ['MOCK_PROBE'],'a') as f:f.write(json.dumps({'args':sys.argv[1:],'time':time.monotonic_ns()})+'\\n')
if '--wait' in sys.argv:
 print('PD2_EVENT '+json.dumps(dict(event='session_probe',phase='launch',check='virtual_gamepad',status='denied' if os.environ.get('MOCK_PROBE_FAIL') else 'ready')))
 raise SystemExit(1 if os.environ.get('MOCK_PROBE_FAIL') else 0)
''')
  self.calls=self.base/'calls.jsonl'
  self.executable(self.base/'bin/box', '''#!/usr/bin/python3
import json,os,pathlib,sys,time
args=sys.argv[1:]
release=pathlib.Path(os.environ['MOCK_CALLS']).parent/'audio-stderr-release'
if pathlib.Path(args[0]).name=='wineserver' and '-k' in args:
 release.touch()
call={'args':args,'pid':os.getpid(),'pgid':os.getpgrp(),'time':time.monotonic_ns(),'libraries':os.environ.get('LD_LIBRARY_PATH','')}
call['dynarec']={name:os.environ.get(name) for name in ('BOX86_DYNAREC','BOX86_DYNAREC_BIGBLOCK','BOX86_DYNAREC_SAFEFLAGS','BOX86_DYNAREC_STRONGMEM')}
call['tuning']={name:os.environ.get(name) for name in ('BOX86_DYNAREC_FORWARD','BOX86_DYNAREC_CALLRET','SDL_VIDEODRIVER','SDL_VIDEO_EGL_DRIVER','XDG_SESSION_TYPE')}
if len(args)>2 and args[1:3]==['reg.exe','import']:
 kind='audio' if args[-1].endswith('pd2-audio-restore.reg') else 'winebus'
 call['restore_kind']=kind
 call['restore']=(pathlib.Path(os.environ['WINEPREFIX'])/('drive_c/pd2-'+kind+'-restore.reg')).read_text(encoding='utf-16')
if pathlib.Path(args[0]).name=='wineserver' and '-k' in args and os.environ.get('MOCK_STOP_NOSERVER'): raise SystemExit(1)
if pathlib.Path(args[0]).name=='wineserver' and '-k' in args and os.environ.get('MOCK_STOP_FAIL'): raise SystemExit(2)
if pathlib.Path(args[0]).name=='wineserver' and '-w' in args:
 record=pathlib.Path(os.environ['MOCK_CALLS']).parent/'fps.json'
 if record.exists():
  pid=json.loads(record.read_text())['pid']; status=pathlib.Path('/proc')/str(pid)/'stat'
  call['fps_alive']=status.exists() and status.read_text().split()[2]!='Z'
with open(os.environ['MOCK_CALLS'],'a') as f:f.write(json.dumps(call)+'\\n')
prog=pathlib.Path(args[0]).name
if prog=='wine' and len(args)>1:
 if args[1]=='reg.exe' and '640x480' in args and os.environ.get('MOCK_DESKTOP_FAIL'):raise SystemExit(1)
 if args[1]=='reg.exe' and 'Save Path' in args and os.environ.get('MOCK_SAVE_PATH_FAIL'):raise SystemExit(1)
 if args[1:3]==['reg.exe','import'] and os.environ.get('MOCK_RESTORE_FAIL'):raise SystemExit(1)
 if args[1]=='reg.exe' and 'DisableInput' in args and os.environ.get('MOCK_FLAG_FAIL'):raise SystemExit(1)
 if args[1:3]==['reg.exe','export'] and os.environ.get('MOCK_EXPORT_FAIL'):raise SystemExit(1)
 if args[1:3]==['reg.exe','export']:
  exported='Windows Registry Editor Version 5.00\\r\\n\\r\\n[HKEY_LOCAL_MACHINE\\\\System\\\\CurrentControlSet\\\\Services\\\\winebus]\\r\\n"Enable SDL"=dword:00000002\\r\\n"DisableInput"=dword:00000001\\r\\n"OtherValue"="keep"\\r\\n'
  name='pd2-winebus-export.reg'
  if args[3].startswith('HKCU'):
   name='pd2-audio-export.reg'
   root='HKEY_CURRENT_USER'+chr(92)+'Software'+chr(92)+'Wine'
   exported='Windows Registry Editor Version 5.00\\r\\n\\r\\n['+root+']\\r\\n['+root+chr(92)+'Drivers]\\r\\n"Audio"="pulse"\\r\\n"OtherAudio"="keep"\\r\\n'
  (pathlib.Path(os.environ['WINEPREFIX'])/('drive_c/'+name)).write_bytes(b'\\xff\\xfe'+exported.encode('utf-16-le'))
 if any(a.endswith('pd2-xinput-probe.exe') for a in args[1:]):
  missing=bool(os.environ.get('MOCK_XINPUT_MISSING'))
  report=dict(schema_version=1,api='ready',devices='missing' if missing else 'ready',buttons='unavailable' if missing else 'changed',axes='unavailable' if missing else 'changed')
  (pathlib.Path(os.environ['PD2_WORK'])/'ProjectD2/pd2-xinput-result.json').write_text(json.dumps(report))
 if any(a.endswith('pd2-audio-probe.exe') for a in args[1:]):
  state=os.environ.get('MOCK_AUDIO_OPEN','ready')
  report=dict(schema_version=1,devices=1 if state=='ready' else 0,open=state,write='ready' if state=='ready' else 'not_run',tone='completed' if state=='ready' else 'not_run',directsound=state)
  (pathlib.Path(os.environ['PD2_WORK'])/'ProjectD2/pd2-audio-result.json').write_text(json.dumps(report))
  if os.environ.get('MOCK_AUDIO_DRIVER_LOG'):
   sys.stderr.write(os.environ['MOCK_AUDIO_DRIVER_LOG'])
  if os.environ.get('MOCK_AUDIO_LATE_STDERR') or os.environ.get('MOCK_AUDIO_HELD_STDERR'):
   release.unlink(missing_ok=True)
   pid=os.fork()
   if pid==0:
    os.close(1)
    if os.environ.get('MOCK_AUDIO_HELD_STDERR'):
     time.sleep(10)
     os._exit(0)
    for _ in range(500):
     if release.exists():
      os.write(2,b'trace:alsa:late_driver_init\\n')
      os._exit(0)
     time.sleep(.02)
    os._exit(1)
   (release.parent/'audio-stderr-child').write_text(str(pid))
  if os.environ.get('MOCK_AUDIO_FLOOD'):
   sys.stderr.write('x'*400000)
 if any(a.endswith('pd2-fps-hotkey.exe') for a in args[1:]) and os.environ.get('MOCK_FPS_SLEEP'):
  (pathlib.Path(os.environ['MOCK_CALLS']).parent/'fps.json').write_text(json.dumps(call))
  time.sleep(120)
 if any(a.endswith('Game.exe') for a in args[1:]):
  if os.environ.get('MOCK_GAME_DELAY'):time.sleep(float(os.environ['MOCK_GAME_DELAY']))
  if os.environ.get('MOCK_GAME_SLEEP'):time.sleep(120)
  print('secret-CD-key-ABCD-EFGH private account player-name')
  raise SystemExit(int(os.environ.get('MOCK_GAME_RC','0')))
 if args[1].endswith('vc_redist.x86.exe'):
  p=pathlib.Path(os.environ['WINEPREFIX'])/'drive_c/windows/system32';p.mkdir(parents=True,exist_ok=True)
  (p/'msvcp140.dll').touch();(p/'vcruntime140.dll').touch()
raise SystemExit(0)
''')
  self.executable(self.base/'bin/mapper', '''#!/usr/bin/python3
import json,os,signal,sys,time
with open(os.environ['MOCK_NAVIGATOR'] if any(a.endswith('controls-test.gptk') for a in sys.argv) else os.environ['MOCK_MAPPER'],'w') as f:json.dump({'args':sys.argv[1:],'pid':os.getpid(),'pgid':os.getpgrp(),'time':time.monotonic_ns(),'textinput':os.environ.get('TEXTINPUTINTERACTIVE')},f)
if os.environ.get('MOCK_MAPPER_EXIT'):raise SystemExit(1)
if os.environ.get('MOCK_IGNORE_TERM'):signal.signal(signal.SIGTERM,signal.SIG_IGN)
while True:time.sleep(.1)
''')
  self.executable(self.base/'bin/timeout', '''#!/usr/bin/python3
import os,sys
args=sys.argv[1:]
while args and args[0].startswith('--'):args.pop(0)
seconds=args.pop(0)
if seconds=='60' and os.environ.get('MOCK_SERVER_TIMEOUT'):raise SystemExit(124)
if seconds=='15' and os.environ.get('MOCK_GRAPHICS_TIMEOUT'):raise SystemExit(124)
if seconds=='30' and os.environ.get('MOCK_QUIESCE_TIMEOUT'):raise SystemExit(124)
os.execvp(args[0],args)
''')
  self.env=os.environ.copy();self.env.update({
   'PD2_HOME':str(self.base),'PD2_PORT':str(self.port),'PD2_STATE':str(self.state),'PD2_PREFIX':str(self.prefix),
   'PD2_WORK':str(self.work),'PD2_RUN':str(self.base/'run'),'PD2_WESTON':str(self.base/'weston'),
   'PD2_WINE':str(self.base/'wine'),'PD2_BOX':str(self.base/'bin/box'),'PD2_PROFILE':'gdi','PD2_SWAP_AB':'0',
   'PD2_CONTROLLER_CONFIG':'','PD2_NATIVE_LIBS':'','PD2_NATIVE_PRELOAD':'',
   'PD2_CRUSTY_SDL':'','PD2_CRUSTY_EGL':'','PD2_CRUSTY_GBM':'','PD2_CRUSTY_DRM':'',
   'PD2_INPUT_MODE':'mapper','PD2_CONTROLLER_TEST':'0','PD2_AUDIO_TEST':'0','PD2_FPS':'0','PD2_GAME_RESOLUTION':'800x600','MOCK_PROBE':str(self.base/'probe.jsonl'),
   'PD2_GPTOKEYB':'mapper', 'MOCK_CALLS':str(self.calls),'MOCK_MAPPER':str(self.base/'mapper.json'),'MOCK_NAVIGATOR':str(self.base/'navigator.json'),
   'PATH':str(self.base/'bin')+os.pathsep+os.environ['PATH']})
  # Mapper path deliberately has no spaces: PortMaster command macro is split.
 def executable(self,path,text):path.write_text(text);path.chmod(0o755)
 def tearDown(self):self.temp.cleanup()
 def execute(self,extra=None):
  env=dict(self.env);env.update(extra or {})
  started=time.monotonic();result=subprocess.run(['bash',str(SCRIPTS/'run-game.sh')],env=env,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=15)
  return result,time.monotonic()-started
 def records(self):return [json.loads(l) for l in self.calls.read_text().splitlines()]
 def mapper(self):return json.loads((self.base/'mapper.json').read_text())
 def assert_dead(self,pid):
  try:os.kill(pid,0)
  except ProcessLookupError:return
  # An adopted zombie cannot run or hold descriptors; allow it until init reaps.
  stat=pathlib.Path('/proc')/str(pid)/'stat'
  if stat.exists() and stat.read_text().split()[2]=='Z':return
  self.fail('Owned process survived cleanup')
 def test_native_bash_syntax(self):
  for p in [ROOT/'sdcard/ports/Project Diablo 2.sh',SCRIPTS/'run-game.sh',SCRIPTS/'weston-session.sh',SCRIPTS/'private-namespace.sh']:
   r=subprocess.run(['bash','-n',str(p)],capture_output=True,text=True);self.assertEqual(r.returncode,0,r.stderr)
 def test_game_arguments_and_scoped_mapper(self):
  r,_=self.execute();self.assertEqual(r.returncode,0,r.stdout)
  game=[v for v in self.records() if any(a.endswith('Game.exe') for a in v['args'][1:])]
  self.assertEqual(game[0]['args'][1:],['explorer.exe','/desktop=PD2Native,640x480','start.exe','/d',r'C:\Diablo II\ProjectD2','/exec',r'C:\Diablo II\ProjectD2\Game.exe','-ddraw']);self.assertNotIn('-3dfx',r.stdout)
  mapper=self.mapper();self.assertEqual(mapper['args'][0],'-1');self.assertTrue(mapper['args'][1].startswith('^bash '));self.assertNotEqual(mapper['args'][1],'Game.exe');self.assert_dead(mapper['pid'])
 def test_native_controller_creates_xbox_before_any_wine_process(self):
   r,_=self.execute({'PD2_INPUT_MODE':'native','PD2_SWAP_AB':'1'});self.assertEqual(r.returncode,0,r.stdout)
   mapper=self.mapper();self.assertEqual(mapper['args'][0],'xbox360');self.assertNotIn('-c',mapper['args'])
   self.assertEqual(mapper['args'][1],'-1');self.assertEqual(mapper['textinput'],'N')
   probes=[json.loads(l) for l in (self.base/'probe.jsonl').read_text().splitlines()]
   self.assertEqual([v['args'][0] for v in probes],['--snapshot','--wait'])
   self.assertLess(probes[0]['time'],mapper['time']);self.assertLess(mapper['time'],probes[1]['time'])
   self.assertTrue(all(probes[1]['time']<call['time'] for call in self.records()))
   self.assertFalse((self.base/'navigator.json').exists());self.assert_dead(mapper['pid'])
 def test_bundled_mapper_precedes_wine_without_gptokeyb_and_is_cleaned(self):
  (self.port/'scripts/xbox_mapper.py').write_text('''import json,os,time
with open(os.environ['MOCK_MAPPER'],'w') as f:json.dump({'pid':os.getpid(),'pgid':os.getpgrp(),'time':time.monotonic_ns()},f)
print('PD2_EVENT '+json.dumps(dict(event='session_probe',phase='launch',check='controller_mapper',status='ready')),flush=True)
while True:time.sleep(.1)
''')
  r,_=self.execute({'PD2_INPUT_MODE':'native','PD2_CONTROLLER_TEST':'1'})
  self.assertEqual(r.returncode,0,r.stdout)
  self.assertNotIn('"status":"fallback"',r.stdout)
  mapper=self.mapper();self.assertEqual(mapper['pid'],mapper['pgid'])
  probes=[json.loads(l) for l in (self.base/'probe.jsonl').read_text().splitlines()]
  self.assertLess(probes[0]['time'],mapper['time']);self.assertLess(mapper['time'],probes[1]['time'])
  self.assertTrue(all(probes[1]['time']<call['time'] for call in self.records()))
  self.assert_dead(mapper['pid'])
 def test_bundled_mapper_failure_explicitly_reports_fallback(self):
  (self.port/'scripts/xbox_mapper.py').write_text('raise SystemExit(4)\n')
  r,_=self.execute({'PD2_INPUT_MODE':'native'})
  self.assertEqual(r.returncode,0,r.stdout)
  self.assertIn('"check":"controller_mapper","status":"fallback"',r.stdout)
  self.assertEqual(self.mapper()['args'][0],'xbox360')
  self.assert_dead(self.mapper()['pid'])
 def test_controller_test_runs_real_probe_path_not_game_or_mouse_mapper(self):
   r,_=self.execute({'PD2_INPUT_MODE':'native','PD2_CONTROLLER_TEST':'1'});self.assertEqual(r.returncode,0,r.stdout)
   self.assertTrue(any(any(a.endswith('pd2-xinput-probe.exe') for a in v['args']) for v in self.records()))
   self.assertFalse(any(any(a.endswith('Game.exe') for a in v['args'][1:]) for v in self.records()))
   self.assertFalse(any('joy.cpl' in v['args'] for v in self.records()))
   self.assertFalse((self.base/'navigator.json').exists());self.assert_dead(self.mapper()['pid'])
   self.assertIn('"check":"xinput_axes","status":"changed"',r.stdout)
   self.assertIn('"check":"xinput_buttons","status":"changed"',r.stdout)
 def test_probe_reports_no_xinput_even_when_linux_mapper_is_ready(self):
   r,_=self.execute({'PD2_INPUT_MODE':'native','PD2_CONTROLLER_TEST':'1','MOCK_XINPUT_MISSING':'1'});self.assertEqual(r.returncode,0,r.stdout)
   self.assertIn('"check":"xinput_devices","status":"missing"',r.stdout)
   self.assertIn('"check":"xinput_axes","status":"unavailable"',r.stdout)
 def test_native_winebus_flags_restart_then_restore_originals(self):
   r,_=self.execute({'PD2_INPUT_MODE':'native'});self.assertEqual(r.returncode,0,r.stdout)
   calls=self.records();game=next(i for i,v in enumerate(calls) if any(a.endswith('Game.exe') for a in v['args'][1:]))
   for flag,value in (('Enable SDL','0'),('DisableInput','0'),('DisableUdevd','1')):
    index=next(i for i,v in enumerate(calls) if flag in v['args'] and '/d' in v['args'])
    self.assertEqual(calls[index]['args'][calls[index]['args'].index('/d')+1],value);self.assertLess(index,game)
   last_flag=next(i for i,v in enumerate(calls) if 'DisableUdevd' in v['args'])
   self.assertTrue(any(last_flag<i<game and '-k' in v['args'] for i,v in enumerate(calls)))
   restores=[(i,v) for i,v in enumerate(calls) if v.get('restore_kind')=='winebus']
   self.assertEqual(len(restores),1);self.assertGreater(restores[0][0],game)
   restored=restores[0][1]['restore'];self.assertIn('"Enable SDL"=dword:00000002',restored)
   self.assertIn('"DisableInput"=dword:00000001',restored);self.assertIn('"DisableUdevd"=-',restored)
   self.assertNotIn('OtherValue',restored)
   self.assertFalse((self.prefix/'drive_c/pd2-winebus-restore.reg').exists())
 def test_export_preflight_preserves_unrelated_file_before_wine_write(self):
   target=self.prefix/'drive_c/pd2-winebus-export.reg';target.write_text('unrelated private text')
   r,_=self.execute({'PD2_INPUT_MODE':'native'});self.assertEqual(r.returncode,1,r.stdout)
   self.assertEqual(target.read_text(),'unrelated private text')
   self.assertFalse(any(any('pd2-winebus-export.reg' in arg for arg in v['args']) for v in self.records()))
   self.assertNotIn('unrelated private text',r.stdout)
 def test_failed_export_does_not_mutate_flags_and_retry_succeeds(self):
   r,_=self.execute({'PD2_INPUT_MODE':'native','MOCK_EXPORT_FAIL':'1'});self.assertEqual(r.returncode,1,r.stdout)
   self.assertFalse(any('Enable SDL' in v['args'] for v in self.records()))
   self.assertFalse((self.prefix/'drive_c/pd2-winebus-restore.reg').exists())
   r,_=self.execute({'PD2_INPUT_MODE':'native'});self.assertEqual(r.returncode,0,r.stdout)
   self.assertFalse((self.prefix/'drive_c/pd2-winebus-restore.reg').exists())
 def test_partial_registry_failure_restores_before_exit(self):
   r,_=self.execute({'PD2_INPUT_MODE':'native','MOCK_FLAG_FAIL':'1'});self.assertEqual(r.returncode,1,r.stdout)
   self.assertTrue(any('restore' in v for v in self.records()))
   self.assertFalse((self.prefix/'drive_c/pd2-winebus-restore.reg').exists())
   self.assertFalse(any(any(a.endswith('Game.exe') for a in v['args']) for v in self.records()))
 def test_interrupted_winebus_marker_recovers_when_server_is_absent(self):
   r,_=self.execute({'PD2_INPUT_MODE':'native','MOCK_RESTORE_FAIL':'1'});self.assertEqual(r.returncode,1,r.stdout)
   marker=self.prefix/'drive_c/pd2-winebus-restore.reg';self.assertTrue(marker.is_file())
   r,_=self.execute({'MOCK_STOP_NOSERVER':'1'});self.assertEqual(r.returncode,0,r.stdout);self.assertFalse(marker.exists())
   self.assertIn('"check":"winebus_backend","status":"restored"',r.stdout)
 def test_virtual_gamepad_probe_failure_stops_before_any_wine_call(self):
   r,_=self.execute({'PD2_INPUT_MODE':'native','MOCK_PROBE_FAIL':'1'});self.assertEqual(r.returncode,1,r.stdout)
   self.assertIn('denied',r.stdout);self.assertFalse(any(pathlib.Path(v['args'][0]).name=='wine' for v in self.records()))
   self.assert_dead(self.mapper()['pid'])
 def test_xbox_mapper_early_exit_never_starts_wine(self):
   r,_=self.execute({'PD2_INPUT_MODE':'native','MOCK_MAPPER_EXIT':'1'});self.assertEqual(r.returncode,1,r.stdout)
   self.assertFalse(any(pathlib.Path(v['args'][0]).name=='wine' for v in self.records()))
 def test_controller_test_requires_native_mode(self):
   r,_=self.execute({'PD2_CONTROLLER_TEST':'1'});self.assertEqual(r.returncode,1,r.stdout)
   self.assertFalse((self.base/'mapper.json').exists())
 def test_invalid_input_mode_never_starts_mapper_or_game(self):
   r,_=self.execute({'PD2_INPUT_MODE':'invalid'});self.assertEqual(r.returncode,1,r.stdout)
   self.assertFalse((self.base/'mapper.json').exists())
   self.assertFalse(any(any(a.endswith('Game.exe') for a in v['args'][1:]) for v in self.records()))
 def test_native_desktop_reapplied_to_existing_prefix_before_game(self):
  r,_=self.execute();self.assertEqual(r.returncode,0,r.stdout)
  calls=self.records()
  desktop=next(i for i,v in enumerate(calls) if '640x480' in v['args'])
  game=next(i for i,v in enumerate(calls) if any(a.endswith('Game.exe') for a in v['args'][1:]))
  self.assertLess(desktop,game)
  self.assertFalse(any('1024x768' in v['args'] for v in calls))
 def test_save_path_repaired_each_launch_in_existing_prefix(self):
  for _ in range(2):
   r,_=self.execute();self.assertEqual(r.returncode,0,r.stdout)
  calls=self.records()
  save=[i for i,v in enumerate(calls) if 'Save Path' in v['args']]
  game=[i for i,v in enumerate(calls) if any(a.endswith('Game.exe') for a in v['args'][1:])]
  self.assertEqual(len(save),2)
  for registry,launch in zip(save,game):
   self.assertLess(registry,launch)
   args=calls[registry]['args'];self.assertEqual(args[args.index('/d')+1],'S:\\')
  self.assertFalse(any('wineboot.exe' in v['args'] for v in calls))
 def test_failed_save_path_never_launches_game_or_mapper(self):
  r,_=self.execute({'MOCK_SAVE_PATH_FAIL':'1'});self.assertEqual(r.returncode,1,r.stdout)
  self.assertIn('invalid_layout',r.stdout)
  self.assertFalse(any(any(a.endswith('Game.exe') for a in v['args'][1:]) for v in self.records()))
  self.assertFalse((self.base/'mapper.json').exists())
 def test_failed_native_desktop_never_launches_game(self):
  r,_=self.execute({'MOCK_DESKTOP_FAIL':'1'});self.assertEqual(r.returncode,1,r.stdout)
  self.assertIn('invalid_layout',r.stdout)
  self.assertFalse(any(any(a.endswith('Game.exe') for a in v['args'][1:]) for v in self.records()))
 def test_portmaster_macro_trailing_kill_flag(self):
  r,_=self.execute({'PD2_GPTOKEYB':self.env['PD2_GPTOKEYB']+' -1'});self.assertEqual(r.returncode,0,r.stdout)
  self.assertEqual(self.mapper()['args'].count('-1'),1)
 def test_nonzero_game_exit_preserved(self):
  r,_=self.execute({'MOCK_GAME_RC':'23'});self.assertEqual(r.returncode,23,r.stdout);self.assertIn('"rc":23',r.stdout);self.assert_dead(self.mapper()['pid'])
 def test_hung_mapper_has_bounded_kill(self):
  r,seconds=self.execute({'MOCK_IGNORE_TERM':'1'});self.assertEqual(r.returncode,0,r.stdout);self.assertLess(seconds,10);self.assert_dead(self.mapper()['pid'])
 def test_server_wait_timeout_reported(self):
  r,_=self.execute({'MOCK_SERVER_TIMEOUT':'1'});self.assertEqual(r.returncode,124,r.stdout);self.assertIn('"reason":"timeout"',r.stdout)
 def test_prefix_init_once(self):
  (self.prefix/'.initialized').unlink();r,_=self.execute();self.assertEqual(r.returncode,0,r.stdout)
  self.assertTrue((self.prefix/'.initialized').exists());self.assertFalse((self.prefix/'.initializing').exists())
  first=len([v for v in self.records() if 'wineboot.exe' in v['args']]);self.assertEqual(first,1)
  r,_=self.execute();self.assertEqual(r.returncode,0,r.stdout)
  self.assertEqual(len([v for v in self.records() if 'wineboot.exe' in v['args']]),1)
 def test_incomplete_prefix_no_game(self):
  (self.prefix/'.initialized').unlink();(self.prefix/'.initializing').touch()
  r,_=self.execute();self.assertEqual(r.returncode,1,r.stdout);self.assertIn('prefix_incomplete',r.stdout)
  self.assertFalse(any(any(a.endswith('Game.exe') for a in v['args'][1:]) for v in self.records()))
 def test_signal_cleans_owned_game_group(self):
  env=dict(self.env);env['MOCK_GAME_SLEEP']='1'
  p=subprocess.Popen(['bash',str(SCRIPTS/'run-game.sh')],env=env,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
  try:
   for _ in range(100):
    if self.calls.exists() and any(any(a.endswith('Game.exe') for a in v['args'][1:]) for v in self.records()):break
    time.sleep(.05)
   p.send_signal(signal.SIGTERM);out,_=p.communicate(timeout=15);self.assertEqual(p.returncode,143,out)
   game=[v for v in self.records() if any(a.endswith('Game.exe') for a in v['args'][1:])][0];self.assert_dead(game['pid']);self.assert_dead(self.mapper()['pid'])
  finally:
   if p.poll() is None:p.kill();p.wait()
 def test_old_audio_path_does_not_snapshot_route_or_force_existing_prefix(self):
  result,_=self.execute();self.assertEqual(result.returncode,0,result.stdout)
  self.assertFalse(any('Audio' in v['args'] or any('pd2-audio' in a for a in v['args']) for v in self.records()))
  self.assertFalse((self.base/'run/alsa-pd2.conf').exists())
  self.assertFalse((self.prefix/'drive_c/pd2-audio-restore.reg').exists())
 def test_audio_restore_marker_recovers_before_next_game(self):
  import importlib.util
  sys.path.insert(0,str(SCRIPTS))
  self.addCleanup(lambda: sys.path.remove(str(SCRIPTS)))
  spec=importlib.util.spec_from_file_location('restore_audio_fixture',SCRIPTS/'audio_config.py')
  audio=importlib.util.module_from_spec(spec);spec.loader.exec_module(audio)
  marker=self.prefix/'drive_c/pd2-audio-restore.reg'
  marker.write_bytes(audio.restore_bytes({'Audio':{'type':1,'data':'pulse\0'.encode('utf-16-le')}}))
  marker.chmod(0o600)
  result,_=self.execute({'MOCK_RESTORE_FAIL':'1'});self.assertEqual(result.returncode,1,result.stdout)
  self.assertTrue(marker.exists())
  result,_=self.execute({'MOCK_STOP_NOSERVER':'1'});self.assertEqual(result.returncode,0,result.stdout)
  self.assertFalse(marker.exists())
  self.assertIn('"check":"audio_backend","status":"restored"',result.stdout)
 def test_audio_opt_in_snapshots_forces_then_restores_only_audio(self):
  result,_=self.execute({'PD2_AUDIO_TEST':'1'});self.assertEqual(result.returncode,0,result.stdout)
  calls=self.records()
  self.assertTrue(any(any(a.endswith('Game.exe') for a in v['args']) for v in calls))
  self.assertTrue(any(v.get('restore_kind')=='audio' for v in calls))
  game=next(i for i,v in enumerate(calls) if any(a.endswith('Game.exe') for a in v['args']))
  export=next(i for i,v in enumerate(calls) if 'export' in v['args'] and any('pd2-audio-export' in a for a in v['args']))
  force=next(i for i,v in enumerate(calls) if 'Audio' in v['args'])
  restore=next(i for i,v in enumerate(calls) if v.get('restore_kind')=='audio')
  self.assertLess(export,force);self.assertLess(force,game);self.assertLess(game,restore)
  self.assertIn('hex(1):70,00,75,00,6c,00,73,00,65,00,00,00',calls[restore]['restore'])
  self.assertNotIn('OtherAudio',calls[restore]['restore'])
  self.assertFalse((self.prefix/'drive_c/pd2-audio-restore.reg').exists())
  self.assertIn('"check":"audio_backend","status":"alsa"',result.stdout)
 # Normal audio setup no longer plays diagnostic probes; probe tests opt in.
 def test_audio_failed_private_route_logs_fallback_then_default_probe(self):
  result,_=self.execute({'PD2_AUDIO_TEST':'1','PD2_AUDIO_PROBE':'1','MOCK_AUDIO_OPEN':'missing'})
  self.assertEqual(result.returncode,0,result.stdout)
  self.assertIn('"check":"audio_route","status":"rk817"',result.stdout)
  self.assertIn('"check":"audio_device","status":"ready"',result.stdout)
  self.assertIn('"check":"audio_control","status":"ready"',result.stdout)
  self.assertIn('"check":"audio_fallback","status":"attempted"',result.stdout)
  self.assertIn('"check":"audio_route","status":"default"',result.stdout)
  self.assertIn('"check":"audio_driver","status":"failed","detail":"silent"',result.stdout)
  calls=self.records()
  probes=[i for i,v in enumerate(calls) if any(a.endswith('pd2-audio-probe.exe') for a in v['args'])]
  self.assertEqual(len(probes),2)
  game=next(i for i,v in enumerate(calls) if any(a.endswith('Game.exe') for a in v['args']))
  self.assertLess(probes[-1],game)
  self.assertFalse((self.base/'run/alsa-pd2.conf').exists())
 def test_audio_driver_detail_prefers_missing_libasound(self):
  result,_=self.execute({'PD2_AUDIO_TEST':'1','PD2_AUDIO_PROBE':'1','MOCK_AUDIO_OPEN':'missing','MOCK_AUDIO_DRIVER_LOG':'err:module:import_dll Library libasound.so.2 (which is needed by L"winealsa.so") not found\n'})
  self.assertEqual(result.returncode,0,result.stdout)
  self.assertIn('"check":"audio_driver","status":"failed","detail":"libasound"',result.stdout)
 def test_audio_enumeration_diagnostics_cover_both_routes(self):
  message='0024:warn:alsa:alsa_try_open The device "default" failed to open: -5 (private detail).\n'
  result,_=self.execute({'PD2_AUDIO_TEST':'1','PD2_AUDIO_PROBE':'1','MOCK_AUDIO_OPEN':'missing','MOCK_AUDIO_DRIVER_LOG':message})
  self.assertEqual(result.returncode,0,result.stdout)
  self.assertEqual(result.stdout.count('"check":"audio_alsa_default","status":"other_error","alsa_rc":-5'),2)
  self.assertEqual(result.stdout.count('"check":"audio_alsa_capture","status":"complete"'),2)
  self.assertNotIn('private detail',result.stdout)
 def test_local_alsa_library_is_selected_for_native_and_wine_only_when_opted_in(self):
  result,_=self.execute({'PD2_AUDIO_TEST':'1','PD2_AUDIO_PROBE':'1','MOCK_AUDIO_OPEN':'missing'})
  self.assertEqual(result.returncode,0,result.stdout)
  self.assertIn('"check":"audio_library","status":"legacy_armhf"',result.stdout)
  prefix=str(self.work/'.alsa-legacy-armhf')+':'
  relevant=[call for call in self.records() if any(arg.endswith(('pd2-audio-probe.exe','Game.exe')) for arg in call['args'])]
  self.assertEqual(len(relevant),3)
  self.assertTrue(all(call['libraries'].startswith(prefix) for call in relevant))
  records=[json.loads(line) for line in (self.base/'run/native-calls.jsonl').read_text().splitlines()]
  self.assertTrue(all(record['libraries'].startswith(prefix) for record in records))
 def test_local_alsa_library_is_absent_from_default_session(self):
  result,_=self.execute()
  self.assertEqual(result.returncode,0,result.stdout)
  self.assertNotIn('"check":"audio_library"',result.stdout)
  self.assertFalse((self.work/'.alsa-legacy-armhf').exists())
  self.assertTrue(all(call['libraries']=='' for call in self.records()))
 def test_failed_local_library_preparation_keeps_original_search_path(self):
  result,_=self.execute({'PD2_AUDIO_TEST':'1','MOCK_COMPAT_FAIL':'1'})
  self.assertEqual(result.returncode,0,result.stdout)
  self.assertIn('"check":"audio_library","status":"unavailable"',result.stdout)
  self.assertTrue(all(call['libraries']=='' for call in self.records()))
 def test_native_armhf_comparison_precedes_wine_on_both_routes(self):
  result,_=self.execute({'PD2_AUDIO_TEST':'1','PD2_AUDIO_PROBE':'1','MOCK_AUDIO_OPEN':'missing','MOCK_NATIVE_RC':'-25'})
  self.assertEqual(result.returncode,0,result.stdout)
  records=[json.loads(line) for line in (self.base/'run/native-calls.jsonl').read_text().splitlines()]
  self.assertEqual([record['private'] for record in records],[True,False])
  probes=[call for call in self.records() if any(arg.endswith('pd2-audio-probe.exe') for arg in call['args'])]
  self.assertEqual(len(probes),2)
  for native,probe in zip(records,probes):self.assertLess(native['time'],probe['time'])
  self.assertEqual(result.stdout.count('"check":"audio_native_default","status":"other_error","alsa_rc":-25'),2)
 def test_audio_driver_reports_loaded_on_alsa_trace(self):
  result,_=self.execute({'PD2_AUDIO_TEST':'1','PD2_AUDIO_PROBE':'1','MOCK_AUDIO_DRIVER_LOG':'trace:alsa:ALSA_InitCards\n'})
  self.assertEqual(result.returncode,0,result.stdout)
  self.assertIn('"check":"audio_driver","status":"loaded"',result.stdout)
  self.assertNotIn('"detail"',result.stdout)
 def test_audio_capture_waits_for_descendant_stderr_after_wineserver_stop(self):
  result,_=self.execute({'PD2_AUDIO_TEST':'1','PD2_AUDIO_PROBE':'1','MOCK_AUDIO_LATE_STDERR':'1'})
  self.assertEqual(result.returncode,0,result.stdout)
  self.assertIn('"check":"audio_diagnostics","status":"legacy_v7"',result.stdout)
  self.assertIn('"check":"audio_driver","status":"loaded"',result.stdout)
  self.assert_dead(int((self.base/'audio-stderr-child').read_text()))
  self.assertFalse((self.work/'audio-driver.log').exists())
 def test_audio_capture_drains_output_beyond_storage_limit(self):
  result,_=self.execute({'PD2_AUDIO_TEST':'1','PD2_AUDIO_PROBE':'1','MOCK_AUDIO_FLOOD':'1','MOCK_AUDIO_DRIVER_LOG':'trace:alsa:init\n'})
  self.assertEqual(result.returncode,0,result.stdout)
  self.assertIn('"check":"audio_driver","status":"loaded"',result.stdout)
  self.assertFalse((self.work/'audio-driver.log').exists())
 def test_audio_capture_timeout_is_not_reported_as_driver_failure_reason(self):
  try:
   result,duration=self.execute({'PD2_AUDIO_TEST':'1','PD2_AUDIO_PROBE':'1','MOCK_AUDIO_HELD_STDERR':'1'})
   self.assertEqual(result.returncode,0,result.stdout)
   self.assertIn('"detail":"capture_timeout"',result.stdout)
   self.assertLess(duration,9)
   self.assertFalse((self.work/'audio-driver.log').exists())
  finally:
   child=self.base/'audio-stderr-child'
   if child.exists():
    try:os.kill(int(child.read_text()),signal.SIGTERM)
    except ProcessLookupError:pass
 def test_audio_export_failure_does_not_force_audio_or_launch_game(self):
  result,_=self.execute({'PD2_AUDIO_TEST':'1','MOCK_EXPORT_FAIL':'1'})
  self.assertEqual(result.returncode,1,result.stdout)
  self.assertFalse(any('Audio' in v['args'] or any(a.endswith('Game.exe') for a in v['args']) for v in self.records()))
 def test_short_game_exits_without_waiting_for_fps_grace(self):
  result,duration=self.execute({'PD2_FPS':'1','MOCK_GAME_DELAY':'0.1'})
  self.assertEqual(result.returncode,0,result.stdout)
  self.assertLess(duration,8)
  self.assertFalse(any(any(a.endswith('pd2-fps-hotkey.exe') for a in v['args']) for v in self.records()))
 def test_fps_hud_enabled_before_game_without_extra_wine_process(self):
   result,duration=self.execute({'PD2_FPS':'1','MOCK_GAME_DELAY':'0.1'})
   self.assertEqual(result.returncode,0,result.stdout)
   self.assertLess(duration,8)
   self.assertIn('"check":"fps_counter","status":"renderer"',result.stdout)
   self.assertEqual((self.work/'ProjectD2/ddraw.dll').read_bytes(),(self.port/'compat/fps-renderer/ddraw.dll').read_bytes())
   self.assertFalse((self.work/'ProjectD2/ddraw.dll').is_symlink())
   self.assertFalse(any(any(a.endswith('pd2-fps-hotkey.exe') for a in v['args']) for v in self.records()))
 def test_fps_off_keeps_original_renderer(self):
   result,_=self.execute({'PD2_FPS':'0','MOCK_GAME_DELAY':'0.1'})
   self.assertEqual(result.returncode,0,result.stdout)
   self.assertIn('"check":"fps_counter","status":"disabled"',result.stdout)
   self.assertTrue((self.work/'ProjectD2/ddraw.dll').is_symlink())
 def test_fps_prepare_failure_is_optional_and_game_still_runs(self):
  (self.port/'compat/fps-renderer/ddraw.dll').write_bytes(b'MZbad')
  result,_=self.execute({'PD2_FPS':'1','MOCK_GAME_DELAY':'0.1'});self.assertEqual(result.returncode,0,result.stdout)
  self.assertIn('"check":"fps_counter","status":"unavailable"',result.stdout)
  self.assertTrue(any(any(a.endswith('Game.exe') for a in v['args']) for v in self.records()))
 def test_controller_probe_skips_audio_mutations_and_fps(self):
  result,_=self.execute({'PD2_INPUT_MODE':'native','PD2_CONTROLLER_TEST':'1','PD2_FPS':'1'})
  self.assertEqual(result.returncode,0,result.stdout)
  self.assertFalse(any('Audio' in v['args'] or any(a.endswith('pd2-fps-hotkey.exe') for a in v['args']) for v in self.records()))
 def test_invalid_fps_or_resolution_never_starts_wine(self):
  for value in ({'PD2_FPS':'private'},{'PD2_GAME_RESOLUTION':'private'}):
   with self.subTest(value=value):
    result,_=self.execute(value);self.assertEqual(result.returncode,1,result.stdout)
    self.assertNotIn('private',result.stdout)
    self.assertFalse(any(pathlib.Path(v['args'][0]).name=='wine' for v in self.records()))
 def test_alternative_resolution_preserves_native_desktop(self):
  result,_=self.execute({'PD2_GAME_RESOLUTION':'1024x768'});self.assertEqual(result.returncode,0,result.stdout)
  game=next(v for v in self.records() if any(a.endswith('Game.exe') for a in v['args']))
  self.assertIn('/desktop=PD2Native,640x480',game['args'])
  self.assertIn('"check":"render_resolution","status":"1024x768"',result.stdout)
 def test_numbered_tuning_reaches_wine_after_audio_refresh(self):
  self.performance_env()
  for mode,profile in [('baseline','gdi'),('forward512','gdi'),('callret','gdi'),('fastflags','gdi'),('gl-kms','opengl'),('gl-auto','opengl')]:
   with self.subTest(mode=mode):
    # Each launch gets fresh volatile work, just like the real tmpfs session.
    self.tearDown(); self.setUp(); self.performance_env()
    self.calls.unlink(missing_ok=True)
    result,_=self.execute({'PD2_TUNING':mode,'PD2_PERFORMANCE':profile,'PD2_PROFILE':profile,'PD2_BIGBLOCK':'1','PD2_AUDIO_TEST':'1','PD2_AUDIO_PROBE':'0'})
    self.assertEqual(result.returncode,0,result.stdout)
    calls=self.records();self.assertTrue(calls)
    game=next(v for v in calls if any(a.endswith('Game.exe') for a in v['args']))
    self.assertIn('.alsa-legacy-armhf',game['libraries'])
    for call in calls:
     if profile=='gdi':
      is_game=any(a.endswith('Game.exe') for a in call['args'])
      self.assertEqual(call['tuning']['BOX86_DYNAREC_FORWARD'],('512' if mode=='forward512' else '128') if is_game else None)
      self.assertEqual(call['tuning']['BOX86_DYNAREC_CALLRET'],'1' if mode=='callret' and is_game else '0')
      self.assertEqual(call['dynarec']['BOX86_DYNAREC_SAFEFLAGS'],'0' if mode=='fastflags' and is_game else '1')
     else:
      self.assertEqual(call['tuning']['SDL_VIDEODRIVER'],'kmsdrm' if mode=='gl-kms' else None)
    self.assertIn('"check":"tuning_profile","status":"'+mode+'"',result.stdout)
 def test_diagnostic_presentation_selects_light_not_hud(self):
  (self.port/'scripts/present_renderer.py').write_text('import pathlib,os\n(pathlib.Path(os.environ["PD2_WORK"])/"light-selected").touch()\n')
  (self.port/'scripts/presentation_watch.py').write_text('# synthetic-only watcher\n')
  result,_=self.execute({'PD2_DIAGNOSTIC':'present','PD2_FPS':'1'})
  self.assertEqual(result.returncode,0,result.stdout)
  self.assertTrue((self.work/'light-selected').exists())
  self.assertIn('"check":"presentation_capture","status":"ready"',result.stdout)
  self.assertNotIn('"check":"fps_counter","status":"renderer"',result.stdout)
 def test_diagnostic_native_layers_do_not_start_wine_or_mapper(self):
  for mode in ('sdl','glx'):
   with self.subTest(mode=mode):
    self.tearDown();self.setUp()
    for helper in ('run-layer.sh','diagnostic_capture.py','safe_log.py'):
     (self.port/'scripts'/helper).write_text((SCRIPTS/helper).read_text())
    (self.port/'scripts/graphics_artifacts.py').write_text('# synthetic pinned-artifact validation\n')
    folder=self.port/'compat/graphics-probe';folder.mkdir()
    self.executable(folder/'graphics-layers.armhf','#!/bin/sh\necho raw-private-loader-output\necho \'PD2_EVENT {"event":"graphics_layer","schema":1,"probe":"'+mode+'","stage":"done","status":"ok","backend":"kmsdrm","renderer":"unknown","frame":0,"code":0}\'\n')
    result,_=self.execute({'PD2_DIAGNOSTIC':mode,'PD2_NATIVE_REAL_LIBS':'','PD2_CRUSTY_GLES':''})
    self.assertEqual(result.returncode,0,result.stdout)
    self.assertFalse(self.calls.exists())
    self.assertFalse((self.base/'mapper.json').exists())
    self.assertNotIn('raw-private',result.stdout)
    self.assertIn('"check":"graphics_test_result","status":"completed"',result.stdout)
 def test_diagnostic_ddraw_is_bounded_and_never_launches_real_engine(self):
  for timed_out in (False,True):
   with self.subTest(timed_out=timed_out):
    self.tearDown();self.setUp()
    for helper in ('run-layer.sh','diagnostic_capture.py','safe_log.py'):
     (self.port/'scripts'/helper).write_text((SCRIPTS/helper).read_text())
    for helper in ('graphics_artifacts.py','present_renderer.py','presentation_watch.py'):
     (self.port/'scripts'/helper).write_text('# synthetic helper\n')
    env={'PD2_DIAGNOSTIC':'ddraw'}
    if timed_out:env['MOCK_GRAPHICS_TIMEOUT']='1'
    result,_=self.execute(env)
    self.assertEqual(result.returncode,124 if timed_out else 0,result.stdout)
    self.assertFalse(any(a.endswith('Game.exe') for call in self.records() for a in call['args']))
    self.assertIn('"check":"graphics_test_result","status":"'+('timeout' if timed_out else 'completed')+'"',result.stdout)
    if not timed_out:
     probe=next(v for v in self.records() if any(a.endswith('pd2-graphics.exe') for a in v['args']))
     self.assertIn('C:\\Diablo II\\ProjectD2',probe['args'])
    self.assertTrue(any(v['args'][0].endswith('wineserver') and '-w' in v['args'] for v in self.records()))
 def test_diagnostic_setup_timeout_has_precise_stage(self):
  result,_=self.execute({'MOCK_QUIESCE_TIMEOUT':'1','PD2_PERFORMANCE':'gdi','PD2_TUNING':'callret'})
  self.assertNotEqual(result.returncode,0)
  self.assertIn('"stage":"prefix_quiesce","status":"failed"',result.stdout)
  self.assertFalse(any(any(a.endswith('Game.exe') for a in v['args']) for v in self.records()))
  self.assertTrue(all(v['tuning']['BOX86_DYNAREC_CALLRET']=='0' for v in self.records()))
 def performance_env(self):
  # The real launcher clears inherited Box86 overrides before run-game.sh.
  for key in ('PD2_PERFORMANCE','PD2_BIGBLOCK','BOX86_DYNAREC','BOX86_DYNAREC_BIGBLOCK','BOX86_DYNAREC_SAFEFLAGS','BOX86_DYNAREC_STRONGMEM'):
   self.env.pop(key,None)
 def test_performance_profiles_export_dynarec_to_all_wine_calls(self):
  self.performance_env()
  for profile in ('gdi','opengl'):
   for bigblock in ('1','2'):
    with self.subTest(profile=profile,bigblock=bigblock):
     self.calls.unlink(missing_ok=True)
     result,_=self.execute({'PD2_PERFORMANCE':profile,'PD2_PROFILE':profile,'PD2_BIGBLOCK':bigblock,'BOX86_DYNAREC':'0','BOX86_DYNAREC_BIGBLOCK':'0','BOX86_DYNAREC_SAFEFLAGS':'0','BOX86_DYNAREC_STRONGMEM':'1'})
     self.assertEqual(result.returncode,0,result.stdout)
     calls=self.records();self.assertTrue(calls)
     expected={'BOX86_DYNAREC':'1','BOX86_DYNAREC_BIGBLOCK':bigblock,'BOX86_DYNAREC_SAFEFLAGS':'1','BOX86_DYNAREC_STRONGMEM':'0'}
     for call in calls:
      scoped=dict(expected)
      if not any(a.endswith('Game.exe') for a in call['args']):scoped['BOX86_DYNAREC_BIGBLOCK']='1'
      self.assertEqual(call['dynarec'],scoped,call['args'])
     games=[v for v in calls if any(a.endswith('Game.exe') for a in v['args'][1:])]
     self.assertEqual(len(games),1)
     self.assertIn('/desktop=PD2Native,640x480',games[0]['args']);self.assertEqual(games[0]['args'][-1],'-ddraw')
     self.assertTrue((self.work/'ProjectD2/ddraw.dll').is_symlink())
     self.assertFalse(any(any(a.endswith('pd2-fps-hotkey.exe') for a in v['args']) for v in calls))
     self.assert_dead(self.mapper()['pid'])
 def test_performance_run_game_defaults_bigblock_to_one(self):
  self.performance_env()
  result,_=self.execute({'PD2_PERFORMANCE':'gdi'});self.assertEqual(result.returncode,0,result.stdout)
  calls=self.records();self.assertTrue(calls)
  self.assertTrue(all(v['dynarec']['BOX86_DYNAREC_BIGBLOCK']=='1' for v in calls))
 def test_performance_off_or_unset_keeps_normal_wine_environment(self):
  self.performance_env()
  for extra in ({},{'PD2_PERFORMANCE':'off','PD2_BIGBLOCK':'2'}):
   with self.subTest(extra=extra):
    self.calls.unlink(missing_ok=True)
    result,_=self.execute(extra);self.assertEqual(result.returncode,0,result.stdout)
    calls=self.records();self.assertTrue(calls)
    self.assertTrue(all(all(value is None for value in v['dynarec'].values()) for v in calls))
    game=next(v for v in calls if any(a.endswith('Game.exe') for a in v['args'][1:]))
    self.assertEqual(game['args'][1:],['explorer.exe','/desktop=PD2Native,640x480','start.exe','/d',r'C:\Diablo II\ProjectD2','/exec',r'C:\Diablo II\ProjectD2\Game.exe','-ddraw'])
    self.assertTrue((self.work/'ProjectD2/ddraw.dll').is_symlink())
    self.assertNotIn('"check":"audio_library"',result.stdout)
    self.assert_dead(self.mapper()['pid'])
 def test_performance_invalid_options_never_start_wine(self):
  self.performance_env()
  for extra in ({'PD2_PERFORMANCE':'private'},{'PD2_PERFORMANCE':'gdi','PD2_BIGBLOCK':'0'},{'PD2_PERFORMANCE':'opengl','PD2_BIGBLOCK':'3'},{'PD2_PERFORMANCE':'off','PD2_BIGBLOCK':'private'}):
   with self.subTest(extra=extra):
    self.calls.unlink(missing_ok=True)
    result,_=self.execute(extra);self.assertEqual(result.returncode,1,result.stdout)
    calls=self.records() if self.calls.exists() else []
    # An EXIT trap may stop wineserver, but must never invoke Wine itself.
    self.assertFalse(any(pathlib.Path(v['args'][0]).name=='wine' for v in calls))
    self.assertFalse((self.base/'mapper.json').exists())
    self.assertNotIn('private',result.stdout)
 def test_performance_launchers_export_defaults_and_preserve_bigblock_override(self):
  self.performance_env()
  # Execute the real wrappers against a synthetic main launcher, never the port.
  main=self.base/'Project Diablo 2.sh'
  main.write_text('''#!/bin/bash
exec python3 -c 'import json,os,sys; print(json.dumps(dict(env={k:os.environ.get(k) for k in ("PD2_PERFORMANCE","PD2_BIGBLOCK","PD2_GAME_RESOLUTION","PD2_FPS")},args=sys.argv[1:])))' "$@"
''')
  for label,profile in (('GDI','gdi'),('OpenGL','opengl')):
   launcher=self.base/('Project Diablo 2 - Performance '+label+'.sh')
   launcher.write_text((ROOT/'sdcard/ports'/launcher.name).read_text())
   for bigblock in (None,'1'):
    with self.subTest(profile=profile,bigblock=bigblock):
     env=dict(self.env);env.update({'PD2_PERFORMANCE':'off','PD2_GAME_RESOLUTION':'1024x768','PD2_FPS':'1'})
     if bigblock is not None:env['PD2_BIGBLOCK']=bigblock
     result=subprocess.run(['bash',str(launcher),'argument with spaces','--test'],env=env,capture_output=True,text=True,timeout=5)
     self.assertEqual(result.returncode,0,result.stderr)
     record=json.loads(result.stdout)
     self.assertEqual(record['env'],{'PD2_PERFORMANCE':profile,'PD2_BIGBLOCK':bigblock or '2','PD2_GAME_RESOLUTION':'800x600','PD2_FPS':'1' if profile=='opengl' else '0'})
     self.assertEqual(record['args'],['argument with spaces','--test'])
  self.assertFalse(self.calls.exists())
if __name__=='__main__':unittest.main()
