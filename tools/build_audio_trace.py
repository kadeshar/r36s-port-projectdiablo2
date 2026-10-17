#!/usr/bin/env python3
"""Cross-build unmodified strace 6.1 for a bounded, native syscall diagnostic."""
import hashlib
import argparse
from pathlib import Path
import subprocess
import tempfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
SOURCE = 'https://strace.io/files/6.1/strace-6.1.tar.xz'
SHA256 = '2579e9cec37dbb786f6ea0bebd15f40dd561ef2bde2a2a2ecdce5963b01859fd'
TARGET = 'sdcard/ports/projectdiablo2/compat/alsa-native/strace.aarch64'

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--source-only', action='store_true')
    args = parser.parse_args()
    content = urllib.request.urlopen(SOURCE, timeout=60).read(3000000)
    if hashlib.sha256(content).hexdigest() != SHA256:
        raise SystemExit('Unexpected strace source')
    (ROOT / 'sdcard/ports/projectdiablo2/compat/alsa-native/strace-6.1.tar.xz').write_bytes(content)
    if args.source_only:
        raise SystemExit(0)
    with tempfile.TemporaryDirectory(prefix='.strace-build-', dir=ROOT / '.state') as directory:
        archive = Path(directory) / 'strace.tar.xz'
        archive.write_bytes(content)
        source = '/src/' + archive.relative_to(ROOT).as_posix()
        subprocess.run(['docker', 'run', '--rm', '-v', str(ROOT) + ':/src',
                        'pd2-alsa-native-builder', 'sh', '-c',
                        'tar -xJf ' + source + ' -C /tmp && cd /tmp/strace-6.1 && '
                        'CC=aarch64-linux-gnu-gcc CFLAGS="-Os -fno-ident" LDFLAGS="-Wl,--build-id=none" '
                        './configure --host=aarch64-linux-gnu --enable-mpers=no --without-libunwind --without-libdw '
                        '--disable-dependency-tracking && make -s -j4 && '
                        'aarch64-linux-gnu-strip -o /src/' + TARGET + ' src/strace && '
                        'aarch64-linux-gnu-readelf -V /src/' + TARGET], check=True)
    result = (ROOT / TARGET).read_bytes()
    print('strace Size:', len(result), 'SHA256:', hashlib.sha256(result).hexdigest())
