#!/usr/bin/env python3
"""Build independent pinned Win32 cnc-ddraw presentation diagnostics (no HUD).
Run: python tools/build_present_renderer.py --test
Offline: requires authenticated .state/ddraw/upstream.zip; never downloads.
Only compat/present-renderer is published; FPS DLL is never touched.
"""
import argparse
import json
import shutil

from cnc_ddraw_build import (
    ROOT, SOURCE_SHA, TOOLS, URL,
    build_win32_ddraw, combined_notices, extract_upstream,
    patch_gdi_scaler, patch_ogl_gl4es, patch_vcxproj,
    record_save, replace_once, sha256, strip_gdi_warning,
)

STATE = ROOT / '.state/present-renderer'
DEST = ROOT / 'sdcard/ports/projectdiablo2/compat/present-renderer'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--test', action='store_true', help='run console-only native unit tests')
    args = parser.parse_args()

    build, src = extract_upstream(STATE)
    patches = []

    for name, backend in (('gdi', 1), ('ogl', 2)):
        path = src / f'src/render_{name}.c'
        original = path.read_text()
        text = replace_once(
            original, '#include "config.h"',
            ('#define PD2_PRESENT_IMPLEMENTATION\n' if backend == 1 else '') +
            '#include "config.h"\n#include "present_metrics.h"')
        text = replace_once(
            text, 'fpsl_init();',
            f'if (IsWindow(g_ddraw.hwnd)) pd2_present_start({backend}, g_ddraw.render.width, g_ddraw.render.height);\n'
            + ('    ' if backend == 1 else '        ') + 'fpsl_init();')
        if name == 'gdi':
            text = strip_gdi_warning(text)
            text = patch_gdi_scaler(text)
            text = replace_once(
                text,
                '                FillRect(g_ddraw.render.hdc, &rc, (HBRUSH)GetStockObject(BLACK_BRUSH));\n                lines_copied = 1;',
                '                pd2_success = FillRect(g_ddraw.render.hdc, &rc, (HBRUSH)GetStockObject(BLACK_BRUSH));\n                lines_copied = 1;')
            text = replace_once(text, '                real_SetDIBitsToDevice(', '                lines_copied = real_SetDIBitsToDevice(')
            text = replace_once(text, '        EnterCriticalSection(&g_ddraw.cs);',
                                '        int pd2_success = 0;\n        EnterCriticalSection(&g_ddraw.cs);')
            text = replace_once(
                text, '            if (g_config.lock_surfaces)\n                LeaveCriticalSection',
                '            if (!g_ddraw.bnet_active)\n                pd2_success = lines_copied != 0 && lines_copied != GDI_ERROR;\n\n'
                '            if (g_config.lock_surfaces)\n                LeaveCriticalSection')
            text = replace_once(
                text, '        LeaveCriticalSection(&g_ddraw.cs);',
                '        LeaveCriticalSection(&g_ddraw.cs);\n'
                '        pd2_present_frame(1, pd2_success, g_ddraw.render.width, g_ddraw.render.height);')
        else:
            text = replace_once(
                text, '        SwapBuffers(g_ogl.hdc);',
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
            text = replace_once(
                text,
                'DWORD timeout = g_config.minfps > 0 ? g_ddraw.minfps_tick_len : INFINITE;',
                'DWORD timeout = g_config.minfps > 0 ? g_ddraw.minfps_tick_len : 100;')
            text = patch_ogl_gl4es(text)
        record_save(src, patches, path, original, text)

    record_save(src, patches, src / 'inc/present_metrics.h', '', (TOOLS / 'present_metrics.h').read_text())
    record_save(src, patches, src / 'inc/pd2_gdi_scaler.h', '', (TOOLS / 'pd2_gdi_scaler.h').read_text())
    patch_vcxproj(src, patches, 'v7.1.0.0-pd2-present4', 'present-renderer')

    tests = ()
    if args.test:
        tests = (
            f'cl /nologo /W4 /WX /O2 /MT /D_CRT_SECURE_NO_WARNINGS /I"{TOOLS}" "{TOOLS / "test_present_metrics.c"}" /Fe:present-metrics-test.exe && present-metrics-test.exe',
            f'cl /nologo /W4 /WX /O2 /MT /D_CRT_SECURE_NO_WARNINGS /I"{TOOLS}" "{TOOLS / "test_gdi_scaler.c"}" /Fe:pd2-scaler-test.exe && pd2-scaler-test.exe',
        )
    artifact = build_win32_ddraw(src, build, tests, 'present-build-command.cmd')

    DEST.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(artifact, DEST / 'ddraw.dll')
    (DEST / 'LICENSE.txt').write_text(combined_notices(src), encoding='utf-8')
    (DEST / 'source.patch').write_text(''.join(patches), encoding='utf-8')

    inputs = ('build_present_renderer.py', 'cnc_ddraw_build.py', 'present_metrics.h', 'test_present_metrics.c', 'pd2_gdi_scaler.h', 'test_gdi_scaler.c')
    manifest = {
        'schema': 1,
        'file': 'ddraw.dll',
        'size': artifact.stat().st_size,
        'sha256': sha256(artifact),
        'upstream': {
            'project': 'FunkyFr3sh/cnc-ddraw',
            'tag': 'v7.1.0.0',
            'source_url': URL,
            'source_sha256': SOURCE_SHA,
            'license': 'MIT; bundled notices in LICENSE.txt',
        },
        'build': {
            'configuration': 'Release Win32',
            'compiler': 'MSVC 14.44.35207',
            'sdk': '10.0.22621.0',
            'crt': 'static /MT',
            'deterministic': '/Brepro /PDBALTPATH:ddraw.pdb',
            'command': 'python tools/build_present_renderer.py' + (' --test' if args.test else ''),
            'inputs_sha256': {n: sha256(TOOLS / n) for n in inputs},
            'source_patch_sha256': sha256(DEST / 'source.patch'),
        },
        'telemetry': {
            'file': 'pd2-present.jsonl',
            'max_bytes': 262144,
            'interval_ms': 1000,
            'event': {
                '1': 'render_sample',
                '2': 'render_status (valid window handle and backend entry, not presentation)',
                '3': 'first successful API presentation, once per backend per process; frames=1 duration_ms=0',
            },
            'backend': {'1': 'gdi', '2': 'opengl'},
            'fields': ['event', 'backend', 'frames', 'duration_ms', 'width', 'height'],
            'values': 'integers only',
            'clock': 'QueryPerformanceCounter',
            'scope': 'successful backend presentations, not game simulation FPS',
        },
        'tests': {
            'native_core': 'passed' if args.test else 'not run',
            'gui': 'not required; not run',
            'physical_r36s': 'not available',
        },
        'scope': 'Presentation diagnostics + shared read-only GDI 5:4/bilinear downscaler; no HUD or source surface mutations.',
    }
    (DEST / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(manifest, indent=2))
    print('Build directory:', build)


if __name__ == '__main__':
    main()
