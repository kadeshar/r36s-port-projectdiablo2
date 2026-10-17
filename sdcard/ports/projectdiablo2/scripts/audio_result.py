#!/usr/bin/env python3
"""Authenticate our explicit Audio Test and read only bounded, closed results."""
import argparse
import hashlib
import json
import os
import re
from pathlib import Path
import stat
import sys
from xinput_result import _checked, _linked, _unique

AUDIO_SIZE = 114176
AUDIO_SHA256 = '0ce817af5dc0583cef4de5579be6d421ed8fb8610d2274216e35822d5490370e'
LIMIT = 4096
DRIVER_LIMIT = 262144
STATUSES = ('ready', 'missing', 'busy', 'denied', 'unsupported', 'error')
FIELDS = {'open': STATUSES, 'directsound': STATUSES + ('not_run',),
          'write': ('ready', 'error', 'not_run'),
          'tone': ('completed', 'error', 'not_run')}


def driver_events(content):
    """Wine 8.0 alsa.c messages, verified against the shipped winealsa.so.

    Only closed observations leave RAM. Warnings may concern capture as well
    as playback; their absence is not proof of successful enumeration.
    """
    def event(check, status):
        return dict(event='session_probe', phase='launch', check=check, status=status)
    lines = content.decode('utf-8', 'replace').splitlines()
    if 'pd2-capture-marker' not in lines:
        return [event('audio_alsa_capture', 'unavailable')]
    stages = {key: set() for key in ('default', 'plughw', 'control', 'cards', 'devices', 'stream', 'params')}
    render = capture = False
    pattern = re.compile(r'^(?:[0-9a-fA-F]+:)*(trace|warn|err):alsa:([A-Za-z0-9_]+) (.*)$')
    for line in lines:
        match = pattern.fullmatch(line)
        if not match:
            continue
        level, function, message = match.groups()
        stage = None
        if function in ('alsa_try_open', 'alsa_probe_num_speakers'):
            node = re.match(r'devnode: (default|plughw:[0-9]+,[0-9]+), flow: [01]$', message)
            failure = re.match(r'The device "(default|plughw:[0-9]+,[0-9]+)" failed to open: (-[0-9]+) \(', message)
            if node and level == 'trace':
                stages['default' if node[1] == 'default' else 'plughw'].add(('attempted', None))
            if failure and level in ('warn', 'err'):
                stage = 'default' if failure[1] == 'default' else 'plughw'
        elif function == 'construct_device_id' and level == 'trace':
            render |= bool(re.match(r'Enumerated device: L?"Out: ', message))
            capture |= bool(re.match(r'Enumerated device: L?"In: ', message))
        elif level in ('warn', 'err'):
            if function == 'alsa_open_device' and message.startswith('Unable to open PCM '):
                stage = 'stream'
            elif function == 'alsa_get_endpoint_ids' and message.startswith('Unable to open ctl for ALSA device '):
                stage = 'control'
            elif function == 'alsa_get_endpoint_ids' and message.startswith('Got a failure during card enumeration: '):
                stage = 'cards'
            elif function == 'alsa_get_card_devices' and message.startswith(('Got a failure during device enumeration on card ', 'Failed to get info for card ')):
                stage = 'devices'
            elif function in ('alsa_get_mix_format', 'alsa_probe_num_speakers', 'alsa_is_format_supported') and message.startswith(('snd_pcm_hw_params_any failed for ', 'Unable to get hw_params:', 'Unable to get max channels:', 'Unable to get min channels:', 'Unable to get min rate:', 'Unable to get max rate:', "Didn't recognize any available ALSA formats", 'Unknown max rate:')):
                stage = 'params'
            elif function == 'alsa_create_stream' and message.startswith(('Unable to get hw_params:', 'Unable to set access:', 'Unable to set ALSA format ', 'Unable to set rate ', 'Unable to set channels ', 'Unable to set hw params:')):
                stage = 'params'
        if stage:
            code = re.search(r': (-[0-9]{1,10}) \(', message)
            alsa_rc = int(code[1]) if code else None
            if alsa_rc is not None and not -2147483648 <= alsa_rc < 0:
                alsa_rc = None
            fallback = 'unsupported' if message.startswith(("Didn't recognize any available ALSA formats", 'Unknown max rate:')) else 'other_error'
            status = {-2: 'missing', -13: 'denied', -16: 'busy', -19: 'missing',
                      -22: 'invalid', -38: 'unsupported', -95: 'unsupported'}.get(alsa_rc, fallback)
            stages[stage].add((status, alsa_rc))
    events = [event('audio_alsa_capture', 'limited' if len(content) >= DRIVER_LIMIT else 'complete')]
    for stage, observations in stages.items():
        # Report every distinct failure rather than hiding one behind another.
        failures = observations - {('attempted', None)}
        for status, alsa_rc in sorted(failures or observations or {('not_observed', None)}, key=lambda item: (item[0], item[1] or 0)):
            value = event('audio_alsa_' + stage, status)
            if alsa_rc is not None:
                value['alsa_rc'] = alsa_rc
            events.append(value)
    events.append(event('audio_alsa_endpoint', 'render_seen' if render else 'capture_only' if capture else 'not_observed'))
    return events


