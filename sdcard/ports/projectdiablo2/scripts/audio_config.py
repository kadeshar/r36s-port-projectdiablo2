#!/usr/bin/env python3
"""Bounded audio routing and Audio-only registry recovery; no audio/mixer writes.

--route --run DIR reports device-node access, NOT successful PCM playback. Only
an unambiguous rk817 playback device gets an exclusive session-local ALSA file.
Registry operations never execute Wine. The caller must distinguish a proven
missing key from export failure, check export success before --snapshot, import
only --validate-approved recovery bytes, stop Wine, and only then --retire.
"""
import argparse
import json
import os
from pathlib import Path
import re
import stat
import sys
import uuid

import winebus_config as wb

HEADER = wb.HEADER
SECTION = r'HKEY_CURRENT_USER\Software\Wine\Drivers'
PARENT_SECTION = r'HKEY_CURRENT_USER\Software\Wine'
EXPORT_NAME = 'pd2-audio-export.reg'
RESTORE_NAME = 'pd2-audio-restore.reg'
CONFIG_NAME = 'alsa-pd2.conf'
MAX_BYTES = 128 * 1024
MAX_VALUE_BYTES = 4096
PROC_LIMIT = 64 * 1024
ERROR_EVENT = wb.ERROR_EVENT
ID_RE = re.compile(r'[A-Za-z0-9_-]{1,32}\Z', re.ASCII)


def _decode(content):
    if not isinstance(content, bytes) or len(content) > MAX_BYTES:
        raise ValueError('invalid export')
    return wb._decode(content)


def _quoted(text):
    """Decode Wine reg.exe export escapes: backslash, quote, CR and LF."""
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
        elif ord(char) < 32 and char != '\t':
            raise ValueError('invalid string')
        result.append(char)
    raise ValueError('unterminated string')


def _value(kind, data):
    if type(kind) is not int or kind not in (1, 2, 7) or not isinstance(data, bytes):
        raise ValueError('invalid value')
    if not 2 <= len(data) <= MAX_VALUE_BYTES or len(data) % 2:
        raise ValueError('invalid value size')
    text = data.decode('utf-16-le', errors='strict')
    if not text.endswith('\x00'):
        raise ValueError('unterminated value')
    if kind in (1, 2) and '\x00' in text[:-1]:
        raise ValueError('embedded terminator')
    if kind == 7 and text != '\x00' and not text.endswith('\x00\x00'):
        raise ValueError('unterminated list')
    return {'type': kind, 'data': data}


def parse_export(content):
    """Return exactly {'Audio': None | {'type': 1|2|7, 'data': bytes}}.

    Missing Audio means delete ONLY Audio on restoration. reg.exe exports child
    keys too: foreign/child sections and unrelated values are not restored.
    A successful parent Wine export also proves absence when Drivers is absent.
    A foreign-only export, duplicate target/parent/value or malformed target fails.
    """
    lines = _decode(content).splitlines()
    if not lines or lines[0] != HEADER:
        raise ValueError('invalid header')
    target_seen = parent_seen = in_target = audio_seen = False
    value = None
    i = 1
    while i < len(lines):
        line = lines[i].strip()
        i += 1
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
        # Consume .reg hex continuations before interpreting any value. Never
        # mistake a continuation line for a new Audio or section declaration.
        while line.endswith('\\'):
            if i >= len(lines):
                raise ValueError('incomplete continuation')
            continuation = lines[i].strip()
            i += 1
            if not continuation or continuation.startswith(('"', '[', ';')):
                raise ValueError('invalid continuation')
            line = line[:-1] + continuation
        if line.startswith('@='):
            continue
        name, remainder = _quoted(line)
        if not remainder.startswith('='):
            raise ValueError('invalid assignment')
        if name.casefold() != 'audio':
            continue
        if audio_seen:
            raise ValueError('duplicate Audio')
        audio_seen = True
        encoded = remainder[1:].strip()
        if encoded.startswith('"'):
            text, tail = _quoted(encoded)
            if tail:
                raise ValueError('trailing value')
            value = _value(1, (text + '\x00').encode('utf-16-le'))
        else:
            match = re.fullmatch(r'hex\(([127])\):([0-9a-fA-F, \t]*)', encoded, re.IGNORECASE)
            if not match:
                raise ValueError('unsupported Audio type')
            tokens = match[2].split(',')
            if not tokens or any(not re.fullmatch(r'[0-9a-fA-F]{2}', token.strip()) for token in tokens):
                raise ValueError('invalid hex')
            if len(tokens) > MAX_VALUE_BYTES:
                raise ValueError('oversize value')
            value = _value(int(match[1]), bytes(int(token.strip(), 16) for token in tokens))
    if not target_seen and not parent_seen:
        raise ValueError('missing section')
    return {'Audio': value}


def restore_bytes(values):
    if type(values) is not dict or set(values) != {'Audio'}:
        raise ValueError('invalid fields')
    value = values['Audio']
    if value is None:
        encoded = '-'
    else:
        if type(value) is not dict or set(value) != {'type', 'data'}:
            raise ValueError('invalid value fields')
        value = _value(value['type'], value['data'])
        encoded = 'hex(%d):%s' % (value['type'], ','.join('%02x' % byte for byte in value['data']))
    text = HEADER + '\r\n\r\n[' + SECTION + ']\r\n"Audio"=' + encoded + '\r\n'
    return b'\xff\xfe' + text.encode('utf-16-le')


