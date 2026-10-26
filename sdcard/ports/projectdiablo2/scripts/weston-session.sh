#!/bin/bash
# Scoped adapter using Westonpack 0.2.7.1 machinery, in a private mount namespace.
# Invoked by sudo unshare --mount --propagation private setsid env ... bash.
set -u
ulimit -c 0
ORIGINAL_RUN=${PD2_RUN:?}
[[ $(id -u) == 0 && "$ORIGINAL_RUN" == /tmp/pd2-r36s.* && ! -L "$ORIGINAL_RUN" ]] || exit 2
printf '%s\n' "$BASHPID" > "$ORIGINAL_RUN/adapter.pid"
chmod 644 "$ORIGINAL_RUN/adapter.pid"
ALIAS="/run/pd2-r36s-$BASHPID"
seat_pid=; weston_pid=; app_pid=; compositor_log_pid=; orig_swappiness=; alias_mounted=0; alias_created=0; tmp_mounted=0; run_mounted=0; host_run_mounted=0; work_mounted=0
error() { printf 'PD2_EVENT {"event":"runtime_error","reason":"%s","phase":"runtime"}\n' "$1"; }
stage() { printf 'PD2_EVENT {"event":"runtime_stage","phase":"runtime","stage":"%s"}\n' "$1"; }
source "$PD2_PORT/scripts/private-namespace.sh" || { error runtime_tool_missing;exit 2; }
stop_pid() {
 local pid=$1 group=${2:-0}
 [[ "$pid" =~ ^[0-9]+$ && "$pid" -gt 1 ]] || return 0
 if [[ "$group" == 1 ]]; then kill -TERM -- "-$pid" 2>/dev/null || true; else kill -TERM "$pid" 2>/dev/null || true; fi
 for ((i=0;i<60;i++)); do kill -0 "$pid" 2>/dev/null || break; sleep 0.1; done
 if [[ "$group" == 1 ]]; then kill -KILL -- "-$pid" 2>/dev/null || true; else kill -KILL "$pid" 2>/dev/null || true; fi
 wait "$pid" 2>/dev/null || true
}
cleanup() {
 local rc=$?;trap - EXIT INT TERM
 stop_pid "$app_pid"
 for record in metrics.pid compositor-metrics.pid mapper-metrics.pid fps.pid game.pid mapper.pid osk.pid; do
   pid=
   [[ -f "${PD2_RUN}/$record" && ! -L "${PD2_RUN}/$record" ]] && read -r pid < "${PD2_RUN}/$record"
   if [[ "$pid" =~ ^[0-9]+$ && "$pid" -gt 1 && $(ps -o pgid= -p "$pid" | tr -d ' ') == "$pid" ]]; then stop_pid "$pid" 1;fi
 done
 if [[ -n ${PD2_NATIVE_LIBS:-} && ${PD2_DIAGNOSTIC:-off} != sdl && ${PD2_DIAGNOSTIC:-off} != glx ]]; then
   timeout --kill-after=5 10 runuser -u "$PD2_USER" --preserve-environment -- env \
    WINEPREFIX="$PD2_PREFIX" WINEARCH=win32 WINEDEBUG=-all BOX86_LOG=0 \
    LD_LIBRARY_PATH="$PD2_NATIVE_LIBS" LD_PRELOAD="$PD2_NATIVE_PRELOAD" \
    "$PD2_BOX" "$PD2_WINE/bin/wineserver" -k 2>/dev/null || true
 fi
 # Compositor/Xwayland have their own setsid group: stop it on ALL exit paths.
 stop_pid "$weston_pid" 1
 # Reset console only after a compositor we owned has released DRM.
 if [[ -n "$weston_pid" ]]; then
  for tty in /dev/tty0 /dev/tty1; do
   [[ -c "$tty" ]] && { printf '\033c' > "$tty"; } 2>/dev/null || true
  done
 fi
 # Let the compositor-only classifier drain EOF; it lives outside Weston group.
 if [[ -n "$compositor_log_pid" ]];then
  for ((i=0;i<20;i++));do kill -0 "$compositor_log_pid" 2>/dev/null || break;sleep 0.1;done
  stop_pid "$compositor_log_pid"
 fi
 stop_pid "$seat_pid"
 cd / || true
 [[ "$work_mounted" == 1 ]] && umount "$PD2_WORK" 2>/dev/null
 [[ -n "$orig_swappiness" && -w /proc/sys/vm/swappiness ]] && echo "$orig_swappiness" > /proc/sys/vm/swappiness 2>/dev/null || true
 pd2_namespace_close
 printf 'PD2_EVENT {"event":"runtime_exit","phase":"runtime","rc":%s}\n' "$rc"
 exit "$rc"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
# Avoid abstract X11 socket clashes with another live desktop too.
[[ ! -e /tmp/.X11-unix/X0 && ! -e /tmp/.X0-lock ]] || { error display_conflict; exit 2; }
[[ -c /dev/dri/card0 ]] || { error missing_drm_device; exit 2; }
[[ -e /dev/uinput ]] || { error missing_uinput; exit 2; }
stage namespace_setup
pd2_namespace_open || exit 2
stage namespace_ready
case "${PD2_AUDIO_SDL:-alsa}" in alsa|dummy) ;; *) error invalid_profile;exit 2;; esac
case "${PD2_AUDIO_DSOUND:-off}" in off|ver2|wine) ;; *) error invalid_profile;exit 2;; esac
case "${PD2_AUDIO_METRICS:-0}" in 0|1) ;; *) error invalid_profile;exit 2;; esac
case "${PD2_AUDIO_VARIANT:-stock}" in A|B|C|D|buffer|dmix|stock) ;; *) error invalid_profile;exit 2;; esac
case "${PD2_AUDIO_ROUTE_PROFILE:-baseline}" in baseline|buffer80|buffer160|dmix160|dmix80) ;; *) error invalid_profile;exit 2;; esac
export PD2_AUDIO_SDL="${PD2_AUDIO_SDL:-alsa}"
export PD2_AUDIO_DSOUND="${PD2_AUDIO_DSOUND:-off}"
export PD2_AUDIO_METRICS="${PD2_AUDIO_METRICS:-0}"
export PD2_AUDIO_VARIANT="${PD2_AUDIO_VARIANT:-stock}"
export PD2_AUDIO_ROUTE_PROFILE="${PD2_AUDIO_ROUTE_PROFILE:-baseline}"
if [[ -r /proc/sys/vm/swappiness ]]; then
 read -r orig_swappiness < /proc/sys/vm/swappiness 2>/dev/null || true
 if [[ -w /proc/sys/vm/swappiness ]]; then
  echo 10 > /proc/sys/vm/swappiness 2>/dev/null || true
 fi
