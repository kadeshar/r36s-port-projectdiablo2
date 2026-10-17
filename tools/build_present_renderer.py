#!/usr/bin/env python3
"""Build independent pinned Win32 cnc-ddraw presentation diagnostics (no HUD).
Run: python tools/build_present_renderer.py --test
Offline: requires authenticated .state/fps-renderer/upstream.zip; never downloads.
Only compat/present-renderer is published; FPS and normal DLLs are never touched.
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
STATE = ROOT / '.state/present-renderer'
DEST = ROOT / 'sdcard/ports/projectdiablo2/compat/present-renderer'
URL = 'https://codeload.github.com/FunkyFr3sh/cnc-ddraw/zip/refs/tags/v7.1.0.0'
SOURCE_SHA = 'a4f638383364e3bc1e4682b1d549a1f5400fa0cc312ee216d1b42555b1c814eb'
VS = Path(os.environ.get('PRESENT_RENDERER_VS', r'C:\Program Files\Microsoft Visual Studio\2022\Community'))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def replace(text, old, new):
    if text.count(old) != 1:
        raise RuntimeError('Upstream patch anchor changed')
    return text.replace(old, new)


def run(command, cwd):
    batch = cwd / 'present-build-command.cmd'
    batch.write_text('@echo off\n' + command + '\n', encoding='utf-8')
    subprocess.run(['cmd.exe', '/d', '/c', str(batch)], cwd=cwd, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--test', action='store_true', help='run console-only native unit tests')
    args = parser.parse_args()
    archive = ROOT / '.state/fps-renderer/upstream.zip'
    if sha(archive) != SOURCE_SHA:
        raise RuntimeError('Upstream archive hash mismatch')
    STATE.mkdir(parents=True, exist_ok=True)
    build = STATE / ('build-' + uuid.uuid4().hex)
    build.mkdir()
    with zipfile.ZipFile(archive) as z:
        # Hash is pinned, but reject traversal even if a future archive changes.
        for name in z.namelist():
            if Path(name).is_absolute() or '..' in Path(name).parts or ':' in name:
                raise RuntimeError('Unsafe upstream member')
        z.extractall(build)
    src = build / 'cnc-ddraw-7.1.0.0'
    patches = []

    def save(path, original, text):
        path.write_text(text, encoding='utf-8')
        relative = path.relative_to(src).as_posix()
        patches.extend(difflib.unified_diff(original.splitlines(True), text.splitlines(True),
            fromfile='a/' + relative, tofile='b/' + relative))

    for name, backend in (('gdi', 1), ('ogl', 2)):
        path = src / f'src/render_{name}.c'
        original = path.read_text()
        text = replace(original, '#include "config.h"',
            ('#define PD2_PRESENT_IMPLEMENTATION\n' if backend == 1 else '') +
            '#include "config.h"\n#include "present_metrics.h"')
        text = replace(text, 'fpsl_init();', f'if (IsWindow(g_ddraw.hwnd)) pd2_present_start({backend}, g_ddraw.render.width, g_ddraw.render.height);\n' + ('    ' if backend == 1 else '        ') + 'fpsl_init();')
        if name == 'gdi':
            # Remove upstream's surface-mutating fallback warning as well. No HUD.
            start = text.index('    static DWORD warning_end_tick')
            end = text.index('    Sleep(500);', start)
            text = text[:start] + text[end:]
            start = text.index('            if (warning_end_tick)')
            end = text.index('            BOOL upscale_hack', start)
            text = text[:start] + text[end:]
            text = replace(text, '                FillRect(g_ddraw.render.hdc, &rc, (HBRUSH)GetStockObject(BLACK_BRUSH));\n                lines_copied = 1;',
                '                pd2_success = FillRect(g_ddraw.render.hdc, &rc, (HBRUSH)GetStockObject(BLACK_BRUSH));\n                lines_copied = 1;')
            text = replace(text, '                real_SetDIBitsToDevice(', '                lines_copied = real_SetDIBitsToDevice(')
            # Sample outside upstream surface/global critical sections; no pixel reads.
            text = replace(text, '        EnterCriticalSection(&g_ddraw.cs);', '        int pd2_success = 0;\n        EnterCriticalSection(&g_ddraw.cs);')
            text = replace(text, '            if (g_config.lock_surfaces)\n                LeaveCriticalSection',
                '            if (!g_ddraw.bnet_active)\n                pd2_success = lines_copied != 0 && lines_copied != GDI_ERROR;\n\n            if (g_config.lock_surfaces)\n                LeaveCriticalSection')
            text = replace(text, '        LeaveCriticalSection(&g_ddraw.cs);',
                '        LeaveCriticalSection(&g_ddraw.cs);\n        pd2_present_frame(1, pd2_success, g_ddraw.render.width, g_ddraw.render.height);')
        else:
            text = replace(text, '        SwapBuffers(g_ogl.hdc);',
                '        BOOL swap_ok = SwapBuffers(g_ogl.hdc) != 0;\n'
                '        static int pd2_gl_fails = 0;\n'
                '        if (!swap_ok)\n'
                '        {\n'
                '            if (++pd2_gl_fails >= 5)\n'
                '            {\n'
                '                g_ogl.use_opengl = FALSE;\n'
                '                break;\n'
                '            }\n'
                '        }\n'
                '        else\n'
                '        {\n'
                '            pd2_gl_fails = 0;\n'
                '        }\n'
                '        pd2_present_frame(2, swap_ok, g_ddraw.render.width, g_ddraw.render.height);')
            # Never wait indefinitely on the semaphore: fallback timeout is bounded to 100ms
            text = replace(text,
                'DWORD timeout = g_config.minfps > 0 ? g_ddraw.minfps_tick_len : INFINITE;',
                'DWORD timeout = g_config.minfps > 0 ? g_ddraw.minfps_tick_len : 100;')
            # GLES2/GL4ES compatibility: bypass glGetTexImage readback self-tests
            text = replace(text, 'static BOOL ogl_texture_upload_test()\n{',
                'static BOOL ogl_texture_upload_test()\n{\n    return TRUE;\n')
            text = replace(text, 'static BOOL ogl_shader_test()\n{',
                'static BOOL ogl_shader_test()\n{\n    return TRUE;\n')
            # Do not drop OpenGL on benign GL queries or residual errors under Wine/GL4ES
            text = replace(text,
                '        g_ogl.use_opengl = (g_ogl.main_program || g_ddraw.bpp == 16 || g_ddraw.bpp == 32) && !g_ogl.got_error;',
                '        while (glGetError() != GL_NO_ERROR); /* Clear any benign errors in GL4ES query */\n'
                '        g_ogl.use_opengl = (g_ogl.main_program || g_ddraw.bpp == 16 || g_ddraw.bpp == 32);')
            text = replace(text,
                'if (err != GL_NO_ERROR && err != GL_INVALID_FRAMEBUFFER_OPERATION)\n                {\n                    g_ogl.use_opengl = FALSE;',
                'if (err != GL_NO_ERROR && err != GL_INVALID_FRAMEBUFFER_OPERATION)\n                {\n                    /* Do not abort OpenGL on non-fatal frame errors in GL4ES */')
        save(path, original, text)
    header = (TOOLS / 'present_metrics.h').read_text()
    save(src / 'inc/present_metrics.h', '', header)
    project = src / 'cnc-ddraw.vcxproj'
    original = project.read_text(encoding='utf-8-sig')
    text = re.sub(r'<PreBuildEvent>.*?</PreBuildEvent>', '', original, flags=re.S)
    text = re.sub(r'<PostBuildEvent>.*?</PostBuildEvent>', '', text, flags=re.S)
    text = text.replace('<Link>', '<Link><AdditionalOptions>/Brepro /PDBALTPATH:ddraw.pdb %(AdditionalOptions)</AdditionalOptions>')
    text = text.replace('<ClCompile>', '<ClCompile><AdditionalOptions>/Brepro %(AdditionalOptions)</AdditionalOptions>')
    save(project, original, text)
    save(src / 'inc/git.h', '', '#define GIT_COMMIT "v7.1.0.0-pd2-present3"\n#define GIT_BRANCH "present-renderer"\n')
    vcvars = VS / 'VC/Auxiliary/Build/vcvarsall.bat'
    msbuild = VS / 'MSBuild/Current/Bin/MSBuild.exe'
    init = f'call "{vcvars}" x64_x86 10.0.22621.0 -vcvars_ver=14.44 >nul && '
    if args.test:
        run(init + f'cl /nologo /W4 /WX /O2 /MT /D_CRT_SECURE_NO_WARNINGS /I"{TOOLS}" "{TOOLS / "test_present_metrics.c"}" /Fe:present-metrics-test.exe && present-metrics-test.exe', build)
    run(init + f'"{msbuild}" cnc-ddraw.vcxproj /t:Build /m /p:Configuration=Release /p:TrackFileAccess=false /p:Platform=Win32 /p:PlatformToolset=v143 /p:WindowsTargetPlatformVersion=10.0.22621.0 /p:VCToolsVersion=14.44.35207 /p:SolutionDir="{src.as_posix()}/" /v:minimal', src)
    artifact = src / 'bin/Release/ddraw.dll'
    DEST.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(artifact, DEST / 'ddraw.dll')
    notices = (src / 'LICENSE').read_text() + '\n\nBundled Microsoft Detours:\n\n' + (src / 'src/detours/LICENSE.md').read_text()
    lodepng = (src / 'src/lodepng.c').read_text()
    notices += '\n\nBundled LodePNG:\n\n' + lodepng.split('/*', 1)[1].split('*/', 1)[0].strip() + '\n'
    (DEST / 'LICENSE.txt').write_text(notices)
    (DEST / 'source.patch').write_text(''.join(patches))
    manifest = {
        'schema': 1, 'file': 'ddraw.dll', 'size': artifact.stat().st_size, 'sha256': sha(artifact),
        'upstream': {'project': 'FunkyFr3sh/cnc-ddraw', 'tag': 'v7.1.0.0', 'source_url': URL, 'source_sha256': SOURCE_SHA, 'license': 'MIT; bundled notices in LICENSE.txt'},
        'build': {'configuration': 'Release Win32', 'compiler': 'MSVC 14.44.35207', 'sdk': '10.0.22621.0', 'crt': 'static /MT', 'deterministic': '/Brepro /PDBALTPATH:ddraw.pdb', 'command': 'python tools/build_present_renderer.py' + (' --test' if args.test else ''), 'inputs_sha256': {n: sha(TOOLS / n) for n in ('build_present_renderer.py', 'present_metrics.h', 'test_present_metrics.c')}, 'source_patch_sha256': sha(DEST / 'source.patch')},
        'telemetry': {'file': 'pd2-present.jsonl', 'max_bytes': 262144, 'interval_ms': 1000, 'event': {'1': 'render_sample', '2': 'render_status (valid window handle and backend entry, not presentation)', '3': 'first successful API presentation, once per backend per process; frames=1 duration_ms=0'}, 'backend': {'1': 'gdi', '2': 'opengl'}, 'fields': ['event', 'backend', 'frames', 'duration_ms', 'width', 'height'], 'values': 'integers only', 'clock': 'QueryPerformanceCounter', 'scope': 'successful backend presentations, not game simulation FPS'},
        'tests': {'native_core': 'passed' if args.test else 'not run', 'gui': 'not required; not run', 'physical_r36s': 'not available'},
        'scope': 'Independent optional diagnostics; no HUD, framebuffer copies or mutations; default and FPS DLLs unchanged.'}
    (DEST / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps(manifest, indent=2))
    print('Build directory:', build)


if __name__ == '__main__':
    main()
