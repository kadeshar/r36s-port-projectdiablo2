# Opt-in GL2 renderer

Separate build of cnc-ddraw v7.1.0.0. Original renderer and HUD artifacts are not modified.

## Rendering contract

- Desktop OpenGL 2 / GLSL 1.10, intended for Wine + GL4ES GLES2; no GL3/core context, FBO or multipass requirement.
- Indexed 8-bit surface stays indexed: one luminance texture plus a 256-entry palette texture, nearest sampling. RGB565, RGB555 and BGRA32 remain supported.
- A dedicated palette gate makes the 1 KiB palette snapshot coherent. It is released before GL calls; there is no full-frame CPU color conversion/copy.
- Tightly packed surfaces upload once; unusual pitch uploads row slices without GLES-incompatible `GL_UNPACK_ROW_LENGTH`.
- Startup performs actual synthetic shader/render/readPixels validation for the active input format, including palette-only recoloring in indexed mode. The native harness exercises all four formats; an unused driver format cannot reject otherwise valid gameplay. Readback never accesses game pixels.
- Surface/palette notifications drive rendering; timeout checks only permit teardown. No forced idle redraw floor. Mode changes rebuild resources through cnc-ddraw's existing thread lifecycle.
- Missing API, failed shader/texture/validation/upload/draw/swap, invalid format or unexpected fallback records a bounded failure and calls `ExitProcess(86)` **only in the DLL host**. No arbitrary PID signalling. Normal release does not take the fatal path. No GDI fallback under headless Weston.
- This specialized backend does not implement cnc-ddraw's optional shader files, upscale hacks or child-window composition. The integrating launcher must select the simple game profile.

## Selection and telemetry

The [selector](<../../scripts/gles2_renderer.py>) authenticates pinned bytes and replaces only the stock renderer symlink in a fresh volatile work directory. It refuses existing regular DLLs, foreign links, linked ancestors, hardlinks, changed identities and hash/size mismatches.

Passive presentation uses the existing numeric `pd2-present.jsonl` protocol. Independent status uses fixed-basename `pd2-gles2.jsonl`: `CREATE_NEW`, read sharing only, maximum 128 records / 32768 bytes; the last record is reserved for fatal evidence. No paths, driver strings, shaders, pixels or player data are logged.

The selector's `--watch --work WORK --pid PID` emits `renderer_gl2` events and drains the final file after the observed wrapper exits. It never terminates the process. `--result --work WORK` returns:

- `86`: an authoritative failed renderer record;
- `0`: a successful renderer frame **and** independent OpenGL first-presentation evidence;
- `1`: missing, invalid or incomplete evidence.

Every decoded event has `event=renderer_gl2`, `stage`, `status`, `code`, `gl_major`, `gl_minor`, `bpp`, `width`, `height`, `render_width`, `render_height`. Source and output dimensions are separate. Stages: context/api/shader/texture/validation/frame/release/policy. Codes: 0 ready; 1 context, 2 API missing, 3 version, 4 vertex shader, 5 fragment shader, 6 link, 7 texture, 8 synthetic validation, 9 upload, 10 draw, 11 swap, 12 format, 13 wait, 14 release, 15 forbidden fallback, 16 GL state.

API presentation is not physical display visibility or simulation FPS.

## Provenance and validation

[Manifest](<manifest.json>), [source patch](<source.patch>) and [license notices](<LICENSE.txt>) accompany the independently pinned [DLL](<ddraw.dll>). Build: MSVC 14.44.35207 / SDK 10.0.22621.0, Release Win32, static CRT, `/Brepro` and fixed PDB alternate path, authenticated offline upstream archive.

Native Windows tests exercised real WGL shader compilation, draw and synthetic pixel validation for indexed8/RGB565/RGB555/BGRA32, palette-only recoloring, NPOT source scaling and resource rebuild. Injected mock failures exercised the pipeline failure paths; writer tests cover caps/CREATE_NEW refusal; a threaded test checks 10000 coherent palette snapshots. Python tests cover selection, schema, watch/result, artifact pins and fail-closed source contracts.

The actual built DLL also passed a windowed native DirectDraw lifecycle smoke: the paletted RGB helper completed all three colors, OpenGL first-presentation was captured, normal renderer release completed and the host exited with code 0. This caught and fixed an unnecessary main-thread WGL unbind during teardown. The test does not change the physical display mode. Reproduce from the project root:

```text
python -B tools/build_gles2_renderer.py --test
python -B tools/gles2_smoke.py
python -B tests/test_gles2_renderer.py -v
```

**No R36S/GL4ES runtime validation or FPS improvement is claimed.** Integration and device acceptance remain necessary. This module does not replace Wine, Box86, audio, game data or system drivers.
