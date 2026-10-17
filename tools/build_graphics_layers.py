#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Build synthetic probes only; no downloads/installations or launch integration.

python tools/build_graphics_layers.py --target all
Requires existing pd2-alsa-native-builder Docker image and VS2022 MSVC 14.44,
Windows SDK 10.0.22621.0. Individual targets: armhf, win32.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / 'sdcard/ports/projectdiablo2/compat/graphics-probe'
VS = Path(os.environ.get('FPS_RENDERER_VS', r'C:\Program Files\Microsoft Visual Studio\2022\Community'))
IMAGE = 'pd2-alsa-native-builder'
INPUTS = ('tools/graphics_layers.c', 'tools/graphics_layers_win.c',
          'tools/build_graphics_layers.py', 'tests/test_graphics_layers.py')
ARM_COMMAND = ('arm-linux-gnueabihf-gcc -std=c99 -Os -Wall -Wextra -Werror '
               '-fno-ident -Wl,--build-id=none tools/graphics_layers.c '
               '-o sdcard/ports/projectdiablo2/compat/graphics-probe/graphics-layers.armhf -ldl && '
               'arm-linux-gnueabihf-strip sdcard/ports/projectdiablo2/compat/graphics-probe/graphics-layers.armhf && '
               'arm-linux-gnueabihf-readelf -h -l -V sdcard/ports/projectdiablo2/compat/graphics-probe/graphics-layers.armhf')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_armhf():
    subprocess.run(['docker', 'run', '--rm', '-v', str(ROOT) + ':/src', '-w', '/src',
                    IMAGE, 'sh', '-c', ARM_COMMAND], check=True)


def build_win32():
    # Fixed relative intermediate paths plus /Brepro; no absolute debug paths.
    batch = DEST / 'build-win32.cmd'
    batch.write_text('@echo off\n'
        f'call "{VS / "VC/Auxiliary/Build/vcvarsall.bat"}" x64_x86 10.0.22621.0 -vcvars_ver=14.44 >nul\n'
        'if errorlevel 1 exit /b 1\n'
        'cl /nologo /W4 /WX /O2 /MT /Brepro /D_CRT_SECURE_NO_WARNINGS '
        '"../../../../../tools/graphics_layers_win.c" /Fo:graphics-layers.obj '
        '/Fe:graphics-layers.exe /link /Brepro user32.lib\n'
        'exit /b %errorlevel%\n', encoding='utf-8')
    subprocess.run(['cmd.exe', '/d', '/c', str(batch)], cwd=DEST, check=True)
    for intermediate in (batch, DEST / 'graphics-layers.obj'):
        if intermediate.resolve().parent != DEST.resolve():
            raise RuntimeError('Unexpected intermediate path')
        intermediate.unlink()


def manifest():
    artifacts = {}
    for name, magic in [('graphics-layers.armhf', b'\x7fELF'), ('graphics-layers.exe', b'MZ')]:
        path = DEST / name
        if path.exists():
            data = path.read_bytes()
            if not data.startswith(magic):
                raise RuntimeError('Invalid artifact format: ' + name)
            artifacts[name] = {'sha256': sha(path), 'size': len(data)}
    value = {'schema': 1, 'license': 'MIT', 'artifacts': artifacts,
             'inputs_sha256': {p: sha(ROOT / p) for p in INPUTS},
             'build': {'armhf': {'image': IMAGE, 'command': ARM_COMMAND, 'link': '-ldl only'},
                       'win32': {'compiler': 'MSVC 14.44', 'sdk': '10.0.22621.0',
                                 'crt': '/MT', 'deterministic': '/Brepro'},
                       'command': 'python tools/build_graphics_layers.py --target all'},
             'runtime': {'deadline_seconds': 15, 'deadline_owner': 'parent',
                         'output': 'stdout PD2_EVENT fixed graphics_layer schema v1',
                         'maximum_events': 7, 'maximum_output_bytes': 4096,
                         'requires_game_assets': False},
             'validation': {'physical_r36s': 'not tested', 'gpu_hardware_success': 'not established'}}
    (DEST / 'manifest.json').write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(value, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target', choices=('all', 'armhf', 'win32'), default='all')
    args = parser.parse_args()
    DEST.mkdir(parents=True, exist_ok=True)
    if args.target in ('all', 'armhf'):
        build_armhf()
    if args.target in ('all', 'win32'):
        build_win32()
    manifest()


if __name__ == '__main__':
    main()
