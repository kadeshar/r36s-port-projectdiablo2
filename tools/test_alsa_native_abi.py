#!/usr/bin/env python3
"""Execute the shipped ARM32 ELF under QEMU with a synthetic ARM32 ALSA ABI.

This validates calling convention, flags, close-on-success and output only;
it does NOT validate the handheld's actual kernel, library or sound hardware.
"""
import json
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
HELPER = '/src/sdcard/ports/projectdiablo2/compat/alsa-native/alsa-native.'


def docker(args, check=True):
    return subprocess.run(['docker', 'run', '--rm', '-v', str(ROOT) + ':/src', '-w', '/src',
                           'pd2-alsa-native-builder', *args], check=check, capture_output=True)


if __name__ == '__main__':
    with tempfile.TemporaryDirectory(prefix='.alsa-abi-', dir=ROOT / '.state') as temporary:
        directory = '/src/' + Path(temporary).relative_to(ROOT).as_posix()
        for arch, prefix, emulator, sysroot in [('armhf', 'arm-linux-gnueabihf', 'qemu-arm', '/usr/arm-linux-gnueabihf'),
                                               ('aarch64', 'aarch64-linux-gnu', 'qemu-aarch64', '/usr/aarch64-linux-gnu')]:
            compiler = [prefix + '-gcc', '-shared', '-fPIC', '-Wall', '-Wextra', '-Werror',
                    '/src/tools/alsa_native_fixture.c', '-o', directory + '/libasound.so.2']
            docker(compiler)
            helper = HELPER + arch
            base = [emulator, '-L', sysroot, '-E', 'LD_LIBRARY_PATH=' + directory]
            for mode, expected in [('errors', (-25, -16)), ('success', (0, 0))]:
                result = docker(base + ['-E', 'PD2_FIXTURE_MODE=' + mode, helper, 'plughw:2,3'])
                value = json.loads(result.stdout)
                assert (value['default_rc'], value['plughw_rc']) == expected, value
                assert value['status'] == 'ready', value
                print(arch, 'QEMU:', mode, 'OK')
            value = json.loads(docker(base + [helper]).stdout)
            assert value['plughw_rc'] is None
            assert docker(base + [helper, 'private-unsupported-node'], check=False).returncode == 2
            docker(compiler + ['-DNO_CLOSE'])
            assert json.loads(docker(base + [helper]).stdout)['status'] == 'symbol_missing'
            assert json.loads(docker([emulator, '-L', sysroot, helper]).stdout)['status'] == 'library_missing'
            print(arch, 'QEMU: default-only, invalid node, missing symbol/library OK')
