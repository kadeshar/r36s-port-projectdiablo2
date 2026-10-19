#!/bin/bash
set -u
ulimit -c 0
case "${PD2_DIAGNOSTIC:-off}" in off|present|sdl|glx|ddraw) ;; *) exit 1;; esac
PD2_GAME_TUNING_ACTIVE=0
export HOME="$PD2_HOME"
export WINEPREFIX="$PD2_PREFIX" WINEARCH=win32 WINEDEBUG=-all
export WINEDLLOVERRIDES='ddraw=n,b;winegstreamer=;winemenubuilder=;mscoree=;mshtml=;winepulse.drv='
export BOX86_LOG=1 BOX86_NORCFILES=1 BOX86_TRACE=0 BOX86_TRACE_INIT=0 BOX86_DUMP=0 BOX86_SHOWBT=0 BOX86_ROLLING_LOG=0 BOX86_JITGDB=0
# PortMaster compatibility: stable SDL GUIDs and optional-library diagnostics.
# Required native libraries are still validated by the privileged adapter.
export BOX86_SDL2_JGUID=1 BOX86_ALLOWMISSINGLIBS=1 BOX86_DLSYM_ERROR=1
# Preserve the production GDI dynarec defaults; setup/recovery use smaller blocks.
export BOX86_DYNAREC=1 BOX86_DYNAREC_BIGBLOCK=2
export BOX86_DYNAREC_SAFEFLAGS=1 BOX86_DYNAREC_STRONGMEM=0 BOX86_DYNAREC_CALLRET=0
export SDL_GAMECONTROLLERCONFIG="$PD2_CONTROLLER_CONFIG" SDL_VIDEODRIVER=x11
export FONTCONFIG_FILE="$PD2_WESTON/fonts/fonts.conf"
mapper_pid=; mapper_metrics_pid=; navigator_pid=; game_pid=; metrics_pid=; fps_pid=; audio_probe_pid=; audio_capture_pid=; wine_ready=0
winebus_restore_attempted=0; audio_restore_attempted=0; dsound_restore_attempted=0
winebus_restore_file="$PD2_PREFIX/drive_c/pd2-winebus-restore.reg"
audio_restore_file="$PD2_PREFIX/drive_c/pd2-audio-restore.reg"
dsound_restore_file="$PD2_PREFIX/drive_c/pd2-dsound-restore.reg"
setup_step=initial
step() {
 setup_step=$1
 printf 'PD2_EVENT {"event":"setup_stage","phase":"launch","stage":"%s","status":"begin"}\n' "$setup_step"
}
step_failed() {
 printf 'PD2_EVENT {"event":"setup_stage","phase":"launch","stage":"%s","status":"failed"}\n' "$setup_step"
}
phase() { printf 'PD2_EVENT {"event":"phase","phase":"%s","profile":"%s"}\n' "$1" "$PD2_PROFILE"; }
error() { step_failed; printf 'PD2_EVENT {"event":"runtime_error","reason":"%s","phase":"launch","rc":%s}\n' "$1" "$2"; }
# Apply armhf preload only to ARM32 Box86, never the native 64-bit shell/Python.
refresh_box_env() {
 box_env=(env LD_LIBRARY_PATH="$PD2_NATIVE_LIBS" LD_PRELOAD="$PD2_NATIVE_PRELOAD"
  CRUSTY_LIBSDL="$PD2_CRUSTY_SDL" CRUSTY_LIBEGL="$PD2_CRUSTY_EGL" CRUSTY_LIBGBM="$PD2_CRUSTY_GBM" CRUSTY_LIBDRM="$PD2_CRUSTY_DRM")
 if [[ -n "${ALSA_CONFIG_PATH:-}" ]]; then
  box_env+=(ALSA_CONFIG_PATH="$ALSA_CONFIG_PATH")
 fi
 if [[ ${PD2_GAME_TUNING_ACTIVE:-0} == 0 ]]; then
  box_env+=(BOX86_DYNAREC_BIGBLOCK=1 BOX86_DYNAREC_SAFEFLAGS=1 BOX86_DYNAREC_CALLRET=0)
 fi
}
refresh_box_env
wine_cmd() { "${box_env[@]}" "$PD2_BOX" "$PD2_WINE/bin/wine" "$@"; }
server_cmd() { "${box_env[@]}" "$PD2_BOX" "$PD2_WINE/bin/wineserver" "$@"; }
setup_cmd() { timeout --kill-after=5 45 "${box_env[@]}" "$PD2_BOX" "$PD2_WINE/bin/wine" "$@"; }
stop_wine() {
 # Wine returns 1 from -k when this prefix has no live server. Treat only
 # that documented no-server result as benign; timeout/other failures stay
 # fatal so a marker cannot be retired before Wine is quiescent.
 local kill_rc wait_rc
 timeout --kill-after=5 10 "${box_env[@]}" "$PD2_BOX" "$PD2_WINE/bin/wineserver" -k; kill_rc=$?
 timeout --kill-after=5 30 "${box_env[@]}" "$PD2_BOX" "$PD2_WINE/bin/wineserver" -w; wait_rc=$?
 [[ "$wait_rc" == 0 && ( "$kill_rc" == 0 || "$kill_rc" == 1 ) ]]
}
restore_winebus() {
 [[ -e "$winebus_restore_file" || -L "$winebus_restore_file" ]] || return 0
 winebus_restore_attempted=1
 python3 -B "$PD2_PORT/scripts/winebus_config.py" --prefix "$PD2_PREFIX" --validate || return 1
 setup_cmd reg.exe import 'C:\pd2-winebus-restore.reg' || return 1
 stop_wine || return 1
 python3 -B "$PD2_PORT/scripts/winebus_config.py" --prefix "$PD2_PREFIX" --retire || return 1
 printf 'PD2_EVENT {"event":"session_probe","phase":"launch","check":"winebus_backend","status":"restored"}\n'
}
# Restore the opt-in Audio experiment, including interrupted sessions.
# Only the original Audio value is restored; no mixer/system writes.
restore_audio() {
 [[ -e "$audio_restore_file" || -L "$audio_restore_file" ]] || return 0
 audio_restore_attempted=1
 python3 -B "$PD2_PORT/scripts/audio_config.py" --prefix "$PD2_PREFIX" --validate || return 1
 stop_wine || return 1
 setup_cmd reg.exe import 'C:\pd2-audio-restore.reg' || return 1
 stop_wine || return 1
 python3 -B "$PD2_PORT/scripts/audio_config.py" --prefix "$PD2_PREFIX" --retire || return 1
 printf 'PD2_EVENT {"event":"session_probe","phase":"launch","check":"audio_backend","status":"restored"}\n'
}
# Restore the opt-in DirectSound experiment, including interrupted sessions.
# Only the five named DirectSound strings are restored; no other registry data.
restore_dsound() {
 [[ -e "$dsound_restore_file" || -L "$dsound_restore_file" ]] || return 0
 dsound_restore_attempted=1
 python3 -B "$PD2_PORT/scripts/audio_dsound.py" --prefix "$PD2_PREFIX" --validate || return 1
 stop_wine || return 1
 setup_cmd reg.exe import 'C:\pd2-dsound-restore.reg' || return 1
 stop_wine || return 1
 python3 -B "$PD2_PORT/scripts/audio_dsound.py" --prefix "$PD2_PREFIX" --retire || return 1
 printf 'PD2_EVENT {"event":"session_probe","phase":"launch","check":"dsound_backend","status":"restored"}\n'
}
stop_owned() {
 local pid=$1
 [[ "$pid" =~ ^[0-9]+$ && "$pid" -gt 1 ]] || return 0
 kill -TERM -- "-$pid" 2>/dev/null || true
 for ((i=0;i<30;i++)); do kill -0 "$pid" 2>/dev/null || break;sleep 0.1;done
 kill -KILL -- "-$pid" 2>/dev/null || true
 wait "$pid" 2>/dev/null || true
}
report_audio_driver() {
 # Conservative, bounded classification of this probe's +alsa stderr.
 # The raw log lives only in volatile RAM and is never persisted. A marker
 # line, written by the probe's own child, proves the capture path itself
 # works even when Wine emits nothing (detail=silent instead of no_log).
 local log="$1" status=failed detail=no_log scan
 if [[ "${2:-0}" != 0 ]]; then
  detail=capture_error
  [[ "$2" == timeout ]] && detail=capture_timeout
 elif [[ -s "$log" ]]; then
  scan="$(head -c 262144 "$log")"
  # libasound is checked before generic loader errors: a missing unix-side
  # ALSA library also surfaces as an err:module: import failure.
  if ! grep -aqx 'pd2-capture-marker' <<< "$scan"; then
   detail=capture_error
  elif ! grep -avq '^pd2-capture-marker$' <<< "$scan"; then
   detail=silent
  elif grep -aqiE 'libasound\.so\.2' <<< "$scan" && grep -aqiE 'cannot open shared object|no such file|not found|error while loading|cannot be found|undefined symbol' <<< "$scan"; then
   detail=libasound
  elif grep -aqE 'err:module:|LdrInitializeThunk|failed to load' <<< "$scan"; then
   detail=load_error
  elif grep -aqE 'err:alsa:' <<< "$scan"; then
   detail=alsa_error
  elif grep -aqE 'trace:alsa:' <<< "$scan"; then
   status=loaded
  else
   detail=unknown
  fi
 fi
 if [[ "$status" == loaded ]]; then
  printf 'PD2_EVENT {"event":"session_probe","phase":"launch","check":"audio_driver","status":"loaded"}\n'
 else
  printf 'PD2_EVENT {"event":"session_probe","phase":"launch","check":"audio_driver","status":"failed","detail":"%s"}\n' "$detail"
 fi
}
run_one_audio_probe() {
 # Return success only when the actual Wine playback path completed. Arg 1
 # requests a bounded WINEDEBUG=+alsa capture for this attempt.
 local capture="${1:-0}" probe_rc=0 probe_state=running capture_rc=0 audio_capture_fd
 local driver_log="$PD2_WORK/audio-driver.log"
 # Same user, namespace and ALSA_CONFIG_PATH as Wine, but native ARM32 and
 # the same native-library search environment. Finish/close PCM before Wine.
 python3 -B "$PD2_PORT/scripts/audio_native.py" --port "$PD2_PORT" --work "$PD2_WORK" || true
 python3 -B "$PD2_PORT/scripts/audio_result.py" --prepare --port "$PD2_PORT" --work "$PD2_WORK" || {
  python3 -B "$PD2_PORT/scripts/audio_result.py" --work "$PD2_WORK" || true
  return 1
 }
 if [[ "$capture" == 1 ]]; then
  # Save the collector PID separately; wait for EOF before inspecting its file.
  # A single unbuffered process stores at most 256 KiB and drains the rest.
  exec {audio_capture_fd}> >(exec python3 -B -c '
import os, sys
remaining = 262144
with open(sys.argv[1], "xb", buffering=0) as output:
    while True:
        data = os.read(0, 8192)
        if not data:
            break
        kept = data[:remaining]
        if kept:
            output.write(kept)
            remaining -= len(kept)
' "$driver_log")
  audio_capture_pid=$!
  # Keep the native shell outside the ARM32 library environment; apply that
  # environment only after exec, to Box86 itself.
  setsid bash -c 'printf "pd2-capture-marker\n" >&2; exec "$@"' pd2-capture "${box_env[@]}" WINEDEBUG=+alsa "$PD2_BOX" "$PD2_WINE/bin/wine" 'C:\Diablo II\ProjectD2\pd2-audio-probe.exe' 2>&"$audio_capture_fd" {audio_capture_fd}>&- & audio_probe_pid=$!
  exec {audio_capture_fd}>&-
 else
  setsid "${box_env[@]}" "$PD2_BOX" "$PD2_WINE/bin/wine" 'C:\Diablo II\ProjectD2\pd2-audio-probe.exe' & audio_probe_pid=$!
 fi
 printf '%s\n' "$audio_probe_pid" > "$PD2_RUN/audio.pid"
 for ((i=0;i<300;i++)); do
  if ! kill -0 "$audio_probe_pid" 2>/dev/null; then probe_state=exited; break; fi
  if [[ "$(ps -o stat= -p "$audio_probe_pid" 2>/dev/null | tr -d ' ')" == Z* ]]; then probe_state=exited; break; fi
  sleep 0.1
 done
 if [[ "$probe_state" == running ]]; then
  stop_owned "$audio_probe_pid"; probe_rc=124
 else
  wait "$audio_probe_pid" 2>/dev/null || probe_rc=$?
 fi
 audio_probe_pid=
 python3 -B "$PD2_PORT/scripts/audio_result.py" --usable --work "$PD2_WORK"; local usable_rc=$?
 # Descendants (including wineserver) may still own stderr. Stop them before
 # waiting for EOF; otherwise buffered/late output can be mistaken for silence.
 stop_wine || true
 if [[ "$capture" == 1 ]]; then
  for ((i=0;i<30;i++)); do
   kill -0 "$audio_capture_pid" 2>/dev/null || break
   sleep 0.1
  done
  if kill -0 "$audio_capture_pid" 2>/dev/null; then
   capture_rc=timeout
   kill -KILL "$audio_capture_pid" 2>/dev/null || true
  fi
  wait "$audio_capture_pid" 2>/dev/null || { [[ "$capture_rc" == timeout ]] || capture_rc=error; }
  audio_capture_pid=
  report_audio_driver "$driver_log" "$capture_rc"
  if [[ "$capture_rc" == 0 ]]; then
   python3 -B "$PD2_PORT/scripts/audio_result.py" --driver-log --work "$PD2_WORK"
  else
   printf 'PD2_EVENT {"event":"session_probe","phase":"launch","check":"audio_alsa_capture","status":"unavailable"}\n'
  fi
 fi
 [[ -L "$PD2_WORK/ProjectD2/pd2-audio-probe.exe" ]] && unlink "$PD2_WORK/ProjectD2/pd2-audio-probe.exe"
 [[ -f "$PD2_WORK/ProjectD2/pd2-audio-result.json" && ! -L "$PD2_WORK/ProjectD2/pd2-audio-result.json" ]] && unlink "$PD2_WORK/ProjectD2/pd2-audio-result.json"
 [[ -f "$driver_log" && ! -L "$driver_log" ]] && unlink "$driver_log"
 [[ "$probe_rc" == 124 ]] && printf 'PD2_EVENT {"event":"session_probe","phase":"launch","check":"audio_test","status":"invalid"}\n'
 return "$usable_rc"
}
run_audio_probe() {
 # Try the explicit rk817 route first. If its real PCM/WinMM test fails,
 # retry once against the system ALSA default before launching Game.exe.
 # The fallback decision is always logged; a private rk817 config that did
 # not prove playback is cleared so the game never inherits a broken route.
 local private_active=0
 printf 'PD2_EVENT {"event":"session_probe","phase":"launch","check":"audio_diagnostics","status":"legacy_v7"}\n'
 [[ -n "${ALSA_CONFIG_PATH:-}" && -f "$PD2_RUN/alsa-pd2.conf" ]] && private_active=1
 if run_one_audio_probe 1; then
  printf 'PD2_EVENT {"event":"session_probe","phase":"launch","check":"audio_fallback","status":"skipped"}\n'
  return 0
 fi
 if [[ "$private_active" == 1 ]]; then
  unset ALSA_CONFIG_PATH
  refresh_box_env
  unlink "$PD2_RUN/alsa-pd2.conf" 2>/dev/null || true
  printf 'PD2_EVENT {"event":"session_probe","phase":"launch","check":"audio_fallback","status":"attempted"}\n'
  printf 'PD2_EVENT {"event":"session_probe","phase":"launch","check":"audio_route","status":"default"}\n'
  run_one_audio_probe 1 || true
 else
  printf 'PD2_EVENT {"event":"session_probe","phase":"launch","check":"audio_fallback","status":"skipped"}\n'
 fi
}
cleanup() {
 local rc=$?;trap - EXIT INT TERM
 # Recovery always runs with conservative setup flags.
 PD2_GAME_TUNING_ACTIVE=0
 refresh_box_env
 stop_owned "$metrics_pid"
 stop_owned "$mapper_metrics_pid"
 stop_owned "$audio_probe_pid"
 if [[ -n "$audio_capture_pid" ]]; then
  kill -KILL "$audio_capture_pid" 2>/dev/null || true
  wait "$audio_capture_pid" 2>/dev/null || true
 fi
 stop_owned "$fps_pid"
 stop_owned "$navigator_pid"
 stop_owned "$mapper_pid"
 stop_owned "$game_pid"
 # Restore ONLY the three backed-up flags after game exit. Keep the marker on
 # failure; the next startup (including mapper fallback) retries restoration.
 if [[ "$wine_ready" == 1 && "$winebus_restore_attempted" == 0 ]] && ! restore_winebus; then
  error invalid_layout 1
  [[ "$rc" == 0 ]] && rc=1
 fi
 if [[ "$wine_ready" == 1 && "$audio_restore_attempted" == 0 ]] && ! restore_audio; then
  error invalid_layout 1
  [[ "$rc" == 0 ]] && rc=1
 fi
 if [[ "$wine_ready" == 1 && "$dsound_restore_attempted" == 0 ]] && ! restore_dsound; then
  error invalid_layout 1
  [[ "$rc" == 0 ]] && rc=1
 fi
 # Prefix-specific shutdown AND wait. Retain failure status if it cannot quiesce.
 step prefix_shutdown
 if [[ ${PD2_DIAGNOSTIC:-off} != sdl && ${PD2_DIAGNOSTIC:-off} != glx ]] && ! stop_wine; then
  error timeout 1
  [[ "$rc" == 0 ]] && rc=1
 fi
 # Persist only prevalidated tiny configuration files, never raw engine logs.
 python3 "$PD2_PORT/scripts/layout.py" --port "$PD2_PORT" --state "$PD2_STATE" --sync-config || true
 phase shutdown
 printf 'PD2_EVENT {"event":"runtime_exit","phase":"game","rc":%s}\n' "$rc"
 exit "$rc"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
phase launch
printf 'PD2_EVENT {"event":"session_probe","phase":"launch","check":"diagnostic_mode","status":"%s"}\n' "${PD2_DIAGNOSTIC:-off}"
if [[ ${PD2_DIAGNOSTIC:-off} != off ]]; then export PD2_METRICS=1; fi
case "${PD2_DIAGNOSTIC:-off}" in sdl|glx)
 source "$PD2_PORT/scripts/run-layer.sh" || exit 1
 pd2_run_layer "$PD2_DIAGNOSTIC"; exit $?;; esac
printf 'PD2_EVENT {"event":"session_probe","phase":"launch","check":"dynarec_bigblock","status":"%s"}\n' 2
input_mode="${PD2_INPUT_MODE:-mapper}"
controller_test="${PD2_CONTROLLER_TEST:-0}"
fps_enabled="${PD2_FPS:-0}"
audio_test="${PD2_AUDIO_TEST:-1}"
[[ "$audio_test" == 0 || "$audio_test" == 1 ]] || { error invalid_profile 1; exit 1; }
audio_probe="${PD2_AUDIO_PROBE:-0}"
[[ "$audio_probe" == 0 || "$audio_probe" == 1 ]] || { error invalid_profile 1; exit 1; }
# Opt-in SDL audio driver selection: defaults to alsa, dummy allowed for A/B tests.
audio_sdl="${PD2_AUDIO_SDL:-alsa}"
case "$audio_sdl" in alsa|dummy) ;; *) error invalid_profile 1; exit 1;; esac
export SDL_AUDIODRIVER="$audio_sdl"
[[ "$SDL_AUDIODRIVER" == "$audio_sdl" ]] || { error invalid_profile 1; exit 1; }
printf 'PD2_EVENT {"event":"session_probe","phase":"launch","check":"audio_sdl","status":"%s"}\n' "$audio_sdl"
# Opt-in PCM telemetry: measurement only.
audio_metrics_enabled="${PD2_AUDIO_METRICS:-0}"
[[ "$audio_metrics_enabled" == 0 || "$audio_metrics_enabled" == 1 ]] || { error invalid_profile 1; exit 1; }
# Opt-in DirectSound HelBuflen A/B; every applied value is backed up and restored.
dsound_mode="${PD2_AUDIO_DSOUND:-off}"
case "$dsound_mode" in off|ver2|wine) ;; *) error invalid_profile 1; exit 1;; esac
audio_variant="${PD2_AUDIO_VARIANT:-stock}"
case "$audio_variant" in A|B|C|D|buffer|dmix|stock) ;; *) error invalid_profile 1; exit 1;; esac
printf 'PD2_EVENT {"event":"session_probe","phase":"launch","check":"audio_variant","status":"%s"}\n' "$audio_variant"
printf 'PD2_EVENT {"event":"session_probe","phase":"launch","check":"audio_schema","status":"v1"}\n'
audio_route_profile="${PD2_AUDIO_ROUTE_PROFILE:-baseline}"
case "$audio_route_profile" in baseline|buffer80|buffer160|dmix160|dmix80) ;; *) error invalid_profile 1; exit 1;; esac
printf 'PD2_EVENT {"event":"session_probe","phase":"launch","check":"audio_route_profile","status":"%s"}\n' "$audio_route_profile"
case "$audio_variant" in
 A)
  if [[ "$audio_sdl" != alsa || "$dsound_mode" != off ]]; then
   error invalid_profile 1; exit 1
  fi
  ;;
 B)
  if [[ "$audio_sdl" != dummy || "$dsound_mode" != off ]]; then
   error invalid_profile 1; exit 1
  fi
  ;;
 C)
  if [[ "$audio_sdl" != dummy || "$dsound_mode" != ver2 ]]; then
   error invalid_profile 1; exit 1
  fi
  ;;
 D)
  if [[ "$audio_sdl" != dummy || "$dsound_mode" != wine ]]; then
   error invalid_profile 1; exit 1
  fi
  ;;
 buffer)
  if [[ "$audio_sdl" != dummy || "$dsound_mode" != off || "$audio_route_profile" != buffer* ]]; then
   error invalid_profile 1; exit 1
  fi
  ;;
 dmix)
  # Current Dmix launcher selects wine; retain off for earlier route-only tests.
  if [[ "$audio_sdl" != dummy || ( "$dsound_mode" != off && "$dsound_mode" != wine ) || "$audio_route_profile" != dmix* ]]; then
   error invalid_profile 1; exit 1
  fi
  ;;
 stock)
  if [[ "$dsound_mode" != off ]]; then
   error invalid_profile 1; exit 1
  fi
  ;;
