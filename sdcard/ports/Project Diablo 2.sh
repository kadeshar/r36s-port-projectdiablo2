#!/bin/bash
# PORTMASTER: projectdiablo2.zip, Project Diablo 2.sh
# Experimental private offline PD2 launcher, v0.1.18.
umask 077
ulimit -c 0
BASE=$(cd -- "$(dirname -- "$0")" && pwd -P) || exit 1
export PD2_PORT="$BASE/projectdiablo2"
# Native Controller from 0.1.13 is now the default; explicit test modes survive.
export PD2_INPUT_MODE="${PD2_INPUT_MODE:-native}"
export PD2_CONTROLLER_TEST="${PD2_CONTROLLER_TEST:-0}"
# Experiments are opt-in; the normal audio path stays unchanged by default.
export PD2_FPS="${PD2_FPS:-0}"
export PD2_AUDIO_TEST="${PD2_AUDIO_TEST:-1}"
export PD2_AUDIO_PROBE="${PD2_AUDIO_PROBE:-0}"
export PD2_START_MENU="${PD2_START_MENU:-1}"
export PD2_PERFORMANCE="${PD2_PERFORMANCE:-gdi}"
case "$PD2_PERFORMANCE" in off|gdi|opengl) ;; *) exit 1;; esac
export PD2_DIAGNOSTIC="${PD2_DIAGNOSTIC:-off}"
case "$PD2_DIAGNOSTIC" in off|present|sdl|glx|ddraw) ;; *) exit 1;; esac
export PD2_TUNING="${PD2_TUNING:-off}"
source "$PD2_PORT/scripts/tuning.sh" || exit 1
pd2_validate_tuning || exit 1
export PD2_BIGBLOCK="${PD2_BIGBLOCK:-2}"
case "$PD2_BIGBLOCK" in 1|2) ;; *) exit 1;; esac
# Empty means use the user's stored choice; an explicit variant is session-only.
if [[ -n ${PD2_GAME_RESOLUTION:-} ]]; then export PD2_GAME_RESOLUTION; else unset PD2_GAME_RESOLUTION; fi
fixed_message() { printf '%s\n' "$1" > /dev/tty0 2>/dev/null || printf '%s\n' "$1" >&2; }
for cmd in python3 timeout setsid unshare flock mount umount mountpoint mkfifo ps readlink stat chgrp runuser; do
 command -v "$cmd" >/dev/null || { fixed_message 'PD2: brak wymaganego narzedzia systemowego.'; exit 1; }
done
[[ -f "$PD2_PORT/scripts/safe_log.py" ]] || { fixed_message 'PD2: niekompletna instalacja portu.'; exit 1; }
export PD2_HOME="$HOME" PD2_USER="$(id -un)" PD2_STATE="$HOME/.local/share/pd2-r36s"
# Never execute Wine as root; Options/Tools root explorers are not a game launcher.
[[ $(id -u) != 0 ]] || { fixed_message 'PD2: uruchom z menu Ports jako zwykly uzytkownik, nie root.'; exit 1; }
mkdir -p "$PD2_STATE" || exit 1
exec 9>"$PD2_STATE/session.lock"
flock -n 9 || { fixed_message 'PD2: inna sesja portu juz dziala.'; exit 1; }
export PD2_RUN=$(mktemp -d /tmp/pd2-r36s.XXXXXXXX) || exit 1
[[ "$PD2_RUN" == /tmp/pd2-r36s.* && -d "$PD2_RUN" && ! -L "$PD2_RUN" ]] || exit 1
mkfifo -m600 "$PD2_RUN/log.pipe" || exit 1
session=$(date -u +%Y%m%dT%H%M%SZ)-$$
python3 "$PD2_PORT/scripts/safe_log.py" stream --dir "$PD2_PORT/logs" --session "$session" < "$PD2_RUN/log.pipe" & log_pid=$!
exec 3>&1 4>&2
exec > "$PD2_RUN/log.pipe" 2>&1
# Memory and swap protection: prevent microSD swap thrashing on 1GB RAM device
if command -v sysctl >/dev/null 2>&1; then
 sysctl -w vm.swappiness=10 >/dev/null 2>&1 || true
fi
sync; echo 3 > /proc/sys/vm/drop_caches 2>/dev/null || true
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
 wait "$log_pid" || fixed_message 'PD2: zapis diagnostyki nie powiodl sie.'
 # Leave only if an unmount failed. Never recurse into mounts during cleanup.
 if ! mountpoint -q "$PD2_RUN/weston" && ! mountpoint -q "$PD2_RUN/gamedata"; then
  [[ "$PD2_RUN" == /tmp/pd2-r36s.* && ! -L "$PD2_RUN" ]] && "${SUDO[@]}" rm -rf -- "$PD2_RUN"
 fi
 if [[ "$rc" != 0 ]]; then fixed_message 'PD2: start nieudany. Sprawdz projectdiablo2/logs; nie usuwaj danych ani zapisow.'; fi
 exit "$rc"
}
trap pd2_port_cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
printf 'PD2_EVENT {"event":"phase","phase":"preflight","port_version":"0.1.18","runtime_version":"8.0"}\n'
error() { printf 'PD2_EVENT {"event":"runtime_error","phase":"preflight","reason":"%s"}\n' "$1"; exit 1; }
XDG_DATA_HOME=${XDG_DATA_HOME:-$HOME/.local/share}
if [[ -d /opt/system/Tools/PortMaster ]]; then controlfolder=/opt/system/Tools/PortMaster
elif [[ -d /opt/tools/PortMaster ]]; then controlfolder=/opt/tools/PortMaster
elif [[ -d "$XDG_DATA_HOME/PortMaster" ]]; then controlfolder="$XDG_DATA_HOME/PortMaster"
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
# Verify all artifacts BEFORE asking the kernel to mount an image.
python3 - "$PD2_PORT" <<'PY'
import hashlib,json,pathlib,sys
try:
 p=pathlib.Path(sys.argv[1]);m=json.loads((p/'runtime-manifest.json').read_text())
 required={'wine-8.0-x86.tar.xz','box86','weston_pkg_0.2.squashfs','vc_redist.x86.exe'}
 if not isinstance(m.get('artifacts'),list) or len(m['artifacts'])!=4 or {a['file'] for a in m['artifacts']}!=required:raise ValueError()
 if (p/'runtime').is_symlink():raise ValueError()
 for a in m['artifacts']:
  f=p/'runtime'/a['file']
  if f.is_symlink() or f.stat().st_size!=a['size']:raise ValueError()
  h=hashlib.sha256()
  with f.open('rb') as s:
   for b in iter(lambda:s.read(1048576),b''):h.update(b)
  if h.hexdigest()!=a['sha256']:raise ValueError()
