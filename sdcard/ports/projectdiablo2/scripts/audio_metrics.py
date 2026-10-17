#!/usr/bin/env python3
"""Private source-instrumented ALSA selection and bounded real-stream capture.

prepare --port PORT --work WORK: publish pinned time32 library privately.
run -- COMMAND ...: anonymous nonblocking pipe inherited ONLY by final game.
No arbitrary library path, samples, device names, or child stdout parsing.
"""
import argparse
import json
import os
from pathlib import Path
import selectors
import subprocess
import sys
import tempfile
import time

from audio_native import artifact_bytes, _checked_work

LIBRARY_PATH = 'compat/audio-metrics/libasound.so.2'
LIBRARY_SIZE = 594668
LIBRARY_SHA256 = 'cbf5cb0457594b7c7a6ab5df598b5aa77bb891a9dfc3f8b197841a36be9266f8'
DIRECTORY = '.alsa-audio-metrics'
LINE_LIMIT = 2048
INPUT_LIMIT = 262144
EVENT_LIMIT = 4096
SOURCE_LIMIT = 32
COUNTERS = ('write_calls', 'write_frames', 'short_writes', 'mmap_begin_calls',
            'mmap_commit_calls', 'mmap_frames', 'hw_params_calls', 'start_calls',
            'prepare_calls', 'resume_calls', 'drop_calls', 'drain_calls',
            'recover_calls', 'recover_epipe_calls', 'recover_successes', 'close_calls',
            'error_results', 'epipe_results', 'estrpipe_results', 'eagain_results',
            'eintr_results', 'other_error_results')
BOUNDS = dict(schema=1, pid=2147483647, stream=8, active=1, params_valid=1,
              rate_hz=768000, channels=256, access=4,
              period_frames=10**9, buffer_frames=10**9,
              lost_updates=10**9, untracked_opens=10**9,
              **{name: 10**15 for name in COUNTERS})


def status(value, check='audio_metrics_capture'):
    return dict(event='session_probe', phase='launch', check=check, status=value)


def emit(value):
    try:
        print('PD2_EVENT ' + json.dumps(value, separators=(',', ':'), sort_keys=True), flush=True)
    except (BrokenPipeError, OSError):
        # Telemetry must not terminate/kill the real game when log capture closes.
        pass


def prepare(port, work):
    work = Path(work).absolute()
    _checked_work(work)
    if not LIBRARY_SIZE or not LIBRARY_SHA256:
        raise ValueError('artifact unavailable')
    content = artifact_bytes(port, LIBRARY_PATH, LIBRARY_SIZE, LIBRARY_SHA256)
    destination = work / DIRECTORY
    if os.path.lexists(destination):
        raise ValueError('stale private library directory')
    with tempfile.TemporaryDirectory(prefix='.audio-metrics-staging-', dir=work) as temporary:
        staged = Path(temporary) / 'libasound.so.2'
        with staged.open('xb') as output:
            output.write(content)
        staged.chmod(0o400)
        Path(temporary).rename(destination)
    return destination


def _unique(pairs):
    output = {}
    for key, value in pairs:
        if key in output:
            raise ValueError('duplicate key')
        output[key] = value
    return output


def decode_line(line):
    if not line or len(line) > LINE_LIMIT:
        raise ValueError('invalid wire line')
    value = json.loads(line.decode('ascii', 'strict'), object_pairs_hook=_unique)
    if type(value) is not dict:
        raise ValueError('invalid wire record')
    if set(value) == {'schema', 'pid', 'limited'}:
        if (type(value['schema']) is not int or value['schema'] != 1 or
                type(value['pid']) is not int or not 1 <= value['pid'] <= BOUNDS['pid'] or
                type(value['limited']) is not int or value['limited'] != 1):
            raise ValueError('invalid cap marker')
        return None
    if set(value) != set(BOUNDS):
        raise ValueError('unexpected wire keys')
    for name, maximum in BOUNDS.items():
        if type(value[name]) is not int or not 0 <= value[name] <= maximum:
            raise ValueError('invalid numeric field')
    if value['schema'] != 1 or value['pid'] == 0 or value['stream'] == 0:
        raise ValueError('invalid wire identity')
    if value['params_valid'] and (not value['rate_hz'] or not value['channels'] or
            not value['period_frames'] or value['period_frames'] > value['buffer_frames']):
        raise ValueError('invalid negotiated parameters')
    if (value['recover_successes'] > value['recover_calls'] or
            value['recover_epipe_calls'] > value['recover_calls'] or
            value['short_writes'] > value['write_calls'] or
            value['error_results'] != sum(value[key] for key in
                ('epipe_results', 'estrpipe_results', 'eagain_results', 'eintr_results', 'other_error_results'))):
        raise ValueError('inconsistent counters')
    return value


