#!/usr/bin/env python3
"""Run our authenticated ARM32 PCM-open comparison, without Box86 or raw logs."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import selectors
import signal
import stat
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace

from audio_config import parse_cards, parse_pcm, _proc_bytes
from audio_syscalls import project_trace, trace_event
from xinput_result import _checked, _unique

HELPER_SIZE = 5540
HELPER_SHA256 = 'f320169c7c596136949f2ff7210808534708a9d22a1de9014179597b05f1aa21'
HELPER_PATH = 'compat/alsa-native/alsa-native.armhf'
HELPER64_SIZE = 10216
HELPER64_SHA256 = '2365cfe1eae1d19d7209d95dd92319e09f11ac75138e5cf42fa7f83341f2d9ec'
HELPER64_PATH = 'compat/alsa-native/alsa-native.aarch64'
TRACE_SIZE = 1453376
TRACE_SHA256 = '56e1dab0112c909206e4ef9b33183c70e9fd5c084739d67d1ca9430fa2fd4ec6'
TRACE_PATH = 'compat/alsa-native/strace.aarch64'
TRACE_LIMIT = 262144
ERRORS = {-2: 'missing', -13: 'denied', -16: 'busy', -19: 'missing',
          -22: 'invalid', -38: 'unsupported', -95: 'unsupported'}


def event(check, status, code=None):
    value = dict(event='session_probe', phase='launch', check=check, status=status)
    if code is not None:
        value['alsa_rc'] = code
    return value


def artifact_bytes(port, relative, size, digest):
    path = Path(port).absolute() / relative
    before = _checked(path, size)
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0))
    with os.fdopen(fd, 'rb') as source:
        actual = os.fstat(source.fileno())
        if (not stat.S_ISREG(actual.st_mode) or actual.st_nlink != 1
                or (before.st_dev, before.st_ino) != (actual.st_dev, actual.st_ino)):
            raise ValueError('unsafe helper')
        content = source.read(size + 1)
    if len(content) != size or hashlib.sha256(content).hexdigest() != digest:
        raise ValueError('invalid helper')
    return content


def helper_bytes(port, arch='armhf'):
    if arch == 'armhf':
        return artifact_bytes(port, HELPER_PATH, HELPER_SIZE, HELPER_SHA256)
    if arch == 'aarch64':
        return artifact_bytes(port, HELPER64_PATH, HELPER64_SIZE, HELPER64_SHA256)
    raise ValueError('invalid architecture')


def native_environment(environ, arch):
    env = dict(os.environ if environ is None else environ)
    if arch == 'armhf':
        env['LD_LIBRARY_PATH'] = env.get('PD2_NATIVE_LIBS', '')
        env['LD_PRELOAD'] = env.get('PD2_NATIVE_PRELOAD', '')
        for library in ('SDL', 'EGL', 'GBM', 'DRM'):
            env['CRUSTY_LIB' + library] = env.get('PD2_CRUSTY_' + library, '')
    else:
        env['LD_LIBRARY_PATH'] = env.get('PD2_NATIVE64_LIBS', '')
        env['LD_PRELOAD'] = ''
        for library in ('SDL', 'EGL', 'GBM', 'DRM'):
            env.pop('CRUSTY_LIB' + library, None)
    env['LC_ALL'] = 'C'
    return env


def plughw_node(proc_root):
    try:
        root = Path(proc_root)
        cards = parse_cards(_proc_bytes(root / 'cards'))
        devices = parse_pcm(_proc_bytes(root / 'pcm'))
        known = [n for n, name in cards.items() if 'rk817' in name.lower() and 'hdmi' not in name.lower()]
        candidates = [(card, device) for card, device in devices if len(known) == 1 and card == known[0]]
        if len(candidates) == 1:
            return 'plughw:%d,%d' % candidates[0]
    except (OSError, ValueError, UnicodeError):
        pass
    return None


def project_report(content, has_plughw, arch='armhf'):
    results = _project_report(content, has_plughw)
    if arch == 'aarch64':
        for value in results:
            value['check'] = {'audio_native_armhf': 'audio_native_aarch64',
                              'audio_native_default': 'audio_native64_default',
                              'audio_native_plughw': 'audio_native64_plughw'}[value['check']]
    return results


def _project_report(content, has_plughw):
    value = json.loads(content.decode('utf-8', 'strict'), object_pairs_hook=_unique)
    if type(value) is not dict or type(value.get('schema_version')) is not int or value['schema_version'] != 1:
        raise ValueError('invalid report')
    status = value.get('status')
    if status in ('library_missing', 'symbol_missing') and set(value) == {'schema_version', 'status'}:
        return [event('audio_native_armhf', status)]
    if status != 'ready' or set(value) != {'schema_version', 'status', 'default_rc', 'plughw_rc'}:
        raise ValueError('invalid report')
    results = [event('audio_native_armhf', 'ready')]
    for name in ('default', 'plughw'):
        code = value[name + '_rc']
        if name == 'plughw' and not has_plughw:
            if code is not None:
                raise ValueError('unexpected device')
            results.append(event('audio_native_plughw', 'not_run'))
        elif type(code) is not int or not -2147483648 <= code <= 0:
            raise ValueError('invalid code')
        else:
            results.append(event('audio_native_' + name, 'ready' if code == 0 else ERRORS.get(code, 'other_error'), code if code < 0 else None))
    return results


def native_events(port, work, environ=None, runner=subprocess.run, machine=None, proc_root='/proc/asound', arch='armhf'):
    # Test hooks are function-only; never accept a different binary/library CLI.
    check = 'audio_native_armhf' if arch == 'armhf' else 'audio_native_aarch64'
    supported = ('aarch64', 'arm64', 'armv7l', 'armv8l', 'arm') if arch == 'armhf' else ('aarch64', 'arm64')
    if (platform.machine() if machine is None else machine) not in supported:
        return [event(check, 'unsupported')]
    env = native_environment(environ, arch)
    try:
        content = helper_bytes(port, arch)
    except FileNotFoundError:
        return [event(check, 'missing')]
    except (OSError, ValueError):
        return [event(check, 'tampered')]
    try:
        # Work is the same private volatile filesystem used by the Wine probe.
        _checked_work(work)
        with tempfile.TemporaryDirectory(prefix='.alsa-native-', dir=work) as directory:
            target = Path(directory) / ('alsa-native.' + arch)
            target.write_bytes(content)
            target.chmod(0o500)
            node = plughw_node(proc_root)
            command = [str(target)] + ([node] if node else [])
            with tempfile.TemporaryFile(dir=directory) as output:
                result = runner(command, env=env, stdout=output, stderr=subprocess.DEVNULL,
                                timeout=8, start_new_session=True, check=False)
                if result.returncode != 0:
                    return [event(check, 'failed')]
                output.seek(0)
                report = output.read(1025)
                if len(report) > 1024:
                    raise ValueError('oversized report')
                return project_report(report, node is not None, arch)
    except subprocess.TimeoutExpired:
        return [event(check, 'timeout')]
    except (OSError, ValueError, TypeError, RecursionError):
        return [event(check, 'failed')]


def _checked_work(work):
    from xinput_result import _linked
    path = Path(work).absolute()
    for parent in (path, *path.parents):
        info = parent.lstat()
        if _linked(info) or not stat.S_ISDIR(info.st_mode):
            raise ValueError('unsafe work')


def collect_trace(command, env, stdout, timeout=8):
    """Bounded in-memory stderr; drain excess and kill only our own group."""
    content = bytearray()
    limited = False
    finished = False
    with subprocess.Popen(command, env=env, stdout=stdout, stderr=subprocess.PIPE,
                          stdin=subprocess.DEVNULL, start_new_session=True) as process:
        try:
            deadline = time.monotonic() + timeout
            with selectors.DefaultSelector() as selector:
                selector.register(process.stderr, selectors.EVENT_READ)
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise subprocess.TimeoutExpired('audio syscall trace', timeout)
                    if not selector.select(remaining):
                        raise subprocess.TimeoutExpired('audio syscall trace', timeout)
                    data = os.read(process.stderr.fileno(), 8192)
                    if not data:
                        break
                    room = TRACE_LIMIT - len(content)
                    limited |= len(data) > room
                    content.extend(data[:room])
            rc = process.wait(timeout=max(0.01, deadline - time.monotonic()))
            finished = True
            return SimpleNamespace(returncode=rc, trace=bytes(content), limited=limited)
        finally:
            if not finished:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait()


def trace_native_events(port, work, arch, environ=None, machine=None, runner=collect_trace, proc_root='/proc/asound'):
    if (platform.machine() if machine is None else machine) not in ('aarch64', 'arm64'):
        return [trace_event(arch, 'unavailable')]
    try:
        helper = helper_bytes(port, arch)
        tracer = artifact_bytes(port, TRACE_PATH, TRACE_SIZE, TRACE_SHA256)
    except FileNotFoundError:
        return [trace_event(arch, 'missing')]
    except (OSError, ValueError):
        return [trace_event(arch, 'tampered')]
    try:
        _checked_work(work)
        with tempfile.TemporaryDirectory(prefix='.alsa-trace-', dir=work) as directory:
            directory = Path(directory)
            target, trace = directory / ('alsa-native.' + arch), directory / 'strace.aarch64'
            for path, content in ((target, helper), (trace, tracer)):
                path.write_bytes(content)
                path.chmod(0o500)
            # The tracer is always AArch64. -E applies the ARM32 library paths
            # to the child only, never to the tracer's own native loader.
            parent_env = native_environment(environ, 'aarch64')
            child_env = native_environment(environ, arch)
            command = [str(trace), '-qq', '-yy', '-s', '128', '-e', 'trace=openat,open,ioctl,close', '-e', 'raw=ioctl']
            for name in ('LD_LIBRARY_PATH', 'LD_PRELOAD', 'CRUSTY_LIBSDL', 'CRUSTY_LIBEGL', 'CRUSTY_LIBGBM', 'CRUSTY_LIBDRM'):
                command += ['-E', name + '=' + child_env.get(name, '')]
            node = plughw_node(proc_root)
            command += ['--', str(target)] + ([node] if node else [])
            with tempfile.TemporaryFile(dir=directory) as output:
                result = runner(command, env=parent_env, stdout=output, timeout=8)
                low = result.trace.lower()
                if b'ptrace' in low and any(text in low for text in (b'operation not permitted', b'permission denied')):
                    return [trace_event(arch, 'denied')]
                if result.returncode != 0:
                    return [trace_event(arch, 'unavailable')]
                output.seek(0)
                report = output.read(1025)
                if len(report) > 1024:
                    raise ValueError('oversized report')
                # Do not replace the untraced baseline with results influenced
                # by ptrace. A valid helper report only proves it ran under trace.
                project_report(report, node is not None, arch)
                return project_trace(result.trace, arch, result.limited)
    except subprocess.TimeoutExpired:
        return [trace_event(arch, 'timeout')]
    except (OSError, ValueError, TypeError, RecursionError):
        return [trace_event(arch, 'unavailable')]


class Parser(argparse.ArgumentParser):
    def error(self, _message):
        raise ValueError('invalid arguments')


def main(argv=None):
    parser = Parser(description=__doc__)
    parser.add_argument('--port', required=True)
    parser.add_argument('--work', required=True)
    try:
        args = parser.parse_args(argv)
        events = []
        for arch in ('armhf', 'aarch64'):
            events.extend(native_events(args.port, args.work, arch=arch))
            events.extend(trace_native_events(args.port, args.work, arch))
    except (OSError, ValueError, TypeError):
        events = [event('audio_native_armhf', 'failed')]
    for value in events:
        print('PD2_EVENT ' + json.dumps(value, separators=(',', ':')), flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
