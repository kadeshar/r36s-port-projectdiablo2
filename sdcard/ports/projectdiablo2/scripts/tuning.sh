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
  *) return 1;;
 esac
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
  gl-auto|gl-kms)
   # Remove the global X11 choice only in the native SDL consumer (Crusty).
   # Wine itself still uses DISPLAY/X11 for window management.
   box_env=(env -u SDL_VIDEODRIVER "${box_env[@]:1}")
   box_env+=(XDG_SESSION_TYPE=x11 SDL_VIDEO_EGL_DRIVER="$PD2_CRUSTY_EGL")
   if [[ "$PD2_TUNING" == gl-kms ]]; then box_env+=(SDL_VIDEODRIVER=kmsdrm); fi
    if [[ ${PD2_RENDERER_VARIANT:-stock} == gles2 ]]; then
     box_env+=(LIBGL_ES=2 LIBGL_GL=21 LIBGL_VABGRA=0 LIBGL_NOERROR=0 LIBGL_NOTEST=0 LIBGL_NOPSA=1)
    fi;;
 esac
}