def validate_restore(content):
    text = _decode(content)
    prefix = HEADER + '\r\n\r\n[' + SECTION + ']\r\n"Audio"='
    if text == prefix + '-\r\n':
        values = {'Audio': None}
    else:
        values = parse_export(content)
    if restore_bytes(values) != content:
        raise ValueError('noncanonical marker')
    return values


def _reservation():
    return b'\xff\xfe' + (HEADER + '\r\n\r\n[' + SECTION + ']\r\n').encode('utf-16-le')


def _publish(path, payload):
    """Publish fully fsynced 0600 bytes without replacing ANY existing entry."""
    wb._absent(path)
    temp = path.with_name('.pd2-audio-' + uuid.uuid4().hex + '.tmp')
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
        values = {'Audio': None}
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


def parse_cards(content):
    if len(content) > PROC_LIMIT:
        raise ValueError('oversize cards')
    lines = content.decode('ascii', errors='strict').splitlines()
    cards = {}
    for line in lines:
        match = re.fullmatch(r'\s*([0-9]{1,3})\s+\[([^\]]+)\]\s*:\s*.*', line)
        if not match:
            if re.match(r'\s*[0-9]+\s*\[', line):
                raise ValueError('invalid card')
            continue  # ALSA's human-readable continuation/no-soundcards lines.
        number, stable = int(match[1]), match[2].strip()
        if number > 255 or not ID_RE.fullmatch(stable) or number in cards or stable in cards.values():
            raise ValueError('invalid card')
        cards[number] = stable
    return cards


def parse_pcm(content):
    if len(content) > PROC_LIMIT:
        raise ValueError('oversize pcm')
    devices = []
    seen = set()
    for line in content.decode('ascii', errors='strict').splitlines():
        if not line.strip():
            continue
        match = re.fullmatch(r'\s*([0-9]{1,3})-([0-9]{1,3}):\s*(.*)', line)
        if not match:
            raise ValueError('invalid PCM')
        card, device = int(match[1]), int(match[2])
        if card > 255 or device > 255 or (card, device) in seen:
            raise ValueError('invalid PCM index')
        seen.add((card, device))
        playback = re.findall(r'\bplayback\s+([0-9]+)\b', match[3])
        if len(playback) > 1 or ('playback' in match[3] and not playback):
            raise ValueError('invalid playback')
        if playback:
            count = int(playback[0])
            if not 1 <= count <= 256:
                raise ValueError('invalid substream count')
            devices.append((card, device))
    return devices


def _proc_bytes(path):
    content, _ = wb._read_regular(path)
    if len(content) > PROC_LIMIT:
        raise ValueError('oversize proc')
    return content


def _device_status(path):
    try:
        wb._check_parents(path)
        info = path.lstat()
        if wb._is_link(info) or not stat.S_ISCHR(info.st_mode):
            return 'missing'
        return 'ready' if os.access(path, os.R_OK | os.W_OK) else 'denied'
    except FileNotFoundError:
        return 'missing'
    except PermissionError:
        return 'denied'


ROUTE_PROFILES = ('baseline', 'dmix160', 'dmix80')


def config_bytes(stable, device, profile='baseline', ipc_key=592834):
    if not isinstance(stable, str) or not ID_RE.fullmatch(stable):
        raise ValueError('invalid ID')
    if type(device) is not int or not 0 <= device <= 255:
        raise ValueError('invalid device')
    if type(ipc_key) is not int or not 1 <= ipc_key <= 2147483647:
        raise ValueError('invalid IPC key')
    if profile not in ROUTE_PROFILES:
        raise ValueError('invalid profile')
    if profile == 'baseline':
        return ('</usr/share/alsa/alsa.conf>\n'
                'pcm.!default {\n type plug\n slave.pcm "hw:CARD=%s,DEV=%d"\n}\n'
                'ctl.!default {\n type hw\n card "%s"\n}\n' % (stable, device, stable)).encode('ascii')
    if profile in ('dmix80', 'dmix160'):
        buf_time = 80000 if profile == 'dmix80' else 160000
        return ('</usr/share/alsa/alsa.conf>\n'
                'pcm.pd2_dmix {\n'
                ' type dmix\n'
                ' ipc_key %d\n'
                ' ipc_key_add_uid true\n'
                ' ipc_perm 0600\n'
                ' slave {\n'
                '  pcm "hw:CARD=%s,DEV=%d"\n'
                '  rate 48000\n'
                '  channels 2\n'
                '  period_time 20000\n'
                '  buffer_time %d\n'
                ' }\n'
                '}\n'
                'pcm.!default {\n type plug\n slave.pcm "pd2_dmix"\n}\n'
                'ctl.!default {\n type hw\n card "%s"\n}\n' % (ipc_key, stable, device, buf_time, stable)).encode('ascii')
    raise ValueError('invalid profile')


