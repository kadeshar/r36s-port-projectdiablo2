#!/usr/bin/env python3
"""Real ARM32 libasound + probe under QEMU, against a simulated old ALSA ABI."""
import json
from pathlib import Path
import re
import subprocess
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[1]
LIB = '/src/sdcard/ports/projectdiablo2/compat/alsa-legacy-armhf'
HELPER = '/src/sdcard/ports/projectdiablo2/compat/alsa-native/alsa-native.armhf'


def docker(args):
    return subprocess.run(['docker', 'run', '--rm', '-v', str(ROOT) + ':/src',
                           'pd2-alsa-native-builder', *args], check=True, capture_output=True)


if __name__ == '__main__':
    with tempfile.TemporaryDirectory(prefix='.alsa-kernel-', dir=ROOT / '.state') as directory:
        path = Path(directory)
        mount = '/src/' + path.relative_to(ROOT).as_posix()
        with tarfile.open(ROOT / 'sdcard/ports/projectdiablo2/runtime/wine-8.0-x86.tar.xz') as archive:
            (path / 'winealsa.so').write_bytes(archive.extractfile('wine-8.0-x86/lib/wine/i386-unix/winealsa.so').read())
        def symbols(binary, undefined):
            text = docker(['arm-linux-gnueabihf-readelf', '--dyn-syms', '--wide', binary]).stdout.decode()
            values = set()
            for line in text.splitlines():
                match = re.search(r'\b(snd_[^\s@]+)@+(ALSA_[A-Za-z0-9._]+)', line)
                if match and (' UND ' in line) == undefined:
                    values.add(match.groups())
            return values
        required = symbols(mount + '/winealsa.so', True)
        exported = symbols(LIB + '/libasound.so.2', False)
        assert required and required <= exported, required - exported
        print('Wine 8.0 winealsa versioned ALSA imports:', len(required), 'satisfied')
        (path / 'alsa.conf').write_text('''pcm.!default { type plug slave.pcm { type hw card 0 device 0 } }
pcm.plughw {
 @args [ CARD DEV ]
 @args.CARD { type integer }
 @args.DEV { type integer }
 type plug
 slave.pcm { type hw card $CARD device $DEV }
}
''')
        docker(['arm-linux-gnueabihf-gcc', '-shared', '-fPIC', '-Wall', '-Wextra', '-Werror',
                '/src/tools/alsa_legacy_kernel_fixture.c', '-o', mount + '/kernel.so', '-ldl'])
        base = ['qemu-arm', '-L', '/usr/arm-linux-gnueabihf', '-E', 'LD_LIBRARY_PATH=' + LIB,
                '-E', 'LD_PRELOAD=' + mount + '/kernel.so', '-E', 'ALSA_CONFIG_PATH=' + mount + '/alsa.conf']
        for denied, expected in [(False, 0), (True, -25)]:
            extra = ['-E', 'PD2_FIXTURE_DENY_LEGACY=1'] if denied else []
            result = docker(base + extra + [HELPER, 'plughw:0,0'])
            value = json.loads(result.stdout)
            assert value['status'] == 'ready', value
            assert (value['default_rc'], value['plughw_rc']) == (expected, expected), (value, result.stderr)
            print('Real ARM32 alsa-lib 1.2.8 legacy SYNC_PTR:', 'error propagation' if denied else 'open/close success', 'OK')
