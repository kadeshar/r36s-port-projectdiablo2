#!/usr/bin/env python3
"""Stage authenticated production DSOAL DLLs into caller's fresh volatile work.

Caller owns session locking, tmpfs setup, Wine lifetime and ordinary layout.
Never prepare a prefix, alter game configuration, or touch saved games.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import struct
import sys
import uuid

PAYLOAD_MANIFEST_SHA256 = '9b2a8e0abc29d5adceafbf0585c7cce9ecaeb6571a2c1fd1eb318f9513bb5ce0'
PAYLOAD_MANIFEST_CRLF_SHA256 = 'b1cea47159b4ce1cdcdebfc5249fd33e406dc5fc8475a4586fc0e47a1923cf48'
DLLS = ('dsound.dll', 'dsoal-aldrv.dll')
MARKER = '.audio-dsoal-session.json'
MODE = 'dsoal'
LOG_LIMIT = 1024 * 1024
DOCUMENT_LIMIT = 512 * 1024
DLL_LIMIT = 16 * 1024 * 1024
OPENAL_INI = b'[general]\ndrivers=winmm\nhrtf=false\nresampler=linear\nrt-prio=0\n'


class DsoalError(Exception):
    """Internal failure; CLI deliberately exposes no paths or exception text."""


def plain(path):
    path = Path(path)
    if '..' in path.parts:
        raise DsoalError()
    path = path.absolute()
    for item in (path, *path.parents):
        try:
            info = item.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise DsoalError()
    return path


def directory(path):
    path = plain(path)
    if not stat.S_ISDIR(path.stat().st_mode):
        raise DsoalError()
    return path


def regular(path, mutable=False):
    path = plain(path)
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or (mutable and info.st_nlink != 1):
        raise DsoalError()
    return path


def bounded_bytes(path, limit):
    path = regular(path)
    with path.open('rb') as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise DsoalError()
    return data


def decode_document(data):
    obj = json.loads(data.decode('utf-8'))
    if not isinstance(obj, dict):
        raise DsoalError()
    return obj


def document(path):
    return decode_document(bounded_bytes(path, DOCUMENT_LIMIT))


def write_new(path, data):
    path = plain(path)
    with path.open('xb') as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def write_json(path, obj):
    write_new(path, (json.dumps(obj, indent=2) + '\n').encode('utf-8'))


def verify_owner(prefix, drive_c):
    # Production runs as its regular owner, never through a root Wine process.
    if hasattr(os, 'getuid'):
        uid = os.getuid()
        if uid == 0 or any(path.stat().st_uid != uid for path in (prefix, drive_c)):
            raise DsoalError()


def prefix_paths(prefix, work):
    prefix = directory(prefix)
    drive_c = directory(prefix / 'drive_c')
    verify_owner(prefix, drive_c)
    work = directory(work)
    if work == prefix or prefix in work.parents or work in prefix.parents:
        raise DsoalError()
    return prefix, work


def pe32(data):
    if len(data) < 64 or data[:2] != b'MZ':
        return False
    offset = struct.unpack_from('<I', data, 0x3c)[0]
    if offset < 64 or offset > len(data) - 26:
        return False
    return (data[offset:offset + 4] == b'PE\0\0'
            and struct.unpack_from('<H', data, offset + 4)[0] == 0x14c
            and struct.unpack_from('<H', data, offset + 24)[0] == 0x10b)


def payload(port):
    incoming = directory(directory(port) / 'compat/dsoal')
    raw = bounded_bytes(incoming / 'manifest.json', DOCUMENT_LIMIT)
    raw_digest = hashlib.sha256(raw).hexdigest()
    lf_digest = hashlib.sha256(raw.replace(b'\r\n', b'\n')).hexdigest()
    if (not re.fullmatch('[0-9a-f]{64}', PAYLOAD_MANIFEST_SHA256)
            or (raw_digest != PAYLOAD_MANIFEST_SHA256
                and raw_digest != PAYLOAD_MANIFEST_CRLF_SHA256
                and lf_digest != PAYLOAD_MANIFEST_SHA256)):
        raise DsoalError()
    manifest = decode_document(raw)
    records = manifest.get('artifacts')
    if (type(manifest.get('schema_version')) is not int or manifest['schema_version'] != 1
            or not isinstance(records, list) or len(records) != 2
            or any(not isinstance(record, dict) or not isinstance(record.get('file'), str)
                   for record in records)
            or {record.get('file') for record in records} != set(DLLS)):
        raise DsoalError()
    result = {}
    for record in records:
        if (set(record) != {'file', 'size', 'sha256'} or type(record.get('size')) is not int
                or not 0 < record['size'] <= DLL_LIMIT
                or not isinstance(record.get('sha256'), str)
                or not re.fullmatch('[0-9a-f]{64}', record['sha256'])):
            raise DsoalError()
        data = bounded_bytes(incoming / record['file'], DLL_LIMIT)
        if (len(data) != record['size'] or hashlib.sha256(data).hexdigest() != record['sha256']
                or not pe32(data)):
            raise DsoalError()
        result[record['file']] = data
    return result


def stage(port, prefix, work):
    port = directory(port)
    prefix, work = prefix_paths(prefix, work)
    # A miswired caller must not turn imported game data into a writable target.
    if work == port or port in work.parents or work in port.parents:
        # SD storage stores ext4 state below its ROM payload.
        # Permit only the exact, bounded tmpfs workspace; imports still reject.
        try:
            from experimental_audio_storage import accepts_workspace
        except ImportError:
            try:
                from .experimental_audio_storage import accepts_workspace
            except ImportError:
                import sys as _sys
                _scripts = Path(__file__).resolve().parent
                if str(_scripts) not in _sys.path:
                    _sys.path.insert(0, str(_scripts))
                from experimental_audio_storage import accepts_workspace
        if not accepts_workspace(port, prefix, work):
            raise DsoalError()
    target = directory(work / 'ProjectD2')
    reserved = {name.casefold() for name in DLLS}
    if any(child.name.casefold() in reserved for child in target.iterdir()):
        raise DsoalError()
    marker = plain(work / MARKER)
    if marker.exists() or marker.is_symlink():
        raise DsoalError()
    artifacts = payload(port)  # Authenticate all inputs before any writes.
    logroot = plain(prefix / 'drive_c/pd2-audio')
    if logroot.exists():
        directory(logroot)
    session = uuid.uuid4().hex
    logdir = plain(logroot / session)
    logdir.mkdir(mode=0o700, parents=True)
    write_new(logdir / 'openal.ini', OPENAL_INI)
    for name in DLLS:
        write_new(target / name, artifacts[name])
    write_json(marker, {'schema_version': 1, 'mode': MODE, 'session': session,
                        'prefix': str(prefix), 'work': str(work)})
    print(session)
    return session


def winmm_opened(data):
    """Source-exact OpenAL Soft 1.23 startup/open evidence, not config echo."""
    initialized = data.find(b'Initialized backend "winmm"')
    playback = data.find(b'Added "winmm" for playback', initialized + 1)
    created = re.search(rb'Created device [^,\r\n]+, "[^"\r\n]*"', data[max(playback, 0):])
    selected = re.findall(rb'Added "([^"\r\n]+)" for playback', data)
    return initialized >= 0 and playback > initialized and created is not None and selected == [b'winmm']


def collect(prefix, work):
    # Caller must first stop Wine: collecting/truncating live logs is unsupported.
    prefix, work = prefix_paths(prefix, work)
    marker = regular(work / MARKER, mutable=True)
    session = document(marker)
    if (set(session) != {'schema_version', 'mode', 'session', 'prefix', 'work'}
            or type(session.get('schema_version')) is not int or session['schema_version'] != 1
            or session.get('mode') != MODE or session.get('prefix') != str(prefix)
            or session.get('work') != str(work) or not isinstance(session.get('session'), str)
            or not re.fullmatch('[0-9a-f]{32}', session['session'])):
        raise DsoalError()
    destination = directory(prefix / 'drive_c/pd2-audio' / session['session'])
    logs = []
    for name in ('openal.log', 'dsoal.log'):
        incoming = destination / name
        if incoming.exists() or incoming.is_symlink():
            logs.append((name, regular(incoming, mutable=True)))
    # Validate every destination before truncating any log.
    output = plain(destination / 'result.json')
    if output.exists() or output.is_symlink():
        raise DsoalError()
    proof = 'unconfirmed'
    for name, incoming in logs:
        with incoming.open('r+b') as stream:
            data = stream.read(LOG_LIMIT)
            stream.truncate(min(incoming.stat().st_size, LOG_LIMIT))
        if name == 'openal.log' and winmm_opened(data):
            proof = 'winmm_opened'
    write_json(output, {'schema_version': 1, 'mode': MODE, 'backend_evidence': proof})
    print('PD2_EVENT ' + json.dumps({'event': 'session_probe', 'phase': 'shutdown',
                                   'check': 'audio_output', 'status': proof}))
    if proof != 'winmm_opened':
        raise DsoalError()
    return proof


class SafeArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        raise DsoalError()


def main(argv=None):
    parser = SafeArgumentParser()
    commands = parser.add_subparsers(dest='operation', required=True)
    staging = commands.add_parser('stage')
    staging.add_argument('--port', required=True)
    for command in (staging, commands.add_parser('collect')):
        command.add_argument('--prefix', required=True)
        command.add_argument('--work', required=True)
    try:
        args = parser.parse_args(argv)
        if args.operation == 'stage':
            stage(args.port, args.prefix, args.work)
        else:
            collect(args.prefix, args.work)
    except (DsoalError, OSError, ValueError, TypeError, KeyError, struct.error):
        print('PD2_EVENT ' + json.dumps({'event': 'runtime_error', 'phase': 'launch',
                                       'reason': 'invalid_layout'}), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
