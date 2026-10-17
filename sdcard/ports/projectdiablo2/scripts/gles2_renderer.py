#!/usr/bin/env python3
"""Authenticate GL2 DLL and decode bounded numeric renderer status.

--port PORT --work WORK selects only over the stock ddraw symlink.
--watch --work WORK --pid PID emits fixed renderer_gl2 events; never signals PID.
--result --work WORK returns 86 for authoritative failure, 0 for successful
GL2 frame+presentation, 1 for unavailable/invalid/incomplete evidence.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import time

RENDERER_SIZE = 398336
RENDERER_SHA256 = '081c82664baefa6dde37cb0de92f167ef045c60e73cb5c78bf0b2fd3336e5ab8'
MAX_RENDERER = 4 * 1024 * 1024
TELEMETRY_FILE = 'pd2-gles2.jsonl'
MAX_TELEMETRY = 32768
MAX_LINE = 256
MAX_RECORDS = 128
KEYS = {'stage', 'code', 'gl_major', 'gl_minor', 'bpp', 'width', 'height', 'render_width', 'render_height'}
STAGES = {1: 'context', 2: 'api', 3: 'shader', 4: 'texture', 5: 'validation', 6: 'frame', 7: 'release', 8: 'policy'}


def _linked(info):
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, 'st_file_attributes', 0) & 0x400)


def _absolute(value):
    path = Path(value)
    if '..' in path.parts:
        raise ValueError('unsafe layout')
    return path if path.is_absolute() else Path.cwd() / path


def _directory(path):
    for item in (*reversed(path.parents), path):
        info = item.lstat()
        if _linked(info) or not stat.S_ISDIR(info.st_mode):
            raise ValueError('unsafe layout')


def _identity(info):
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns


def _read_file(path, maximum, growing=False):
    _directory(path.parent)
    before = path.lstat()
    if _linked(before) or not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size > maximum:
        raise ValueError('invalid artifact')
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_BINARY', 0))
    try:
        actual = os.fstat(fd)
        if ((actual.st_dev, actual.st_ino) != (before.st_dev, before.st_ino) or actual.st_nlink != 1 or not stat.S_ISREG(actual.st_mode)
                or (not growing and _identity(actual) != _identity(before)) or actual.st_size < before.st_size or actual.st_size > maximum):
            raise ValueError('invalid artifact')
        with os.fdopen(fd, 'rb') as stream:
            fd = None
            data = stream.read(before.st_size if growing else maximum + 1)
        after = path.lstat()
        # Status is append-only while the DLL runs. Re-read next poll if a write
        # raced the snapshot, rather than treating a partial line as a record.
        if (_linked(after) or after.st_nlink != 1 or (after.st_dev, after.st_ino) != (before.st_dev, before.st_ino)
                or (not growing and _identity(after) != _identity(before))
                or after.st_size < before.st_size or after.st_size > maximum or len(data) != before.st_size):
            raise ValueError('artifact changed')
        return data, (before.st_dev, before.st_ino)
    finally:
        if fd is not None:
            os.close(fd)


def prepare_renderer(port, work):
    port, work = _absolute(port), _absolute(work)
    source = port / 'compat/gles2-renderer/ddraw.dll'
    data, _ = _read_file(source, MAX_RENDERER)
    if not 0 < RENDERER_SIZE <= MAX_RENDERER or len(data) != RENDERER_SIZE or hashlib.sha256(data).hexdigest() != RENDERER_SHA256:
        raise ValueError('invalid renderer')
    directory = work / 'ProjectD2'
    _directory(directory)
    expected = port / 'compat/cnc-ddraw/ddraw.dll'
    targets = [p for p in directory.iterdir() if p.name.lower() == 'ddraw.dll']
    if len(targets) != 1:
        raise ValueError('invalid renderer link')
    target = targets[0]

    def original_link():
        info = target.lstat()
        if not stat.S_ISLNK(info.st_mode) or Path(os.readlink(target)) != expected:
            raise ValueError('invalid renderer link')
        return _identity(info)

    original = original_link()
    pending = directory / '.pd2-gles2-renderer.tmp'
    fd = os.open(pending, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_BINARY', 0), 0o600)
    created = pending.lstat()
    try:
        with os.fdopen(fd, 'wb') as stream:
            fd = None
            stream.write(data)
        if original_link() != original:
            raise ValueError('renderer link changed')
        os.replace(pending, target)
    finally:
        if fd is not None:
            os.close(fd)
        if os.path.lexists(pending):
            info = pending.lstat()
            if not _linked(info) and (info.st_dev, info.st_ino) == (created.st_dev, created.st_ino):
                pending.unlink()


def _unique(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise ValueError('duplicate key')
        out[key] = value
    return out


def decode_record(raw):
    try:
        if len(raw) > MAX_LINE:
            return None
        value = json.loads(raw, object_pairs_hook=_unique)
        if type(value) is not dict or set(value) != KEYS or any(type(n) is not int for n in value.values()):
            return None
        if value['stage'] not in STAGES or not 0 <= value['code'] <= 16:
            return None
        if value['bpp'] not in (0, 8, 16, 32) or not all(0 <= value[k] <= 9 for k in ('gl_major', 'gl_minor')):
            return None
        if not all(0 <= value[k] <= 16384 for k in ('width', 'height', 'render_width', 'render_height')):
            return None
        value['event'] = 'renderer_gl2'
        value['status'] = 'failed' if value['code'] else 'ready'
        value['stage'] = STAGES[value['stage']]
        return value
    except (ValueError, TypeError, RecursionError, UnicodeError):
        return None


def records(data, partial=False):
    if len(data) > MAX_TELEMETRY:
        raise ValueError('capture limit')
    lines = data.split(b'\n')
    tail = lines.pop()
    if len(tail) > MAX_LINE or (tail and not partial) or len(lines) > MAX_RECORDS:
        raise ValueError('invalid capture')
    decoded = [decode_record(line) for line in lines]
    if any(value is None for value in decoded):
        raise ValueError('invalid capture')
    return decoded


def emit(value):
    print('PD2_EVENT ' + json.dumps(value, separators=(',', ':')), flush=True)


def _pid_identity(pid):
    # Linux starttime guards PID reuse without reading/exporting cmdline/env.
    proc = Path('/proc') / str(pid) / 'stat'
    try:
        with proc.open('r', encoding='ascii') as stream:
            text = stream.read(8193)
        if len(text) > 8192:
            return None
        fields = text[text.rindex(')') + 2:].split()
        return fields[19]
    except FileNotFoundError:
        if Path('/proc').is_dir():
            return None
    except (OSError, ValueError, IndexError):
        return None
    try:
        os.kill(pid, 0)  # Existence only, never TERM/KILL.
        return 'available'
    except (ProcessLookupError, PermissionError):
        return None


def watch(work, pid):
    path = _absolute(work) / 'ProjectD2' / TELEMETRY_FILE
    owner = _pid_identity(pid)
    if owner is None:
        return 1
    previous = b''
    identity = None
    emitted = 0
    failure = False
    while True:
        alive = _pid_identity(pid) == owner
        try:
            data, current = _read_file(path, MAX_TELEMETRY, growing=True)
        except FileNotFoundError:
            data, current = b'', identity
        except (OSError, ValueError):
            return 1
        if identity is not None and current != identity:
            return 1
        if not data.startswith(previous):
            return 1
        identity = current
        decoded = records(data, partial=alive)
        for value in decoded[emitted:]:
            emit(value)
            failure |= value['status'] == 'failed'
        emitted = len(decoded)
        previous = data
        if not alive:
            return 86 if failure else 0
        if emitted >= MAX_RECORDS:
            return 86 if failure else 0
        time.sleep(0.25)


def result(work):
    directory = _absolute(work) / 'ProjectD2'
    data, _ = _read_file(directory / TELEMETRY_FILE, MAX_TELEMETRY)
    decoded = records(data)
    if any(v['status'] == 'failed' for v in decoded):
        return 86
    if not any(v['stage'] == 'frame' and v['status'] == 'ready' for v in decoded):
        return 1
    # Independent passive presentation channel must confirm successful GL swap.
    from presentation_watch import decode_record as decode_present
    data, _ = _read_file(directory / 'pd2-present.jsonl', 262144)
    lines = data.splitlines()
    if not lines or len(lines) > 4096:
        return 1
    values = [decode_present(line) if len(line) <= 512 else None for line in lines]
    if any(v is None for v in values):
        return 1
    return 0 if any(v.get('backend') == 'opengl' and v.get('status') == 'first_present' for v in values) else 1


class _Parser(argparse.ArgumentParser):
    def error(self, _message):
        raise ValueError('invalid arguments')


def main(argv=None):
    parser = _Parser(description=__doc__)
    parser.add_argument('--port')
    parser.add_argument('--work', required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--watch', action='store_true')
    mode.add_argument('--result', action='store_true')
    parser.add_argument('--pid', type=int)
    try:
        args = parser.parse_args(argv)
        if args.watch:
            if args.pid is None or args.pid <= 1 or args.port:
                return 1
            return watch(args.work, args.pid)
        if args.result:
            if args.port or args.pid is not None:
                return 1
            return result(args.work)
        if not args.port or args.pid is not None:
            return 1
        prepare_renderer(args.port, args.work)
        print('{"status":0}', flush=True)
        return 0
    except (OSError, ValueError, TypeError, RecursionError):
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