except Exception:
 print('PD2_EVENT {"event":"runtime_error","reason":"unsupported_runtime","phase":"preflight"}')
 sys.exit(1)
PY
[[ $? == 0 ]] || exit 1
"${SUDO[@]}" mount --bind "$PD2_PORT/gamedata" "$PD2_RUN/gamedata" || error invalid_layout
mounted_data=1
"${SUDO[@]}" mount -o remount,bind,ro "$PD2_RUN/gamedata" || error invalid_layout
python3 "$PD2_PORT/scripts/layout.py" --port "$PD2_PORT" --state "$PD2_STATE" --data "$PD2_RUN/gamedata/Diablo II" || exit 1
layout_get() { python3 "$PD2_PORT/scripts/layout.py" --port "$PD2_PORT" --state "$PD2_STATE" --get "$1"; }
export PD2_WINE="$(layout_get wine)" PD2_BOX="$(layout_get box)" PD2_PREFIX="$(layout_get prefix)" PD2_WORK="$(layout_get work)" PD2_PROFILE="$(layout_get profile)" PD2_SWAP_AB="$(layout_get swap_ab)"
export PD2_GAME_RESOLUTION="$(layout_get game_resolution)"
"${SUDO[@]}" mount -t squashfs -o loop,ro "$PD2_PORT/runtime/weston_pkg_0.2.squashfs" "$PD2_RUN/weston" || error unsupported_runtime
mounted_weston=1
export PD2_WESTON="$PD2_RUN/weston"
printf 'PD2_EVENT {"event":"phase","phase":"runtime","profile":"%s"}\n' "$PD2_PROFILE"
python3 "$PD2_PORT/scripts/metrics.py" --port "$PD2_PORT" || true
export PD2_METRICS="$(python3 "$PD2_PORT/scripts/metrics.py" --port "$PD2_PORT" --enabled)"
export PD2_PARENT_MNT_NS="$(readlink /proc/self/ns/mnt)"
# Only explicit variables are forwarded through sudo; user Wine runs via runuser.
"${SUDO[@]}" unshare --mount --propagation private setsid env \
 PD2_PORT="$PD2_PORT" PD2_RUN="$PD2_RUN" PD2_WESTON="$PD2_WESTON" PD2_USER="$PD2_USER" PD2_HOME="$PD2_HOME" PD2_STATE="$PD2_STATE" \
 PD2_WINE="$PD2_WINE" PD2_BOX="$PD2_BOX" PD2_PREFIX="$PD2_PREFIX" PD2_WORK="$PD2_WORK" PD2_PROFILE="$PD2_PROFILE" PD2_SWAP_AB="$PD2_SWAP_AB" \
 PD2_DIAGNOSTIC="$PD2_DIAGNOSTIC" PD2_TUNING="$PD2_TUNING" PD2_BIGBLOCK="$PD2_BIGBLOCK" PD2_PERFORMANCE="$PD2_PERFORMANCE" PD2_GAME_RESOLUTION="$PD2_GAME_RESOLUTION" PD2_FPS="$PD2_FPS" PD2_AUDIO_TEST="$PD2_AUDIO_TEST" PD2_AUDIO_PROBE="$PD2_AUDIO_PROBE" PD2_START_MENU="$PD2_START_MENU" \
 PD2_INPUT_MODE="$PD2_INPUT_MODE" PD2_CONTROLLER_TEST="$PD2_CONTROLLER_TEST" PD2_GPTOKEYB="$PD2_GPTOKEYB" PD2_CONTROLLER_CONFIG="$PD2_CONTROLLER_CONFIG" PD2_METRICS="$PD2_METRICS" PD2_PARENT_MNT_NS="$PD2_PARENT_MNT_NS" PD2_HOST_NATIVE_LIBS="${LD_LIBRARY_PATH:-}" \
 bash "$PD2_PORT/scripts/weston-session.sh" 3>&- 4>&- & runner_pid=$!
wait "$runner_pid"; rc=$?
if [[ "$rc" != 0 && ! -f "$PD2_RUN/adapter.pid" ]];then
 printf 'PD2_EVENT {"event":"runtime_error","phase":"runtime","reason":"namespace_unavailable"}\n'
fi
# sudo may own a supervising PID rather than the setsid group. Normal exit has
# already cleaned up its children; cancellation relies additionally on traps.
runner_pid=
exit "$rc"
