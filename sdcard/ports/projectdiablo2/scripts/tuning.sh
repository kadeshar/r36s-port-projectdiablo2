#!/bin/bash
# Explicit session-only experiments. Never source user config or evaluate strings.
pd2_validate_tuning() {
 case "${PD2_RENDERER_VARIANT:-stock}" in stock|gles2) ;; *) return 1;; esac
 case "${PD2_BOX_VARIANT:-stock}" in stock|a35) ;; *) return 1;; esac
 if [[ ${PD2_RENDERER_VARIANT:-stock} == gles2 ]]; then
  [[ ${PD2_PERFORMANCE:-off} == opengl && ${PD2_TUNING:-off} == gl-kms && ${PD2_FPS:-0} == 0 && ${PD2_DIAGNOSTIC:-off} == off && ${PD2_CONTROLLER_TEST:-0} == 0 && ${PD2_BIGBLOCK:-1} == 1 ]] || return 1
 fi
 case "${PD2_TUNING:-off}" in
  off) return 0;;
  baseline|forward512|callret|fastflags) [[ ${PD2_PERFORMANCE:-off} == gdi ]];;
  gl-auto|gl-kms) [[ ${PD2_PERFORMANCE:-off} == opengl ]];;
  crusty_glx_gl4es)
   [[ ${PD2_PERFORMANCE:-off} == opengl && ${PD2_RENDERER_VARIANT:-stock} == stock && ${PD2_DIAGNOSTIC:-off} == off && ${PD2_START_MENU:-0} == 0 && ${PD2_FPS:-0} == 0 && ${PD2_CONTROLLER_TEST:-0} == 0 ]] ;;
  *) return 1;;
 esac
}
# Header/ABI checks only: never dlopen ARMHF libraries in native Python.
# Runtime wrappers must resolve inside the pinned, read-only Westonpack mount.
pd2_validate_glx_libraries() {
 python3 -B - "$@" <<'PY'
import pathlib,struct,sys
try:
 root=pathlib.Path(sys.argv[1]).resolve(strict=True)
 wrappers=[root/'lib_armhf/graphics/crusty_glx/libcrusty.so',root/'lib_armhf/graphics/gl4es_glxpass/libGL.so.1']
 providers=[pathlib.Path(p) for p in sys.argv[2:]]
 if len(providers)!=5:raise ValueError()
 for index,path in enumerate(wrappers+providers):
  if not path.is_absolute():raise ValueError()
  path=path.resolve(strict=True)
  if not path.is_file():raise ValueError()
  if index<2:
   if not path.is_relative_to(root/'lib_armhf/graphics'):raise ValueError()
  elif any(path.is_relative_to(root/p) for p in ('lib_armhf/graphics','lib_aarch64/graphics')):raise ValueError()
  with path.open('rb') as stream:header=stream.read(52)
  if len(header)!=52 or header[:7]!=b'\x7fELF\x01\x01\x01':raise ValueError()
  if struct.unpack_from('<HHI',header,16)!=(3,40,1):raise ValueError()
  # EF_ARM_ABI_FLOAT_HARD, never soft-float or AArch64/x86 impostors.
  flags=struct.unpack_from('<I',header,36)[0]
  if not flags & 0x400 or flags & 0x200:raise ValueError()
except (OSError,ValueError,IndexError):sys.exit(1)
PY
}
pd2_tune_box_env() {
 # Called after every native-library refresh (including ALSA compatibility).
 # Only Wine/Box children inherit these overrides; Python/mapper/Weston do not.
 case "${PD2_TUNING:-off}" in
  off) return 0;;
  baseline|forward512|callret|fastflags)
   # Registry/prefix setup and recovery must never use risky game overrides.
   [[ ${PD2_GAME_TUNING_ACTIVE:-0} == 1 ]] || return 0
   box_env+=(BOX86_DYNAREC_FORWARD=128 BOX86_DYNAREC_CALLRET=0 BOX86_DYNAREC_SAFEFLAGS=1)
   case "$PD2_TUNING" in
    forward512) box_env+=(BOX86_DYNAREC_FORWARD=512);;
    callret) box_env+=(BOX86_DYNAREC_CALLRET=1);;
    fastflags) box_env+=(BOX86_DYNAREC_SAFEFLAGS=0);;
   esac;;
  gl-auto|gl-kms|crusty_glx_gl4es)
   # Remove the global X11 choice only in the native SDL consumer (Crusty).
   # Wine itself still uses DISPLAY/X11 for window management.
   box_env=(env -u SDL_VIDEODRIVER "${box_env[@]:1}")
   box_env+=(XDG_SESSION_TYPE=x11 SDL_VIDEO_EGL_DRIVER="$PD2_CRUSTY_EGL")
   if [[ "$PD2_TUNING" == gl-kms || "$PD2_TUNING" == crusty_glx_gl4es ]]; then box_env+=(SDL_VIDEODRIVER=kmsdrm); fi
   if [[ "$PD2_TUNING" == crusty_glx_gl4es ]]; then
    box_env+=(SDL_VIDEO_GL_DRIVER="$PD2_CRUSTY_GLES" BOX86_DYNAREC_SAFEFLAGS=1 BOX86_DYNAREC_CALLRET=0)
   fi
    if [[ ${PD2_RENDERER_VARIANT:-stock} == gles2 ]]; then
     box_env+=(LIBGL_ES=2 LIBGL_GL=21 LIBGL_VABGRA=0 LIBGL_NOERROR=0 LIBGL_NOTEST=0 LIBGL_NOPSA=1)
    fi;;
 esac
}