fi
uid=$(id -u "$PD2_USER");gid=$(id -g "$PD2_USER");group=$(id -gn "$PD2_USER")
# Wine can create engine logs only in bounded volatile RAM. No raw crash/network
# logs persist on SD. EXE/DLL/MPQ assets remain symlinks into the read-only bind.
mkdir -m1777 /tmp/.X11-unix
ln -s "$W/fonts" /tmp/fonts
ln -s "$W/share" /tmp/share
mkfifo -m600 /tmp/drmpipe;chown "$uid:$gid" /tmp/drmpipe
export FONTCONFIG_PATH="$W/fonts" FONTCONFIG_FILE="$W/fonts/fonts.conf" XKB_CONFIG_ROOT="$W/share/xkb"
export WESTON_DATA_DIR="$W/data" WESTON_LIBEXEC_DIR="$W/libexec"
libweston="$W/lib_aarch64/libweston-14";modules="$W/lib_aarch64/weston"
export WESTON_MODULE_MAP="drm-backend.so=$libweston/drm-backend.so;gl-renderer.so=$libweston/gl-renderer.so;kiosk-shell.so=$modules/kiosk-shell.so;xwayland.so=$libweston/xwayland.so;"
# Daemon and libseat use the same namespace-private compiled default path.
export LIBSEAT_BACKEND=seatd SEATD_SOCK=/run/seatd.sock
# Private MIT-MAGIC-COOKIE-1 auth: Xwayland is root-owned, the probe/game
# are the original user. The file lives only in the session tmp namespace.
export PD2_XAUTHORITY="$R/xauthority" XAUTHORITY="$R/xauthority"
export XDG_RUNTIME_DIR="$R/wayland"
mkdir -m700 -p "$XDG_RUNTIME_DIR" "$R/bin"
chown "$uid:$gid" "$XDG_RUNTIME_DIR" "$R/bin"
# Xwayland is found through PATH and this build supports a configurable path.
runuser -u "$PD2_USER" --preserve-environment -- python3 -B "$PD2_PORT/scripts/x11_auth.py" --path "$PD2_XAUTHORITY" || { error xauth_prepare_failed;exit 2; }
[[ -f "$PD2_XAUTHORITY" && ! -L "$PD2_XAUTHORITY" && $(stat -c %a "$PD2_XAUTHORITY") == 600 ]] || { error xauth_prepare_failed;exit 2; }
printf '#!/bin/bash\nexec "%s/bin/Xwayland" "$@" -auth "%s/xauthority" -fp built-ins\n' "$W" "$R" > "$R/bin/Xwayland"
chmod 700 "$R/bin/Xwayland";chown "$uid:$gid" "$R/bin/Xwayland"
export PATH="$R/bin:$W/bin:$PATH"
export DISPLAY=:0 WAYLAND_DISPLAY=wayland-pd2
native_search="$W/lib_aarch64:${PD2_HOST_NATIVE_LIBS:-}"
# Resolve REAL native providers before putting Crusty EGL/GBM proxies in LD path.
CRUSTY_LIBSDL=$(python3 -B "$PD2_PORT/scripts/graphics_probe.py" --weston "$W" --role sdl --arch aarch64 --search "$native_search") || { error graphics_provider_missing;exit 2; }
CRUSTY_LIBEGL=$(python3 -B "$PD2_PORT/scripts/graphics_probe.py" --weston "$W" --role egl --arch aarch64 --search "$native_search") || { error graphics_provider_missing;exit 2; }
export CRUSTY_LIBSDL CRUSTY_LIBEGL
if CRUSTY_LIBGBM=$(python3 -B "$PD2_PORT/scripts/graphics_probe.py" --weston "$W" --role gbm --arch aarch64 --search "$native_search");then export CRUSTY_LIBGBM;else unset CRUSTY_LIBGBM;fi
if CRUSTY_LIBDRM=$(python3 -B "$PD2_PORT/scripts/graphics_probe.py" --weston "$W" --role drm --arch aarch64 --search "$native_search");then export CRUSTY_LIBDRM;else unset CRUSTY_LIBDRM;fi
# Preserve the verified GDI/DRM compositor environment and input routing.
export CRUSTY_NO_LIBINPUT=1 CRUSTY_BLOCK_INPUT=0 CRUSTY_SHOW_CURSOR=1 CRUSTY_WLMODE=0 CRUSTY_WLDISP=wayland-pd2
# Keep the compositor's drawable native-size. cnc-ddraw scales the game's
# 1024x768 surface BEFORE Xwayland/Weston; a larger Crusty SDL window is not
# a guaranteed downscaler on the R36S KMS/EGL stack.
export CRUSTY_RESOLUTION=640x480
export PD2_NATIVE_LIBS="$W/lib_armhf/extra_wayland:$W/lib_armhf:/usr/local/lib/arm-linux-gnueabihf:/usr/lib/arm-linux-gnueabihf:/lib/arm-linux-gnueabihf:/usr/lib32"
# Preserve the real-provider search path before GL proxy directories are added.
native32_search="$PD2_NATIVE_LIBS"
export PD2_NATIVE_REAL_LIBS="$native32_search"
export PD2_NATIVE64_LIBS="$W/lib_aarch64:/usr/local/lib/aarch64-linux-gnu:/usr/lib/aarch64-linux-gnu:/lib/aarch64-linux-gnu"
stage library_probe
for lib in libc.so.6 libX11.so.6 libXext.so.6 libasound.so.2 libudev.so.1 libfreetype.so.6 libfontconfig.so.1; do
 resolved=$(LD_LIBRARY_PATH="$PD2_NATIVE_LIBS" "$W/tools/findlib32" "$lib")
 if [[ -z "$resolved" ]]; then
  printf 'PD2_EVENT {"event":"runtime_error","reason":"missing_library","phase":"runtime","library":"%s"}\n' "$lib"
  exit 2
 fi
