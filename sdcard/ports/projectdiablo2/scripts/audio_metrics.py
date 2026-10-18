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
import re
import selectors
import subprocess
import sys
import tempfile
import time

from audio_native import artifact_bytes, _checked_work

LIBRARY_PATH = 'compat/audio-metrics/libasound.so.2'
LIBRARY_SIZE = 594672
LIBRARY_SHA256 = '958fde9fed0460ed6eb0201a5b151099de91d08326a55e4c9ed6dcc35144072d'
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
BOUNDS = dict(schema=1, pid=2147483647, stream=10**9, active=1, params_valid=1,
              rate_hz=768000, channels=256, access=4,
              period_frames=10**9, buffer_frames=10**9,
              lost_updates=10**9, untracked_opens=10**9,
              producer_monotonic_ms=10**15,
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


def _classify_pid(pid):
    try:
        comm = Path(f'/proc/{pid}/comm').read_text(encoding='ascii', errors='ignore').strip().lower()
    except OSError:
        comm = ''
    try:
        cmdline = Path(f'/proc/{pid}/cmdline').read_bytes().split(b'\0')
        cmdline_str = [arg.decode('ascii', errors='ignore').lower() for arg in cmdline]
    except OSError:
        cmdline_str = []
    if 'game.exe' in comm or any('game.exe' in arg for arg in cmdline_str):
        return 'game'
    if any('pd2' in arg and 'probe' in arg for arg in cmdline_str) or 'probe' in comm:
        return 'probe'
    if 'wineserver' in comm or any('wineserver' in arg for arg in cmdline_str):
        return 'server'
    if any(w in comm for w in ('services.exe', 'explorer.exe', 'svchost.exe', 'wine')):
        return 'wine'
    if any(any(w in arg for w in ('services.exe', 'explorer.exe', 'svchost.exe', 'wine')) for arg in cmdline_str):
        return 'wine'
    return 'unknown'


def parse_proc_hw_params(content):
    """Parse /proc/asound/cardX/pcmYp/subZ/hw_params text. Return dict."""
    if not content or content.strip() == 'closed':
        return {'state': 'closed'}
    params = {}
    for line in content.splitlines():
        line = line.strip()
        if not line or ':' not in line:
            continue
        key, val = [p.strip() for p in line.split(':', 1)]
        if key in ('format', 'access', 'subformat'):
            params[key] = val
        elif key in ('channels', 'period_size', 'buffer_size'):
            try:
                params[key] = int(val)
            except ValueError:
                pass
        elif key == 'rate':
            token = val.split()[0]
            try:
                params['rate_hz'] = int(token)
            except ValueError:
                pass
    return params


def parse_proc_sw_params(content):
    """Parse /proc/asound/cardX/pcmYp/subZ/sw_params text. Return dict."""
    if not content or content.strip() == 'closed':
        return {}
    params = {}
    for line in content.splitlines():
        line = line.strip()
        if not line or ':' not in line:
            continue
        key, val = [p.strip() for p in line.split(':', 1)]
        if key in ('avail_min', 'start_threshold', 'stop_threshold'):
            try:
                params[key] = int(val)
            except ValueError:
                pass
    return params


def parse_proc_status(content):
    """Parse /proc/asound/cardX/pcmYp/subZ/status text. Return dict."""
    if not content or content.strip() == 'closed':
        return {'state': 'closed'}
    st = {}
    for line in content.splitlines():
        line = line.strip()
        if not line or ':' not in line:
            continue
        key, val = [p.strip() for p in line.split(':', 1)]
        if key == 'state':
            st['state'] = val
        elif key in ('owner_pid', 'delay', 'avail', 'hw_ptr', 'appl_ptr'):
            try:
                st[key] = int(val)
            except ValueError:
                pass
    return st


def sample_hardware_pcm(proc_root=Path('/proc/asound'), clock=time.monotonic):
    try:
        proc_root = Path(proc_root)
        if not proc_root.is_dir():
            return None
        preferred_card = None
        cards_file = proc_root / 'cards'
        if cards_file.is_file():
            try:
                cards_txt = cards_file.read_text(encoding='ascii', errors='ignore')
                for line in cards_txt.splitlines():
                    m = re.match(r'\s*([0-9]{1,3})\s+\[([^\]]+)\]', line)
                    if m and 'rk817' in m.group(2).lower():
                        preferred_card = int(m.group(1))
                        break
            except OSError:
                pass
        active_sub = None
        fallback_sub = None
        for sub in proc_root.glob('card*/pcm*p/sub*'):
            try:
                st_text = (sub / 'status').read_text(encoding='ascii', errors='ignore')
                st = parse_proc_status(st_text)
                card_m = re.search(r'card([0-9]+)', str(sub))
                is_preferred = (preferred_card is not None and card_m and int(card_m.group(1)) == preferred_card)
                if st.get('state') in ('RUNNING', 'PREPARED', 'DRAINING', 'XRUN'):
                    active_sub = (sub, st)
                    if is_preferred:
                        break
                elif fallback_sub is None or is_preferred:
                    fallback_sub = (sub, st)
            except OSError:
                continue
        target = active_sub or fallback_sub
        if not target:
            return None
        sub, st = target
        event_data = {
            'event': 'audio_hardware_pcm',
            'state': st.get('state', 'unknown'),
            'sample_monotonic_ms': min(10**15, max(0, int(clock() * 1000)))
        }
        card_m = re.search(r'card([0-9]+)', str(sub))
        dev_m = re.search(r'pcm([0-9]+)p', str(sub))
        if card_m:
            event_data['card'] = int(card_m.group(1))
        if dev_m:
            event_data['device'] = int(dev_m.group(1))
        for k in ('owner_pid', 'delay', 'avail', 'hw_ptr', 'appl_ptr'):
            if k in st:
                event_data[k] = st[k]
        if event_data['state'] != 'closed':
            try:
                hw_text = (sub / 'hw_params').read_text(encoding='ascii', errors='ignore')
                hw = parse_proc_hw_params(hw_text)
                if hw:
                    for k in ('format', 'access', 'channels', 'rate_hz', 'period_size', 'buffer_size'):
                        if k in hw:
                            name = 'period_frames' if k == 'period_size' else ('buffer_frames' if k == 'buffer_size' else k)
                            event_data[name] = hw[k]
            except OSError:
                pass
            try:
                sw_text = (sub / 'sw_params').read_text(encoding='ascii', errors='ignore')
                sw = parse_proc_sw_params(sw_text)
                if sw:
                    for k in ('avail_min', 'start_threshold', 'stop_threshold'):
                        if k in sw:
                            event_data[k] = sw[k]
            except OSError:
                pass
        return event_data
    except Exception:
        return None


class Capture:
    """All wire bytes bounded/discarded in memory; only strict projections emitted."""
    def __init__(self, output=emit, clock=time.monotonic, classifier=_classify_pid):
        self.output, self.clock, self.classifier = output, clock, classifier
        self.buffer = bytearray()
        self.discard_line = False
        self.sources = {}
        self.roles = {}
        self.stream_frames = {}
        self.total_playback_frames = 0
        self.playback_observed = False
        self.consecutive_playback_snapshots = 0
        self.first_playback_time = None
        self.sustained_playback_observed = False
        self.data_lost = False
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
                self.roles[pid] = self.classifier(pid)
            if self.events >= EVENT_LIMIT:
                self.limited = True
                self.note('capture_limit')
                return

            key = (pid, value['stream'])
            prev_write, prev_mmap = self.stream_frames.get(key, (0, 0))
            curr_write = value['write_frames']
            curr_mmap = value['mmap_frames']
            delta_write = max(0, curr_write - prev_write)
            delta_mmap = max(0, curr_mmap - prev_mmap)
            self.stream_frames[key] = (curr_write, curr_mmap)

            if value['lost_updates'] > 0 or value['untracked_opens'] > 0:
                self.data_lost = True

            if value['params_valid'] and (delta_write > 0 or delta_mmap > 0):
                self.total_playback_frames += (delta_write + delta_mmap)
                now = self.clock()
                if not self.playback_observed:
                    self.playback_observed = True
                    self.note('playback_observed')
                self.consecutive_playback_snapshots += 1
                if self.first_playback_time is None:
                    self.first_playback_time = now
                if (not self.sustained_playback_observed and
                        self.consecutive_playback_snapshots >= 3 and
                        (now - self.first_playback_time) >= 2.0):
                    self.sustained_playback_observed = True
                    self.note('sustained_playback')

            value.update(event='audio_pcm', role=self.roles[pid], source=self.sources[pid],
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
        elif self.events > 0:
            if self.data_lost:
                self.note('data_lost')
            if self.total_playback_frames > 0:
                if self.data_lost or self.limited:
                    self.note('partial_coverage')
                elif not self.playback_observed:
                    self.note('playback_observed')
            elif not self.invalid:
                self.note('no_playback')


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
        last_hw_sample = 0.0
        with selectors.DefaultSelector() as selector:
            selector.register(read_fd, selectors.EVENT_READ)
            eof = False
            while True:
                now = time.monotonic()
                if now - last_hw_sample >= 1.0:
                    last_hw_sample = now
                    hw_event = sample_hardware_pcm()
                    if hw_event:
                        emit(hw_event)
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
        hw_event = sample_hardware_pcm()
        if hw_event:
            emit(hw_event)
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
