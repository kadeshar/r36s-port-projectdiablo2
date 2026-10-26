"""Root-only mount adapter. Entry requires a fresh private mount namespace."""
import argparse
import os
from pathlib import Path
import pwd
import re
import signal
import subprocess
import sys

from storage_common import StorageError, no_links, regular, source_data, validated


def call(args, **kwargs):
    result = subprocess.run([str(a) for a in args], **kwargs)
    if result.returncode:
        raise StorageError('Command failed ({}): {}'.format(result.returncode, args[0]))
    return result


def empty_dir(path):
    no_links(path)
    path.mkdir(parents=True, exist_ok=True)
    if not path.is_dir() or any(path.iterdir()) or os.path.ismount(str(path)):
        raise StorageError('Mount destination is not an empty directory: ' + str(path))


def run(args):
    if os.geteuid() != 0 or args.uid <= 0:
        raise StorageError('Adapter requires root mounts and a non-root game user')
    if not re.fullmatch(r'mnt:\[\d+\]', args.parent_ns):
        raise StorageError('Missing parent mount namespace')
    if os.readlink('/proc/self/ns/mnt') == args.parent_ns:
        raise StorageError('Refusing mounts in parent namespace')
    user = pwd.getpwuid(args.uid)
    port, info, pins = validated(args.port)
    image = port / info['state_file']
    # Loop devices are global even when mounts are private. Never attach an image
    # already kept alive by an orphaned namespace or a manual diagnostic mount.
    attached = subprocess.run(['losetup', '-j', str(image)], stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, universal_newlines=True)
    if attached.returncode or attached.stdout.strip():
        raise StorageError('State image already attached or loop status unavailable')
    state = port / 'storage/mounted-state'
    wine = port / info['wine_file']
    external_data = source_data(port) if args.mode == 'launch' else None
    mounts = []
    child = None
    previous = {}
    def cancel(signum, frame):
        # runuser supervises and forwards termination to its unprivileged child.
        if child is not None and child.poll() is None:
            child.terminate()
        else:
            raise InterruptedError('Storage session cancelled')
    try:
        for signum in (signal.SIGINT, signal.SIGTERM):
            previous[signum] = signal.signal(signum, cancel)
        empty_dir(state)
        flags = 'loop,ro,noload,nosuid,nodev,noexec' if args.mode == 'check' else 'loop,rw,nosuid,nodev,errors=remount-ro'
        call(['mount', '-t', 'ext4', '-o', flags, image, state])
        mounts.append(state)
        if args.mode == 'check':
            point = port / 'storage/mounted-wine-check'
            empty_dir(point)
        else:
            if state.stat().st_uid != user.pw_uid:
                remaining = [p for p in state.iterdir() if p.name != 'lost+found']
                if remaining:
                    raise StorageError('Existing state belongs to another user; refusing ownership changes')
                os.chown(state, user.pw_uid, user.pw_gid)
            point = state / ('runtime-' + pins['wine-8.0-x86.tar.xz']['sha256'][:12])
            empty_dir(point)
        call(['mount', '-t', 'squashfs', '-o', 'loop,ro,nosuid,nodev', wine, point])
        mounts.append(point)
        regular(point / 'wine-8.0-x86/bin/wine')
        regular(point / 'wine-8.0-x86/bin/wineserver')
        # Read/access check only: never execute an x86 runtime while validating mounts.
        access_check = ('import os,sys; '
                        'bad=[p for p in sys.argv[1:] if not os.access(p,os.R_OK|os.X_OK)]; '
                        'sys.exit(1 if bad else 0)')
        call(['runuser', '-u', user.pw_name, '--preserve-environment', '--',
              sys.executable, '-B', '-c', access_check,
              point / 'wine-8.0-x86/bin/wine', point / 'wine-8.0-x86/bin/wineserver',
              port / 'runtime/box86'])
        if args.mode == 'check':
            usage = os.statvfs(str(state))
            print('PASS: ext4 image and read-only Wine mounted in private namespace')
            print('State available bytes:', usage.f_bavail * usage.f_frsize)
            print('No Wine, compositor or game was executed')
            return 0
        if external_data is not None:
            target = port / 'gamedata'
            empty_dir(target)
            call(['mount', '--bind', external_data, target])
            mounts.append(target)
            call(['mount', '-o', 'remount,bind,ro,nosuid,nodev', target])
        # Only immutable assets are shared; configs/saves/logs are this payload's own.
        for name in ('config', 'saves', 'logs'):
            no_links(port / name)
            (port / name).mkdir(exist_ok=True)
        env = dict(os.environ, HOME=user.pw_dir, USER=user.pw_name, LOGNAME=user.pw_name,
                   PD2_EXPERIMENT_ACTIVE='sd-storage-v1', PD2_EXPERIMENT_STATE=str(state))
        child = subprocess.Popen(['runuser', '-u', user.pw_name, '--preserve-environment', '--',
                                  'bash', str(regular(port / 'private-launcher.sh'))], env=env)
        return child.wait()
    finally:
        failures = []
        for mount in reversed(mounts):
            # Never use lazy/forced unmount or recurse through mounted images.
            result = subprocess.run(['umount', str(mount)])
            if result.returncode:
                failures.append(str(mount))
        for signum, handler in previous.items():
            signal.signal(signum, handler)
        if failures:
            raise StorageError('Unmount failed; do not reuse image until detached: ' + ', '.join(failures))


def main():
    # sudo/non-login shells may omit sbin; use trusted system tools explicitly.
    os.environ['PATH'] = os.pathsep.join(['/usr/sbin', '/sbin', os.environ.get('PATH', os.defpath)])
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', required=True)
    parser.add_argument('--uid', type=int, required=True)
    parser.add_argument('--parent-ns', required=True)
    parser.add_argument('--mode', choices=('check', 'launch'), required=True)
    args = parser.parse_args()
    try:
        return run(args)
    except (OSError, ValueError, StorageError) as exc:
        print('PD2 SD storage: ' + str(exc), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
