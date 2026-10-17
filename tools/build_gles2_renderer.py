#!/usr/bin/env python3
"""Build the independently pinned fail-closed GL2 cnc-ddraw renderer, offline.

Requires .state/fps-renderer/upstream.zip. Does not change any stock/HUD DLL.
"""
from pathlib import Path
import argparse
import difflib
import hashlib
import json
import os
import re
import shutil
import subprocess
import uuid
import zipfile

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / 'tools'
DEST = ROOT / 'sdcard/ports/projectdiablo2/compat/gles2-renderer'
SOURCE_SHA = 'a4f638383364e3bc1e4682b1d549a1f5400fa0cc312ee216d1b42555b1c814eb'
URL = 'https://codeload.github.com/FunkyFr3sh/cnc-ddraw/zip/refs/tags/v7.1.0.0'
INPUTS = ('gles2_backend.c', 'gles2_pipeline.h', 'gles2_events.h', 'gles2_palette.h', 'present_metrics.h')
VS = Path(os.environ.get('GLES2_RENDERER_VS', r'C:\Program Files\Microsoft Visual Studio\2022\Community'))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def patch_source(src):
    """Strict source-specific transform; return distributable unified diff."""
    patches = []

    def save(path, text):
        original = path.read_text(encoding='utf-8-sig') if path.exists() else ''
        path.write_text(text, encoding='utf-8')
        name = path.relative_to(src).as_posix()
        patches.extend(difflib.unified_diff(original.splitlines(True), text.splitlines(True),
            fromfile='a/' + name, tofile='b/' + name))

    save(src / 'src/render_ogl.c', (TOOLS / 'gles2_backend.c').read_text())
    for name in INPUTS[1:]:
        save(src / 'inc' / name, (TOOLS / name).read_text())
    dd = src / 'src/dd.c'
    text = dd.read_text()
    start = text.index('        if (_strcmpi(g_config.renderer, "direct3d9on12") == 0)')
    end = text.index('        LONG ref = InterlockedDecrement(&g_ddraw.ref);', start)
    text = text[:start] + '''        /* Opt-in GL2 DLL: never select a silent GDI/D3D fallback. */
        extern void pd2_gles2_fatal(unsigned stage, unsigned code);
        if (!oglu_load_dll()) pd2_gles2_fatal(2, 2);
        g_config.opengl_core = FALSE;
        g_config.minfps = 0;
        g_ddraw.renderer = ogl_render_main;

''' + text[end:]
    save(dd, text)
    palette = src / 'src/ddpalette.c'
    text = palette.read_text()
    text = text.replace('#include "ddpalette.h"', '#include "ddpalette.h"\n#include "gles2_palette.h"')
    begin = text.index('HRESULT ddp_SetEntries(')
    end = text.index('HRESULT dd_CreatePalette(', begin)
    section = text[begin:end]
    anchor = '    RGBQUAD data_rgb[256];'
    if section.count(anchor) != 1 or section.count('            return DD_OK;') != 1 or section.count('    return DD_OK;') != 2:
        raise RuntimeError('Palette lock anchors changed')
    section = section.replace(anchor, '    AcquireSRWLockExclusive(&pd2_gles2_palette_gate);\n' + anchor)
    section = section.replace('            return DD_OK;', '            ReleaseSRWLockExclusive(&pd2_gles2_palette_gate);\n            return DD_OK;')
    section = section.replace('    if (g_ddraw.ref && g_ddraw.primary', '    ReleaseSRWLockExclusive(&pd2_gles2_palette_gate);\n\n    if (g_ddraw.ref && g_ddraw.primary')
    save(palette, text[:begin] + section + text[end:])
    # Defense in depth for any future/unexpected renderer pointer path.
    gdi = src / 'src/render_gdi.c'
    save(gdi, '''#include <windows.h>
extern void pd2_gles2_fatal(unsigned stage, unsigned code);
DWORD WINAPI gdi_render_main(void) { pd2_gles2_fatal(8, 15); return 0; }
''')
    d3d = src / 'src/render_d3d9.c'
    text = d3d.read_text()
    anchor = 'DWORD WINAPI d3d9_render_main(void)\n{'
    if text.count(anchor) != 1:
        raise RuntimeError('D3D fallback anchor changed')
    text = text.replace(anchor, anchor + '\n    extern void pd2_gles2_fatal(unsigned stage, unsigned code);\n    pd2_gles2_fatal(8, 15);')
    save(d3d, text)
    project = src / 'cnc-ddraw.vcxproj'
    text = project.read_text(encoding='utf-8-sig')
    text = re.sub(r'<PreBuildEvent>.*?</PreBuildEvent>', '', text, flags=re.S)
    text = re.sub(r'<PostBuildEvent>.*?</PostBuildEvent>', '', text, flags=re.S)
    text = text.replace('<Link>', '<Link><AdditionalOptions>/Brepro /PDBALTPATH:ddraw.pdb %(AdditionalOptions)</AdditionalOptions>')
    text = text.replace('<ClCompile>', '<ClCompile><AdditionalOptions>/Brepro %(AdditionalOptions)</AdditionalOptions>')
    save(project, text)
    save(src / 'inc/git.h', '#define GIT_COMMIT "v7.1.0.0-pd2-gl2-1"\n#define GIT_BRANCH "gles2-renderer"\n')
    return ''.join(patches)