done
# Xwayland itself is AArch64 and DT_NEEDED includes desktop libGL.so.1.
# Mali/GL4ES firmwares need Westonpack's Mesa X11 stub, only for Xwayland.
xwayland_gl=
host_gl=$(LD_LIBRARY_PATH="$W/lib_aarch64" "$W/tools/findlib" libGL.so.1)
if [[ -z "$host_gl" ]];then
 xwayland_gl="$W/lib_aarch64/graphics/mesa_x11_stub"
else
 if python3 - "$host_gl" <<'PY'
import pathlib,sys
try:
 data=pathlib.Path(sys.argv[1]).read_bytes()
 sys.exit(0 if b'gl4es' in data.lower() else 1)
except OSError:sys.exit(0)
PY
 then xwayland_gl="$W/lib_aarch64/graphics/mesa_x11_stub";fi
fi
export PD2_NATIVE_PRELOAD=
preload="$W/lib_aarch64/graphics/crusty_gbm/libcrusty.so"
backendlib="$W/lib_aarch64/graphics/crusty_gbm"
weston_args=(-B drm --drm-device card0 --renderer=gl)
export PD2_CRUSTY_SDL="$(LD_LIBRARY_PATH="$PD2_NATIVE_LIBS" "$W/tools/findlib32" libSDL2-2.0.so.0)"
export PD2_CRUSTY_EGL="$(LD_LIBRARY_PATH="$PD2_NATIVE_LIBS" "$W/tools/findlib32" libEGL.so.1)"
export PD2_CRUSTY_GBM="$(LD_LIBRARY_PATH="$PD2_NATIVE_LIBS" "$W/tools/findlib32" libgbm.so.1)"
export PD2_CRUSTY_DRM="$(LD_LIBRARY_PATH="$PD2_NATIVE_LIBS" "$W/tools/findlib32" libdrm.so.2)"
stage seatd_start
SDL_VIDEO_EGL_DRIVER="$CRUSTY_LIBEGL" LD_LIBRARY_PATH="$backendlib:$W/lib_aarch64" LD_PRELOAD="$preload" "$W/seatd" -g "$group" -l error & seat_pid=$!
for ((i=0;i<50;i++)); do [[ -S "$SEATD_SOCK" ]] && break; kill -0 "$seat_pid" 2>/dev/null || break; sleep 0.1; done
if [[ ! -S "$SEATD_SOCK" ]];then
 if kill -0 "$seat_pid" 2>/dev/null;then error seatd_timeout;else error seatd_failed;fi
 exit 2
