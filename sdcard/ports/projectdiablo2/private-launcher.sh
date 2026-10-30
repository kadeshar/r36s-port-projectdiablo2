#!/bin/bash
# PORTMASTER: projectdiablo2.zip, Project Diablo 2.sh
# Experimental private offline PD2 launcher, v1.3.
umask 077
ulimit -c 0
BASE=$(cd -- "$(dirname -- "$0")" && pwd -P) || exit 1
export PD2_PORT="$BASE"
# Native Controller from 0.1.13 is now the default; explicit test modes survive.
export PD2_INPUT_MODE="${PD2_INPUT_MODE:-native}"
export PD2_CONTROLLER_TEST="${PD2_CONTROLLER_TEST:-0}"
# Experiments are opt-in; the normal audio path stays unchanged by default.
export PD2_FPS="${PD2_FPS:-0}"
export PD2_AUDIO_TEST="${PD2_AUDIO_TEST:-1}"
export PD2_AUDIO_PROBE="${PD2_AUDIO_PROBE:-0}"
# Opt-in measurement/tuning experiments; both stay off unless a launcher sets them.
export PD2_AUDIO_METRICS="${PD2_AUDIO_METRICS:-0}"
case "$PD2_AUDIO_METRICS" in 0|1) ;; *) exit 1;; esac
export PD2_AUDIO_DSOUND="${PD2_AUDIO_DSOUND:-off}"
case "$PD2_AUDIO_DSOUND" in off|ver2|wine) ;; *) exit 1;; esac
export PD2_AUDIO_SDL="${PD2_AUDIO_SDL:-alsa}"
case "$PD2_AUDIO_SDL" in alsa|dummy) ;; *) exit 1;; esac
export PD2_AUDIO_VARIANT="${PD2_AUDIO_VARIANT:-stock}"
case "$PD2_AUDIO_VARIANT" in A|B|C|D|buffer|dmix|stock) ;; *) exit 1;; esac
export PD2_AUDIO_ROUTE_PROFILE="${PD2_AUDIO_ROUTE_PROFILE:-baseline}"
case "$PD2_AUDIO_ROUTE_PROFILE" in baseline|buffer80|buffer160|dmix160|dmix80) ;; *) exit 1;; esac
export PD2_START_MENU="${PD2_START_MENU:-1}"
export PD2_DIAGNOSTIC="${PD2_DIAGNOSTIC:-off}"
case "$PD2_DIAGNOSTIC" in off|present|sdl|glx|ddraw) ;; *) exit 1;; esac
# Empty means use the user's stored choice; an explicit variant is session-only.
if [[ -n ${PD2_GAME_RESOLUTION:-} ]]; then export PD2_GAME_RESOLUTION; else unset PD2_GAME_RESOLUTION; fi
# Loot filter: 'default' or a *.filter name from port/filters; empty uses the
# stored choice. Only safe names survive layout validation; nothing else here.
if [[ -n ${PD2_LOOT_FILTER:-} && ${PD2_LOOT_FILTER} =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,123}\.filter$ ]]; then export PD2_LOOT_FILTER; else unset PD2_LOOT_FILTER; fi
fixed_message() { printf '%s\n' "$1" > /dev/tty0 2>/dev/null || printf '%s\n' "$1" >&2; }
for cmd in python3 timeout setsid unshare flock mount umount mountpoint mkfifo ps readlink stat chgrp runuser; do
 command -v "$cmd" >/dev/null || { fixed_message 'PD2: missing required system tool.'; exit 1; }
