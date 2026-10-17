#!/usr/bin/env python3
"""Build high-performance OpenGL-enabled cnc-ddraw Win32 DLL for R36S (ver2).

Applies GL4ES/OpenGL ES 2.0 compatibility fixes:
- Bypasses desktop-only glGetTexImage upload/shader self-tests.
- Prevents silent fallback to GDI upon benign GL queries.
- Retains pure hardware acceleration on Mali-G31 GPU.
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
STATE = ROOT / '.state/cnc-ddraw'
DEST = ROOT / 'sdcard/ports/projectdiablo2/compat/cnc-ddraw'
UPSTREAM_ZIP = Path(r'C:\AI fast\R36S\projectdiablo2\.state\fps-renderer\upstream.zip')
SOURCE_SHA = 'a4f638383364e3bc1e4682b1d549a1f5400fa0cc312ee216d1b42555b1c814eb'
VS = Path(os.environ.get('PRESENT_RENDERER_VS', r'C:\Program Files\Microsoft Visual Studio\2022\Community'))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def replace(text, old, new):
    if text.count(old) != 1:
        raise RuntimeError(f'Upstream patch anchor changed or not found:\n{old}')
    return text.replace(old, new)


def run(command, cwd):
    batch = cwd / 'cnc-build-command.cmd'
    batch.write_text('@echo off\n' + command + '\n', encoding='utf-8')
    subprocess.run(['cmd.exe', '/d', '/c', str(batch)], cwd=cwd, check=True)


def main():
    if not UPSTREAM_ZIP.exists():
        raise RuntimeError(f'Upstream archive missing: {UPSTREAM_ZIP}')
    if sha(UPSTREAM_ZIP) != SOURCE_SHA:
        raise RuntimeError('Upstream archive hash mismatch')

    STATE.mkdir(parents=True, exist_ok=True)
    build = STATE / ('build-' + uuid.uuid4().hex)
    build.mkdir()

    with zipfile.ZipFile(UPSTREAM_ZIP) as z:
        for name in z.namelist():
            if Path(name).is_absolute() or '..' in Path(name).parts or ':' in name:
                raise RuntimeError('Unsafe upstream member')
        z.extractall(build)

    src = build / 'cnc-ddraw-7.1.0.0'
    patches = []

    def save(path, original, text):
        path.write_text(text, encoding='utf-8')
        relative = path.relative_to(src).as_posix()
        patches.extend(difflib.unified_diff(
            original.splitlines(True), text.splitlines(True),
            fromfile='a/' + relative, tofile='b/' + relative))

    # 1. Patch render_gdi.c: remove driver warning watermark
    path_gdi = src / 'src/render_gdi.c'
    orig_gdi = path_gdi.read_text()
    text_gdi = orig_gdi
    start = text_gdi.index('    static DWORD warning_end_tick')
    end = text_gdi.index('    Sleep(500);', start)
    text_gdi = text_gdi[:start] + text_gdi[end:]
    start = text_gdi.index('            if (warning_end_tick)')
    end = text_gdi.index('            BOOL upscale_hack', start)
    text_gdi = text_gdi[:start] + text_gdi[end:]
    save(path_gdi, orig_gdi, text_gdi)

    # 2. Patch render_ogl.c: unlock OpenGL under GL4ES/GLES2
    path_ogl = src / 'src/render_ogl.c'
    orig_ogl = path_ogl.read_text()
    text_ogl = orig_ogl

    # Bypass texture upload test (desktop glGetTexImage readback fails on GL4ES)
    text_ogl = replace(text_ogl, 'static BOOL ogl_texture_upload_test()\n{',
                       'static BOOL ogl_texture_upload_test()\n{\n    return TRUE;\n')

    # Bypass shader test (desktop glGetTexImage readback fails on GL4ES)
    text_ogl = replace(text_ogl, 'static BOOL ogl_shader_test()\n{',
                       'static BOOL ogl_shader_test()\n{\n    return TRUE;\n')

    # Clear benign GL errors and don't bail out of OpenGL
    text_ogl = replace(
        text_ogl,
        '        g_ogl.use_opengl = (g_ogl.main_program || g_ddraw.bpp == 16 || g_ddraw.bpp == 32) && !g_ogl.got_error;',
        '        while (glGetError() != GL_NO_ERROR); /* Clear benign errors in GL4ES query */\n'
        '        g_ogl.use_opengl = (g_ogl.main_program || g_ddraw.bpp == 16 || g_ddraw.bpp == 32);'
    )

    # Do not abort OpenGL on non-fatal frame errors in GL4ES
    text_ogl = replace(
        text_ogl,
        'if (err != GL_NO_ERROR && err != GL_INVALID_FRAMEBUFFER_OPERATION)\n                {\n                    g_ogl.use_opengl = FALSE;',
        'if (err != GL_NO_ERROR && err != GL_INVALID_FRAMEBUFFER_OPERATION)\n                {\n                    /* Do not abort OpenGL on non-fatal frame errors in GL4ES */'
    )
    save(path_ogl, orig_ogl, text_ogl)

    # 3. Project file adjustments for reproducible build
    project = src / 'cnc-ddraw.vcxproj'
    orig_proj = project.read_text(encoding='utf-8-sig')
    text_proj = re.sub(r'<PreBuildEvent>.*?</PreBuildEvent>', '', orig_proj, flags=re.S)
    text_proj = re.sub(r'<PostBuildEvent>.*?</PostBuildEvent>', '', text_proj, flags=re.S)
    text_proj = text_proj.replace('<Link>', '<Link><AdditionalOptions>/Brepro /PDBALTPATH:ddraw.pdb %(AdditionalOptions)</AdditionalOptions>')
    text_proj = text_proj.replace('<ClCompile>', '<ClCompile><AdditionalOptions>/Brepro %(AdditionalOptions)</AdditionalOptions>')
    save(project, orig_proj, text_proj)

    save(src / 'inc/git.h', '', '#define GIT_COMMIT "v7.1.0.0-pd2-ver2-ogl"\n#define GIT_BRANCH "release-ver2"\n')

    vcvars = VS / 'VC/Auxiliary/Build/vcvarsall.bat'
    msbuild = VS / 'MSBuild/Current/Bin/MSBuild.exe'
    init = f'call "{vcvars}" x64_x86 10.0.22621.0 -vcvars_ver=14.44 >nul && '

    cmd = (
        init +
        f'"{msbuild}" cnc-ddraw.vcxproj /t:Build /m /p:Configuration=Release '
        f'/p:TrackFileAccess=false /p:Platform=Win32 /p:PlatformToolset=v143 '
        f'/p:WindowsTargetPlatformVersion=10.0.22621.0 /p:VCToolsVersion=14.44.35207 '
        f'/p:SolutionDir="{src.as_posix()}/" /v:minimal'
    )
    run(cmd, src)

    artifact = src / 'bin/Release/ddraw.dll'
    DEST.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(artifact, DEST / 'ddraw.dll')

    notices = (src / 'LICENSE').read_text() + '\n\nBundled Microsoft Detours:\n\n' + (src / 'src/detours/LICENSE.md').read_text()
    lodepng = (src / 'src/lodepng.c').read_text()
    notices += '\n\nBundled LodePNG:\n\n' + lodepng.split('/*', 1)[1].split('*/', 1)[0].strip() + '\n'
    (DEST / 'LICENSE.txt').write_text(notices, encoding='utf-8')
    (DEST / 'source.patch').write_text(''.join(patches), encoding='utf-8')

    manifest = {
        'schema': 1,
        'file': 'ddraw.dll',
        'size': artifact.stat().st_size,
        'sha256': sha(artifact),
        'version': '7.1.0.0-ver2-ogl',
        'upstream': {
            'project': 'FunkyFr3sh/cnc-ddraw',
            'tag': 'v7.1.0.0',
            'source_sha256': SOURCE_SHA,
            'license': 'MIT'
        },
        'build': {
            'configuration': 'Release Win32',
            'compiler': 'MSVC 14.44.35207',
            'sdk': '10.0.22621.0',
            'crt': 'static /MT',
            'purpose': 'DirectDraw GPU acceleration on Mali-G31 via GL4ES without GDI fallback'
        }
    }
    (DEST / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    print('SUCCESS: Compiled ddraw.dll for ver2')
    print(json.dumps(manifest, indent=2))


if __name__ == '__main__':
    main()
