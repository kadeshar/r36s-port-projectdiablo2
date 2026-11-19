#!/bin/bash
# Functions sourced ONLY by the privileged adapter inside its new mount namespace.
# Bundled seatd has a compiled /run/seatd.sock and no -s option. Shadow /run
# locally, retaining other existing entries as links into a private host-run bind.
pd2_namespace_open() {
 local cur_ns
 cur_ns=$(readlink /proc/self/ns/mnt 2>/dev/null || echo "")
 if [[ -n "$cur_ns" && -n "${PD2_PARENT_MNT_NS:-}" ]]; then
  if [[ "$cur_ns" == "$PD2_PARENT_MNT_NS" && "${PD2_USER:-}" != "root" ]]; then
   error namespace_isolation_required
   return 2
  fi
 fi
 [[ "$ORIGINAL_RUN" == /tmp/pd2-r36s.* && ! -L "$ORIGINAL_RUN" && -d "$ORIGINAL_RUN" && "$ALIAS" == "/run/pd2-r36s-$BASHPID" ]] || { error invalid_layout; return 2; }
 mkdir -m700 "$ORIGINAL_RUN/host-run" || { error run_isolation_failed; return 2; }
 mount --rbind /run "$ORIGINAL_RUN/host-run" || { error run_isolation_failed; return 2; };host_run_mounted=1
 mkdir -m755 "$ORIGINAL_RUN/private-run" || { error run_isolation_failed; return 2; }
 # Do not copy socket files or overwrite/remove the host's seatd socket.
 local entry name
 shopt -s nullglob dotglob
 for entry in "$ORIGINAL_RUN/host-run/"*;do
  name=${entry##*/}
  [[ "$name" == seatd.sock || "$name" == "${ALIAS##*/}" ]] && continue
  ln -s -- "$ALIAS/host-run/$name" "$ORIGINAL_RUN/private-run/$name" || { shopt -u nullglob dotglob;error run_isolation_failed;return 2; }
 done
 shopt -u nullglob dotglob
 mount --bind "$ORIGINAL_RUN/private-run" /run || { error run_isolation_failed;return 2; };run_mounted=1
 mkdir -m700 "$ALIAS" || { error alias_setup_failed;return 2; };alias_created=1
 mount --rbind "$ORIGINAL_RUN" "$ALIAS" || { error alias_setup_failed;return 2; };alias_mounted=1
 mkdir -m1777 "$ALIAS/private-tmp" || { error tmp_isolation_failed;return 2; }
 mount --bind "$ALIAS/private-tmp" /tmp || { error tmp_isolation_failed;return 2; };tmp_mounted=1
 export PD2_RUN="$ALIAS" PD2_WESTON="$ALIAS/weston"
 R=$ALIAS;W="$PD2_WESTON"
}
is_mountpoint() {
 if command -v mountpoint >/dev/null 2>&1; then
  mountpoint -q "$1"
 else
  local d1 d2
  d1=$(stat -c %d "$1" 2>/dev/null)
  d2=$(stat -c %d "$1/.." 2>/dev/null)
  [[ -n "$d1" && -n "$d2" && "$d1" -ne "$d2" ]]
 fi
}
pd2_namespace_close() {
 # A cwd inside Weston/alias or private /tmp pins that mount (EBUSY).
 cd / || { error namespace_cleanup_failed; return 2; }
 # Restore paths in dependency order. All mounts belong to this namespace only.
 if [[ "$tmp_mounted" == 1 ]];then umount /tmp 2>/dev/null || error namespace_cleanup_failed;fi
 if [[ "$alias_mounted" == 1 ]];then umount -R "$ALIAS" 2>/dev/null || error namespace_cleanup_failed;fi
 if [[ "$alias_created" == 1 && "$ALIAS" == "/run/pd2-r36s-$BASHPID" ]] && ! is_mountpoint "$ALIAS";then rmdir "$ALIAS" 2>/dev/null || true;fi
 if [[ "$run_mounted" == 1 ]];then umount /run 2>/dev/null || error namespace_cleanup_failed;fi
 if [[ "$host_run_mounted" == 1 ]];then umount -R "$ORIGINAL_RUN/host-run" 2>/dev/null || error namespace_cleanup_failed;fi
}
