# Independent presentation diagnostics

Optional cnc-ddraw 7.1.0.0 Win32 static-CRT DLL. This is neither the default DLL nor the FPS HUD DLL. Select with `scripts/present_renderer.py --port PORT --work VOLATILE_WORK` before game startup, **instead of** the FPS selector. Selection authenticates a hardcoded exact SHA-256/size and replaces only the original normal-renderer symlink in `VOLATILE_WORK/ProjectD2`. It refuses regular files and FPS-renderer links. Caller must own a quiescent work tree; this is not a concurrent attacker-writable-directory API.

## Fixed numeric wire format

Windows current directory must be a fresh, session-volatile work directory. The DLL uses only the fixed basename `pd2-present.jsonl`, opens it with `CREATE_NEW`, and refuses existing files/links. No filename option, environment override, network, raw strings, screenshot, framebuffer snapshot or instrumentation pixel modification. Upstream's fallback warning HUD is removed. Ordinary upstream rendering behavior otherwise remains intact.

Every line contains exactly these integer-valued fields:

- `event`: 1 = `render_sample`; 2 = backend-entry `render_status`; 3 = first-success `render_status`.
- `backend`: 1 = GDI; 2 = OpenGL. There is no Direct3D instrumentation.
- `frames`: successful presentation API calls in this interval. GDI requires nonzero/non-GDI_ERROR return from StretchDIBits/SetDIBitsToDevice, or a successful Battle.net FillRect. OpenGL requires successful SwapBuffers. Repeated or unchanged frames still count; this is **not game simulation FPS**.
- `duration_ms`: monotonic QPC elapsed interval, at least 1000 for samples; no catch-up bursts.
- `width`, `height`: render-target dimensions, integers 1..65535.

Status event 2 has `frames=0,duration_ms=0`, occurs at backend entry only after `IsWindow(g_ddraw.hwnd)`, and proves **a valid window handle/backend entry**, not a successful presentation or physical display. OpenGL context setup may subsequently fall back to GDI; each backend gets its own entry record. Samples identify the actual presentation path.

Event 3 has `frames=1,duration_ms=0` and is emitted immediately on the first successful presentation API call, **once per backend per process** (not reset on backend restarts). It confirms API success even if the game then idles before a one-second sample. The parent maps it to `render_status` with `status=first_present`. It does not force extra rendering, prove changed pixels, or confirm a physical display. That presentation remains counted normally in the next interval sample; event 3 is not an extra frame.

Sampling is render-loop driven; a completely blocked or stopped loop emits no further samples. A running loop with failed calls can emit zero-frame samples. There is no background timer or GUI requirement for tests. Backend restarts reset their sample interval but **never reset the process-wide byte budget**. Logging stops permanently on any write failure or before the next line would exceed **262144 bytes**; no rotation, truncation, retries or unbounded append. A single shared nonblocking gate serializes both backends. The output handle permits readers but denies other Windows writers/deleters while open. File boundedness assumes the caller's private session directory, as with selector layout.

The selector CLI writes only `{"status":0}` (ready) or `{"status":1}` (unavailable) and matching exit code. The parent owns mapping numeric wire enums into its diagnostic event allowlist. No changes to main launch scripts or logging policy are included here.

## Build and test (no GUI)

From the project root:

```text
python tools/build_present_renderer.py --test
python -m unittest discover -s tests -p test_present_renderer.py -v
```

Requires existing authenticated `.state/fps-renderer/upstream.zip`, VS2022 Community MSVC 14.44.35207 and Windows SDK 10.0.22621.0. Build is offline and uses a fresh `.state/present-renderer/build-*` directory. `--test` runs console native tests including QPC interval arithmetic, numeric formatting, backend enum rejection, failed-presentation accounting, real fixed-file writer, process-wide budget exhaustion and refusal to reopen an existing file. Python tests cover artifact/manifest pins and selector fail-closed behavior; symlink tests skip on Windows without symlink privilege. No game, Wine or physical R36S test is claimed.

`source.patch` includes instrumentation header and build project changes; `LICENSE.txt` retains upstream MIT, Detours and LodePNG notices. `manifest.json` pins archive, DLL, build inputs and patch. Rebuilds must match the selector's hardcoded pin before deployment; the selector never trusts manifest hashes dynamically.
