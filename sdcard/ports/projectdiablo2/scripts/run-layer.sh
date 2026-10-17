#!/bin/bash
# Source only from run-game.sh: all paths are fixed and probe bytes authenticated.
pd2_run_layer() {
 local mode=$1 rc
 step graphics_test
 if [[ $mode == ddraw ]]; then
  python3 -B "$PD2_PORT/scripts/graphics_artifacts.py" --port "$PD2_PORT" --work "$PD2_WORK" --arch win32 || { error invalid_layout 1; return 1; }
  timeout --kill-after=2 15 "${box_env[@]}" "$PD2_BOX" "$PD2_WINE/bin/wine" explorer.exe /desktop=PD2Native,640x480 start.exe /d 'C:\Diablo II\ProjectD2' /exec 'C:\Diablo II\ProjectD2\pd2-graphics.exe' 2>&1 | python3 -B "$PD2_PORT/scripts/diagnostic_capture.py"
  rc=${PIPESTATUS[0]}
 else
  python3 -B "$PD2_PORT/scripts/graphics_artifacts.py" --port "$PD2_PORT" --work "$PD2_WORK" --arch armhf || { error invalid_layout 1; return 1; }
  # No Box86 for native ARMHF. Use its real SDL/EGL providers, not AArch64 ones.
  local native_env=("${box_env[@]}")
  if [[ $mode == sdl ]]; then
   native_env+=(LD_PRELOAD= LD_LIBRARY_PATH="$PD2_NATIVE_REAL_LIBS" SDL_VIDEO_GL_DRIVER="$PD2_CRUSTY_GLES")
  fi
  timeout --kill-after=2 15 "${native_env[@]}" "$PD2_PORT/compat/graphics-probe/graphics-layers.armhf" --mode "$mode" 2>&1 | python3 -B "$PD2_PORT/scripts/diagnostic_capture.py"
  rc=${PIPESTATUS[0]}
 fi
 case $rc in
  0) printf 'PD2_EVENT {"event":"session_probe","phase":"launch","check":"graphics_test_result","status":"completed"}\n';;
  124|137) printf 'PD2_EVENT {"event":"session_probe","phase":"launch","check":"graphics_test_result","status":"timeout"}\n';;
  *) printf 'PD2_EVENT {"event":"session_probe","phase":"launch","check":"graphics_test_result","status":"failed"}\n';;
 esac
 return "$rc"
}
