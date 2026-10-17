# Optional immediate FPS renderer

This **opt-in** Win32 `ddraw.dll` is built from FunkyFr3sh/cnc-ddraw **v7.1.0.0**, with the MIT-licensed renderer-only HUD patch. It does not replace or change `../cnc-ddraw/ddraw.dll`. The launcher owns ON/OFF DLL selection; this directory alone does not wire the launcher.

When selected, every rendered game frame includes `FPS: --` at the top left until the first valid sampling window (at least 0.5 seconds after the first completed presentation). It then shows rounded **completed renderer presentations / elapsed wall-clock time**, measured with QueryPerformanceCounter. This is renderer FPS, not simulation ticks, requested cap, monitor refresh, or a guessed value. Identical frames presented again count as presentations. Sampling resets on renderer restart, window/primary/mode changes or output resize. No hotkey, text entry, chat, helper process, new input hook, game-data inspection, ReadProcessMemory, or HUD log output is involved. Existing upstream compatibility hooks remain unchanged.

## Implementation

A shared 3x5 bitmap font (2x scale) draws a small black-backed HUD onto a **renderer-private snapshot**, used as input to GDI blitting, OpenGL texture upload, and D3D9 texture upload. It never changes the game surface's pixel storage or pointer, and never changes a palette. This avoids the concurrent-game-blit corruption that save/restore directly on a game's primary surface could cause. Upstream global/surface locking is retained unchanged. Games that ignore surface locks can still tear during the snapshot, as with upstream rendering, but HUD processing cannot overwrite their writes.

8-bit output uses the actual palette's darkest/lightest existing entries; 16-bit RGB555/RGB565 and 32-bit output use black/white pixels. A degenerate all-one-color palette necessarily cannot display contrasting text. Normal game palettes are supported. The small fixed HUD is clipped safely to small surfaces. Existing upstream crop/upscale behavior applies to the source image and may crop the HUD in special nonstandard modes.

One reusable allocation and one surface copy per rendered frame are added (approximately 300 KiB for 640x480x8). The HUD changes independently of game damage, so GPU uploads are requested on every rendered frame. No per-frame allocation, GDI font/DC creation, file I/O, or logging. Allocation failure safely falls back to the untouched upstream pixels without a HUD. Buffer capacity is reset/reclaimed on renderer/mode changes; at most one snapshot is retained per initialized backend until process exit/restart.

## Build and tests

From the project root on Windows:

```text
python tools/build_fps_renderer.py --test-pe
```

Requires Python 3, Visual Studio 2022 Community MSVC **14.44.35207**, Windows SDK **10.0.22621.0**, x64-to-x86 tools. Set `FPS_RENDERER_VS` to another VS2022 installation root if needed. Upstream Release/Win32 project uses static CRT `/MT`. Compiler and linker use `/Brepro`; fixed build version strings avoid checkout state. Source is downloaded from the pinned codeload URL and checked against its SHA256 before patching. Build directories are fresh and owned under `.state/fps-renderer`; the tool never deletes unknown paths or writes the default renderer.

`--test` builds/runs the native deterministic core suite only. `--test-pe` additionally opens a synthetic DirectDraw/GDI window (no game required), creates a shuffled 8-bit palette, renders at about 20 FPS, reads actual window output pixels to check the immediate unknown-value HUD and subsequent numeric measurement, and checks the original primary remains unchanged. MSVC process tracking or desktop capture may require a non-confined Windows shell; such failures must not be reported as successful tests.

The core tests cover controlled 50/20 FPS samples, warmup, clock/reset handling, exact glyph pixels, palette-index selection, 8/16/32-bit output, clipping, padded pitch and byte-exact restoration for the standalone core. The renderer itself uses only private snapshot writes, not restoration of game memory.

`manifest.json` records artifact size/SHA256, upstream archive provenance, build-input hashes and the tests actually completed. `source.patch` contains the minimal upstream renderer diff; the two HUD headers and reproducible builder are under `tools/`. `LICENSE.txt` retains upstream's MIT notice. The full pinned source remains downloadable from the manifest URL.

## Verification limits

Native Windows tests do **not** establish physical R36S/Wine/Box86 behavior, visual legibility in every game mode, hardware GPU performance, or OpenGL/D3D9 runtime correctness. Physical R36S hardware is unavailable here. GPU paths share the tested drawing/sampling code and are build-checked; only a successful backend-specific runtime test would establish their runtime behavior. Consult the manifest and build/test report for actual results rather than interpreting test-source presence as a pass.