fi
stage seatd_ready
printf '[core]\nxwayland=true\n[output]\nname=DSI-1\nscale=1\nx11-wm-class=game.exe,Game.exe,explorer.exe,Explorer.exe,wine,Wine\nx11-wm-name=Diablo II,Wine desktop,Default,Game.exe,explorer.exe\n[output]\nname=DPI-1\nscale=1\nx11-wm-class=game.exe,Game.exe,explorer.exe,Explorer.exe,wine,Wine\nx11-wm-name=Diablo II,Wine desktop,Default,Game.exe,explorer.exe\n[input-method]\npath=\n[xwayland]\npath=%s/bin/Xwayland\n' "$R" > "$R/weston.ini"
chmod 600 "$R/weston.ini";chown "$uid:$gid" "$R/weston.ini"
cd "$W" || exit 2
# Match upstream privileged compositor; Wine/game still use runuser below.
# Its private runtime is root-owned; do not force SDL to connect to its own
# not-yet-created X11/Wayland server, or let SDL load the Crusty EGL proxy.
mkdir -m700 "$R/compositor-runtime" || { error invalid_layout;exit 2; }
[[ -d "$R/compositor-runtime" && ! -L "$R/compositor-runtime" ]] || { error invalid_layout;exit 2; }
mkfifo -m600 "$R/compositor.pipe" || { error invalid_layout;exit 2; }
[[ -p "$R/compositor.pipe" && ! -L "$R/compositor.pipe" ]] || { error invalid_layout;exit 2; }
( cd /;exec python3 -B "$PD2_PORT/scripts/graphics_probe.py" --stream ) < "$R/compositor.pipe" & compositor_log_pid=$!
printf 'PD2_EVENT {"event":"compositor_note","phase":"runtime","note":"root_service"}\n'
stage weston_start
setsid env -u DISPLAY -u WAYLAND_DISPLAY XDG_RUNTIME_DIR="$R/compositor-runtime" \
 SDL_VIDEO_EGL_DRIVER="$CRUSTY_LIBEGL" CRUSTY_SHOW_CURSOR=0 XWAYLAND_LD_LIBRARY_PATH="$xwayland_gl:$backendlib:$W/lib_aarch64" \
 LD_LIBRARY_PATH="$backendlib:$W/lib_aarch64" LD_PRELOAD="$preload" "$W/wp_weston" -c "$R/weston.ini" \
 "${weston_args[@]}" --shell=kiosk-shell.so -i0 -Swayland-pd2 --xwayland > "$R/compositor.pipe" 2>&1 & weston_pid=$!