done
[[ -f "$PD2_PORT/scripts/safe_log.py" ]] || { fixed_message 'PD2: incomplete port installation.'; exit 1; }
[[ ${PD2_EXPERIMENT_ACTIVE:-} == sd-storage-v1 && -n ${PD2_EXPERIMENT_STATE:-} ]] || exit 1
export PD2_HOME="$HOME" PD2_USER="$(id -un)" PD2_STATE="$PD2_EXPERIMENT_STATE"
[[ "$PD2_STATE" == "$PD2_PORT/storage/mounted-state" && -d "$PD2_STATE" ]] || exit 1
# Never execute Wine as root; Options/Tools root explorers are not a game launcher.
[[ $(id -u) != 0 ]] || { fixed_message 'PD2: launch from Ports menu as regular user, not root.'; exit 1; }
mkdir -p "$PD2_STATE" || exit 1
exec 9>"$PD2_STATE/session.lock"
flock -n 9 || { fixed_message 'PD2: another port session is already running.'; exit 1; }
export PD2_RUN=$(mktemp -d /tmp/pd2-r36s.XXXXXXXX) || exit 1
[[ "$PD2_RUN" == /tmp/pd2-r36s.* && -d "$PD2_RUN" && ! -L "$PD2_RUN" ]] || exit 1
mkfifo -m600 "$PD2_RUN/log.pipe" || exit 1
session=$(date -u +%Y%m%dT%H%M%SZ)-$$
python3 "$PD2_PORT/scripts/safe_log.py" stream --dir "$PD2_PORT/logs" --session "$session" < "$PD2_RUN/log.pipe" & log_pid=$!
exec 3>&1 4>&2
exec > "$PD2_RUN/log.pipe" 2>&1
# Experimental storage wrapper does not change global cache/swappiness here.
mounted_data=0; mounted_weston=0; runner_pid=; have_pm=0
SUDO=()
pd2_port_cleanup() {
 local rc=$?;trap - EXIT INT TERM
 if [[ -n "$runner_pid" ]]; then
   # Read the actual setsid adapter PID, not sudo/unshare's supervising PID.
   adapter_pid=
   [[ -f "$PD2_RUN/adapter.pid" && ! -L "$PD2_RUN/adapter.pid" ]] && read -r adapter_pid < "$PD2_RUN/adapter.pid"
   if [[ "$adapter_pid" =~ ^[0-9]+$ && "$adapter_pid" -gt 1 && $(ps -o pgid= -p "$adapter_pid" | tr -d ' ') == "$adapter_pid" ]]; then
     "${SUDO[@]}" kill -TERM -- "-$adapter_pid" 2>/dev/null || true
   fi
   for ((i=0;i<450;i++)); do ps -p "$runner_pid" >/dev/null || break; sleep 0.1; done
   if ps -p "$runner_pid" >/dev/null; then
     for record in metrics.pid compositor-metrics.pid mapper-metrics.pid audio.pid fps.pid game.pid navigator.pid mapper.pid compositor.pid adapter.pid; do
       pid=
       [[ -f "$PD2_RUN/$record" && ! -L "$PD2_RUN/$record" ]] && read -r pid < "$PD2_RUN/$record"
       if [[ "$pid" =~ ^[0-9]+$ && "$pid" -gt 1 && $(ps -o pgid= -p "$pid" | tr -d ' ') == "$pid" ]]; then
         "${SUDO[@]}" kill -KILL -- "-$pid" 2>/dev/null || true
       fi
     done
   fi
   if ! ps -p "$runner_pid" >/dev/null; then wait "$runner_pid" 2>/dev/null || true; fi
 fi
 [[ "$mounted_weston" == 1 ]] && "${SUDO[@]}" umount "$PD2_RUN/weston" 2>/dev/null
 [[ "$mounted_data" == 1 ]] && "${SUDO[@]}" umount "$PD2_RUN/gamedata" 2>/dev/null
 printf 'PD2_EVENT {"event":"runtime_exit","phase":"shutdown","rc":%s}\n' "$rc"
 [[ "$have_pm" == 1 ]] && ( pm_finish )
 exec 1>&3 2>&4
 for ((i=0;i<100;i++)); do kill -0 "$log_pid" 2>/dev/null || break; sleep 0.1; done
 kill -TERM "$log_pid" 2>/dev/null || true
 wait "$log_pid" || fixed_message 'PD2: failed to write diagnostics.'
 # Leave only if an unmount failed. Never recurse into mounts during cleanup.
 if ! mountpoint -q "$PD2_RUN/weston" && ! mountpoint -q "$PD2_RUN/gamedata"; then
  [[ "$PD2_RUN" == /tmp/pd2-r36s.* && ! -L "$PD2_RUN" ]] && "${SUDO[@]}" rm -rf -- "$PD2_RUN"
 fi
 if [[ "$rc" != 0 ]]; then fixed_message 'PD2: launch failed. Check projectdiablo2/logs; do not delete game data or saves.'; fi
 exit "$rc"
}
trap pd2_port_cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
last_event_ms=
now_ms() {
 local t
 t=$(date +%s%3N)
 [[ "$t" =~ ^[0-9]+$ ]] || t=$(( $(date +%s) * 1000 ))
 printf '%s' "$t"
}
# Append elapsed_ms = wall time since the previous phase marker in this
# process, so each JSONL line shows the cost of the work before it.
emit() {
 local t e=''
 t=$(now_ms)
 if [[ -n "${last_event_ms:-}" ]]; then e=',"elapsed_ms":'$(( t - last_event_ms )); fi
 last_event_ms=$t
 printf 'PD2_EVENT {%s%s}\n' "$1" "$e"
}
emit "\"event\":\"phase\",\"phase\":\"preflight\",\"port_version\":\"1.3\",\"runtime_version\":\"8.0\""
error() { printf 'PD2_EVENT {"event":"runtime_error","phase":"preflight","reason":"%s"}\n' "$1"; exit 1; }
XDG_DATA_HOME=${XDG_DATA_HOME:-$HOME/.local/share}
if [[ -d /opt/system/Tools/PortMaster ]]; then controlfolder=/opt/system/Tools/PortMaster
elif [[ -d /opt/tools/PortMaster ]]; then controlfolder=/opt/tools/PortMaster
elif [[ -d "$XDG_DATA_HOME/PortMaster" ]]; then controlfolder="$XDG_DATA_HOME/PortMaster"
elif [[ -d /roms2/ports/PortMaster ]]; then controlfolder=/roms2/ports/PortMaster
else controlfolder=/roms/ports/PortMaster; fi
[[ -f "$controlfolder/control.txt" ]] || error invalid_layout
source "$controlfolder/control.txt" || error unsupported_runtime
export PORT_32BIT=Y
[[ -f "$controlfolder/device_info.txt" ]] && source "$controlfolder/device_info.txt"
[[ -f "$controlfolder/mod_${CFW_NAME}.txt" ]] && source "$controlfolder/mod_${CFW_NAME}.txt"
get_controls || error unsupported_runtime
# Firmware hooks may install their own traps; retain our session-owned cleanup.
trap pd2_port_cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
have_pm=1
read -r -a SUDO <<< "${ESUDO:-sudo -n}"
[[ ${SUDO[0]:-} == sudo ]] && SUDO+=(-n)
export PD2_GPTOKEYB="${GPTOKEYB:-}" PD2_CONTROLLER_CONFIG="${sdl_controllerconfig:-}"
[[ -n "$PD2_GPTOKEYB" ]] || error unsupported_runtime
[[ $(uname -m) == aarch64 ]] || error unsupported_runtime
# Disable inherited instrumentation before any runtime can print input or memory.
for key in ${!BOX86_@} ${!WINE@}; do unset "$key"; done
mkdir -p "$PD2_RUN/gamedata" "$PD2_RUN/weston"
# Verify the runtime BEFORE asking the kernel to mount an image. This child
# trusts the stamp produced by its already-locked launcher session; a missing
# or stale stamp fails over to full validation before mounting anything.
python3 - "$PD2_PORT" <<'PY'
import sys
port=sys.argv[1]
sys.path.insert(0,port+'/storage-tools')
try:
 import storage_common
 storage_common.validated(port,trust_stamp=True,trust_fallback_full=True)
