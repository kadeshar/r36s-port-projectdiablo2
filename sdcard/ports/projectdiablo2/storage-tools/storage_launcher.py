"""Unprivileged experiment entry. Never called automatically by build/tests."""
import argparse
import contextlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import traceback

from storage_common import StorageError, no_links, source_data, validated


def fixed_message(msg):
    for dev in ('/dev/tty0', '/dev/tty1'):
        try:
            with open(dev, 'w') as f:
                f.write(msg + '\n')
                return
        except OSError:
            pass
    print(msg, file=sys.stderr, flush=True)


@contextlib.contextmanager
def lock(path, create=True):
    import fcntl
    no_links(path)
    if create:
        path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_RDWR | (os.O_CREAT if create else 0) | getattr(os, 'O_NOFOLLOW', 0)
    fd = os.open(str(path), flags, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise StorageError('Another production/experimental session is active') from exc
        yield
    finally:
        os.close(fd)


def system_path(value):
    # ArkOS SSH sessions omit sbin even when the required tools are installed.
    parts = [p for p in value.split(os.pathsep) if p]
    return os.pathsep.join(dict.fromkeys(parts + ['/usr/sbin', '/sbin']))


def launch(port, mode):
    logs = no_links(port / 'logs')
    logs.mkdir(exist_ok=True)
    target = no_links(logs / 'storage-session.log')

    def log(msg, level='INFO'):
        ts = time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())
        line = f"[{ts}] [{level}] {msg}"
        print(line, flush=True)
        try:
            with target.open('a', encoding='utf-8') as f:
                f.write(line + '\n')
        except OSError:
            pass

    log(f"=== PD2 SD Storage Session Started (mode: {mode}) ===")
    log(f"Platform: {sys.platform}, UID: {os.getuid() if hasattr(os, 'getuid') else 'N/A'}")
    log(f"Port path: {port}")

    if sys.platform != 'linux' or os.getuid() == 0:
        err = 'Run from Ports as a normal Linux user, not root'
        log(err, level='ERROR')
        fixed_message('PD2 SD: launch as normal user (ark), not root.')
        raise StorageError(err)

    os.environ['PATH'] = system_path(os.environ.get('PATH', os.defpath))
    for command in ('sudo', 'unshare', 'mount', 'umount', 'losetup', 'runuser', 'bash', 'python3'):
        if not shutil.which(command):
            err = 'Missing tool: ' + command
            log(err, level='ERROR')
            fixed_message('PD2 SD: missing tool: ' + command)
            raise StorageError(err)
    log("Required system tools verified: sudo, unshare, mount, umount, losetup, runuser, bash, python3")

    with contextlib.ExitStack() as stack:
        # Serialize validation and stamp publication with adapter startup. A
        # shared stamp temp file must never be written by concurrent launchers.
        log("Acquiring session locks...")
        try:
            stack.enter_context(lock(port / 'storage/session.lock'))
            if mode == 'launch':
                stack.enter_context(lock(Path.home() / '.local/share/pd2-r36s/session.lock'))
            log("Session locks acquired")
        except Exception as exc:
            log(f"Failed to acquire session lock: {exc}", level='ERROR')
            fixed_message("PD2 SD: another game session is running")
            raise

        try:
            # Every fresh launcher process performs full digest validation.
            # Only its child adapter may trust the resulting session stamp.
            port, info, pins = validated(port, write_stamp=True)
            if mode == 'check':
                log("Full runtime integrity validation completed; stamp refreshed")
            else:
                log("Validated storage manifest and runtime integrity successfully")
        except Exception as exc:
            log(f"Validation failed: {exc}", level='ERROR')
            fixed_message(f"PD2 SD: validation failed: {exc}")
            raise

        box_path = str(port / 'runtime/box86')
        try:
            os.chmod(box_path, 0o755)
        except OSError:
            pass
        if not os.access(box_path, os.R_OK | os.X_OK):
            err = 'Bundled Box86 is not executable; ROM filesystem must allow exec'
            log(err, level='ERROR')
            fixed_message('PD2 SD: box86 not executable (check ROM filesystem mount)')
            raise StorageError(err)
        log("Box86 executable verified")

        if mode == 'launch':
            try:
                game_loc = source_data(port)
                log(f"Game data source: {'local projectdiablo2-sd/gamedata' if game_loc is None else str(game_loc)}")
            except Exception as exc:
                log(f"Game data resolution failed: {exc}", level='ERROR')
                fixed_message("PD2 SD: Diablo II game files not found")
                raise

        parent_ns = os.readlink('/proc/self/ns/mnt')
        adapter = no_links(port / 'storage-tools/storage_session.py')
        command = ['sudo', '-n', 'unshare', '--mount', '--propagation', 'private',
                   sys.executable, '-B', str(adapter), '--port', str(port), '--uid', str(os.getuid()),
                   '--parent-ns', parent_ns, '--mode', mode]
        log("Starting adapter: " + ' '.join(command))

        proc = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                universal_newlines=True, bufsize=1)
        with target.open('a', encoding='utf-8') as out_f:
            for line in proc.stdout:
                out_f.write(line)
                out_f.flush()
                print(line, end='', flush=True)
        rc = proc.wait()
        log(f"Adapter finished with exit code {rc}")
        if rc != 0:
            fixed_message(f"PD2 SD: launch failed (rc={rc}). Check projectdiablo2-sd/logs")
        return rc


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', required=True)
    parser.add_argument('--check', action='store_true', help='Mount/read validation only; no game or compositor')
    args = parser.parse_args()
    port = Path(args.port)
    mode = 'check' if args.check else 'launch'
    try:
        return launch(port, mode)
    except (OSError, ValueError, StorageError) as exc:
        print('PD2 SD experiment: ' + str(exc), file=sys.stderr)
        fixed_message('PD2 SD: ' + str(exc))
        try:
            log_path = port / 'logs/storage-session.log'
            if log_path.parent.is_dir():
                with log_path.open('a', encoding='utf-8') as f:
                    ts = time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())
                    f.write(f"[{ts}] [FATAL] {exc}\n")
                    traceback.print_exc(file=f)
        except OSError:
            pass
        return 1


if __name__ == '__main__':
    sys.exit(main())
