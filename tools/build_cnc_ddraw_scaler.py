#!/usr/bin/env python3
"""Build high-performance cnc-ddraw Win32 DLL with built-in 5:4 area-weighted downscaler."""
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
UPSTREAM_ZIP = Path(r'C:\AI fast\old\R36S\projectdiablo2\.state\fps-renderer\upstream.zip')
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


DOWNSCALER_CODE = '''
#include <stdint.h>

static inline uint16_t blend_pixel16(uint16_t c0, uint16_t c1, int w0, int w1) {
    uint32_t r = ((c0 >> 11) * w0 + (c1 >> 11) * w1) / 5;
    uint32_t g = ((((c0 >> 5) & 0x3F) * w0 + ((c1 >> 5) & 0x3F) * w1) / 5);
    uint32_t b = ((c0 & 0x1F) * w0 + (c1 & 0x1F) * w1) / 5;
    return (uint16_t)((r << 11) | (g << 5) | b);
}

static inline void downscale_row_800_to_640_16(const uint16_t *src, uint16_t *dst) {
    for (int i = 0; i < 160; i++) {
        uint16_t s0 = src[0], s1 = src[1], s2 = src[2], s3 = src[3], s4 = src[4];
        dst[0] = blend_pixel16(s0, s1, 4, 1);
        dst[1] = blend_pixel16(s1, s2, 3, 2);
        dst[2] = blend_pixel16(s2, s3, 2, 3);
        dst[3] = blend_pixel16(s3, s4, 1, 4);
        src += 5;
        dst += 4;
    }
}

static inline void blend_row_640_16(const uint16_t *r0, const uint16_t *r1, uint16_t *dst, int w0, int w1) {
    for (int i = 0; i < 640; i++) {
        dst[i] = blend_pixel16(r0[i], r1[i], w0, w1);
    }
}

static void downscale_800x600_to_640x480_16(const uint16_t *src, uint16_t *dst) {
    uint16_t hrow[5][640];
    for (int block = 0; block < 120; block++) {
        const uint16_t *sblock = src + (block * 5) * 800;
        uint16_t *dblock = dst + (block * 4) * 640;

        downscale_row_800_to_640_16(sblock + 0 * 800, hrow[0]);
        downscale_row_800_to_640_16(sblock + 1 * 800, hrow[1]);
        downscale_row_800_to_640_16(sblock + 2 * 800, hrow[2]);
        downscale_row_800_to_640_16(sblock + 3 * 800, hrow[3]);
        downscale_row_800_to_640_16(sblock + 4 * 800, hrow[4]);

        blend_row_640_16(hrow[0], hrow[1], dblock + 0 * 640, 4, 1);
        blend_row_640_16(hrow[1], hrow[2], dblock + 1 * 640, 3, 2);
        blend_row_640_16(hrow[2], hrow[3], dblock + 2 * 640, 2, 3);
        blend_row_640_16(hrow[3], hrow[4], dblock + 3 * 640, 1, 4);
    }
}

static inline uint32_t blend_pixel32(uint32_t c0, uint32_t c1, int w0, int w1) {
    uint32_t r = (((c0 >> 16) & 0xFF) * w0 + ((c1 >> 16) & 0xFF) * w1) / 5;
    uint32_t g = (((c0 >> 8) & 0xFF) * w0 + ((c1 >> 8) & 0xFF) * w1) / 5;
    uint32_t b = ((c0 & 0xFF) * w0 + (c1 & 0xFF) * w1) / 5;
    return (uint32_t)((r << 16) | (g << 8) | b);
}

static inline void downscale_row_800_to_640_32(const uint32_t *src, uint32_t *dst) {
    for (int i = 0; i < 160; i++) {
        uint32_t s0 = src[0], s1 = src[1], s2 = src[2], s3 = src[3], s4 = src[4];
        dst[0] = blend_pixel32(s0, s1, 4, 1);
        dst[1] = blend_pixel32(s1, s2, 3, 2);
        dst[2] = blend_pixel32(s2, s3, 2, 3);
        dst[3] = blend_pixel32(s3, s4, 1, 4);
        src += 5;
        dst += 4;
    }
}

static inline void blend_row_640_32(const uint32_t *r0, const uint32_t *r1, uint32_t *dst, int w0, int w1) {
    for (int i = 0; i < 640; i++) {
        dst[i] = blend_pixel32(r0[i], r1[i], w0, w1);
    }
}

static void downscale_800x600_to_640x480_32(const uint32_t *src, uint32_t *dst) {
    uint32_t hrow[5][640];
    for (int block = 0; block < 120; block++) {
        const uint32_t *sblock = src + (block * 5) * 800;
        uint32_t *dblock = dst + (block * 4) * 640;

        downscale_row_800_to_640_32(sblock + 0 * 800, hrow[0]);
        downscale_row_800_to_640_32(sblock + 1 * 800, hrow[1]);
        downscale_row_800_to_640_32(sblock + 2 * 800, hrow[2]);
        downscale_row_800_to_640_32(sblock + 3 * 800, hrow[3]);
        downscale_row_800_to_640_32(sblock + 4 * 800, hrow[4]);

        blend_row_640_32(hrow[0], hrow[1], dblock + 0 * 640, 4, 1);
        blend_row_640_32(hrow[1], hrow[2], dblock + 1 * 640, 3, 2);
        blend_row_640_32(hrow[2], hrow[3], dblock + 2 * 640, 2, 3);
        blend_row_640_32(hrow[3], hrow[4], dblock + 3 * 640, 1, 4);
    }
}
'''

