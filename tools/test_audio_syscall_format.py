#!/usr/bin/env python3
"""Verify the parser with actual upstream strace 6.1 and host-kernel syscalls.

The container-only PCM alias is /dev/null. This tests the tracing format and
numeric projection, NOT the handheld kernel or ARM compat ptrace support.
"""
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'sdcard/ports/projectdiablo2/scripts'))
from audio_syscalls import project_trace
from safe_log import validate_event

if __name__ == '__main__':
    command = ('tar -xJf /src/sdcard/ports/projectdiablo2/compat/alsa-native/strace-6.1.tar.xz -C /tmp && '
               'cd /tmp/strace-6.1 && ./configure --enable-mpers=no --without-libunwind --without-libdw > /dev/null && '
               'make -s -j4 > /dev/null && gcc /src/tools/audio_syscall_fixture.c -o /tmp/fixture && '
               'mkdir -p /dev/snd && ln -s /dev/null /dev/snd/pcmC2D3p && '
               'src/strace -qq -yy -s 128 -e trace=openat,open,ioctl,close -e raw=ioctl -- /tmp/fixture')
    result = subprocess.run(['docker', 'run', '--rm', '--cap-add=SYS_PTRACE', '--security-opt=seccomp=unconfined',
                             '-v', str(ROOT) + ':/src:ro', 'pd2-alsa-native-builder', 'sh', '-c', command],
                            check=True, capture_output=True, timeout=180)
    values = project_trace(result.stderr, 'aarch64')
    calls = [value for value in values if value['check'] == 'audio_syscall_ioctl']
    assert any(value['request'] == 0x80044100 and value['syscall_rc'] == -25
               and value['node'] == 'pcm' and value['device_major'] == 1 and value['device_minor'] == 3 for value in calls), values
    assert all(validate_event(value) == value for value in values), values
    print('Upstream strace 6.1 real host format: request, ENOTTY, FD and char-device identity OK')
