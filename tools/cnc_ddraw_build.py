#!/usr/bin/env python3
"""Shared deterministic offline MSVC builder helpers for cnc-ddraw 7.1.0.0 DLLs."""
import difflib
import hashlib
import os
from pathlib import Path
import re
import subprocess
import uuid
import zipfile

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / 'tools'
URL = 'https://codeload.github.com/FunkyFr3sh/cnc-ddraw/zip/refs/tags/v7.1.0.0'
SOURCE_SHA = 'a4f638383364e3bc1e4682b1d549a1f5400fa0cc312ee216d1b42555b1c814eb'
VS = Path(os.environ.get('PRESENT_RENDERER_VS', r'C:\Program Files\Microsoft Visual Studio\2022\Community'))

STRETCH_TARGET = '''            else if (!g_ddraw.child_window_exists &&
                (g_ddraw.render.width != g_ddraw.width || g_ddraw.render.height != g_ddraw.height))
            {
                lines_copied = real_StretchDIBits(
                    g_ddraw.render.hdc,
                    g_ddraw.render.viewport.x,
                    g_ddraw.render.viewport.y,
                    g_ddraw.render.viewport.width,
                    g_ddraw.render.viewport.height,
                    0,
                    0,
                    g_ddraw.width,
                    g_ddraw.height,
                    g_ddraw.primary->surface,
                    g_ddraw.primary->bmi,
                    DIB_RGB_COLORS,
                    SRCCOPY);
            }'''

STRETCH_REPLACEMENT = '''            else if (!g_ddraw.child_window_exists &&
                (g_ddraw.render.width != g_ddraw.width || g_ddraw.render.height != g_ddraw.height))
            {
                lines_copied = pd2_gdi_scale_present();

                if (lines_copied == 0)
                {
                    lines_copied = real_StretchDIBits(
                        g_ddraw.render.hdc,
                        g_ddraw.render.viewport.x,
                        g_ddraw.render.viewport.y,
                        g_ddraw.render.viewport.width,
                        g_ddraw.render.viewport.height,
                        0,
                        0,
                        g_ddraw.width,
                        g_ddraw.height,
                        g_ddraw.primary->surface,
                        g_ddraw.primary->bmi,
                        DIB_RGB_COLORS,
                        SRCCOPY);
                }
            }'''


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def replace_once(text, old, new):
    if text.count(old) != 1:
        raise RuntimeError(f'Upstream patch anchor changed ({text.count(old)} matches):\n{old}')
    return text.replace(old, new)


def find_upstream_zip():
    for candidate in (ROOT / '.state/ddraw/upstream.zip', ROOT / '.state/fps-renderer/upstream.zip'):
        if candidate.is_file():
            if sha256(candidate) != SOURCE_SHA:
                raise RuntimeError(f'Upstream archive hash mismatch: {candidate}')
            return candidate
    raise RuntimeError('Missing pinned upstream cnc-ddraw archive under .state/ddraw/upstream.zip')


def run_cmd(command, cwd, script_name='build-command.cmd'):
    batch = cwd / script_name
    batch.write_text('@echo off\n' + command + '\n', encoding='utf-8')
    subprocess.run(['cmd.exe', '/d', '/c', str(batch)], cwd=cwd, check=True)


def extract_upstream(state_dir):
    archive = find_upstream_zip()
    state_dir.mkdir(parents=True, exist_ok=True)
    build = state_dir / ('build-' + uuid.uuid4().hex)
    build.mkdir()
    with zipfile.ZipFile(archive) as z:
        for name in z.namelist():
            if Path(name).is_absolute() or '..' in Path(name).parts or ':' in name:
                raise RuntimeError('Unsafe upstream member')
        z.extractall(build)
    return build, build / 'cnc-ddraw-7.1.0.0'


def record_save(src, patches, path, original, text):
    path.write_text(text, encoding='utf-8')
    relative = path.relative_to(src).as_posix()
    patches.extend(difflib.unified_diff(
        original.splitlines(True), text.splitlines(True),
        fromfile='a/' + relative, tofile='b/' + relative))