def command(text, cwd):
    batch = cwd / 'gles2-build-command.cmd'
    batch.write_text('@echo off\n' + text + '\n', encoding='utf-8')
    subprocess.run(['cmd.exe', '/d', '/c', str(batch)], cwd=cwd, check=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--test', action='store_true')
    args = parser.parse_args(argv)
    archive = ROOT / '.state/fps-renderer/upstream.zip'
    if sha(archive) != SOURCE_SHA:
        raise RuntimeError('Upstream archive hash mismatch')
    build = ROOT / '.state/gles2-renderer' / ('build-' + uuid.uuid4().hex)
    build.mkdir(parents=True)
    with zipfile.ZipFile(archive) as z:
        for name in z.namelist():
            if Path(name).is_absolute() or '..' in Path(name).parts or ':' in name:
                raise RuntimeError('Unsafe upstream member')
        z.extractall(build)
    src = build / 'cnc-ddraw-7.1.0.0'
    patch = patch_source(src)
    init = f'call "{VS / "VC/Auxiliary/Build/vcvarsall.bat"}" x64_x86 10.0.22621.0 -vcvars_ver=14.44 >nul && '
    if args.test:
        command(init + f'cl /nologo /W4 /WX /O2 /MT /D_CRT_SECURE_NO_WARNINGS /I"{TOOLS}" /I"{src / "inc"}" "{TOOLS / "gles2_test.c"}" /Fe:gles2-test.exe user32.lib gdi32.lib opengl32.lib && gles2-test.exe', build)
    command(init + f'"{VS / "MSBuild/Current/Bin/MSBuild.exe"}" cnc-ddraw.vcxproj /t:Build /m /p:Configuration=Release /p:TrackFileAccess=false /p:Platform=Win32 /p:PlatformToolset=v143 /p:WindowsTargetPlatformVersion=10.0.22621.0 /p:VCToolsVersion=14.44.35207 /p:SolutionDir="{src.as_posix()}/" /v:minimal', src)
    artifact = src / 'bin/Release/ddraw.dll'
    DEST.mkdir(parents=True, exist_ok=True)
    # Output files are generated build artifacts, never existing source inputs.
    shutil.copyfile(artifact, DEST / 'ddraw.dll')
    notices = (src / 'LICENSE').read_text() + '\n\nBundled Microsoft Detours:\n\n' + (src / 'src/detours/LICENSE.md').read_text()
    notices += '\n\nBundled LodePNG:\n\n' + (src / 'src/lodepng.c').read_text().split('/*', 1)[1].split('*/', 1)[0].strip() + '\n'
    (DEST / 'LICENSE.txt').write_text(notices)
    (DEST / 'source.patch').write_text(patch)
    manifest = {
        'schema': 1, 'file': 'ddraw.dll', 'size': artifact.stat().st_size, 'sha256': sha(artifact),
        'upstream': {'project': 'FunkyFr3sh/cnc-ddraw', 'tag': 'v7.1.0.0', 'source_url': URL, 'source_sha256': SOURCE_SHA, 'license': 'MIT; bundled notices in LICENSE.txt'},
        'build': {'compiler': 'MSVC 14.44.35207', 'sdk': '10.0.22621.0', 'configuration': 'Release Win32', 'crt': 'static /MT', 'deterministic': '/Brepro /PDBALTPATH:ddraw.pdb', 'inputs_sha256': {n: sha(TOOLS/n) for n in ('build_gles2_renderer.py', *INPUTS, 'gles2_test.c')}, 'source_patch_sha256': sha(DEST/'source.patch')},
        'renderer': {'gl': 'desktop GL2 / GLSL110 via GL4ES GLES2', 'source_bpp': [8, 16, 32], 'palette': 'luminance index + 256x1 RGBA texture, nearest', 'selftest': 'startup active-mode synthetic shader/draw/readPixels; native harness tests indexed8, RGB565, RGB555, BGRA32 and palette updates', 'fatal_exit': 86, 'fallback': 'none; only host ExitProcess', 'presentation': 'pd2-present.jsonl unchanged protocol', 'status': 'pd2-gles2.jsonl numeric fixed schema, 128 records / 32768 bytes'},
        'tests': {'native': 'passed' if args.test else 'not run', 'physical_r36s': 'not available'}}
    (DEST / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps(manifest, indent=2))
    print('Build directory:', build)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
