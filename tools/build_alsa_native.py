#!/usr/bin/env python3
"""Build our ARM hard-float helper in an isolated, old-glibc container."""
import hashlib
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
PREFIX = 'sdcard/ports/projectdiablo2/compat/alsa-native/alsa-native.'

if __name__ == '__main__':
    if not (ROOT / PREFIX).parent.is_dir():
        raise SystemExit('Missing helper destination')
    for arch, compiler in [('armhf', 'arm-linux-gnueabihf'), ('aarch64', 'aarch64-linux-gnu')]:
        target = PREFIX + arch
        subprocess.run(['docker', 'run', '--rm', '-v', str(ROOT) + ':/src', '-w', '/src',
                    'pd2-alsa-native-builder', 'sh', '-c',
                    compiler + '-gcc -std=c99 -Os -Wall -Wextra -Werror -fno-ident '
                    '-Wl,--build-id=none tools/alsa_native.c -o ' + target + ' -ldl && '
                    + compiler + '-strip ' + target + ' && '
                    + compiler + '-readelf -h -l -V ' + target], check=True)
        content = (ROOT / target).read_bytes()
        print(arch, 'Size:', len(content), 'SHA256:', hashlib.sha256(content).hexdigest())
