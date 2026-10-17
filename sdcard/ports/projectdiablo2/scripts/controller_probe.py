#!/usr/bin/env python3
"""Bounded Linux mapper readiness check; never read input events or names."""
import argparse
import json
import os
from pathlib import Path
import re
import stat
import tempfile
import time

MAX_ITEMS = 256
MAX_BYTES = 8192
MAX_POLLS = 51
EVENT = re.compile(r'event[0-9]{1,10}\Z', re.ASCII)


def _private_parent(path, run_dir):
    """Only accept a direct child of the launcher's trusted private directory."""
    if run_dir is None:
        run_dir = os.environ.get('PD2_RUN')
    if not run_dir:
        raise ValueError()
    root = Path(run_dir).absolute()
    path = Path(path).absolute()
    if path.parent != root:
        raise ValueError()
    for node in (root, *root.parents):
        if stat.S_ISLNK(node.lstat().st_mode):
            raise ValueError()
    info = root.stat()
    if not stat.S_ISDIR(info.st_mode):
        raise ValueError()
    if os.name == 'posix' and (info.st_uid != os.getuid() or info.st_mode & 0o077):
        raise ValueError()
    try:
        info = path.lstat()
    except FileNotFoundError:
        return path
    if not stat.S_ISREG(info.st_mode):
        raise ValueError()
    return path


def _identifiers(sys_root):
    result = set()
    with os.scandir(sys_root) as entries:
        for count, entry in enumerate(entries, 1):
            if count > MAX_ITEMS:
                raise ValueError()
            if EVENT.fullmatch(entry.name):
                result.add(entry.name)
    return result


def snapshot(path, *, run_dir=None, sys_root=Path('/sys/class/input')):
    """Atomically persist only bounded kernel event identifiers."""
    temporary = None
    try:
        path = _private_parent(path, run_dir)
        data = json.dumps(sorted(_identifiers(sys_root)), separators=(',', ':')).encode('ascii')
        if len(data) > MAX_BYTES:
            raise ValueError()
        fd, temporary = tempfile.mkstemp(prefix='.controller-', dir=path.parent)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        _private_parent(path, run_dir)
        os.replace(temporary, path)
        temporary = None
        return 'ready'
    except PermissionError:
        return 'denied'
    except (ValueError, TypeError):
        return 'invalid'
    except OSError:
        return 'unavailable'
    finally:
        if temporary is not None:
            os.unlink(temporary)


def _baseline(path, run_dir):
    path = _private_parent(path, run_dir)
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0))
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_BYTES:
            raise ValueError()
        data = os.read(fd, MAX_BYTES + 1)
    finally:
        os.close(fd)
    if len(data) > MAX_BYTES:
        raise ValueError()
    values = json.loads(data.decode('ascii'))
    if (not isinstance(values, list) or len(values) > MAX_ITEMS
            or any(not isinstance(x, str) or not EVENT.fullmatch(x) for x in values)
            or len(set(values)) != len(values)):
        raise ValueError()
    return set(values)


def _id(path):
    with open(path, 'rb', buffering=0) as stream:
        value = stream.read(17)
    if len(value) > 16 or not re.fullmatch(rb'[0-9a-fA-F]{4}\s*', value):
        raise ValueError()
    return value.strip().lower()


def _candidate(name, sys_root, virtual_root, dev_root):
    device = (Path(sys_root) / name / 'device').resolve(strict=True)
    virtual = Path(virtual_root).resolve(strict=True)
    if device == virtual or virtual not in device.parents:
        return False
    if _id(device / 'id/vendor') != b'045e' or _id(device / 'id/product') != b'028e':
        return False
    node = Path(dev_root) / name
    if not stat.S_ISCHR(node.stat().st_mode):
        return False
    fd = os.open(node, os.O_RDWR | getattr(os, 'O_NONBLOCK', 0) | getattr(os, 'O_NOFOLLOW', 0))
    try:
        return stat.S_ISCHR(os.fstat(fd).st_mode)
    finally:
        os.close(fd)


def wait(path, *, run_dir=None, sys_root=Path('/sys/class/input'),
         virtual_root=Path('/sys/devices/virtual/input'), dev_root=Path('/dev/input'),
         clock=time.monotonic, sleep=time.sleep):
    """Wait at most five seconds for a new openable virtual Xbox controller."""
    try:
        baseline = _baseline(path, run_dir)
    except PermissionError:
        return 'denied'
    except (ValueError, TypeError, UnicodeError, RecursionError):
        return 'invalid'
    except FileNotFoundError:
        return 'invalid'
    except OSError:
        return 'unavailable'
    deadline = clock() + 5.0
    status = 'missing'
    for poll in range(MAX_POLLS):
        try:
            names = _identifiers(sys_root) - baseline
            for name in sorted(names):
                try:
                    if _candidate(name, sys_root, virtual_root, dev_root):
                        return 'ready'
                except FileNotFoundError:
                    pass  # A kernel node may disappear during enumeration.
                except PermissionError:
                    status = 'denied'
                except (OSError, ValueError, RuntimeError):
                    if status != 'denied':
                        status = 'unavailable'
        except PermissionError:
            status = 'denied'
        except (OSError, ValueError):
            if status != 'denied':
                status = 'unavailable'
        remaining = deadline - clock()
        if remaining <= 0 or poll == MAX_POLLS - 1:
            break
        sleep(min(0.1, remaining))
    return status


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument('--snapshot', type=Path)
    choice.add_argument('--wait', type=Path)
    args = parser.parse_args(argv)
    status = snapshot(args.snapshot) if args.snapshot is not None else wait(args.wait)
    if args.wait is not None or status != 'ready':
        print('PD2_EVENT ' + json.dumps(dict(event='session_probe', check='virtual_gamepad',
              phase='launch', status=status), separators=(',', ':')), flush=True)
    return 0 if status == 'ready' else 1


if __name__ == '__main__':
    raise SystemExit(main())
