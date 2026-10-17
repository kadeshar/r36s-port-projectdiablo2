#!/usr/bin/env python3
"""Private, bounded Winebus snapshot markers; never execute registry commands.

The caller must prepare-export before exporting with reg.exe, snapshot only after
that export succeeds, and successfully import our validated marker and stop
wineserver before retire. Export contents are never logged. Only the three named
DWORDs can appear in a restore marker.
"""
import argparse
import os
from pathlib import Path
import re
import stat
import sys
import uuid

MAX_BYTES = 128 * 1024
FLAGS = ('Enable SDL', 'DisableInput', 'DisableUdevd')
SECTION = r'HKEY_LOCAL_MACHINE\System\CurrentControlSet\Services\winebus'
HEADER = 'Windows Registry Editor Version 5.00'
EXPORT_NAME = 'pd2-winebus-export.reg'
RESTORE_NAME = 'pd2-winebus-restore.reg'
ERROR_EVENT = 'PD2_EVENT {"event":"runtime_error","reason":"invalid_layout","phase":"launch","rc":1}'


def _decode(content):
    if not isinstance(content, bytes) or len(content) > MAX_BYTES:
        raise ValueError('invalid export')
    if content.startswith(b'\xff\xfe'):
        text = content[2:].decode('utf-16-le', errors='strict')
    else:
        text = content.decode('utf-8-sig', errors='strict')
    if '\x00' in text or '\ufeff' in text:
        raise ValueError('invalid encoding')
    return text


def parse_export(content):
    """Read an exported key, returning exactly FLAGS with DWORD ints or None.

    None means the flag was absent and must be deleted when restoring. Foreign
    sections (including children) and unrelated values are deliberately ignored.
    """
    lines = _decode(content).splitlines()
    if not lines or lines[0] != HEADER:
        raise ValueError('invalid header')
    values = dict.fromkeys(FLAGS)
    names = {name.casefold(): name for name in FLAGS}
    seen = set()
    target_seen = False
    in_target = False
    for line in lines[1:]:
        line = line.strip()
        if not line or line.startswith(';'):
            continue
        if line.startswith('['):
            match = re.fullmatch(r'\[([^\[\]]+)\]', line)
            if not match:
                raise ValueError('invalid section')
            in_target = match[1].casefold() == SECTION.casefold()
            if in_target:
                if target_seen:
                    raise ValueError('duplicate section')
                target_seen = True
            continue
        if not in_target:
            continue
        match = re.fullmatch(r'"([^"\\]*)"(.*)', line)
        if not match or match[1].casefold() not in names:
            continue
        name = names[match[1].casefold()]
        if name in seen:
            raise ValueError('duplicate flag')
        seen.add(name)
        dword = re.fullmatch(r'\s*=\s*dword:([0-9a-fA-F]{1,8})', match[2], re.IGNORECASE)
        if not dword:
            raise ValueError('invalid DWORD')
        values[name] = int(dword[1], 16)
    if not target_seen:
        raise ValueError('missing section')
    return values


def restore_bytes(values):
    """Return the single canonical UTF-16LE/BOM restore representation."""
    if not isinstance(values, dict) or set(values) != set(FLAGS):
        raise ValueError('invalid flags')
    lines = [HEADER, '', '[' + SECTION + ']']
    for name in FLAGS:
        value = values[name]
        if value is None:
            encoded = '-'
        elif type(value) is int and 0 <= value <= 0xffffffff:
            encoded = 'dword:%08x' % value
        else:
            raise ValueError('invalid DWORD')
        lines.append('"%s"=%s' % (name, encoded))
    return b'\xff\xfe' + ('\r\n'.join(lines) + '\r\n').encode('utf-16-le')


def validate_restore(content):
    """Accept only canonical markers, not general .reg input."""
    text = _decode(content)
    prefix = HEADER + '\r\n\r\n[' + SECTION + ']\r\n'
    pattern = re.escape(prefix)
    for name in FLAGS:
        pattern += re.escape('"' + name + '"=') + r'(-|dword:[0-9a-f]{8})\r\n'
    match = re.fullmatch(pattern, text)
    if not match:
        raise ValueError('invalid marker')
    values = {name: None if value == '-' else int(value[6:], 16)
              for name, value in zip(FLAGS, match.groups())}
    if content != restore_bytes(values):
        raise ValueError('noncanonical marker')
    return values


def _is_link(info):
    # Junctions/reparse points on Windows must not bypass the symlink check.
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, 'st_file_attributes', 0) & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400))


def _check_parents(path):
    for parent in reversed(path.parents):
        info = parent.lstat()
        if _is_link(info) or not stat.S_ISDIR(info.st_mode):
            raise ValueError('invalid parent')


def _regular(path):
    _check_parents(path)
    info = path.lstat()
    if _is_link(info) or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise ValueError('invalid file')
    return info


def _same(left, right):
    return (left.st_dev, left.st_ino) == (right.st_dev, right.st_ino)


