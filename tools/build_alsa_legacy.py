#!/usr/bin/env python3
"""Cross-build unmodified alsa-lib with the legacy ARM32 kernel ABI."""
import bz2
import hashlib
from pathlib import Path
import subprocess
import tempfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
SOURCE = 'https://www.alsa-project.org/files/pub/lib/alsa-lib-1.2.8.tar.bz2'
DIGEST = '1ab01b74e33425ca99c2e36c0844fd6888273193bd898240fe8f93accbcbf347'
DESTINATION = 'sdcard/ports/projectdiablo2/compat/alsa-legacy-armhf'

if __name__ == '__main__':
    destination = ROOT / DESTINATION
    if not destination.is_dir():
        raise SystemExit('Missing destination')
    content = urllib.request.urlopen(SOURCE, timeout=60).read(2000000)
    if hashlib.sha256(content).hexdigest() != DIGEST:
        raise SystemExit('Unexpected ALSA source')
    (destination / 'alsa-lib-1.2.8.tar.bz2').write_bytes(content)
    with tempfile.TemporaryDirectory(prefix='.alsa-legacy-build-', dir=ROOT / '.state') as temporary:
        archive = Path(temporary) / 'alsa.tar'
        archive.write_bytes(bz2.decompress(content))
        source = '/src/' + archive.relative_to(ROOT).as_posix()
        command = ('tar -xf ' + source + ' -C /tmp && cd /tmp/alsa-lib-1.2.8 && '
                   'CC=arm-linux-gnueabihf-gcc CFLAGS="-Os -fno-ident" LDFLAGS="-Wl,--build-id=none" '
                   './configure --host=arm-linux-gnueabihf --prefix=/usr --libdir=/usr/lib/arm-linux-gnueabihf '
                   '--with-configdir=/usr/share/alsa --with-plugindir=/usr/lib/arm-linux-gnueabihf/alsa-lib '
                   '--disable-maintainer-mode --disable-static --enable-shared --disable-python && '
                   'arm-linux-gnueabihf-gcc -std=c11 -D__bitwise= -Iinclude -fsyntax-only /src/tools/alsa_legacy_abi.c && '
                   'make -s -j4 && arm-linux-gnueabihf-strip -o /src/' + DESTINATION + '/libasound.so.2 src/.libs/libasound.so.2.0.0 && '
                   'arm-linux-gnueabihf-readelf -d -V /src/' + DESTINATION + '/libasound.so.2')
        subprocess.run(['docker', 'run', '--rm', '-v', str(ROOT) + ':/src',
                        'pd2-alsa-native-builder', 'sh', '-c', command], check=True)
    library = (destination / 'libasound.so.2').read_bytes()
    print('Legacy ALSA size:', len(library), 'SHA256:', hashlib.sha256(library).hexdigest())
