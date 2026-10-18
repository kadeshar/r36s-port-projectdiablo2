#!/usr/bin/env python3
"""Bounded DirectSound registry backup for the HelBuflen stutter experiment.

Only the five named REG_SZ values under one section may appear in a marker;
REG_SZ is the only type Wine's DirectSound configuration reads as text. reg.exe is
never executed here. The caller must prepare-export before exporting, snapshot
only after that export succeeds, stop Wine before importing the marker, and only
then retire. Export contents are never logged and never restored.
"""
import argparse
import os
from pathlib import Path
import re
import stat
import sys
import uuid

import winebus_config as wb

HEADER = wb.HEADER
PARENT_SECTION = r'HKEY_CURRENT_USER\Software\Wine'
SECTION = r'HKEY_CURRENT_USER\Software\Wine\DirectSound'
EXPORT_NAME = 'pd2-dsound-export.reg'
RESTORE_NAME = 'pd2-dsound-restore.reg'
VERIFY_NAME = 'pd2-dsound-verify.reg'
VALUES = ('HelBuflen', 'MaxHardwareChannels', 'SndQueueMax',
          'DefaultSampleRate', 'DefaultBitsPerSample')
EXPECTED_PROFILES = {
    'ver2': {
        'HelBuflen': '8192',
        'MaxHardwareChannels': '16',
        'SndQueueMax': '28',
        'DefaultSampleRate': '44100',
        'DefaultBitsPerSample': '16',
    },
    'wine': {
        'HelBuflen': '65536',
    },
}
MAX_BYTES = wb.MAX_BYTES
MAX_TEXT = 1024
ERROR_EVENT = wb.ERROR_EVENT


def _valid(text):
    # Control characters, backslash and quote would break the canonical line
    # form; the experiment only ever writes plain numeric strings.
    return len(text) <= MAX_TEXT and not any(ord(char) < 32 or char in '\\"' for char in text)


def _quoted(text):
    if not text.startswith('"'):
        raise ValueError('invalid string')
    result = []
    i = 1
    while i < len(text):
        char = text[i]
        i += 1
        if char == '"':
            return ''.join(result), text[i:]
        if char == '\\':
            if i == len(text) or text[i] not in ('\\', '"', 'r', 'n'):
                raise ValueError('invalid escape')
            char = {'r': '\r', 'n': '\n'}.get(text[i], text[i])
            i += 1
        result.append(char)
    raise ValueError('unterminated string')


def parse_export(content):
    """Return exactly VALUES, each a REG_SZ string or None when absent.

    Parent HKCU\\Software\\Wine must be present (or target section present).
    If target section is absent but parent is present, all VALUES are None.
    Foreign sections (including children) and unrelated values are ignored. A
    named value of any other type is refused rather than silently changed.
    """
    lines = wb._decode(content).splitlines()
    if not lines or lines[0] != HEADER:
        raise ValueError('invalid header')
    values = dict.fromkeys(VALUES)
    names = {name.casefold(): name for name in VALUES}
    seen = set()
    parent_seen = False
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
            section = match[1].casefold()
            if section == PARENT_SECTION.casefold():
                if parent_seen:
                    raise ValueError('duplicate parent')
                parent_seen = True
            in_target = section == SECTION.casefold()
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
            raise ValueError('duplicate value')
        seen.add(name)
        encoded = match[2].strip()
        if not encoded.startswith('='):
            raise ValueError('invalid assignment')
        encoded = encoded[1:].strip()
        if not encoded.startswith('"'):
            raise ValueError('unsupported value type')
        text, tail = _quoted(encoded)
        if tail or not _valid(text):
            raise ValueError('invalid value')
        values[name] = text
    if not target_seen and not parent_seen:
        raise ValueError('missing section')
    return values


def restore_bytes(values):
    """Return the single canonical UTF-16LE/BOM restore representation."""
    if type(values) is not dict or set(values) != set(VALUES):
        raise ValueError('invalid values')
    lines = [HEADER, '', '[' + SECTION + ']']
    for name in VALUES:
        value = values[name]
        if value is None:
            encoded = '-'
        elif isinstance(value, str) and _valid(value):
            encoded = '"' + value + '"'
        else:
            raise ValueError('invalid value')
        lines.append('"%s"=%s' % (name, encoded))
    return b'\xff\xfe' + ('\r\n'.join(lines) + '\r\n').encode('utf-16-le')