esac
resolution="${PD2_GAME_RESOLUTION:-640x480}"
[[ "$fps_enabled" == 0 || "$fps_enabled" == 1 ]] || { error invalid_profile 1; exit 1; }
case "$resolution" in 640x480|800x600|1024x768|native) ;; *) error invalid_profile 1; exit 1;; esac
printf 'PD2_EVENT {"event":"session_probe","phase":"launch","check":"render_resolution","status":"%s"}\n' "$resolution"
[[ "$input_mode" == mapper || "$input_mode" == native ]] || { error invalid_profile 1; exit 1; }
[[ "$controller_test" == 0 || ( "$controller_test" == 1 && "$input_mode" == native ) ]] || { error invalid_profile 1; exit 1; }
profile="$PD2_PORT/defaults/controls.gptk"
[[ "$PD2_SWAP_AB" == 1 ]] && profile="$PD2_PORT/defaults/controls-swap.gptk"
# PortMaster supplies the trusted command; never globally target Game.exe.
read -r -a mapper <<< "$PD2_GPTOKEYB"
[[ ${#mapper[@]} -gt 0 ]] || { error unsupported_runtime 1; exit 1; }
if [[ ${mapper[-1]} == -1 || ${mapper[-1]} == -k || ${mapper[-1]} == -sudokill ]]; then unset 'mapper[-1]';fi
[[ ${#mapper[@]} -gt 0 ]] || { error unsupported_runtime 1; exit 1; }
kill_pattern="^bash ${0%.sh}[.]sh([[:space:]]|$)"
export HOTKEY=back TEXTINPUTINTERACTIVE=Y TEXTINPUTNOAUTOCAPITALS=Y PCKILLMODE=Y
export SDL_JOYSTICK_ALLOW_BACKGROUND_EVENTS=1
start_mapper() {
 local args=(-1 "$kill_pattern" -c "$profile")
 if [[ "$input_mode" == native ]]; then
  # This Wine has udev but no SDL backend. Create a standard virtual Xbox,
  # not a second keyboard/mouse; do not combine xbox360 with -c or text entry.
  args=(xbox360 -1 "$kill_pattern")
 fi
 setsid "${mapper[@]}" "${args[@]}" & mapper_pid=$!
 printf '%s\n' "$mapper_pid" > "$PD2_RUN/mapper.pid"
 sleep 0.2
 kill -0 "$mapper_pid" 2>/dev/null || { error unsupported_runtime 1; exit 1; }
}
start_xbox_mapper() {
 # Bundled evdev->uinput Xbox mapper: complete mapping of the built-in pad
 # (face buttons, both sticks, digital L2/R2 triggers, d-pad), independent
 # of the SDL build and gamecontrollerdb present on the image.
 setsid python3 -B "$PD2_PORT/scripts/xbox_mapper.py" & mapper_pid=$!
 printf '%s\n' "$mapper_pid" > "$PD2_RUN/mapper.pid"
 sleep 1.0
 if kill -0 "$mapper_pid" 2>/dev/null; then return 0; fi
 wait "$mapper_pid" 2>/dev/null || true
 # Fast fail: fall back to PortMaster gptokeyb (partial mapping on this image).
 printf 'PD2_EVENT {"event":"session_probe","phase":"launch","check":"controller_mapper","status":"fallback"}\n'
 start_mapper
}
if [[ "$input_mode" == native ]]; then
 export TEXTINPUTINTERACTIVE=N PCKILLMODE=N
 # Enumerate existing event IDs before spawning; require a NEW accessible virtual
 # Xbox before the first Wine process so startup does not rely on udev hotplug.
 python3 -B "$PD2_PORT/scripts/controller_probe.py" --snapshot "$PD2_RUN/controller-before.json" || { error unsupported_runtime 1; exit 1; }
 start_xbox_mapper
 python3 -B "$PD2_PORT/scripts/controller_probe.py" --wait "$PD2_RUN/controller-before.json" || { error unsupported_runtime 1; exit 1; }
 kill -0 "$mapper_pid" 2>/dev/null || { error unsupported_runtime 1; exit 1; }
fi
# Linux executable launchers avoid requiring a system-wide binfmt registration.
mkdir -p "$PD2_STATE/wine-launchers"
for prog in wine wineserver; do
 printf '#!/bin/bash\nexec env LD_LIBRARY_PATH="$PD2_NATIVE_LIBS" LD_PRELOAD="$PD2_NATIVE_PRELOAD" CRUSTY_LIBSDL="$PD2_CRUSTY_SDL" CRUSTY_LIBEGL="$PD2_CRUSTY_EGL" CRUSTY_LIBGBM="$PD2_CRUSTY_GBM" CRUSTY_LIBDRM="$PD2_CRUSTY_DRM" "$PD2_BOX" "$PD2_WINE/bin/%s" "$@"\n' "$prog" > "$PD2_STATE/wine-launchers/$prog"
 chmod 700 "$PD2_STATE/wine-launchers/$prog"
done
export WINESERVER="$PD2_STATE/wine-launchers/wineserver" WINELOADER="$PD2_STATE/wine-launchers/wine"
# These DOS drive links live on Linux/ext4, not exFAT. No copying of game files.
ln -sfn "$PD2_PORT/runtime" "$WINEPREFIX/dosdevices/r:"
# Quiesce only our private prefix before setup/recovery. No global process kill.
step prefix_quiesce
stop_wine || { error timeout 1; exit 1; }
if [[ ! -f "$WINEPREFIX/.initialized" ]]; then
 step prefix_initialize
 if [[ -f "$WINEPREFIX/.initializing" ]]; then error prefix_incomplete 1; exit 1; fi
 : > "$WINEPREFIX/.initializing"
 timeout --kill-after=10 180 "${box_env[@]}" "$PD2_BOX" "$PD2_WINE/bin/wine" wineboot.exe -u
 rc=$?; if [[ "$rc" != 0 ]]; then error nonzero_exit "$rc"; exit "$rc"; fi
 timeout --kill-after=10 120 "${box_env[@]}" "$PD2_BOX" "$PD2_WINE/bin/wineserver" -w
 rc=$?; if [[ "$rc" != 0 ]]; then error timeout "$rc"; exit "$rc"; fi
 setup_cmd reg.exe add 'HKCU\Software\Wine' /v Version /t REG_SZ /d win10 /f || exit 1
 setup_cmd reg.exe add 'HKCU\Software\Wine\Drivers' /v Audio /t REG_SZ /d alsa /f || exit 1
 timeout --kill-after=10 180 "${box_env[@]}" "$PD2_BOX" "$PD2_WINE/bin/wine" 'R:\vc_redist.x86.exe' /install /quiet /norestart
 rc=$?; if [[ "$rc" != 0 && "$rc" != 194 ]]; then error nonzero_exit "$rc"; exit "$rc"; fi
 # Installation exit code alone is insufficient: check the native x86 VC DLLs.
 for dll in msvcp140.dll vcruntime140.dll; do
   [[ -f "$WINEPREFIX/drive_c/windows/system32/$dll" ]] || { error missing_library 1; exit 1; }
 done
 setup_cmd reg.exe add 'HKCU\Software\Wine\AppDefaults\Game.exe\DllOverrides' /v ddraw /t REG_SZ /d 'native,builtin' /f || exit 1
 mv "$WINEPREFIX/.initializing" "$WINEPREFIX/.initialized"
fi
wine_ready=1
# Recover a previous interrupted controller experiment BEFORE selecting a mode.
step recover_winebus
restore_winebus || { error invalid_layout 1; exit 1; }
step recover_audio
restore_audio || { error invalid_layout 1; exit 1; }
step recover_dsound
restore_dsound || { error invalid_layout 1; exit 1; }
if [[ "$audio_test" == 1 ]]; then
 # Export the existing parent key: success also proves a missing Drivers/Audio.
 # Publish a durable, Audio-only restore marker BEFORE touching the registry.
 step audio_prepare
 python3 -B "$PD2_PORT/scripts/audio_config.py" --prefix "$PD2_PREFIX" --prepare-export || { error invalid_layout 1; exit 1; }
 step audio_export
 setup_cmd reg.exe export 'HKCU\Software\Wine' 'C:\pd2-audio-export.reg' /y || { error invalid_layout 1; exit 1; }
 step audio_snapshot
 python3 -B "$PD2_PORT/scripts/audio_config.py" --prefix "$PD2_PREFIX" --snapshot || { error invalid_layout 1; exit 1; }
 step audio_select
 setup_cmd reg.exe add 'HKCU\Software\Wine\Drivers' /v Audio /t REG_SZ /d alsa /f || { error invalid_layout 1; exit 1; }
 stop_wine || { error timeout 1; exit 1; }
 # Only this opt-in session selects the time32 ARM32 libasound. Wine is
 # quiescent before switching; native ARM32 probes inherit the same path.
 if python3 -B "$PD2_PORT/scripts/audio_compat.py" --port "$PD2_PORT" --work "$PD2_WORK"; then
  export PD2_NATIVE_LIBS="$PD2_WORK/.alsa-legacy-armhf:$PD2_NATIVE_LIBS"
  refresh_box_env
 fi
 # Session-local rk817 routing only if unambiguous, accessible and not busy.
 # Missing/denied/busy devices retain the system ALSA default; never change mixers.
 step audio_route
 python3 -B "$PD2_PORT/scripts/audio_config.py" --route --run "$PD2_RUN" --profile "$audio_route_profile" || { error invalid_layout 1; exit 1; }
 if [[ -f "$PD2_RUN/alsa-pd2.conf" && ! -L "$PD2_RUN/alsa-pd2.conf" ]]; then
  export ALSA_CONFIG_PATH="$PD2_RUN/alsa-pd2.conf"
  refresh_box_env
  printf 'PD2_EVENT {"event":"session_probe","phase":"launch","check":"audio_config_path","status":"active"}\n'
 else
  printf 'PD2_EVENT {"event":"session_probe","phase":"launch","check":"audio_config_path","status":"default"}\n'
 fi
 printf 'PD2_EVENT {"event":"session_probe","phase":"launch","check":"audio_backend","status":"alsa"}\n'
fi
if [[ "$dsound_mode" != off ]]; then
 # Back up the whole DirectSound key BEFORE the first mutation; a missing key is
 # recorded as an explicit deletion marker, never inferred from a stale export.
 dsound_restore_attempted=0
 step dsound_prepare
 python3 -B "$PD2_PORT/scripts/audio_dsound.py" --prefix "$PD2_PREFIX" --prepare-export || { error invalid_layout 1; exit 1; }
 step dsound_export
 setup_cmd reg.exe export 'HKCU\Software\Wine' 'C:\pd2-dsound-export.reg' /y || { error invalid_layout 1; exit 1; }
 step dsound_snapshot
 python3 -B "$PD2_PORT/scripts/audio_dsound.py" --prefix "$PD2_PREFIX" --snapshot || { error invalid_layout 1; exit 1; }
 step dsound_select
 case "$dsound_mode" in
  ver2)
   while read -r name value; do
    setup_cmd reg.exe add 'HKCU\Software\Wine\DirectSound' /v "$name" /t REG_SZ /d "$value" /f || { error invalid_layout 1; exit 1; }
   done <<'DSOUND_VER2'
HelBuflen 8192
MaxHardwareChannels 16
SndQueueMax 28
DefaultSampleRate 44100
DefaultBitsPerSample 16
DSOUND_VER2
   ;;
  wine)
   setup_cmd reg.exe add 'HKCU\Software\Wine\DirectSound' /v HelBuflen /t REG_SZ /d 65536 /f || { error invalid_layout 1; exit 1; }
   ;;
 esac
 # DirectSound reads these values when it loads per process; quiesce so only the
 # freshly started Game.exe inherits them.
 stop_wine || { error timeout 1; exit 1; }
 step dsound_verify
 setup_cmd reg.exe export 'HKCU\Software\Wine' 'C:\pd2-dsound-verify.reg' /y || { error invalid_layout 1; exit 1; }
 python3 -B "$PD2_PORT/scripts/audio_dsound.py" --prefix "$PD2_PREFIX" --verify-applied "$dsound_mode" || { error invalid_layout 1; exit 1; }
 printf 'PD2_EVENT {"event":"session_probe","phase":"launch","check":"dsound_profile","status":"%s"}\n' "$dsound_mode"
else
 printf 'PD2_EVENT {"event":"session_probe","phase":"launch","check":"dsound_profile","status":"off"}\n'
fi
if [[ "$input_mode" == native ]]; then
 # Backup durable original DWORDs/missing values before the first mutation.
 # SDL is not compiled in this Wine. Explicitly select its Linux evdev/udev
 # backend; inotify avoids relying on a daemon monitor in the mount namespace.
 step winebus_prepare
 python3 -B "$PD2_PORT/scripts/winebus_config.py" --prefix "$PD2_PREFIX" --prepare-export || { error invalid_layout 1; exit 1; }
 step winebus_export
 setup_cmd reg.exe export 'HKLM\System\CurrentControlSet\Services\winebus' 'C:\pd2-winebus-export.reg' /y || { error invalid_layout 1; exit 1; }
 step winebus_snapshot
 python3 -B "$PD2_PORT/scripts/winebus_config.py" --prefix "$PD2_PREFIX" --snapshot || { error invalid_layout 1; exit 1; }
 step winebus_select
 for flag in 'Enable SDL' DisableInput; do
  setup_cmd reg.exe add 'HKLM\System\CurrentControlSet\Services\winebus' /v "$flag" /t REG_DWORD /d 0 /f || { error invalid_layout 1; exit 1; }
 done
 setup_cmd reg.exe add 'HKLM\System\CurrentControlSet\Services\winebus' /v DisableUdevd /t REG_DWORD /d 1 /f || { error invalid_layout 1; exit 1; }
 # Registry flags are consumed by winebus at startup, not dynamically.
 stop_wine || { error timeout 1; exit 1; }
 printf 'PD2_EVENT {"event":"session_probe","phase":"launch","check":"winebus_backend","status":"udev"}\n'
fi
# Wineboot may recreate Z:. Remove just this prefix's host filesystem mapping.
if [[ -L "$WINEPREFIX/dosdevices/z:" ]]; then unlink "$WINEPREFIX/dosdevices/z:"; fi
# Installer drive is not exposed to the running game either.
if [[ -L "$WINEPREFIX/dosdevices/r:" ]]; then unlink "$WINEPREFIX/dosdevices/r:"; fi
# Repair location settings for EXISTING prefixes too, without moving any saves.
# The S: link is validated/renewed by layout.py and still targets port/saves.
step game_registry
setup_cmd reg.exe add 'HKCU\Software\Blizzard Entertainment\Diablo II' /v InstallPath /t REG_SZ /d 'C:\Diablo II' /f || { error invalid_layout 1; exit 1; }
setup_cmd reg.exe add 'HKCU\Software\Blizzard Entertainment\Diablo II' /v 'Save Path' /t REG_SZ /d 'S:\' /f || { error invalid_layout 1; exit 1; }
# PD2 uses the selected 800x600/1024x768 game surface; cnc-ddraw maps it
# into this native-size desktop, including mouse coordinates.
setup_cmd reg.exe add 'HKCU\Software\Wine\Explorer' /v Desktop /t REG_SZ /d Default /f || { error invalid_layout 1; exit 1; }
setup_cmd reg.exe add 'HKCU\Software\Wine\Explorer\Desktops' /v Default /t REG_SZ /d '640x480' /f || { error invalid_layout 1; exit 1; }
setup_cmd reg.exe add 'HKCU\Software\Wine\AppDefaults\Game.exe\DllOverrides' /v ddraw /t REG_SZ /d 'native,builtin' /f || true
cd "$PD2_WORK/ProjectD2" || { error invalid_layout 1; exit 1; }
# Counts/statuses only: never names or contents of characters/configuration.
python3 -B "$PD2_PORT/scripts/session_probe.py" --port "$PD2_PORT" --state "$PD2_STATE" || true
# The known keyboard/mouse fallback starts only after Wine setup succeeds.
if [[ "$input_mode" == mapper ]]; then start_mapper; fi
if [[ "$controller_test" == 1 ]]; then
 # Own pinned x86 executable; NO mouse/keyboard navigation mapper in this test.
 python3 -B "$PD2_PORT/scripts/xinput_result.py" --work "$PD2_WORK" --port "$PD2_PORT" --prepare || { error invalid_layout 1; exit 1; }
fi
if [[ "$controller_test" == 0 && "$audio_test" == 1 && "$audio_probe" == 1 ]]; then
 run_audio_probe
fi
if [[ "$controller_test" == 0 ]]; then
 if [[ ${PD2_DIAGNOSTIC:-off} == present || ${PD2_DIAGNOSTIC:-off} == ddraw ]]; then
  if python3 -B "$PD2_PORT/scripts/present_renderer.py" --port "$PD2_PORT" --work "$PD2_WORK" >/dev/null; then
   printf 'PD2_EVENT {"event":"session_probe","phase":"launch","check":"presentation_capture","status":"ready"}\n'
  else
   printf 'PD2_EVENT {"event":"session_probe","phase":"launch","check":"presentation_capture","status":"unavailable"}\n'
   error invalid_layout 1; exit 1
  fi
 elif [[ "$fps_enabled" == 1 ]]; then
  # Select the authenticated automatic HUD before the first game frame. This
  # changes only the volatile work copy; no input helper or second Wine desktop.
  timeout --kill-after=2 10 python3 -B "$PD2_PORT/scripts/fps_renderer.py" --port "$PD2_PORT" --work "$PD2_WORK" || \
   printf 'PD2_EVENT {"event":"session_probe","phase":"launch","check":"fps_counter","status":"unavailable"}\n'
 else
  printf 'PD2_EVENT {"event":"session_probe","phase":"launch","check":"fps_counter","status":"disabled"}\n'
 fi
fi
# Attach the observer only after setup, with no old Wine process retaining ALSA.
audio_game_wrapper=()
if [[ "$audio_metrics_enabled" == 1 ]]; then
 stop_wine || { error timeout 1; exit 1; }
 if python3 -B "$PD2_PORT/scripts/audio_metrics.py" prepare --port "$PD2_PORT" --work "$PD2_WORK"; then
  export PD2_NATIVE_LIBS="$PD2_WORK/.alsa-audio-metrics:$PD2_NATIVE_LIBS"
  audio_game_wrapper=(python3 -B "$PD2_PORT/scripts/audio_metrics.py" run --)
 fi
fi
step game_start
PD2_GAME_TUNING_ACTIVE=1
refresh_box_env
phase game
if [[ ${PD2_DIAGNOSTIC:-off} == present || ${PD2_DIAGNOSTIC:-off} == ddraw ]]; then
 setsid python3 -B "$PD2_PORT/scripts/presentation_watch.py" --work "$PD2_WORK" --pid "$BASHPID" & fps_pid=$!
 printf '%s\n' "$fps_pid" > "$PD2_RUN/fps.pid"
fi
if [[ ${PD2_DIAGNOSTIC:-off} == ddraw ]]; then
 source "$PD2_PORT/scripts/run-layer.sh" || exit 1
 pd2_run_layer ddraw; exit $?
fi
# Keep the working 640x480 named desktop. start.exe /d explicitly sets the
# WINDOWS working directory, so config lookup does not depend on a Unix cwd
# or explorer inheritance. Wine's /exec waits without opening another console
# and stops option/title parsing before the EXE path (which contains spaces).
if [[ "$controller_test" == 1 ]]; then
 setsid "${box_env[@]}" "$PD2_BOX" "$PD2_WINE/bin/wine" explorer.exe /desktop=PD2Native,640x480 start.exe /d 'C:\Diablo II\ProjectD2' /exec 'C:\Diablo II\ProjectD2\pd2-xinput-probe.exe' & game_pid=$!
else
 setsid "${audio_game_wrapper[@]}" "${box_env[@]}" "$PD2_BOX" "$PD2_WINE/bin/wine" explorer.exe /desktop=PD2Native,640x480 start.exe /d 'C:\Diablo II\ProjectD2' /exec 'C:\Diablo II\ProjectD2\Game.exe' -ddraw & game_pid=$!
fi
printf '%s\n' "$game_pid" > "$PD2_RUN/game.pid"
if [[ ${PD2_METRICS:-0} == 1 ]];then
 # Anchor resource accounting to Wine/game, not mapper or the sampler itself.
 setsid python3 -B "$PD2_PORT/scripts/metrics.py" --port "$PD2_PORT" --pid "$game_pid" --wine-prefix "$WINEPREFIX" --uid "$(id -u)" --wine-exe "$PD2_BOX" & metrics_pid=$!
 printf '%s\n' "$metrics_pid" > "$PD2_RUN/metrics.pid"
 if [[ -n "$mapper_pid" ]]; then
  setsid python3 -B "$PD2_PORT/scripts/metrics.py" --port "$PD2_PORT" --pid "$mapper_pid" --role mapper & mapper_metrics_pid=$!
  printf '%s\n' "$mapper_metrics_pid" > "$PD2_RUN/mapper-metrics.pid"
 fi
fi
wait "$game_pid"; rc=$?;game_pid=
PD2_GAME_TUNING_ACTIVE=0
refresh_box_env
if [[ "$rc" == 0 ]]; then
 timeout --kill-after=5 60 "${box_env[@]}" "$PD2_BOX" "$PD2_WINE/bin/wineserver" -w;rc=$?
 [[ "$rc" != 0 ]] && error timeout "$rc"
 if [[ "$rc" == 0 && "$controller_test" == 1 ]]; then
  python3 -B "$PD2_PORT/scripts/xinput_result.py" --work "$PD2_WORK" || rc=1
 fi
else error nonzero_exit "$rc";fi
exit "$rc"