def _read_regular(path):
    expected = _regular(path)
    if expected.st_size > MAX_BYTES:
        raise ValueError('oversize file')
    fd = os.open(str(path), os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_BINARY', 0))
    with os.fdopen(fd, 'rb') as source:
        actual = os.fstat(source.fileno())
        if not _same(expected, actual) or not stat.S_ISREG(actual.st_mode) or actual.st_nlink != 1:
            raise ValueError('changed file')
        content = source.read(MAX_BYTES + 1)
    if len(content) > MAX_BYTES:
        raise ValueError('oversize file')
    return content, expected


def _unlink_checked(path, expected):
    if not _same(_regular(path), expected):
        raise ValueError('changed file')
    path.unlink()


def _absent(path):
    _check_parents(path)
    try:
        path.lstat()
    except FileNotFoundError:
        return
    raise ValueError('existing marker')


def _sync_directory(directory):
    # Windows does not expose portable directory fsync; POSIX must persist the
    # marker's directory entry before the caller can mutate the registry.
    if os.name != 'posix':
        return
    _check_parents(directory / '.pd2-directory-check')
    expected = directory.lstat()
    fd = os.open(str(directory), os.O_RDONLY | os.O_DIRECTORY | getattr(os, 'O_NOFOLLOW', 0))
    try:
        actual = os.fstat(fd)
        if not stat.S_ISDIR(actual.st_mode) or not _same(expected, actual):
            raise ValueError('changed directory')
        os.fsync(fd)
    finally:
        os.close(fd)


def _prepare_export(export, marker):
    # This is a reservation for reg.exe /y, not evidence of a successful export.
    # The shell must check reg.exe's exit status before invoking snapshot.
    _absent(marker)
    try:
        export.lstat()
    except FileNotFoundError:
        _check_parents(export)
        fd = os.open(str(export), os.O_WRONLY | os.O_CREAT | os.O_EXCL
                     | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_BINARY', 0), 0o600)
        with os.fdopen(fd, 'wb') as output:
            payload = b'\xff\xfe' + (HEADER + '\r\n\r\n[' + SECTION + ']\r\n').encode('utf-16-le')
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
        _sync_directory(export.parent)
    else:
        # A previous valid export may be retried, but never overwrite arbitrary
        # files, directories, symlinks, or files shared through hardlinks.
        parse_export(_read_regular(export)[0])


def _snapshot(export, marker):
    # Refusal must leave an existing recovery marker and the source untouched.
    _absent(marker)
    content, export_info = _read_regular(export)
    payload = restore_bytes(parse_export(content))
    temp = marker.with_name('.pd2-winebus-' + uuid.uuid4().hex + '.tmp')
    _check_parents(temp)
    fd = os.open(str(temp), os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0)
                 | getattr(os, 'O_BINARY', 0), 0o600)
    temp_info = os.fstat(fd)
    try:
        with os.fdopen(fd, 'wb') as output:
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
        _absent(marker)
        # Hard-link publication is atomic and never replaces an existing path.
        os.link(str(temp), str(marker))
    finally:
        # During publication nlink is temporarily two, so inspect identity here.
        _check_parents(temp)
        current = temp.lstat()
        if _is_link(current) or not stat.S_ISREG(current.st_mode) or not _same(current, temp_info):
            raise ValueError('changed temporary file')
        temp.unlink()
    _sync_directory(marker.parent)
    _unlink_checked(export, export_info)
    _sync_directory(marker.parent)


def _retire(export, marker):
    content, marker_info = _read_regular(marker)
    validate_restore(content)
    try:
        export_info = _regular(export)
    except FileNotFoundError:
        export_info = None
    # Both paths are checked before either is removed; marker is retired last.
    # Preflight directory fsync so unsupported persistence fails before deletion.
    _sync_directory(marker.parent)
    if export_info is not None:
        _unlink_checked(export, export_info)
    _unlink_checked(marker, marker_info)
    _sync_directory(marker.parent)


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise ValueError('invalid arguments')


def main(argv=None):
    try:
        parser = _Parser(add_help=False, allow_abbrev=False)
        parser.add_argument('--prefix', required=True)
        mode = parser.add_mutually_exclusive_group(required=True)
        mode.add_argument('--prepare-export', action='store_true')
        mode.add_argument('--snapshot', action='store_true')
        mode.add_argument('--validate', action='store_true')
        mode.add_argument('--retire', action='store_true')
        args = parser.parse_args(argv)
        directory = Path(os.path.abspath(args.prefix)) / 'drive_c'
        export, marker = directory / EXPORT_NAME, directory / RESTORE_NAME
        if args.prepare_export:
            _prepare_export(export, marker)
        elif args.snapshot:
            _snapshot(export, marker)
        elif args.validate:
            validate_restore(_read_regular(marker)[0])
        else:
            _retire(export, marker)
        return 0
    except Exception:
        print(ERROR_EVENT)
        return 1


if __name__ == '__main__':
    sys.exit(main())