printf '%s\n' "$weston_pid" > "$R/compositor.pid"
chmod 644 "$R/compositor.pid"
ready=0
for ((i=0;i<150;i++)); do
 if [[ -S /tmp/.X11-unix/X0 ]]; then ready=1;break;fi
 kill -0 "$weston_pid" 2>/dev/null || break;sleep 0.1
done
if [[ "$ready" != 1 ]]; then
 if kill -0 "$weston_pid" 2>/dev/null;then error compositor_timeout;else
  wait "$weston_pid";compositor_rc=$?
  printf 'PD2_EVENT {"event":"runtime_exit","phase":"runtime","rc":%s}\n' "$compositor_rc"
  error compositor_failed
 fi
 exit 2
fi
stage x11_probe
# Weston binds the pathname socket under inherited umask 077, as root.
# Grant only the original user's primary group access to THIS private socket.
# Do not relax global umask, compositor runtime or any host socket permissions.
[[ -d /tmp/.X11-unix && ! -L /tmp/.X11-unix && -S /tmp/.X11-unix/X0 && ! -L /tmp/.X11-unix/X0 && $(stat -c %u /tmp/.X11-unix/X0) == 0 ]] || { error x11_socket_failed;exit 2; }
chgrp "$gid" /tmp/.X11-unix/X0 && chmod 660 /tmp/.X11-unix/X0 || { error x11_socket_failed;exit 2; }
# A listening socket is NOT readiness: the first X11 Setup triggers lazy
# Xwayland. Probe both transports as the game user, without xdpyinfo/Xlib.
timeout --kill-after=5 35 runuser -u "$PD2_USER" --preserve-environment -- python3 -B "$PD2_PORT/scripts/x11_probe.py"
x11_rc=$?
if [[ "$x11_rc" != 0 ]];then
 printf 'PD2_EVENT {"event":"runtime_error","phase":"runtime","reason":"x11_probe_failed","rc":%s}\n' "$x11_rc"
 exit 2
