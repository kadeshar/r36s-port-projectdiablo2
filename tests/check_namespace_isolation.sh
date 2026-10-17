#!/bin/bash
# Native mount-namespace smoke test only. No Wine, ARM executable or game.
set -e
PROJECT=$(cd -- "$(dirname -- "$0")/.." && pwd)
if [[ $(id -u) != 0 ]];then echo 'SKIP native namespace check: root required';exit 0;fi
if ! unshare --mount --propagation private true;then echo 'SKIP native namespace check: kernel denies unshare';exit 0;fi
ORIGIN=$(mktemp -d /tmp/pd2-r36s.namespace-check.XXXXXXXX)
[[ "$ORIGIN" == /tmp/pd2-r36s.namespace-check.* && -d "$ORIGIN" && ! -L "$ORIGIN" ]] || exit 1
finish() { [[ "$ORIGIN" == /tmp/pd2-r36s.namespace-check.* && ! -L "$ORIGIN" ]] && rm -rf -- "$ORIGIN"; }
trap finish EXIT
mkdir "$ORIGIN/gamedata" "$ORIGIN/weston"
printf 'unchanged\n' > "$ORIGIN/gamedata/asset"
PARENT_NS=$(readlink /proc/self/ns/mnt)
export PD2_PARENT_MNT_NS="$PARENT_NS"
unshare --mount --propagation private bash -s -- "$ORIGIN" "$PROJECT" <<'CHILD'
set -eu
ORIGINAL_RUN=$1;PROJECT=$2;ALIAS="/run/pd2-r36s-$BASHPID"
alias_mounted=0;alias_created=0;tmp_mounted=0;run_mounted=0;host_run_mounted=0
error() { echo "NAMESPACE_ERROR $1"; }
source "$PROJECT/sdcard/ports/projectdiablo2/scripts/private-namespace.sh"
trap pd2_namespace_close EXIT
# Read-only asset bind must survive the recursive alias mount.
mount --bind "$ORIGINAL_RUN/gamedata" "$ORIGINAL_RUN/gamedata"
mount -o remount,bind,ro "$ORIGINAL_RUN/gamedata"
pd2_namespace_open
[[ $(stat -c %a /tmp) == 1777 && -d "$R/gamedata" && -d "$R/host-run" ]]
if printf changed > "$R/gamedata/asset" 2>/dev/null;then echo 'Readonly data guard failed';exit 1;fi
python3 - <<'PY'
import os,socket,pathlib
s=socket.socket(socket.AF_UNIX);s.bind('/run/seatd.sock');s.close()
assert pathlib.Path('/run/seatd.sock').is_socket()
PY
marker="pd2-isolation-marker-$BASHPID"
printf '%s\n' "$marker" > "$R/marker-name"
printf 'private\n' > "/tmp/$marker"
# Regression: real hardware crash left adapter cwd in the Weston alias mount.
cd "$W"
pd2_namespace_close
trap - EXIT
umount "$ORIGINAL_RUN/gamedata"
CHILD
marker=$(< "$ORIGIN/marker-name")
[[ "$marker" == pd2-isolation-marker-* && ! -e "/tmp/$marker" ]]
[[ $(< "$ORIGIN/gamedata/asset") == unchanged ]]
[[ $(readlink /proc/self/ns/mnt) == "$PARENT_NS" ]]
echo 'PASS native namespace: private run/socket/tmp, readonly assets, host namespace unchanged'