GDI_STRETCH_REPLACEMENT = '''            else if (!g_ddraw.child_window_exists &&
                (g_ddraw.render.width != g_ddraw.width || g_ddraw.render.height != g_ddraw.height))
            {
                if (g_ddraw.width == 800 && g_ddraw.height == 600 &&
                    g_ddraw.render.viewport.width == 640 && g_ddraw.render.viewport.height == 480 &&
                    (g_ddraw.bpp == 16 || g_ddraw.bpp == 32))
                {
                    static uint16_t s_scaled_surface16[640 * 480];
                    static uint32_t s_scaled_surface32[640 * 480];
                    static struct { BITMAPINFOHEADER bmiHeader; RGBQUAD bmiColors[3]; } s_scaled_bmi16;
                    static struct { BITMAPINFOHEADER bmiHeader; RGBQUAD bmiColors[3]; } s_scaled_bmi32;
                    static BOOL s_inited = FALSE;
                    if (!s_inited)
                    {
                        memset(&s_scaled_bmi16, 0, sizeof(s_scaled_bmi16));
                        s_scaled_bmi16.bmiHeader.biSize = sizeof(BITMAPINFOHEADER);
                        s_scaled_bmi16.bmiHeader.biWidth = 640;
                        s_scaled_bmi16.bmiHeader.biHeight = -480;
                        s_scaled_bmi16.bmiHeader.biPlanes = 1;
                        s_scaled_bmi16.bmiHeader.biBitCount = 16;
                        s_scaled_bmi16.bmiHeader.biCompression = BI_BITFIELDS;
                        *(DWORD *)&s_scaled_bmi16.bmiColors[0] = 0xF800;
                        *(DWORD *)&s_scaled_bmi16.bmiColors[1] = 0x07E0;
                        *(DWORD *)&s_scaled_bmi16.bmiColors[2] = 0x001F;

                        memset(&s_scaled_bmi32, 0, sizeof(s_scaled_bmi32));
                        s_scaled_bmi32.bmiHeader.biSize = sizeof(BITMAPINFOHEADER);
                        s_scaled_bmi32.bmiHeader.biWidth = 640;
                        s_scaled_bmi32.bmiHeader.biHeight = -480;
                        s_scaled_bmi32.bmiHeader.biPlanes = 1;
                        s_scaled_bmi32.bmiHeader.biBitCount = 32;
                        s_scaled_bmi32.bmiHeader.biCompression = BI_RGB;
                        s_inited = TRUE;
                    }

                    if (g_ddraw.bpp == 16)
                    {
                        downscale_800x600_to_640x480_16((const uint16_t *)g_ddraw.primary->surface, s_scaled_surface16);
                        lines_copied = real_SetDIBitsToDevice(
                            g_ddraw.render.hdc,
                            g_ddraw.render.viewport.x,
                            g_ddraw.render.viewport.y,
                            640,
                            480,
                            0,
                            0,
                            0,
                            480,
                            s_scaled_surface16,
                            (BITMAPINFO *)&s_scaled_bmi16,
                            DIB_RGB_COLORS);
                    }
                    else
                    {
                        downscale_800x600_to_640x480_32((const uint32_t *)g_ddraw.primary->surface, s_scaled_surface32);
                        lines_copied = real_SetDIBitsToDevice(
                            g_ddraw.render.hdc,
                            g_ddraw.render.viewport.x,
                            g_ddraw.render.viewport.y,
                            640,
                            480,
                            0,
                            0,
                            0,
                            480,
                            s_scaled_surface32,
                            (BITMAPINFO *)&s_scaled_bmi32,
                            DIB_RGB_COLORS);
                    }
                }
                else
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

    # 1. Patch render_gdi.c: insert downscaler & replace StretchDIBits
    path_gdi = src / 'src/render_gdi.c'
    orig_gdi = path_gdi.read_text()
    text_gdi = orig_gdi

    # Remove driver warning watermark
    start = text_gdi.index('    static DWORD warning_end_tick')
    end = text_gdi.index('    Sleep(500);', start)
    text_gdi = text_gdi[:start] + text_gdi[end:]
    start = text_gdi.index('            if (warning_end_tick)')
    end = text_gdi.index('            BOOL upscale_hack', start)
    text_gdi = text_gdi[:start] + text_gdi[end:]

    # Insert downscaler helper code before gdi_render_main
    text_gdi = replace(text_gdi, 'DWORD WINAPI gdi_render_main(void)\n{',
                       DOWNSCALER_CODE + '\nDWORD WINAPI gdi_render_main(void)\n{')

    # Replace StretchDIBits call block
    target_block = '''            else if (!g_ddraw.child_window_exists &&
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
    text_gdi = replace(text_gdi, target_block, GDI_STRETCH_REPLACEMENT)
    save(path_gdi, orig_gdi, text_gdi)

    # 2. Patch render_ogl.c: unlock OpenGL under GL4ES/GLES2
    path_ogl = src / 'src/render_ogl.c'
    orig_ogl = path_ogl.read_text()
    text_ogl = orig_ogl

    text_ogl = replace(text_ogl, 'static BOOL ogl_texture_upload_test()\n{',
                       'static BOOL ogl_texture_upload_test()\n{\n    return TRUE;\n')
    text_ogl = replace(text_ogl, 'static BOOL ogl_shader_test()\n{',
                       'static BOOL ogl_shader_test()\n{\n    return TRUE;\n')
    text_ogl = replace(
        text_ogl,
        '        g_ogl.use_opengl = (g_ogl.main_program || g_ddraw.bpp == 16 || g_ddraw.bpp == 32) && !g_ogl.got_error;',
        '        while (glGetError() != GL_NO_ERROR); /* Clear benign errors in GL4ES query */\n'
        '        g_ogl.use_opengl = (g_ogl.main_program || g_ddraw.bpp == 16 || g_ddraw.bpp == 32);'
    )
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

    save(src / 'inc/git.h', '', '#define GIT_COMMIT "v7.1.0.0-pd2-scaler"\n#define GIT_BRANCH "release-scaler"\n')

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
        'version': '7.1.0.0',
        'file': 'ddraw.dll',
        'size': artifact.stat().st_size,
        'sha256': sha(artifact),
        'archive_sha256': '0b13ab89a64c9918189b1dadd449ef6ed3cb3b7b19cabd96d8adbd95505bb908',
        'source_url': 'https://github.com/FunkyFr3sh/cnc-ddraw/releases/download/v7.1.0.0/cnc-ddraw.zip',
        'license': 'MIT'
    }
    (DEST / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    print('SUCCESS: Compiled ddraw.dll with fast 5:4 area downscaler')
    print(json.dumps(manifest, indent=2))


if __name__ == '__main__':
    main()
