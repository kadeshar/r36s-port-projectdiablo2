# Synthetic graphics layers (MIT)

These independent probes use only generated solid red, green, blue frames,
640x480, approximately two seconds per frame; never game data. They do not edit
configuration or install libraries. Do not run alongside a game session.

## Build and tests (repository root)

```
python tools/build_graphics_layers.py --target all
python -m unittest discover -s tests -p test_graphics_layers.py -v
```

The existing `pd2-alsa-native-builder` image must already be present and Docker
running; no pull/package installation is performed. ARM hard-float links only
libdl and libc (no SDL, X11 or GL development packages). Win32 requires VS2022
Community MSVC 14.44 and SDK 10.0.22621.0 (same setup as build_fps_renderer);
`FPS_RENDERER_VS` can select its installation. Individual build targets are
`--target armhf` and `--target win32`. Outputs are stripped ARM ELF and static-CRT
Win32 PE; deterministic flags are `--build-id=none`/`-fno-ident` and `/Brepro`.
`manifest.json` pins input and output SHA256 hashes and build commands. A missing
artifact entry means that target has not been built, NOT a passing test.

## Parent launch contract

- ARM: `graphics-layers.armhf --mode sdl` or `--mode glx`.
- SDL requires `CRUSTY_LIBSDL` to point to the real SDL2 shared library, and
  loads its API directly from that handle (not preload wrapper symbols). It
  requests an OpenGL ES 2.0 context with a double-buffered window.
- GLX opens `libX11.so.6` and ordinary `libGL.so.1`, intentionally retaining
  the parent's Crusty preload environment. It selects an RGBA/double-buffered
  visual and creates an ordinary GLX context, not an EGL shortcut.
- Win32: `graphics-layers.exe`, launched by the parent through Wine with current
  directory set to the chosen isolated renderer session (which must contain
  `ddraw.dll`). It calls `LoadLibraryA("ddraw.dll")`, verifies the resolved path
  is exactly that current-directory copy, and never links ddraw.lib. Uses an
  8-bit paletted primary surface, exclusive synthetic mode, then restores mode
  and cooperative level on normal/error cleanup. No assets/config writes.
- Parent MUST impose a 15-second deadline on the entire process group/Wine
  session including driver initialization and cleanup; calls can hang inside
  external libraries. The helpers deliberately do not pretend their internal
  sleeps can enforce a driver-call deadline.
- Consume only stdout lines beginning `PD2_EVENT ` with the strict schema below.
  Drop stderr/other stdout: external loaders/drivers may produce raw strings.
  Helper-owned output is at most 7 lines, less than 4096 bytes. Parent still
  bounds ALL captured external output to <=16KB and validates every field.

Each line contains fixed JSON fields, no raw renderer/backend/library/error
strings or paths:

| Key | Allowed values |
| --- | --- |
| event | `graphics_layer` |
| schema | integer `1` |
| probe | `sdl`, `glx`, `ddraw` |
| stage | `start`, `library`, `context`, `frame`, `done`, `error` |
| status | `ok`, `failed` |
| backend | `unknown`, `x11`, `wayland`, `kmsdrm`, `directfb`, `dummy`, `windows`, `other` |
| renderer | `unknown`, `gpu`, `software` |
| frame | integer 0..3; 1=red, 2=green, 3=blue; 0=non-frame |
| code | integer 0..20; defined codes below |

Return/diagnostic codes: 0 success; 1 library missing/unloadable (SDL includes
missing CRUSTY_LIBSDL, Win includes wrong resolved path); 2 required symbol or GL
entry missing; 3 SDL video init; 4 SDL context attributes; 5 window; 6 GL context
creation/current binding; 7 X display; 8 GLX visual; 9 Win current-directory
lookup; 10 DirectDrawCreate; 11 cooperative level; 12 display mode;
13 primary surface; 14 palette; 15 color fill; 16..19 reserved; 20 invalid CLI.
Library stage means required symbols resolved, not driver initialization.
Backend `unknown` before identification, `other` for unlisted SDL driver;
DirectDraw always `windows` (API family, not host detection).

`renderer` classifies GL_RENDERER internally: known software signatures win,
then known GPU-driver families, otherwise unknown. DirectDraw is always unknown.
A `gpu` label is a driver-string classification, NOT proof of hardware rendering.
A frame event means swap/fill API completed; it does NOT establish visible panel
output, correct colors or scanout. SDL/GLX swap APIs have no success return.
Host compile/unit tests are NOT R36S GPU validation. Physical observation and
launch-level timeout/error handling are owned by the parent integration.
