#!/usr/bin/env python3
"""Fallback unshare implementation using Linux syscalls when unshare binary is missing."""
import ctypes
import os
import sys

CLONE_NEWNS = 0x00020000
MS_REC = 0x4000
MS_PRIVATE = 1 << 18


def unshare_mount_namespace():
    try:
        libc = ctypes.CDLL(None, use_errno=True)
        if hasattr(libc, 'unshare'):
            rc = libc.unshare(CLONE_NEWNS)
        else:
            # Syscall fallback: aarch64=97, armhf=337, x86_64=272, i386=310
            SYS_unshare = 97 if sys.maxsize > 2**32 else 337
            rc = libc.syscall(SYS_unshare, CLONE_NEWNS)
        if rc != 0:
            err = ctypes.get_errno()
            return False, err
        libc.mount(b"none", b"/", None, MS_REC | MS_PRIVATE, None)
        return True, 0
    except Exception as exc:
        return False, str(exc)


def main():
    args = sys.argv[1:]
    cmd_start = 0
    while cmd_start < len(args):
        arg = args[cmd_start]
        if arg in ('--mount', '-m'):
            cmd_start += 1
        elif arg == '--propagation':
            cmd_start += 2
        elif arg.startswith('--propagation='):
            cmd_start += 1
        elif arg.startswith('-'):
            cmd_start += 1
        else:
            break

    target_cmd = args[cmd_start:]
    if not target_cmd:
        print("Usage: unshare_shim.py [options] <command> [args...]", file=sys.stderr)
        sys.exit(1)

    ok, err = unshare_mount_namespace()
    if not ok:
        is_root = (os.getuid() == 0) if hasattr(os, 'getuid') else False
        if is_root:
            sys.stderr.write(f"[WARN] unshare syscall unavailable ({err}), continuing in host namespace\n")
        else:
            sys.stderr.write(f"[ERROR] unshare syscall failed ({err})\n")
            sys.exit(1)

    os.execvp(target_cmd[0], target_cmd)


if __name__ == '__main__':
    main()