def validate_restore(content):
    """Accept only canonical markers, not general .reg input."""
    text = wb._decode(content)
    prefix = HEADER + '\r\n\r\n[' + SECTION + ']\r\n'
    pattern = re.escape(prefix)
    for name in VALUES:
        pattern += re.escape('"' + name + '"=') + r'(-|"[^"\\\r\n]*")\r\n'
    match = re.fullmatch(pattern, text)
    if not match:
        raise ValueError('invalid marker')
    values = {name: None if value == '-' else value[1:-1]
              for name, value in zip(VALUES, match.groups())}
    if content != restore_bytes(values):
        raise ValueError('noncanonical marker')
    return values


def _reservation():
    return b'\xff\xfe' + (HEADER + '\r\n\r\n[' + SECTION + ']\r\n').encode('utf-16-le')


def _publish(path, payload):
    """Publish fully fsynced 0600 bytes without replacing ANY existing entry."""
    wb._absent(path)
    temp = path.with_name('.pd2-dsound-' + uuid.uuid4().hex + '.tmp')
    wb._check_parents(temp)
    fd = os.open(str(temp), os.O_WRONLY | os.O_CREAT | os.O_EXCL
                 | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_BINARY', 0), 0o600)
    expected = os.fstat(fd)
    try:
        with os.fdopen(fd, 'wb') as output:
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
        wb._absent(path)
        os.link(str(temp), str(path))
    finally:
        wb._check_parents(temp)
        actual = temp.lstat()
        if wb._is_link(actual) or not stat.S_ISREG(actual.st_mode) or not wb._same(actual, expected):
            raise ValueError('changed temporary')
        temp.unlink()
    wb._sync_directory(path.parent)


def _prepare_export(export, marker):
    wb._absent(marker)
    try:
        export.lstat()
    except FileNotFoundError:
        _publish(export, _reservation())
    else:
        parse_export(wb._read_regular(export)[0])


def _snapshot(export, marker, missing=False):
    wb._absent(marker)
    content, expected = wb._read_regular(export)
    if missing:
        # Explicit missing-key evidence is the CALLER's responsibility. Only an
        # untouched reservation may be used, never a stale successful export.
        if content != _reservation():
            raise ValueError('not a reservation')
        values = dict.fromkeys(VALUES)
    else:
        values = parse_export(content)
    _publish(marker, restore_bytes(values))
    wb._unlink_checked(export, expected)
    wb._sync_directory(marker.parent)


def _retire(export, marker):
    content, expected = wb._read_regular(marker)
    validate_restore(content)
    try:
        export_info = wb._regular(export)
    except FileNotFoundError:
        export_info = None
    wb._sync_directory(marker.parent)
    if export_info is not None:
        wb._unlink_checked(export, export_info)
    wb._unlink_checked(marker, expected)
    wb._sync_directory(marker.parent)


def _verify_applied(verify_path, profile):
    if profile not in EXPECTED_PROFILES:
        raise ValueError('invalid profile')
    content, expected_info = wb._read_regular(verify_path)
    try:
        values = parse_export(content)
        expected = EXPECTED_PROFILES[profile]
        for name, expected_val in expected.items():
            actual = values.get(name)
            if actual is None or actual != expected_val:
                raise ValueError('mismatched value')
            if not actual.isdigit():
                raise ValueError('non-numeric value')
        helbuflen = values.get('HelBuflen')
        if not helbuflen or not helbuflen.isdigit():
            raise ValueError('invalid helbuflen')
    finally:
        wb._unlink_checked(verify_path, expected_info)
        wb._sync_directory(verify_path.parent)
    print('PD2_EVENT {"event":"session_probe","phase":"launch","check":"dsound_helbuflen","status":"%s"}' % helbuflen)


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
        mode.add_argument('--snapshot-missing', action='store_true')
        mode.add_argument('--validate', action='store_true')
        mode.add_argument('--retire', action='store_true')
        mode.add_argument('--verify-applied', choices=('ver2', 'wine'))
        args = parser.parse_args(argv)
        directory = Path(os.path.abspath(args.prefix)) / 'drive_c'
        export, marker = directory / EXPORT_NAME, directory / RESTORE_NAME
        if args.prepare_export:
            _prepare_export(export, marker)
        elif args.snapshot or args.snapshot_missing:
            _snapshot(export, marker, missing=args.snapshot_missing)
        elif args.validate:
            validate_restore(wb._read_regular(marker)[0])
        elif args.verify_applied:
            _verify_applied(directory / VERIFY_NAME, args.verify_applied)
        else:
            _retire(export, marker)
        return 0
    except Exception:
        print(ERROR_EVENT)
        return 1


if __name__ == '__main__':
    sys.exit(main())
