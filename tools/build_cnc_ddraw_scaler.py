#!/usr/bin/env python3
"""Build production Win32 cnc-ddraw with division-free 5:4/bilinear GDI downscaler.
Run: python tools/build_cnc_ddraw_scaler.py --test
Offline: requires pinned .state/ddraw/upstream.zip; never downloads.
"""
import argparse
import json
import shutil

from cnc_ddraw_build import (
    ROOT, SOURCE_SHA, TOOLS, URL,
    build_win32_ddraw, combined_notices, extract_upstream,
    patch_gdi_scaler, patch_ogl_gl4es, patch_vcxproj,
    record_save, sha256, strip_gdi_warning,
)

STATE = ROOT / '.state/cnc-ddraw'
DEST = ROOT / 'sdcard/ports/projectdiablo2/compat/cnc-ddraw'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--test', action='store_true', help='run native C scaler tests before building DLL')
    args = parser.parse_args()

    build, src = extract_upstream(STATE)
    patches = []

    path_gdi = src / 'src/render_gdi.c'
    orig_gdi = path_gdi.read_text()
    text_gdi = patch_gdi_scaler(strip_gdi_warning(orig_gdi))
    record_save(src, patches, path_gdi, orig_gdi, text_gdi)

    path_ogl = src / 'src/render_ogl.c'
    orig_ogl = path_ogl.read_text()
    record_save(src, patches, path_ogl, orig_ogl, patch_ogl_gl4es(orig_ogl))

    scaler_hdr = (TOOLS / 'pd2_gdi_scaler.h').read_text()
    record_save(src, patches, src / 'inc/pd2_gdi_scaler.h', '', scaler_hdr)

    patch_vcxproj(src, patches, 'v7.1.0.0-pd2-scaler2', 'release-scaler')

    tests = ()
    if args.test:
        tests = (
            f'cl /nologo /W4 /WX /O2 /MT /D_CRT_SECURE_NO_WARNINGS /I"{TOOLS}" "{TOOLS / "test_gdi_scaler.c"}" /Fe:pd2-scaler-test.exe && pd2-scaler-test.exe',
        )
    artifact = build_win32_ddraw(src, build, tests, 'cnc-build-command.cmd')

    DEST.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(artifact, DEST / 'ddraw.dll')
    (DEST / 'LICENSE.txt').write_text(combined_notices(src), encoding='utf-8')
    (DEST / 'source.patch').write_text(''.join(patches), encoding='utf-8')

    inputs = ('build_cnc_ddraw_scaler.py', 'cnc_ddraw_build.py', 'pd2_gdi_scaler.h', 'test_gdi_scaler.c')
    manifest = {
        'schema': 1,
        'version': '7.1.0.0',
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
            'command': 'python tools/build_cnc_ddraw_scaler.py' + (' --test' if args.test else ''),
            'inputs_sha256': {n: sha256(TOOLS / n) for n in inputs},
            'source_patch_sha256': sha256(DEST / 'source.patch'),
        },
        'tests': {
            'native_core': 'passed' if args.test else 'not run',
            'physical_r36s': 'pending user validation',
        },
        'scope': 'GDI 5:4 SWAR downscaler (800x600->640x480) + cached bilinear fallback (8/16/32bpp) with bounded pd2-scale.jsonl telemetry.',
    }
    (DEST / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(manifest, indent=2))
    print('Build directory:', build)


if __name__ == '__main__':
    main()