except Exception:
 print('PD2_EVENT {"event":"runtime_error","reason":"unsupported_runtime","phase":"preflight"}')
 sys.exit(1)
PY
[[ $? == 0 ]] || exit 1
"${SUDO[@]}" mount --bind "$PD2_PORT/gamedata" "$PD2_RUN/gamedata" || error invalid_layout
mounted_data=1
"${SUDO[@]}" mount -o remount,bind,ro "$PD2_RUN/gamedata" || error invalid_layout
python3 "$PD2_PORT/scripts/layout.py" --port "$PD2_PORT" --state "$PD2_STATE" --data "$PD2_RUN/gamedata/Diablo II" || exit 1
# One --dump spawn replaces the former six --get python spawns.
layout_dump=$(python3 "$PD2_PORT/scripts/layout.py" --port "$PD2_PORT" --state "$PD2_STATE" --dump) || exit 1
while IFS=$'\t' read -r layout_key layout_value; do
 case "$layout_key" in
  wine) export PD2_WINE="$layout_value";;
  box) export PD2_BOX="$layout_value";;
  prefix) export PD2_PREFIX="$layout_value";;
  work) export PD2_WORK="$layout_value";;
  profile) export PD2_PROFILE="$layout_value";;
  swap_ab) export PD2_SWAP_AB="$layout_value";;
  game_resolution) export PD2_GAME_RESOLUTION="$layout_value";;
  loot_filter) export PD2_LOOT_FILTER="$layout_value";;
 esac
