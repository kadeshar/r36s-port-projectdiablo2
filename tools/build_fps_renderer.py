#!/usr/bin/env python3
"""Build isolated Win32 static-CRT FPS renderer; never writes default renderer.
Requires Python 3 + VS2022 Community MSVC 14.44 / Windows SDK 10.0.22621.0.
Run: python tools/build_fps_renderer.py [--test]
"""
from pathlib import Path
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / 'tools'
STATE = ROOT / '.state/fps-renderer'
DEST = ROOT / 'sdcard/ports/projectdiablo2/compat/fps-renderer'
URL = 'https://codeload.github.com/FunkyFr3sh/cnc-ddraw/zip/refs/tags/v7.1.0.0'
SOURCE_SHA = 'a4f638383364e3bc1e4682b1d549a1f5400fa0cc312ee216d1b42555b1c814eb'
VS = Path(os.environ.get('FPS_RENDERER_VS', r'C:\Program Files\Microsoft Visual Studio\2022\Community'))

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def replace(text, old, new):
    if text.count(old) != 1:
        raise RuntimeError(f'Upstream patch anchor changed: {old!r}')
    return text.replace(old, new)

def run(command, cwd):
    # CMD parses a batch file reliably; list2cmdline cannot quote embedded commands.
    batch = cwd / 'fps-build-command.cmd'
    batch.write_text('@echo off\n' + command + '\n', encoding='utf-8')
    subprocess.run(['cmd.exe', '/d', '/c', str(batch)], cwd=cwd, check=True)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--test', action='store_true')
    parser.add_argument('--test-pe', action='store_true', help='also run visible synthetic Win32 DirectDraw/GDI pixel probe')
    args = parser.parse_args()
    STATE.mkdir(parents=True, exist_ok=True)
    archive = STATE / 'upstream.zip'
    if not archive.exists():
        urllib.request.urlretrieve(URL, archive)
    if sha(archive) != SOURCE_SHA:
        raise RuntimeError('Upstream archive hash mismatch')
    # Fresh owned build directory each run; no removal or overwriting unknown files.
    import uuid
    build = STATE / ('build-' + uuid.uuid4().hex)
    build.mkdir()  # Inherit workspace permissions; Windows tempfile mode 0700 does not.
    with zipfile.ZipFile(archive) as z:
        z.extractall(build)
    src = build / 'cnc-ddraw-7.1.0.0'
    patches = []
    import difflib
    for name in ('gdi', 'ogl', 'd3d9'):
        path = src / f'src/render_{name}.c'
        original = path.read_text()
        text = original
        text = replace(text, '#include "config.h"', '#include "config.h"\n#include "fps_hud_renderer.h"')
        text = replace(text, 'fpsl_init();', 'pd2_reset();\n    fpsl_init();')
        # Keep upstream global/surface locking unchanged. Snapshot is private;
        # unsynchronized upstream Blt cannot lose writes to save/restore or pointer swaps.
        text = text.replace('g_ddraw.primary->surface', 'pd2_pixels()')
        text = replace(text, '        fpsl_frame_start();', '        pd2_ready = 0;\n        fpsl_frame_start();')
        if name == 'gdi':
            text = replace(text, '            int lines_copied = 0;', '            pd2_begin();\n            int lines_copied = 0;')
            text = replace(text, '                real_SetDIBitsToDevice(', '                lines_copied = real_SetDIBitsToDevice(')
            text = replace(text, '            if (g_config.lock_surfaces)\n                LeaveCriticalSection', '            if (lines_copied != 0 && lines_copied != GDI_ERROR) pd2_present();\n\n            if (g_config.lock_surfaces)\n                LeaveCriticalSection')
        else:
            anchor = '            if (InterlockedExchange(&g_ddraw.render.surface_updated, FALSE) || g_config.minfps == -2)'
            text = replace(text, anchor, '            pd2_begin();\n' + anchor)
            if name == 'ogl':
                text = replace(text, '        SwapBuffers(g_ogl.hdc);', '        if (SwapBuffers(g_ogl.hdc)) pd2_present();')
            else:
                text = replace(text, '            /* Force redraw for GDI games (ClueFinders) */', '            pd2_present();\n            /* Force redraw for GDI games (ClueFinders) */')
        path.write_text(text)
        patches.extend(difflib.unified_diff(original.splitlines(True), text.splitlines(True), fromfile=f'a/src/render_{name}.c', tofile=f'b/src/render_{name}.c'))
    for name in ('fps_hud_core.h', 'fps_hud_renderer.h'):
        shutil.copyfile(TOOLS / name, src / 'inc' / name)
    project = src / 'cnc-ddraw.vcxproj'
    text = project.read_text(encoding='utf-8-sig')
    text = re.sub(r'<PreBuildEvent>.*?</PreBuildEvent>', '', text, flags=re.S)
    text = re.sub(r'<PostBuildEvent>.*?</PostBuildEvent>', '', text, flags=re.S)
    # Deterministic COFF/PE content; fixed version strings, no checkout/git state.
    text = text.replace('<Link>', '<Link><AdditionalOptions>/Brepro /PDBALTPATH:ddraw.pdb %(AdditionalOptions)</AdditionalOptions>')
    text = text.replace('<ClCompile>', '<ClCompile><AdditionalOptions>/Brepro %(AdditionalOptions)</AdditionalOptions>')
    project.write_text(text, encoding='utf-8')
    (src / 'inc/git.h').write_text('#define GIT_COMMIT "v7.1.0.0-pd2-fps1"\n#define GIT_BRANCH "fps-renderer"\n')
    vcvars = VS / 'VC/Auxiliary/Build/vcvarsall.bat'
    msbuild = VS / 'MSBuild/Current/Bin/MSBuild.exe'
    init = f'call "{vcvars}" x64_x86 10.0.22621.0 -vcvars_ver=14.44 >nul && '
    run(init + f'"{msbuild}" cnc-ddraw.vcxproj /t:Build /m /p:Configuration=Release /p:TrackFileAccess=false /p:Platform=Win32 /p:PlatformToolset=v143 /p:WindowsTargetPlatformVersion=10.0.22621.0 /p:VCToolsVersion=14.44.35207 /p:SolutionDir="{src.as_posix()}/" /v:minimal', src)
    artifact = src / 'bin/Release/ddraw.dll'
    if args.test or args.test_pe:
        test = TOOLS / 'test_fps_hud.c'
        run(init + f'cl /nologo /W4 /WX /O2 /MT /D_CRT_SECURE_NO_WARNINGS /I"{TOOLS}" "{test}" /Fe:fps-hud-test.exe && fps-hud-test.exe', build)
    if args.test_pe:
        (build / 'ddraw.ini').write_text('[ddraw]\nrenderer=gdi\nwindowed=true\nwidth=640\nheight=480\nmaxfps=0\nminfps=0\nmaintas=false\nvsync=false\n')
        test = TOOLS / 'test_fps_renderer_pe.c'
        run(init + f'cl /nologo /W3 /O2 /MT /D_CRT_SECURE_NO_WARNINGS /I"{TOOLS}" "{test}" /Fe:fps-renderer-probe.exe /link user32.lib gdi32.lib && fps-renderer-probe.exe "{artifact}"', build)
    DEST.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(artifact, DEST / 'ddraw.dll')
    notices = (src / 'LICENSE').read_text() + '\n\nBundled Microsoft Detours:\n\n' + (src / 'src/detours/LICENSE.md').read_text()
    lodepng = (src / 'src/lodepng.c').read_text()
    notices += '\n\nBundled LodePNG:\n\n' + lodepng.split('/*', 1)[1].split('*/', 1)[0].strip() + '\n'
    (DEST / 'LICENSE.txt').write_text(notices)
    (DEST / 'source.patch').write_text(''.join(patches))
    inputs = {name: sha(TOOLS/name) for name in ('build_fps_renderer.py','fps_hud_core.h','fps_hud_renderer.h','test_fps_hud.c','test_fps_renderer_pe.c')}
    manifest = {
        'schema': 1, 'file': 'ddraw.dll', 'size': artifact.stat().st_size, 'sha256': sha(artifact),
        'upstream': {'project': 'FunkyFr3sh/cnc-ddraw', 'tag': 'v7.1.0.0', 'source_url': URL, 'source_sha256': SOURCE_SHA, 'license': 'MIT (upstream bundled third-party notices retained in LICENSE.txt)'},
        'build': {'configuration': 'Release Win32', 'compiler': 'MSVC 14.44.35207', 'sdk': '10.0.22621.0', 'crt': 'static /MT', 'deterministic': '/Brepro /PDBALTPATH:ddraw.pdb', 'command': 'python tools/build_fps_renderer.py' + (' --test-pe' if args.test_pe else ' --test' if args.test else ''), 'inputs_sha256': inputs},
        'tests': {'native_core': 'passed' if args.test or args.test_pe else 'not run', 'pe_directdraw_gdi': 'passed' if args.test_pe else 'not run', 'physical_r36s': 'not available'},
        'scope': 'Optional renderer only; upstream OFF artifact is never written.'}
    (DEST / 'manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
    print(json.dumps(manifest, indent=2))
    print('Build directory:', build)

if __name__ == '__main__':
    main()