def strip_gdi_warning(text):
    start = text.index('    static DWORD warning_end_tick')
    end = text.index('    Sleep(500);', start)
    text = text[:start] + text[end:]
    start = text.index('            if (warning_end_tick)')
    end = text.index('            BOOL upscale_hack', start)
    return text[:start] + text[end:]


def patch_gdi_scaler(text):
    text = replace_once(text, '#include "config.h"', '#include "config.h"\n#include "pd2_gdi_scaler.h"')
    return replace_once(text, STRETCH_TARGET, STRETCH_REPLACEMENT)


def patch_ogl_gl4es(text):
    text = replace_once(text, 'static BOOL ogl_texture_upload_test()\n{',
                        'static BOOL ogl_texture_upload_test()\n{\n    return TRUE;\n')
    text = replace_once(text, 'static BOOL ogl_shader_test()\n{',
                        'static BOOL ogl_shader_test()\n{\n    return TRUE;\n')
    text = replace_once(
        text,
        '        g_ogl.use_opengl = (g_ogl.main_program || g_ddraw.bpp == 16 || g_ddraw.bpp == 32) && !g_ogl.got_error;',
        '        while (glGetError() != GL_NO_ERROR); /* Clear benign errors in GL4ES query */\n'
        '        g_ogl.use_opengl = (g_ogl.main_program || g_ddraw.bpp == 16 || g_ddraw.bpp == 32);'
    )
    return replace_once(
        text,
        'if (err != GL_NO_ERROR && err != GL_INVALID_FRAMEBUFFER_OPERATION)\n                {\n                    g_ogl.use_opengl = FALSE;',
        'if (err != GL_NO_ERROR && err != GL_INVALID_FRAMEBUFFER_OPERATION)\n                {\n                    /* Do not abort OpenGL on non-fatal frame errors in GL4ES */'
    )


def patch_vcxproj(src, patches, git_commit, git_branch):
    project = src / 'cnc-ddraw.vcxproj'
    original = project.read_text(encoding='utf-8-sig')
    text = re.sub(r'<PreBuildEvent>.*?</PreBuildEvent>', '', original, flags=re.S)
    text = re.sub(r'<PostBuildEvent>.*?</PostBuildEvent>', '', text, flags=re.S)
    text = text.replace('<Link>', '<Link><AdditionalOptions>/Brepro /PDBALTPATH:ddraw.pdb %(AdditionalOptions)</AdditionalOptions>')
    text = text.replace('<ClCompile>', '<ClCompile><AdditionalOptions>/Brepro %(AdditionalOptions)</AdditionalOptions>')
    record_save(src, patches, project, original, text)
    record_save(src, patches, src / 'inc/git.h', '',
                f'#define GIT_COMMIT "{git_commit}"\n#define GIT_BRANCH "{git_branch}"\n')


def build_win32_ddraw(src, build, test_commands=(), script_name='build-command.cmd'):
    vcvars = VS / 'VC/Auxiliary/Build/vcvarsall.bat'
    msbuild = VS / 'MSBuild/Current/Bin/MSBuild.exe'
    init = f'call "{vcvars}" x64_x86 10.0.22621.0 -vcvars_ver=14.44 >nul && '
    for cmd in test_commands:
        run_cmd(init + cmd, build, script_name)
    msbuild_cmd = (
        f'"{msbuild}" cnc-ddraw.vcxproj /t:Build /m /p:Configuration=Release '
        f'/p:TrackFileAccess=false /p:Platform=Win32 /p:PlatformToolset=v143 '
        f'/p:WindowsTargetPlatformVersion=10.0.22621.0 /p:VCToolsVersion=14.44.35207 '
        f'/p:SolutionDir="{src.as_posix()}/" /v:minimal'
    )
    run_cmd(init + msbuild_cmd, src, script_name)
    return src / 'bin/Release/ddraw.dll'


def combined_notices(src):
    notices = (src / 'LICENSE').read_text() + '\n\nBundled Microsoft Detours:\n\n' + (src / 'src/detours/LICENSE.md').read_text()
    lodepng = (src / 'src/lodepng.c').read_text()
    notices += '\n\nBundled LodePNG:\n\n' + lodepng.split('/*', 1)[1].split('*/', 1)[0].strip() + '\n'
    return notices