def read_driver_events(work):
    path = Path(work).absolute() / 'audio-driver.log'
    before = _checked(path, DRIVER_LIMIT)
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NONBLOCK', 0))
    with os.fdopen(fd, 'rb') as source:
        actual = os.fstat(source.fileno())
        if (not stat.S_ISREG(actual.st_mode) or actual.st_nlink != 1
                or (actual.st_dev, actual.st_ino) != (before.st_dev, before.st_ino)):
            raise ValueError('unsafe capture')
        content = source.read(DRIVER_LIMIT + 1)
    if len(content) > DRIVER_LIMIT:
        raise ValueError('oversized capture')
    return driver_events(content)


def validate(value):
    if (type(value) is not dict or set(value) != {'schema_version', 'devices', *FIELDS}
            or type(value['schema_version']) is not int or value['schema_version'] != 1
            or type(value['devices']) is not int or not 0 <= value['devices'] <= 256):
        raise ValueError('invalid report')
    if any(type(value[key]) is not str or value[key] not in choices
           for key, choices in FIELDS.items()):
        raise ValueError('invalid report')
    if value['open'] != 'ready' and (value['write'] != 'not_run' or value['tone'] != 'not_run'):
        raise ValueError('inconsistent report')
    if value['write'] != 'ready' and value['tone'] != 'not_run':
        raise ValueError('inconsistent report')
    return dict(value)


def prepare_probe(port, work):
    source = Path(port).absolute() / 'compat/audio-probe/audio-probe.exe'
    info = _checked(source, AUDIO_SIZE)
    fd = os.open(source, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NONBLOCK', 0))
    with os.fdopen(fd, 'rb') as reader:
        actual = os.fstat(reader.fileno())
        identity = lambda value: (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns)
        if (not stat.S_ISREG(actual.st_mode) or actual.st_nlink != 1 or identity(actual) != identity(info)):
            raise ValueError('invalid probe')
        content = reader.read(AUDIO_SIZE + 1)
    if (identity(_checked(source, AUDIO_SIZE)) != identity(info) or len(content) != AUDIO_SIZE
            or hashlib.sha256(content).hexdigest() != AUDIO_SHA256):
        raise ValueError('invalid probe')
    directory = Path(work).absolute() / 'ProjectD2'
    for path in (directory, *directory.parents):
        entry = path.lstat()
        if _linked(entry) or not stat.S_ISDIR(entry.st_mode):
            raise ValueError('unsafe work')
    target = directory / 'pd2-audio-probe.exe'
    report = directory / 'pd2-audio-result.json'
    if os.path.lexists(target) or os.path.lexists(report):
        raise ValueError('stale probe')
    target.symlink_to(source)


def read_summary(work):
    path = Path(work).absolute() / 'ProjectD2/pd2-audio-result.json'
    before = _checked(path, LIMIT)
    flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NONBLOCK', 0)
    fd = os.open(path, flags)
    with os.fdopen(fd, 'rb') as source:
        actual, after = os.fstat(source.fileno()), _checked(path, LIMIT)
        if (not stat.S_ISREG(actual.st_mode) or actual.st_nlink != 1 or actual.st_size > LIMIT
                or (actual.st_dev, actual.st_ino) != (before.st_dev, before.st_ino)
                or (actual.st_dev, actual.st_ino) != (after.st_dev, after.st_ino)):
            raise ValueError('unsafe report')
        content = source.read(LIMIT + 1)
    if len(content) > LIMIT:
        raise ValueError('invalid report')
    return validate(json.loads(content.decode('utf-8', 'strict'), object_pairs_hook=_unique))


class Parser(argparse.ArgumentParser):
    def error(self, _message):
        raise ValueError('invalid arguments')


def playback_ready(value):
    return (value['open'] == 'ready' and value['directsound'] == 'ready'
            and value['write'] == 'ready' and value['tone'] == 'completed')


def main(argv=None, stdout=None):
    stdout = sys.stdout if stdout is None else stdout
    parser = Parser(description=__doc__)
    parser.add_argument('--port')
    parser.add_argument('--work', required=True)
    parser.add_argument('--prepare', action='store_true')
    parser.add_argument('--usable', action='store_true')
    parser.add_argument('--driver-log', action='store_true')
    try:
        args = parser.parse_args(argv)
        if args.driver_log:
            if args.port or args.prepare or args.usable:
                raise ValueError('invalid arguments')
            try:
                events = read_driver_events(args.work)
            except (OSError, ValueError):
                events = [dict(event='session_probe', phase='launch', check='audio_alsa_capture', status='unavailable')]
            for event in events:
                stdout.write('PD2_EVENT ' + json.dumps(event, separators=(',', ':')) + '\n')
            stdout.flush()
            return 0
        if args.prepare:
            if not args.port or args.usable:
                raise ValueError('invalid arguments')
            prepare_probe(args.port, args.work)
            return 0
        if args.port:
            raise ValueError('invalid arguments')
        value = read_summary(args.work)
    except (OSError, ValueError, TypeError, RecursionError):
        events = [dict(event='session_probe', phase='launch', check='audio_test', status='invalid')]
        rc = 1
    else:
        events = [dict(event='session_probe', phase='launch', check='audio_endpoints',
                       status='ready' if value['devices'] else 'missing', count=value['devices'])]
        events.extend(dict(event='session_probe', phase='launch', check='audio_' + name,
                           status=value[name]) for name in FIELDS)
        rc = 0 if not args.usable or playback_ready(value) else 1
    for event in events:
        stdout.write('PD2_EVENT ' + json.dumps(event, separators=(',', ':')) + '\n')
    stdout.flush()
    return rc


if __name__ == '__main__':
    raise SystemExit(main())