done <<< "$layout_dump"
"${SUDO[@]}" mount -t squashfs -o loop,ro "$PD2_PORT/runtime/weston_pkg_0.2.squashfs" "$PD2_RUN/weston" || error unsupported_runtime
mounted_weston=1
export PD2_WESTON="$PD2_RUN/weston"
emit "\"event\":\"phase\",\"phase\":\"runtime\",\"profile\":\"$PD2_PROFILE\""
# One metrics spawn: preflight sample goes to the log stream (stderr), the
# enabled token to stdout.
export PD2_METRICS="$(python3 "$PD2_PORT/scripts/metrics.py" --port "$PD2_PORT" --preflight)"
export PD2_PARENT_MNT_NS="$(readlink /proc/self/ns/mnt)"
# Only explicit variables are forwarded through sudo; user Wine runs via runuser.
"${SUDO[@]}" unshare --mount --propagation private setsid env \
 PD2_PORT="$PD2_PORT" PD2_RUN="$PD2_RUN" PD2_WESTON="$PD2_WESTON" PD2_USER="$PD2_USER" PD2_HOME="$PD2_HOME" PD2_STATE="$PD2_STATE" \
 PD2_WINE="$PD2_WINE" PD2_BOX="$PD2_BOX" PD2_PREFIX="$PD2_PREFIX" PD2_WORK="$PD2_WORK" PD2_PROFILE="$PD2_PROFILE" PD2_SWAP_AB="$PD2_SWAP_AB" \
 PD2_DIAGNOSTIC="$PD2_DIAGNOSTIC" PD2_GAME_RESOLUTION="$PD2_GAME_RESOLUTION" PD2_LOOT_FILTER="$PD2_LOOT_FILTER" PD2_FPS="$PD2_FPS" PD2_AUDIO_TEST="$PD2_AUDIO_TEST" PD2_AUDIO_PROBE="$PD2_AUDIO_PROBE" PD2_START_MENU="$PD2_START_MENU" \
 PD2_INPUT_MODE="$PD2_INPUT_MODE" PD2_CONTROLLER_TEST="$PD2_CONTROLLER_TEST" PD2_GPTOKEYB="$PD2_GPTOKEYB" PD2_CONTROLLER_CONFIG="$PD2_CONTROLLER_CONFIG" PD2_METRICS="$PD2_METRICS" PD2_PARENT_MNT_NS="$PD2_PARENT_MNT_NS" PD2_HOST_NATIVE_LIBS="${LD_LIBRARY_PATH:-}" \
 PD2_AUDIO_METRICS="$PD2_AUDIO_METRICS" PD2_AUDIO_DSOUND="$PD2_AUDIO_DSOUND" PD2_AUDIO_SDL="$PD2_AUDIO_SDL" PD2_AUDIO_VARIANT="$PD2_AUDIO_VARIANT" PD2_AUDIO_ROUTE_PROFILE="$PD2_AUDIO_ROUTE_PROFILE" \
 bash "$PD2_PORT/scripts/weston-session.sh" 3>&- 4>&- & runner_pid=$!
wait "$runner_pid"; rc=$?
if [[ "$rc" != 0 && ! -f "$PD2_RUN/adapter.pid" ]];then
 printf 'PD2_EVENT {"event":"runtime_error","phase":"runtime","reason":"namespace_unavailable"}\n'
fi
# sudo may own a supervising PID rather than the setsid group. Normal exit has
# already cleaned up its children; cancellation relies additionally on traps.
runner_pid=
exit "$rc"
