#!/usr/bin/env python3
"""Independent stock/A35 Box86 choice in a fresh private session.

stock returns None: caller must retain its existing authenticated PD2_BOX.
a35 returns session/box86-a35: never replaces the installed runtime. The caller
must serialize setup/launch and supply its existing private session directory.
CLI uses fixed JSON only; output never contains user/device paths.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import struct
import sys

BOX_SIZE = 7822456
BOX_SHA256 = '45fa17057d5b23b3580d8a0af444f194a333d08b4a4774c0e5232af693ef6774'
SOURCE_COMMIT = 'fa59e748f91cee8542cfc996214bc4d582e4d6dd'
SOURCE_SHA256 = 'ed172675183984cc8d65d3fb8f795c32aae3d85a05511f0f22524cda8f801a26'
MAX_BOX = 32 * 1024 * 1024
MAX_MANIFEST = 65536


def _linked(info):
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, 'st_file_attributes', 0) & 0x400)


def _absolute(value):
    path = Path(value)
    if '..' in path.parts:
        raise ValueError('unsafe path')
    return path if path.is_absolute() else Path.cwd() / path


def _directory(path):
    for item in (*reversed(path.parents), path):
        info = item.lstat()
        if _linked(info) or not stat.S_ISDIR(info.st_mode):
            raise ValueError('unsafe directory')


def _identity(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)


def _read(path, maximum, expected=None):
    _directory(path.parent)
    before = path.lstat()
    if (_linked(before) or not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
            or not 0 < before.st_size <= maximum or (expected is not None and before.st_size != expected)):
        raise ValueError('unsafe source')
    flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_BINARY', 0)
    fd = os.open(path, flags)
    try:
        opened = os.fstat(fd)
        if opened.st_nlink != 1 or not stat.S_ISREG(opened.st_mode) or _identity(opened) != _identity(before):
            raise ValueError('source changed')
        with os.fdopen(fd, 'rb') as stream:
            fd = None
            data = stream.read(maximum + 1)
        after = path.lstat()
        if (_linked(after) or after.st_nlink != 1 or _identity(after) != _identity(before)
                or len(data) != before.st_size):
            raise ValueError('source changed')
        return data
    finally:
        if fd is not None:
            os.close(fd)


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate manifest key')
        result[key] = value
    return result


def _elf(data):
    if len(data) < 52 or data[:7] != b'\x7fELF\x01\x01\x01':
        raise ValueError('not ARM ELF32')
    kind, machine, version = struct.unpack_from('<HHI', data, 16)
    flags = struct.unpack_from('<I', data, 36)[0]
    if kind not in (2, 3) or machine != 40 or version != 1 or flags >> 24 != 5 or not flags & 0x400 or flags & 0x200:
        raise ValueError('not ARM EABI5 hardfloat')


def authenticate(port):
    """Return authenticated A35 bytes without staging or filesystem writes."""
    if not 0 < BOX_SIZE <= MAX_BOX or len(BOX_SHA256) != 64:
        raise ValueError('A35 build unavailable')
    source = _absolute(port) / 'compat/box86-a35'
    manifest = json.loads(_read(source / 'manifest.json', MAX_MANIFEST), object_pairs_hook=_object)
    if (manifest.get('schema') != 1 or manifest.get('variant') != 'a35'
            or manifest.get('file') != 'box86' or manifest.get('size') != BOX_SIZE
            or manifest.get('sha256') != BOX_SHA256
            or manifest.get('source', {}).get('commit') != SOURCE_COMMIT
            or manifest.get('source', {}).get('archive_sha256') != SOURCE_SHA256):
        raise ValueError('manifest not authenticated')
    data = _read(source / 'box86', MAX_BOX, BOX_SIZE)
    if hashlib.sha256(data).hexdigest() != BOX_SHA256:
        raise ValueError('binary authentication failed')
    _elf(data)
    return data


def prepare_variant(port, session, variant):
    if variant == 'stock':
        return None
    if variant != 'a35':
        raise ValueError('unknown variant')
    session = _absolute(session)
    _directory(session)
    # A shared/writable-by-other session cannot protect a verified executable.
    info = session.lstat()
    if os.name != 'nt' and (info.st_uid != os.getuid() or info.st_mode & 0o022):
        raise ValueError('session not private')
    data = authenticate(port)
    destination = session / 'box86-a35'
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_BINARY', 0)
    fd = os.open(destination, flags, 0o700)
    created = os.fstat(fd)
    try:
        with os.fdopen(fd, 'wb') as stream:
            fd = None
            stream.write(data)
            stream.flush()
            if os.name != 'nt':
                os.fchmod(stream.fileno(), 0o700)
        copied = destination.lstat()
        if (_linked(copied) or copied.st_nlink != 1 or copied.st_size != BOX_SIZE
                or (copied.st_dev, copied.st_ino) != (created.st_dev, created.st_ino)):
            raise ValueError('destination changed')
    except BaseException:
        if os.path.lexists(destination):
            current = destination.lstat()
            if not _linked(current) and (current.st_dev, current.st_ino) == (created.st_dev, created.st_ino):
                destination.unlink()
        raise
    finally:
        if fd is not None:
            os.close(fd)
    return destination


class _Parser(argparse.ArgumentParser):
    def error(self, _message):
        raise ValueError('invalid arguments')


def main(argv=None, stdout=None):
    stdout = sys.stdout if stdout is None else stdout
    parser = _Parser(description=__doc__)
    parser.add_argument('--port', required=True)
    parser.add_argument('--session', required=True)
    parser.add_argument('--variant', required=True)
    variant = 'unknown'
    try:
        args = parser.parse_args(argv)
        if args.variant in ('stock', 'a35'):
            variant = args.variant
        prepare_variant(args.port, args.session, args.variant)
        rc = 0
    except (OSError, ValueError, TypeError, AttributeError, RecursionError):
        rc = 1
    stdout.write(json.dumps({'variant': variant, 'status': 'ready' if rc == 0 else 'unavailable'}, separators=(',', ':')) + '\n')
    stdout.flush()
    return rc


if __name__ == '__main__':
    raise SystemExit(main())
