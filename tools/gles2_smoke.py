#!/usr/bin/env python3
"""Windows-only actual DirectDraw->GL2 DLL lifecycle smoke, synthetic data only.

Uses the existing paletted RGB helper in a fresh windowed directory. No physical
mode change, game assets, Wine, pipes or system installation. Keeps bounded test
logs in .state for inspection. Does not claim any R36S compatibility/performance.
"""
from pathlib import Path
import json
import os
import shutil
import subprocess
import uuid

ROOT = Path(__file__).resolve().parents[1]
PORT = ROOT / 'sdcard/ports/projectdiablo2'


def main():
    if os.name != 'nt':
        print('Native DirectDraw lifecycle: SKIP (Windows required)')
        return 0
    directory = ROOT / '.state' / ('gles2-smoke-' + uuid.uuid4().hex)
    directory.mkdir(parents=True)
    shutil.copyfile(PORT / 'compat/gles2-renderer/ddraw.dll', directory / 'ddraw.dll')
    shutil.copyfile(PORT / 'compat/graphics-probe/graphics-layers.exe', directory / 'pd2-graphics.exe')
    (directory / 'ddraw.ini').write_text('[ddraw]\nwindowed=true\nfullscreen=false\nwidth=640\nheight=480\nrenderer=opengl\nmaxfps=30\nminfps=0\nvsync=false\nsinglecpu=false\nshader=\nno_compat_warning=true\n')
    with (directory / 'stdout.txt').open('xb') as out, (directory / 'stderr.txt').open('xb') as err:
        process = subprocess.run([str(directory / 'pd2-graphics.exe')], cwd=directory,
            stdin=subprocess.DEVNULL, stdout=out, stderr=err, timeout=20, check=False)
    print('Smoke directory:', directory)
    print('Native DirectDraw process exit:', process.returncode)
    if process.returncode:
        return process.returncode
    output = (directory / 'stdout.txt').read_bytes()
    status = (directory / 'pd2-gles2.jsonl').read_bytes()
    present = (directory / 'pd2-present.jsonl').read_bytes()
    if len(output) > 16384 or len(status) > 32768 or len(present) > 262144:
        raise RuntimeError('Synthetic capture exceeded bounds')
    events = [json.loads(line.removeprefix(b'PD2_EVENT ')) for line in output.splitlines()]
    renderer = [json.loads(line) for line in status.splitlines()]
    presentations = [json.loads(line) for line in present.splitlines()]
    if (not any(v.get('stage') == 'done' and v.get('code') == 0 for v in events)
            or any(v.get('code') != 0 for v in renderer)
            or not any(v.get('stage') == 6 and v.get('code') == 0 for v in renderer)
            or not any(v.get('stage') == 7 and v.get('code') == 0 for v in renderer)
            or not any(v.get('event') == 3 and v.get('backend') == 2 for v in presentations)):
        raise RuntimeError('Synthetic lifecycle evidence incomplete')
    print('Native DirectDraw paletted RGB/context/GL2 first_present/normal teardown: PASS')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
