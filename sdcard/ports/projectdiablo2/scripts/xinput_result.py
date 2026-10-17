#!/usr/bin/env python3
"""Read only the bounded native probe report and emit fixed, nonsecret enums."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import time

MAX_BYTES = 4096
PROBE_SIZE = 117760
PROBE_SHA256 = 'a29deca066455a989e5c8b81eec216d78090bccb1d76be0ee0d9b34f16df85c6'
FIELDS = {
    "api": ("ready", "library_missing", "entry_missing"),
    "devices": ("ready", "missing", "error"),
    "buttons": ("changed", "unchanged", "unavailable"),
    "axes": ("changed", "unchanged", "unavailable"),
}

CONTROL_NAMES = ('a', 'b', 'y', 'x', 'start', 'select', 'menu', 'l1', 'l2', 'l3',
                 'r1', 'r2', 'r3', 'up', 'down', 'left', 'right')
CONTROL_STATES = ('passed', 'pressed', 'not_seen', 'unavailable', 'unsupported')
PHYSICAL_STATES = ('passed', 'pressed', 'not_seen', 'multiple', 'unavailable')


def validate(value):
    """Return a fresh exact-schema summary, or raise ValueError (never coerce)."""
    if type(value) is not dict or type(value.get('schema_version')) is not int:
        raise ValueError("invalid report")
    version = value['schema_version']
    extra = {'controls', 'physical_controls'} if version == 2 else set()
    if version not in (1, 2) or set(value) != {'schema_version', *FIELDS, *extra}:
        raise ValueError("invalid report")
    for field, choices in (('controls', CONTROL_STATES), ('physical_controls', PHYSICAL_STATES)):
        if version == 2:
            controls = value[field]
            if type(controls) is not dict or set(controls) != set(CONTROL_NAMES):
                raise ValueError("invalid report")
            if any(type(status) is not str or status not in choices for status in controls.values()):
                raise ValueError("invalid report")
    for key, choices in FIELDS.items():
        if type(value[key]) is not str or value[key] not in choices:
            raise ValueError("invalid report")
    if value["api"] != "ready" and value["devices"] != "error":
        raise ValueError("inconsistent report")
    available = value["devices"] == "ready"
    if any((value[key] != "unavailable") != available for key in ("buttons", "axes")):
        raise ValueError("inconsistent report")
    if version == 2:
        for name, status in value['controls'].items():
            if status == 'unsupported' and name != 'menu':
                raise ValueError('inconsistent report')
            if not available and status not in ('unavailable', 'unsupported'):
                raise ValueError('inconsistent report')
        return dict(value, controls=dict(value['controls']),
                    physical_controls=dict(value['physical_controls']))
    return dict(value)


def _unique(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("invalid report")
        value[key] = item
    return value


def _linked(info):
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0)
        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def _checked(path, limit=MAX_BYTES):
    # Do not resolve(): doing so would hide a linked ancestor.
    for parent in reversed(path.parents):
        info = os.lstat(parent)
        if _linked(info) or not stat.S_ISDIR(info.st_mode):
            raise ValueError("unsafe report")
    info = os.lstat(path)
    if _linked(info) or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise ValueError("unsafe report")
    if info.st_size > limit:
        raise ValueError("invalid report")
    return info


def read_summary(work):
    """Read WORK/ProjectD2/pd2-xinput-result.json; reject links and unsafe files.

    Filesystem failures raise OSError; malformed/unsafe reports raise ValueError.
    An O_NOFOLLOW open plus before/after identity checks protect the leaf. Every
    ancestor is checked both before and after opening; the work tree must not be
    concurrently replaced by an untrusted process.
    """
    # Keep '..' visible for ancestor checks rather than normalizing through links.
    path = Path(work)
    if not path.is_absolute():
        path = Path.cwd() / path
    path = path / "ProjectD2" / "pd2-xinput-result.json"
    before = _checked(path)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    flags |= getattr(os, "O_NONBLOCK", 0)  # Never block on a replaced FIFO.
    fd = os.open(path, flags)
    try:
        actual = os.fstat(fd)
        after = _checked(path)
        if (not stat.S_ISREG(actual.st_mode) or actual.st_nlink != 1
                or actual.st_size > MAX_BYTES
                or (actual.st_dev, actual.st_ino) != (before.st_dev, before.st_ino)
                or (actual.st_dev, actual.st_ino) != (after.st_dev, after.st_ino)):
            raise ValueError("unsafe report")
        with os.fdopen(fd, "rb") as reader:
            fd = None
            data = reader.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            raise ValueError("invalid report")
        value = json.loads(data.decode("utf-8", "strict"), object_pairs_hook=_unique)
        return validate(value)
    finally:
        if fd is not None:
            os.close(fd)


def prepare_probe(port, work):
    """Authenticate our executable, then link it into a fresh volatile session."""
    source = Path(port).absolute() / 'compat/xinput-probe/xinput-probe.exe'
    info = _checked(source, PROBE_SIZE)
    if info.st_size != PROBE_SIZE or hashlib.sha256(source.read_bytes()).hexdigest() != PROBE_SHA256:
        raise ValueError('invalid probe')
    directory = Path(work).absolute() / 'ProjectD2'
    for path in (directory, *directory.parents):
        entry = path.lstat()
        if _linked(entry) or not stat.S_ISDIR(entry.st_mode):
            raise ValueError('unsafe work')
    target = directory / 'pd2-xinput-probe.exe'
    report = directory / 'pd2-xinput-result.json'
    # No stale results and no replacement/deletion of any existing session file.
    if any(os.path.lexists(path) for path in (target, report,
            directory / 'pd2-button-step.txt', directory / 'pd2-button-physical.txt')):
        raise ValueError('stale probe')
    target.symlink_to(source)


class _Parser(argparse.ArgumentParser):
    def error(self, _message):
        raise ValueError("invalid arguments")


def main(argv=None, stdout=None):
    """Emit four session_probe events, or one fixed runtime_error; return 0/1."""
    stdout = sys.stdout if stdout is None else stdout
    parser = _Parser(description=__doc__)
    parser.add_argument("--work", required=True)
    parser.add_argument("--port")
    parser.add_argument("--prepare", action='store_true')
    try:
        args = parser.parse_args(argv)
        if args.prepare:
            if not args.port:
                raise ValueError('invalid arguments')
            prepare_probe(args.port, args.work)
            return 0
        if args.port:
            raise ValueError('invalid arguments')
        value = read_summary(args.work)
    except (OSError, ValueError, TypeError, RecursionError):
        events = [{"event": "runtime_error", "phase": "launch",
                   "reason": "invalid_layout", "rc": 1}]
        rc = 1
    else:
        events = [{"event": "session_probe", "phase": "launch",
                   "check": "xinput_" + key, "status": value[key]} for key in FIELDS]
        if value['schema_version'] == 2:
            for field, prefix in (('controls', 'xinput_button_'),
                                  ('physical_controls', 'physical_button_')):
                events.extend(dict(event='session_probe', phase='launch',
                                   check=prefix + name, status=value[field][name])
                              for name in CONTROL_NAMES)
        rc = 0
    for event in events:
        stdout.write("PD2_EVENT " + json.dumps(event, separators=(",", ":")) + "\n")
    stdout.flush()
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
