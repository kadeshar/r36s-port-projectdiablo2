#!/usr/bin/env python3
"""Resolve known native providers; output only a path to the caller and enum telemetry.
Never log a path, environment, arbitrary dlerror text, username or driver string.
"""
import argparse,json,os,pathlib,re,struct,subprocess,sys
sys.dont_write_bytecode=True
CANDIDATES={
 'sdl':('libSDL2.so','libSDL2.so.0','libSDL2-2.0.so','libSDL2-2.0.so.0'),
 'egl':('libEGL.so','libEGL.so.1'),
 'gles':('libGLESv2.so.2','libGLESv2.so'),
 'gbm':('libgbm.so.1','libgbm.so'),
 'drm':('libdrm.so','libdrm.so.2','libdrm.so.1'),
}
ARCH={'aarch64':(2,183),'armhf':(1,40)}
def event(role,arch,status):
 print('PD2_EVENT '+json.dumps({'event':'graphics_probe','role':role,'arch':arch,'status':status},separators=(',',':')),file=sys.stderr,flush=True)
def valid_native(path,arch,weston):
 try:
  p=pathlib.Path(path)
  if not p.is_absolute() or not p.is_file():return None
  p=p.resolve()
  # Do not hand a Crusty/Mesa proxy back to Crusty as its REAL SDL/EGL/GBM.
  if p.is_relative_to(pathlib.Path(weston).resolve()/'lib_aarch64/graphics') or p.is_relative_to(pathlib.Path(weston).resolve()/'lib_armhf/graphics'):return None
  with p.open('rb') as f:header=f.read(20)
  cls,machine=ARCH[arch]
  if len(header)!=20 or header[:4]!=b'\x7fELF' or header[4]!=cls or header[5]!=1 or struct.unpack_from('<H',header,18)[0]!=machine:return None
  return str(p)
 except (OSError,ValueError):return None

def resolve(weston,role,arch,search,runner=subprocess.run):
 tool=pathlib.Path(weston)/'tools'/('findlib' if arch=='aarch64' else 'findlib32')
 env=dict(os.environ,LD_LIBRARY_PATH=search,LD_PRELOAD='')
 invalid=False;failed=False
 for name in CANDIDATES[role]:
  try:
   result=runner([str(tool),name],env=env,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,encoding='utf-8',errors='replace',timeout=5)
  except (OSError,subprocess.SubprocessError):failed=True;continue
  if result.returncode!=0:failed=failed or result.returncode<0;continue
  lines=result.stdout.strip().splitlines()
  if not lines:continue
  chosen=valid_native(lines[-1],arch,weston)
  if chosen:return chosen,'ready'
  invalid=True
 return None,('invalid' if invalid else 'probe_failed' if failed else 'missing')

def classify(text):
 from safe_log import parse_line,validate_event
 # Existing narrow loader/fault patterns; never accept incoming PD2_EVENT text.
 if not text.startswith('PD2_EVENT '):
  value=parse_line(text)
  if value:return value
 line=re.sub(r'^\[[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{3}\]\s*','',text.rstrip('\r\n'))
 note=None
 for module,label in [('drm-backend.so','drm_module'),('gl-renderer.so','gl_module'),('kiosk-shell.so','shell_module'),('xwayland.so','xwayland_module')]:
  if re.fullmatch(r"Loading module '[^\r\n]{1,512}/"+re.escape(module)+r"'",line):note=label
 if re.fullmatch(r'EGL version: [0-9]+\.[0-9]+[^\r\n]{0,128}',line):note='egl_ready'
 if re.fullmatch(r'GL version: [^\r\n]{1,128}',line):note='gl_ready'
 if re.fullmatch(r'Output .{1,128} enabled with head\(s\) .{1,128}',line):note='output_ready'
 if line=='xserver listening on display :0':note='xserver_listening'
 if re.fullmatch(r'Spawned Xwayland server, pid [0-9]{1,10}',line):note='xwayland_spawn'
 if line=='xserver exited, will restart on demand':note='xwayland_restart'
 if line=='xserver crashing too fast, not restarting':note='xwayland_crash'
 if line in ('Failed to initialize glamor, falling back to sw','EGL setup failed, disabling glamor','EGL backend init_screen() failed, disabling glamor','Failed to get wl_drm, disabling Glamor and DRI3'):note='xwayland_software_fallback'
 if line in ('XKB: Failed to load keymap. Loading default keymap instead.','Errors from xkbcomp are not fatal to the X server'):note='xwayland_keymap_fallback'
 if note:return {'event':'compositor_note','phase':'runtime','note':note}
 if line in ('Failed to spawn the Xwayland server','xcb_connect_to_fd failed'):
  return {'event':'runtime_error','phase':'runtime','reason':'xwayland_start_failed'}
 if line in ('could not open default font','could not open default cursor font'):
  return {'event':'runtime_error','phase':'runtime','reason':'xwayland_font_failed'}
 if re.fullmatch(r'exec of .{1,512} failed: .{1,128}',line):
  return {'event':'runtime_error','phase':'runtime','reason':'xwayland_exec_failed'}
 # Timestamp-prefixed loader errors must also be categorized, without echo.
 if not line.startswith('PD2_EVENT '):
  value=parse_line(line)
  if value:return value
 low=line.lower()
 for phrase,reason in [('failed to initialize egl','egl_init_failed'),('failed to create gbm device','gbm_init_failed'),('failed to create gl context','gl_context_failed'),('failed to create gles context','gl_context_failed'),('could not initialize sdl','sdl_init_failed'),('sdl_createwindow failed','sdl_init_failed'),('failed to load module','compositor_module_failed')]:
  if phrase in low:return {'event':'runtime_error','phase':'runtime','reason':reason}
 if 'permission denied' in low and any(word in low for word in ('drm','mali','/dev/fb')):
  return {'event':'runtime_error','phase':'runtime','reason':'driver_access_denied'}
 return None

def stream(source,sink):
 from safe_log import MAX_LINE,validate_event
 oversized=False
 while True:
  chunk=source.readline(MAX_LINE+1)
  if not chunk:break
  if oversized or len(chunk)>MAX_LINE:
   oversized=not chunk.endswith(b'\n');continue
  value=classify(chunk.decode('utf-8','replace'))
  if value and validate_event(value):
   try:sink.write('PD2_EVENT '+json.dumps(value,separators=(',',':'))+'\n');sink.flush()
   except (OSError,ValueError):pass  # Continue draining; never fall back to raw.

def main():
 if sys.argv[1:]==['--stream']:
  stream(sys.stdin.buffer,sys.stdout);return 0
 parser=argparse.ArgumentParser()
 parser.add_argument('--weston',required=True);parser.add_argument('--role',choices=tuple(CANDIDATES),required=True)
 parser.add_argument('--arch',choices=tuple(ARCH),required=True);parser.add_argument('--search',default='')
 args=parser.parse_args()
 path,status=resolve(args.weston,args.role,args.arch,args.search)
 event(args.role,args.arch,status)
 if path:print(path);return 0
 return 1
if __name__=='__main__':raise SystemExit(main())