def route(run, proc_root=Path('/proc/asound'), snd_root=Path('/dev/snd'),
          alsa_base=Path('/usr/share/alsa/alsa.conf'), device_status=None,
          profile='baseline'):
    """Synthetic roots/callback are function-only test hooks, never CLI options."""
    run = Path(os.path.abspath(run))
    destination = run / CONFIG_NAME
    wb._check_parents(destination)
    info = run.lstat()
    if wb._is_link(info) or not stat.S_ISDIR(info.st_mode):
        raise ValueError('invalid run')
    if os.name == 'posix' and (info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700):
        raise ValueError('nonprivate run')
    wb._absent(destination)  # A stale file must never be mistaken for this run's fix.
    result = {'audio_route': 'missing', 'audio_device': 'missing'}
    try:
        cards = parse_cards(_proc_bytes(Path(proc_root) / 'cards'))
        devices = parse_pcm(_proc_bytes(Path(proc_root) / 'pcm'))
    except FileNotFoundError:
        return result
    except PermissionError:
        return {'audio_route': 'denied', 'audio_device': 'denied'}
    except (ValueError, UnicodeError):
        return {'audio_route': 'ambiguous', 'audio_device': 'missing'}
    if any(card not in cards for card, _ in devices):
        return {'audio_route': 'ambiguous', 'audio_device': 'missing'}
    access = device_status or _device_status
    statuses = {(card, device): access(Path(snd_root) / ('pcmC%dD%dp' % (card, device)))
                for card, device in devices}
    aggregate = 'ready' if 'ready' in statuses.values() else ('denied' if 'denied' in statuses.values() else 'missing')
    result['audio_device'] = aggregate
    known = [number for number, stable in cards.items()
             if 'rk817' in stable.lower() and 'hdmi' not in stable.lower()]
    if not known:
        result['audio_route'] = 'default' if cards else 'missing'
        return result
    if len(known) != 1:
        result['audio_route'] = 'ambiguous'
        return result
    candidates = [(card, device) for card, device in devices if card == known[0]]
    if len(candidates) != 1:
        result['audio_route'] = 'ambiguous' if len(candidates) > 1 else 'missing'
        return result
    card, device = candidates[0]
    result['audio_device'] = statuses[(card, device)]
    # Read-only control-node access hint for the same card; never changes any
    # permissions, mixer or system file. It only helps separate a PCM problem
    # from a missing/denied control node in the diagnostic log.
    result['audio_control'] = access(Path(snd_root) / ('controlC%d' % card))
    if result['audio_device'] != 'ready':
        result['audio_route'] = result['audio_device']
        return result
    # Read-only occupancy hint, not a lock or proof that a later open succeeds.
    # Missing status is unknown; an observed occupied substream is never stolen.
    status_path = Path(proc_root) / ('card%d' % card) / ('pcm%dp' % device) / 'sub0/status'
    try:
        status = _proc_bytes(status_path).strip()
    except FileNotFoundError:
        status = None
    except PermissionError:
        result['audio_route'] = 'denied'
        return result
    except (ValueError, UnicodeError):
        result['audio_route'] = 'ambiguous'
        return result
    if status is not None and status != b'closed':
        result['audio_route'] = 'busy'
        return result
    if profile not in ROUTE_PROFILES:
        raise ValueError('invalid profile')
    if not Path(alsa_base).is_file() or not os.access(alsa_base, os.R_OK):
        result['audio_route'] = 'default'
        return result
    _publish(destination, config_bytes(cards[card], device, profile=profile))
    result['audio_route'] = 'rk817'
    return result


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise ValueError('invalid arguments')


def main(argv=None):
    try:
        parser = _Parser(add_help=False, allow_abbrev=False)
        parser.add_argument('--prefix')
        parser.add_argument('--run')
        parser.add_argument('--profile', choices=ROUTE_PROFILES, default='baseline')
        mode = parser.add_mutually_exclusive_group(required=True)
        for name in ('route', 'prepare-export', 'snapshot', 'snapshot-missing', 'validate', 'retire'):
            mode.add_argument('--' + name, action='store_true')
        args = parser.parse_args(argv)
        if args.route:
            if not args.run or args.prefix:
                raise ValueError('invalid route arguments')
            for check, status in route(args.run, profile=args.profile).items():
                print('PD2_EVENT ' + json.dumps({'event': 'session_probe', 'phase': 'launch',
                                                'check': check, 'status': status}, separators=(',', ':')))
        else:
            if not args.prefix or args.run or args.profile != 'baseline':
                raise ValueError('invalid registry arguments')
            directory = Path(os.path.abspath(args.prefix)) / 'drive_c'
            export, marker = directory / EXPORT_NAME, directory / RESTORE_NAME
            if args.prepare_export:
                _prepare_export(export, marker)
            elif args.snapshot or args.snapshot_missing:
                _snapshot(export, marker, missing=args.snapshot_missing)
            elif args.validate:
                validate_restore(wb._read_regular(marker)[0])
            else:
                _retire(export, marker)
        return 0
    except Exception:
        print(ERROR_EVENT)
        return 1


if __name__ == '__main__':
    sys.exit(main())