class Capture:
    """All wire bytes bounded/discarded in memory; only strict projections emitted."""
    def __init__(self, output=emit, clock=time.monotonic):
        self.output, self.clock = output, clock
        self.buffer = bytearray()
        self.discard_line = False
        self.sources = {}
        self.input_bytes = self.events = 0
        self.limited = self.invalid = False
        self.seen_status = set()

    def note(self, name):
        if name not in self.seen_status:
            self.seen_status.add(name)
            self.output(status(name))

    def line(self, line):
        try:
            value = decode_line(line)
            if value is None:
                self.limited = True
                self.note('capture_limit')
                return
            pid = value.pop('pid')
            if pid not in self.sources:
                if len(self.sources) >= SOURCE_LIMIT:
                    self.limited = True
                    self.note('capture_limit')
                    return
                self.sources[pid] = len(self.sources) + 1
            if self.events >= EVENT_LIMIT:
                self.limited = True
                self.note('capture_limit')
                return
            value.update(event='audio_pcm', source=self.sources[pid],
                         sample_monotonic_ms=min(10**15, max(0, int(self.clock() * 1000))))
            self.events += 1
            self.output(value)
        except (ValueError, TypeError, UnicodeError, RecursionError):
            self.invalid = True
            self.note('invalid_capture')

    def feed(self, chunk):
        remaining = max(0, INPUT_LIMIT - self.input_bytes)
        if len(chunk) > remaining:
            self.limited = True
            self.note('capture_limit')
        data = chunk[:remaining]
        self.input_bytes += len(data)
        # Incremental byte scan, max LINE_LIMIT retained even for no-newline input.
        for byte in data:
            if byte == 10:
                if not self.discard_line:
                    self.line(bytes(self.buffer))
                self.buffer.clear()
                self.discard_line = False
            elif not self.discard_line:
                if len(self.buffer) >= LINE_LIMIT:
                    self.buffer.clear()
                    self.discard_line = True
                    self.invalid = True
                    self.note('invalid_capture')
                else:
                    self.buffer.append(byte)

    def finish(self):
        if self.buffer or self.discard_line:
            self.invalid = True
            self.note('invalid_capture')
        if not self.events and not self.limited and not self.invalid:
            self.note('no_stream')


def run(command, environ=None):
    """Keep normal child stdout/stderr untouched. Never timeout/kill the game."""
    env = dict(os.environ if environ is None else environ)
    env.pop('PD2_AUDIO_METRICS_FD', None)
    if os.name != 'posix' or not hasattr(os, 'pipe2'):
        emit(status('unavailable'))
        return subprocess.call(command, env=env)
    read_fd, write_fd = os.pipe2(os.O_NONBLOCK | os.O_CLOEXEC)
    env['PD2_AUDIO_METRICS_FD'] = str(write_fd)
    process = None
    capture = Capture()
    try:
        # No new session: the parent launcher owns and cleans the whole game group.
        process = subprocess.Popen(command, env=env, pass_fds=(write_fd,))
        os.close(write_fd)
        write_fd = -1
        emit(status('ready'))  # Transport readiness only, not audio playback.
        deadline = None
        with selectors.DefaultSelector() as selector:
            selector.register(read_fd, selectors.EVENT_READ)
            eof = False
            while True:
                for _key, _mask in selector.select(0.25):
                    try:
                        data = os.read(read_fd, 8192)
                    except BlockingIOError:
                        continue
                    if data:
                        capture.feed(data)
                    else:
                        eof = True
                rc = process.poll()
                if rc is not None:
                    if deadline is None:
                        deadline = time.monotonic() + 2
                    if eof or time.monotonic() >= deadline:
                        break
                if eof and rc is None:
                    # No writer remains, but real game still runs. Do not busy-poll.
                    selector.unregister(read_fd)
                    rc = process.wait()
                    break
        capture.finish()
        rc = process.wait()
        return 128 - rc if rc < 0 else rc
    finally:
        os.close(read_fd)
        if write_fd >= 0:
            os.close(write_fd)


class Parser(argparse.ArgumentParser):
    def error(self, _message):
        raise ValueError('invalid arguments')


def main(argv=None):
    parser = Parser(description=__doc__)
    sub = parser.add_subparsers(dest='operation', required=True, parser_class=Parser)
    prep = sub.add_parser('prepare')
    prep.add_argument('--port', required=True)
    prep.add_argument('--work', required=True)
    execute = sub.add_parser('run')
    execute.add_argument('command', nargs=argparse.REMAINDER)
    args = None
    try:
        args = parser.parse_args(argv)
        if args.operation == 'prepare':
            prepare(args.port, args.work)
            emit(status('ready', 'audio_metrics_library'))
            return 0
        command = args.command
        if command[:1] == ['--']:
            command = command[1:]
        if not command:
            raise ValueError('missing final command')
        return run(command)
    except (OSError, ValueError, TypeError):
        check = 'audio_metrics_library' if getattr(args, 'operation', None) == 'prepare' else 'audio_metrics_capture'
        emit(status('unavailable', check))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
