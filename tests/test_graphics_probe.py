"""Synthetic graphics-provider/diagnostic tests, never load a GPU or game."""
import importlib.util,io,json,pathlib,shutil,struct,sys,unittest,uuid
from unittest import mock
from types import SimpleNamespace
ROOT=pathlib.Path(__file__).resolve().parents[1];SCRIPTS=ROOT/'sdcard/ports/projectdiablo2/scripts'
sys.path.insert(0,str(SCRIPTS))
s=importlib.util.spec_from_file_location('graphics_probe_test',SCRIPTS/'graphics_probe.py');probe=importlib.util.module_from_spec(s);s.loader.exec_module(probe)
import safe_log
class GraphicsProbeTests(unittest.TestCase):
 def setUp(self):
  self.base=ROOT/'tests'/('graphics-fixture-'+uuid.uuid4().hex);self.base.mkdir()
  self.addCleanup(shutil.rmtree,self.base);self.weston=self.base/'weston';self.weston.mkdir()
 def elf(self,path,arch='aarch64'):
  path.parent.mkdir(parents=True,exist_ok=True);h=bytearray(20);h[:4]=b'\x7fELF';h[4],machine=probe.ARCH[arch];h[5]=1;struct.pack_into('<H',h,18,machine);path.write_bytes(h);return path
 def test_upstream_candidates_and_fallback_preserve_status(self):
  lib=self.elf(self.base/'native/libMali.so');seen=[]
  def runner(args,**kwargs):
   seen.append(args[-1]);self.assertEqual(kwargs['env']['LD_PRELOAD'],'')
   return SimpleNamespace(returncode=1,stdout='') if args[-1]=='libEGL.so' else SimpleNamespace(returncode=0,stdout='constructor-secret-noise\n'+str(lib)+'\n')
  result,status=probe.resolve(self.weston,'egl','aarch64','controlled',runner)
  self.assertEqual(result,str(lib.resolve()));self.assertEqual(status,'ready');self.assertEqual(seen,['libEGL.so','libEGL.so.1'])
  self.assertEqual(len(probe.CANDIDATES['sdl']),4)
 def test_wrong_arch_nonelf_relative_and_shim_rejected(self):
  hf=self.elf(self.base/'native/libSDL2.so','armhf');self.assertIsNone(probe.valid_native(str(hf),'aarch64',self.weston))
  self.assertEqual(probe.valid_native(str(hf),'armhf',self.weston),str(hf.resolve()))
  self.assertIsNone(probe.valid_native('relative.so','aarch64',self.weston))
  fake=self.base/'native/not-elf';fake.write_text('private-secret');self.assertIsNone(probe.valid_native(str(fake),'aarch64',self.weston))
  shim=self.elf(self.weston/'lib_aarch64/graphics/crusty_gbm/libcrusty.so');self.assertIsNone(probe.valid_native(str(shim),'aarch64',self.weston))
 def test_python37_provider_validation_preserves_proxy_boundary(self):
  native=self.elf(self.base/'native/libEGL.so')
  shims=[self.elf(self.weston/arch/'graphics/crusty_gbm/libEGL.so') for arch in ('lib_aarch64','lib_armhf')]
  sibling=self.elf(self.weston/'lib_aarch64/graphics-native/libEGL.so')
  link=self.base/'native/proxy.so'
  try:link.symlink_to(shims[0])
  except OSError:link=None  # Windows without symlink privileges.
  with mock.patch.object(pathlib.Path,'is_relative_to',side_effect=AttributeError('Python 3.7'),create=True):
   self.assertEqual(probe.valid_native(native,'aarch64',self.weston),str(native.resolve()))
   self.assertEqual(probe.valid_native(sibling,'aarch64',self.weston),str(sibling.resolve()))
   for shim in shims:self.assertIsNone(probe.valid_native(shim,'aarch64',self.weston))
   if link is not None:self.assertIsNone(probe.valid_native(link,'aarch64',self.weston))
 def test_optional_missing_and_probe_failure_have_no_raw_exception(self):
  missing=lambda *a,**k:SimpleNamespace(returncode=1,stdout='')
  self.assertEqual(probe.resolve(self.weston,'gbm','aarch64','',missing),(None,'missing'))
  bad=lambda *a,**k:SimpleNamespace(returncode=-11,stdout='secret')
  self.assertEqual(probe.resolve(self.weston,'sdl','aarch64','',bad),(None,'probe_failed'))
 def test_closed_graphics_and_compositor_schema(self):
  event={'event':'graphics_probe','role':'egl','arch':'aarch64','status':'ready'};self.assertIsNotNone(safe_log.validate_event(event))
  for key,value in [('path','/home/private/lib.so'),('role','username'),('arch','private-host'),('status','private-password')]:
   changed=dict(event);changed[key]=value;self.assertIsNone(safe_log.validate_event(changed))
  self.assertIsNone(safe_log.validate_event({'event':'compositor_note','note':'private-user'}))
 def test_notes_drop_all_driver_strings_and_paths(self):
  cases={"[01:02:03.456] Loading module '/private/user/gl-renderer.so'":'gl_module','EGL version: 1.4 private-driver-token':'egl_ready','GL version: OpenGL ES 3.2 username-password':'gl_ready'}
  for raw,note in cases.items():
   event=probe.classify(raw);self.assertEqual(event['note'],note);self.assertNotIn('private',json.dumps(event));self.assertNotIn('username',json.dumps(event))
  self.assertIsNone(probe.classify('AccountName password CD-KEY blah'))
  self.assertIsNone(probe.classify('PD2_EVENT {"event":"compositor_note","note":"root_service"}'))
 def test_fault_and_known_errors_only(self):
  self.assertEqual(probe.classify('Segmentation fault')['reason'],'fault')
  self.assertEqual(probe.classify('[01:02:03.456] failed to initialize EGL: private info')['reason'],'egl_init_failed')
  self.assertEqual(probe.classify('cannot open /dev/mali0: Permission denied')['reason'],'driver_access_denied')
 def test_stream_drains_huge_raw_line_without_echo(self):
  source=io.BytesIO(b'private-CD-key'+b'x'*20000+b'\nEGL version: 1.4 private\n');sink=io.StringIO();probe.stream(source,sink)
  self.assertEqual(source.read(),b'');self.assertEqual(len(sink.getvalue().splitlines()),1);self.assertNotIn('private',sink.getvalue());self.assertIn('egl_ready',sink.getvalue())
 def test_stream_drains_after_broken_sink(self):
  class Broken:
   def write(self,text):raise OSError('private-path')
  source=io.BytesIO(b'EGL version: 1.4\n'+b'raw-user-data\n');probe.stream(source,Broken());self.assertEqual(source.read(),b'')
 def test_lazy_xwayland_notes_and_failures_drop_raw_text(self):
  cases={'xserver listening on display :0':'xserver_listening','Spawned Xwayland server, pid 123':'xwayland_spawn','xserver crashing too fast, not restarting':'xwayland_crash','Failed to initialize glamor, falling back to sw':'xwayland_software_fallback','XKB: Failed to load keymap. Loading default keymap instead.':'xwayland_keymap_fallback'}
  for raw,note in cases.items():
   value=probe.classify('[01:02:03.456] '+raw);self.assertEqual(value['note'],note);self.assertIsNotNone(safe_log.validate_event(value))
  for raw,reason in [('Failed to spawn the Xwayland server','xwayland_start_failed'),('could not open default font','xwayland_font_failed'),('exec of /private/password failed: Permission denied','xwayland_exec_failed')]:
   value=probe.classify(raw);self.assertEqual(value['reason'],reason);self.assertNotIn('private',json.dumps(value));self.assertIsNotNone(safe_log.validate_event(value))
  value=probe.classify('[01:02:03.456] /private/Xwayland: error while loading shared libraries: libcrypto.so.1.1: cannot open shared object file: No such file or directory')
  self.assertEqual(value['library'],'libcrypto.so.1.1');self.assertNotIn('private',json.dumps(value))
  self.assertIsNone(probe.classify('[01:02:03.456] PD2_EVENT {"event":"compositor_note","note":"root_service"}'))
 def test_compositor_env_is_scoped_root_game_is_nonroot(self):
  source=(SCRIPTS/'weston-session.sh').read_text()
  self.assertIn('setsid env -u DISPLAY -u WAYLAND_DISPLAY',source)
  self.assertIn('XDG_RUNTIME_DIR="$R/compositor-runtime"',source)
  self.assertIn('SDL_VIDEO_EGL_DRIVER="$CRUSTY_LIBEGL"',source)
  self.assertIn('runuser -u "$PD2_USER" --preserve-environment -- env PD2_AUDIO_TEST="${PD2_AUDIO_TEST:-1}" bash "$R/game-session.sh"',source)
  self.assertIn('CRUSTY_RESOLUTION=640x480',source);self.assertIn('-auth "%s/xauthority"',source);self.assertIn('PD2_XAUTHORITY="$R/xauthority"',source);self.assertNotIn('--use-pixman',source)
  self.assertIn('mkfifo -m600 "$R/compositor.pipe" || { error invalid_layout;exit 2; }',source)
  self.assertIn('[[ -p "$R/compositor.pipe" && ! -L "$R/compositor.pipe" ]]',source)
if __name__=='__main__':unittest.main()