fi
stage x11_ready
# Test is only a request to show the menu in this working game session.
# No separate pre-PortMaster KMSDRM initialization, settings writes or audio.
if [[ ${PD2_START_MENU:-0} == 1 ]]; then
 menu_selection=$(runuser -u "$PD2_USER" --preserve-environment -- python3 -B "$PD2_PORT/scripts/start_menu.py")
 menu_rc=$?
 if [[ "$menu_rc" == 10 ]]; then
  printf 'PD2_EVENT {"event":"session_probe","phase":"launch","check":"start_menu","status":"cancelled"}\n'
  exit 0
 fi
 menu_valid=0
 if [[ "$menu_rc" == 0 ]]; then
  case "$menu_selection" in
   'default default'|'default 0'|'default 1'|'default 2'|'default 3'|'default 4'|\
    'native default'|'native 0'|'native 1'|'native 2'|'native 3'|'native 4'|\
    '640x480 default'|'640x480 0'|'640x480 1'|'640x480 2'|'640x480 3'|'640x480 4'|\
    '800x600 default'|'800x600 0'|'800x600 1'|'800x600 2'|'800x600 3'|'800x600 4'|\
    '1024x768 default'|'1024x768 0'|'1024x768 1'|'1024x768 2'|'1024x768 3'|'1024x768 4') menu_valid=1;;
  esac
 fi
 if [[ "$menu_valid" == 1 ]]; then
  menu_resolution="${menu_selection%% *}"
  menu_fps="${menu_selection#* }"
  [[ "$menu_resolution" == default ]] || export PD2_GAME_RESOLUTION="$menu_resolution"
  [[ "$menu_fps" == default ]] || export PD2_FPS="$menu_fps"
  printf 'PD2_EVENT {"event":"session_probe","phase":"launch","check":"start_menu","status":"selected"}\n'
 else
  # Launcher menu MUST wait for a visible menu and explicit confirmation. Never launch
  # the game after a missing/broken menu or an invalid selection protocol.
  printf '%s\n' 'PD2: blad launchera; gra nie zostala uruchomiona. Sprawdz log.' >&2
  printf '%s\n' 'PD2: launcher menu failed; game not started. Check logs.' > /dev/tty0 2>/dev/null || true
  printf '%s\n' 'PD2: launcher menu failed; game not started. Check logs.' > /dev/tty1 2>/dev/null || true
  printf 'PD2_EVENT {"event":"session_probe","phase":"launch","check":"start_menu","status":"failed"}\n'
  exit 1
 fi
fi
stage volatile_work_prepare
mount -t tmpfs -o "size=16M,nosuid,nodev,mode=0700,uid=$uid,gid=$gid" tmpfs "$PD2_WORK" || { error volatile_work_failed; exit 2; };work_mounted=1
runuser -u "$PD2_USER" --preserve-environment -- python3 "$PD2_PORT/scripts/layout.py" --port "$PD2_PORT" --state "$PD2_STATE" --data "$R/gamedata/Diablo II" --volatile-work || { error volatile_work_failed;exit 2; }
stage volatile_work_ready
cd "$PD2_PORT" || exit 2
export PD2_AUDIO_PROBE="${PD2_AUDIO_PROBE:-0}"
case "${PD2_DIAGNOSTIC:-off}" in present|ddraw)
 # This root adapter owns the Weston PID/start; no process-name discovery.
 setsid python3 -B "$PD2_PORT/scripts/metrics.py" --port "$PD2_PORT" --pid "$weston_pid" --role compositor &
 compositor_metrics_pid=$!
 printf '%s\n' "$compositor_metrics_pid" > "$R/compositor-metrics.pid"
 chmod 644 "$R/compositor-metrics.pid"
 ;; esac
ln -s "$PD2_PORT/scripts/run-game.sh" "$R/game-session.sh"
runuser -u "$PD2_USER" --preserve-environment -- env PD2_AUDIO_TEST="${PD2_AUDIO_TEST:-1}" bash "$R/game-session.sh" & app_pid=$!
wait "$app_pid";rc=$?;app_pid=
exit "$rc"
