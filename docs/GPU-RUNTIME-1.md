# GPU Runtime 1 — R36S / dArkOSen

This is a new renderer implementation, not just another configuration matrix. It is not yet fully confirmed on physical R36S hardware and does not guarantee 20+ FPS.

## Installation and Execution

1. Extract the update package into the existing `ports` directory, overwriting port files. Do not delete your prefix, configuration, game files, or saves.
2. Back up your saves; use a throwaway character for the first test run. An unrecoverable GPU error will terminate the game process, which can risk losing unsaved progress. Launch **Project Diablo 2 - GPU**. Do not re-run A–F diagnostics. The first launch still runs safe Wine initialization; it may take a few minutes.
3. Play normally in a familiar location with audio enabled, including brief combat encounters. Exit normally to Ports and re-launch GPU mode without rebooting the console.
4. If GPU mode fails to start, return to the main production launcher / Performance GDI. Do not wipe the prefix. A GPU error no longer silently falls back to an invisible GDI presentation.

There is no on-screen FPS HUD. Measurements are automatically recorded in the safe log; the presentation counter tracks swap calls and is not a game logic simulation counter nor a guarantee of physical LCD frame output.

## Changes Overview

- Standalone `cnc-ddraw` build featuring a GL2/GLSL 1.10 backend via GL4ES → GLES2/KMS. No GL3/core profiles, multi-pass overhead, error masking, or silent fallback.
- For 8-bit surfaces, color indexing and palette lookups are performed directly on the GPU. Updating the palette does not require converting the entire surface on the CPU. RGB565, RGB555, and BGRA32 surfaces are supported as well.
- Fast synthetic validation of shaders and textures during initialization. No frame reads from the game surface and no forced 30 repaints of unchanged buffers.
- Audio remains ALSA time32/rk817. A companion library built from the same tree adds bounded logging of real PCM operations without audio recording or global changes to ALSA priority/buffers.
- CPU tracking is scoped to verified Wine processes, preserving tracking across process reparenting. `verified_subset` does not imply complete coverage; `partial/unavailable` does not denote zero load.

## Box86 A35 is Independent

The GPU profile defaults to the standard Box86 build to decouple emulator behavior from renderer changes. An optional build from the same commit, tuned specifically for Cortex-A35 without assuming optional CRC/crypto instructions, can be chosen for an individual session:

```bash
PD2_BOX_VARIANT=a35 bash "Project Diablo 2 - GPU.sh"
```

A35 can also be paired with the existing GDI launcher. There is no extra test launcher script. The options `stock|a35` and `stock|gles2` represent a bounded enum, not filesystem library paths. Neither Wine nor system drivers have been replaced. A35 is not a promise of higher FPS; it has a known upstream limitation in time64 conversion, documented in the [A35 variant README](compat/box86-a35/README.md). It is strictly intended for the pinned Wine runtime.

## Log Export

From the port directory:

```bash
python3 scripts/safe_log.py export --dir logs --manifest runtime-manifest.json
```

Copy `logs/diagnostic-export.zip` to your PC before running a subsequent export. Up to 10 sessions are retained. A log from a standard GPU run along with your observations (whether video displayed, fluidity in familiar areas, whether audio stuttered, and if a second consecutive launch worked) is sufficient.

## Reading the Results

`renderer_gl2` displays actual stages, bpp, surface dimensions from the engine, and output frame dimensions. `render_status:first_present` with `backend:opengl` signifies a successful `SwapBuffers` API call, not physical display on the LCD. Resizing the window does not automatically downscale game rendering resolution. The previously selected resolution remains active; comparisons require identical scenes and settings.

`audio_pcm` tracks public ALSA API calls within the final Wine runtime process tree. Parameters describe the PCM client, not necessarily the hardware device behind `plug`. `recover_epipe_calls` is not an index of distinct audible gaps. The absence of an active stream (`no_stream`) denotes no observed output, not functional audio. No artificial delay has been injected to mask buffer stuttering.

In earlier logs, the OpenGL profile fell back to GDI. This package resolves that specific fallback path, but physical console testing is necessary to confirm driver stability and real-world performance.
