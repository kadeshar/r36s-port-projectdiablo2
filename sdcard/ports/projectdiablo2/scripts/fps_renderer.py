#!/usr/bin/env python3
"""Select the automatic render-FPS HUD in the volatile session only.

No keyboard messages, chat commands, process injection, or extra Wine process.
The caller owns a quiescent tmpfs work tree prepared by layout.py. Authenticate
bounded renderer bytes before replacing only its known cnc-ddraw symlink.
"""
import argparse
import hashlib
import os
from pathlib import Path
import stat
import sys

RENDERER_SIZE = 438272
RENDERER_SHA256 = 'acb44f73f3ee0b2aa4ac98ed860b40e0d9389162eaa7de9ec0028affc778ba5a'
MAX_RENDERER = 4 * 1024 * 1024


def _linked(info):
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, 'st_file_attributes', 0) & 0x400)


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
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)


def _renderer(source):
    _directory(source.parent)
    before = source.lstat()
    if (_linked(before) or not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
            or not 0 < RENDERER_SIZE <= MAX_RENDERER or before.st_size != RENDERER_SIZE):
        raise ValueError('invalid renderer')
    flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_BINARY', 0)
    fd = os.open(source, flags)
    try:
        actual = os.fstat(fd)
        if (not stat.S_ISREG(actual.st_mode) or actual.st_nlink != 1
                or _identity(actual) != _identity(before)):
            raise ValueError('invalid renderer')
        with os.fdopen(fd, 'rb') as stream:
            fd = None
            data = stream.read(RENDERER_SIZE + 1)
        after = source.lstat()
        if (_linked(after) or after.st_nlink != 1 or _identity(after) != _identity(before)
                or len(data) != RENDERER_SIZE
                or hashlib.sha256(data).hexdigest() != RENDERER_SHA256):
            raise ValueError('invalid renderer')
        return data
    finally:
        if fd is not None:
            os.close(fd)


def prepare_renderer(port, work):
    port, work = _absolute(port), _absolute(work)
    data = _renderer(port / 'compat/fps-renderer/ddraw.dll')
    directory = work / 'ProjectD2'
    _directory(directory)
    expected = port / 'compat/cnc-ddraw/ddraw.dll'
    targets = [path for path in directory.iterdir() if path.name.lower() == 'ddraw.dll']
    if len(targets) != 1:
        raise ValueError('invalid renderer link')
    target = targets[0]

    def original_link():
        info = target.lstat()
        if not stat.S_ISLNK(info.st_mode) or Path(os.readlink(target)) != expected:
            raise ValueError('invalid renderer link')
        return _identity(info)

    original = original_link()
    pending = directory / '.pd2-fps-renderer.tmp'
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_BINARY', 0)
    fd = os.open(pending, flags, 0o600)
    created = pending.lstat()
    try:
        with os.fdopen(fd, 'wb') as stream:
            fd = None
            stream.write(data)
        if original_link() != original:
            raise ValueError('renderer link changed')
        # Replace the link itself, never follow it into the pinned companion.
        os.replace(pending, target)
    finally:
        if fd is not None:
            os.close(fd)
        if os.path.lexists(pending):
            info = pending.lstat()
            if not _linked(info) and (info.st_dev, info.st_ino) == (created.st_dev, created.st_ino):
                pending.unlink()


class _Parser(argparse.ArgumentParser):
    def error(self, _message):
        raise ValueError('invalid arguments')


def main(argv=None, stdout=None):
    stdout = sys.stdout if stdout is None else stdout
    parser = _Parser(description=__doc__)
    parser.add_argument('--port', required=True)
    parser.add_argument('--work', required=True)
    try:
        args = parser.parse_args(argv)
        prepare_renderer(args.port, args.work)
        status, rc = 'renderer', 0
    except (OSError, ValueError, TypeError, RecursionError):
        status, rc = 'unavailable', 1
    stdout.write('PD2_EVENT {"event":"session_probe","phase":"launch",'
                 '"check":"fps_counter","status":"' + status + '"}\n')
    stdout.flush()
    return rc


if __name__ == '__main__':
    raise SystemExit(main())
