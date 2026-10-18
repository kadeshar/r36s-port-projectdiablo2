# MEMORY.md — Development History and Knowledge Base for Project Diablo 2 on R36S

This document records the detailed history of engineering work, architectural analysis, diagnosed issues, and implemented solutions throughout the development and optimization of the **Project Diablo 2** port for the **R36S** handheld console (ArkOS / Rockchip RK3326).

---

## GDI compositor startup regression — session 20261018T191920Z-10605

- User reports the earlier main-launcher rollback did not help. Attached [session log](<C:/Users/kadeshar/.dsh/attachments/v1/files/96/96b969be60719f4a9c150b323ef195261738a4bd7a1252556e6469bee9fba6f7/pd2-session-20261018T191920Z-10605.jsonl>) shows GDI, native providers ready, seatd ready, DRM/GL modules and EGL/GL initialized; Weston exits 1 before X11 readiness, menu or Wine. `compositor_failed`, then runtime/shutdown 2. Logger omitted 56 lines; exact native fatal message is unavailable. CRLF is not the explanation for this observed run: the launcher and adapter both executed.
- Remaining production startup delta from the conversion: shared adapter changed `CRUSTY_BLOCK_INPUT=0` to global `1`. Restore `0` for production/legacy profiles; enable `1` only inside the explicit `crusty_glx_gl4es` branch. This is a targeted rollback of an unintended default change, not a hardware-confirmed diagnosis of Weston's fatal error.
- Added regression executing actual adapter export/profile selection with inherited `CRUSTY_BLOCK_INPUT=1`: GDI and legacy OpenGL must reset to `0`; explicit GLX must set `1`. Test failed for both legacy paths before correction. Synthetic environment tests do not establish working hardware startup.
- Main launcher left untouched in this fix. Replace only [weston-session.sh](<sdcard/ports/projectdiablo2/scripts/weston-session.sh>) on the SD card; no prefix/config/save reset, no ZIP. Confirm startup on R36S and provide the next log if it still fails.
- Validation: 34 Linux tests passed (PortMaster GLX 12, graphics providers 10, OpenGL entry 2, GPU runtime 10). These cover profile environment isolation and existing synthetic regressions, not real-device compositor startup.
- User instruction persisted in [AGENTS.md](<AGENTS.md>): no main-launcher modifications without explicit instruction naming that launcher; experiments must not alter production defaults via shared code.

## PortMaster adaptation — implementation (historical; host changes subsequently rolled back)

- Implementing [conversion plan](<plan/portmaster_convert.md>) directly in `sdcard/ports/`; no update ZIP. Existing local audio changes preserved.
- Baseline after switching this session to full access: 37 layout tests, 2 OpenGL entry tests passed; GPU runtime: 2 passed, 8 Linux-only tests skipped on Windows. Earlier workspace-confined layout attempts failed creating fixtures with `WinError 5`; one authorized Windows permissions repair did not resolve confined execution. Full access removed that test-execution obstacle.
- Shared host cleanup resets both console TTYs only after a session started Weston, captures service activity before PortMaster hooks and queues bounded nonblocking `restart` only for previously active `oga_events.service`, and keeps original exit status. Service restoration stays outside private `/run`; adapter handles post-compositor console cleanup, host handles forced-exit fallback. All wrappers delegate to the main launcher.
- Weston Crusty input blocking enabled. Box86 gains stable SDL GUIDs, optional-library handling and symbol diagnostics; production GDI/audio defaults preserved. New GLX path uses `SAFEFLAGS=1`, `CALLRET=0`; legacy risky test profiles remain separate, unchanged.
- Separate PortMaster GLX experiment reuses pinned Westonpack ARMHF Crusty GLX + GL4ES providers, session-only OpenGL configuration, no headless startup menu, no new runtime downloads. Required provider/library validation precedes headless/noop. This is not evidence of working scanout or better FPS on R36S.
- Inspected both wrapper binaries directly from the existing SquashFS using `unsquashfs -cat`: Crusty GLX and GL4ES GLX pass libraries are ELF32 little-endian ARM ET_DYN with flags `0x5000400` (hard-float). No runtime binaries changed. This verifies the new ABI gate against the bundled wrappers, not target-device providers or GPU behavior.
- Final regression (WSL/Ubuntu, Python 3.12.3): `python3 -m unittest discover -s tests` — **727 tests, OK, 4 skipped**, 466.641 s. Focused host lifecycle: 8 OK; PortMaster shell integration: 3 OK (including existing macro coverage); isolated GLX: 11 OK. Earlier Windows full pass: 713 tests, 146 skipped, before final test additions.
- All 23 shipped Bash entry/helper scripts pass `bash -n`; release allowlist validates 101 files including the new launcher. SHA-256 and size verification passes for all 4 runtime artifacts; root and payload runtime manifests agree. `git diff --check` passes. No release ZIP built, no physical SD/device deployment performed.
- Hardware acceptance still required: game image, controls, audio, quit/interruption cleanup and restored brightness/volume/suspend keys. GDI remains rollback.

## Dmix follow-up — session 20261018T180608Z-62502

- User reports that the next test after the startup-validation fix also did not help. Problem remains unresolved; no further diagnosis requested.
- Attached log: [pd2-session-20261018T180608Z-62502.jsonl](<C:/Users/kadeshar/.dsh/attachments/v1/files/1d/1d5264b229ae2686ecac2aa796db47e2c42ebf7abd8c99289c659e7978cc7153/pd2-session-20261018T180608Z-62502.jsonl>), SHA-256 `1d5264b229ae2686ecac2aa796db47e2c42ebf7abd8c99289c659e7978cc7153`. Log not analyzed in this follow-up; record reflects user feedback only.

## Dmix startup regression — session 20261018T174656Z-35723

- Attached session ends with `invalid_profile` immediately after `audio_route_profile=dmix160`; no game playback occurs.
- Cause: [`Audio Dmix launcher`](<sdcard/ports/Project Diablo 2 - Audio Dmix.sh>) selects DirectSound `wine`, while [`run-game.sh`](<sdcard/ports/projectdiablo2/scripts/run-game.sh>) required `off` for variant `dmix`.
- Fix: accept `wine` or legacy `off` for dmix; retain SDL dummy and dmix route constraints. Production defaults unchanged.
- Regression: real Dmix wrapper → real run-game validation with synthetic Wine; verifies game execution, 160000-us requested config and DirectSound restoration. Separate negative combinations and legacy route-only coverage. New wrapper test reproduced the exact `invalid_profile` before the fix.
- Validation (WSL/Ubuntu): 78 shell integration tests and 96 audio tests passed; `bash -n` on run-game and `git diff --check` passed.
- Deployment: replace only `ports/projectdiablo2/scripts/run-game.sh` for this startup fix; no prefix/save reset. Hardware startup and audio quality remain unverified.

## 1. Project Genesis and Architectural Verification

### Initial User Assumptions:
- The user observed that *N.O.V.A. 3* (`nova3-native-arm`) ran smoothly on the R36S as an Android port, whereas the existing *Project Diablo 2* port was running very slowly (only 10–15 FPS).
- A question arose: could the *Winlator* Android emulator be ported to the R36S to run PD2 with better performance?

### Technical Analysis and Conclusion:
- **N.O.V.A. 3 vs Winlator:**
  - `nova3` is a native ARM binary (`libNOVA3_neon.so`) executed via a lightweight bionic loader with direct OpenGL ES and SDL2 calls on Linux (0% CPU emulation).
  - *Winlator* on Android is a Java/Kotlin app that creates a PRoot container running an Ubuntu Linux distribution containing Wine + Box86/Box64 + VirGL/Mesa.
- **Conclusion:** The R36S already runs a native Linux OS (ArkOS). Porting an Android application (APK) would require emulating Android on Linux just to run Linux in a container on Linux — creating severe CPU overhead and catastrophic performance degradation. The only architecturally sound and fastest approach is running **Box86 + Wine 8.0 x86 + Westonpack compositor** directly on native ArkOS.

---

## 2. Phase 1: Controller Diagnosis and Fixes (0.1.12 → 0.1.13)

### Symptoms:
- The port did not respond to auxiliary buttons; pausing the game, opening menus, or using analog stick clicks (L3/R3) was impossible.
- An integrated XInput probe revealed that 5 key physical inputs were completely unmapped.

### Investigation and Solution:
- Kernel diagnostic tools captured raw `evdev` events directly from the built-in R36S controller:
  - Select: `0x2C0`
  - Start: `0x2C1`
  - L3 (left analog click): `0x2C2`
  - R3 (right analog click): `0x2C3`
  - Menu (FN button): `0x2C4`
- Updated the [`xbox_mapper.py`](sdcard/ports/projectdiablo2/scripts/xbox_mapper.py) translator, which creates a virtual Microsoft Xbox 360 controller in `uinput` userspace.
- All 17 physical inputs passed 100% verification.

---

## 3. Phase 2: Missing Audio Investigation and the ENOTTY Error (0.1.14)

### Symptoms:
- Complete silence in game. In the Diablo II options menu, the *Sound Settings* tab was completely grayed out.
- Wine reported 0 available audio endpoints.

### System-level Investigation:
1. Checked the Linux kernel layer: the Rockchip RK817 sound codec (`/dev/snd/pcmC0D0p` and `/dev/snd/controlC0`) was present, permissions were correct, and native ALSA playback worked.
2. Enabled `WINEDEBUG=+alsa`. Wine attempted to open the ALSA node, but immediately failed with a driver initialization error in `winealsa.drv`.
3. Ran an ARM-compiled `strace` to inspect syscalls:
   - Calling `ioctl(fd, SNDRV_PCM_IOCTL_SYNC_PTR, ptr)` returned `-25` (`ENOTTY` – Inappropriate ioctl for device).

### Root Cause:
- The R36S kernel is a 64-bit Linux (AArch64). The ALSA driver in this kernel expects a 32-bit time type (`time_t = 4 bytes`) for 32-bit processes (ARMHF compatibility), resulting in `sizeof(snd_pcm_sync_ptr) = 132 bytes` (`ioctl 0xC0844123`).
- Modern Linux distributions (such as newer Debian/Ubuntu builds) transitioned to **time64** (addressing the Year 2038 problem on 32-bit systems). Consequently, standard `libasound.so.2` dispatched a 136-byte structure (`ioctl 0xC0884123`). The 64-bit Rockchip kernel rejected this unsupported ioctl with `-25 ENOTTY`.

### Solution:
- Compiled `alsa-lib 1.2.8` from source retaining 32-bit `time_t` (without time64 flags).
- Placed the library in `compat/alsa-legacy-armhf/libasound.so.2`, and [`audio_compat.py`](sdcard/ports/projectdiablo2/scripts/audio_compat.py) preloads it into RAM before starting Wine. Sound began working immediately.

---

## 4. Phase 3: Start Menu Flickering Issue (0.1.15 → 0.1.16)

### Symptoms:
- The Diablo II styled start menu for resolution and FPS selection flickered continuously on every frame, making text unreadable.

### Cause and Solution:
- The X11 menu script was redrawing the entire screen in an unconstrained loop without checking if any button state had changed.
- Implemented double-buffering in memory and an event-driven redraw mechanism: the frame is rendered once, and redrawn only when a D-Pad navigation event changes the selected item.

---

## 5. Phase 4: Overcoming 10–15 FPS and Black Screen Syndrome

### Baseline:
- The game ran correctly in GDI mode with functional video and audio, but delivered only 10–15 FPS, preventing enjoyable gameplay.

### Attempted OpenGL Acceleration:
- Enabled the `PD2_PERFORMANCE=opengl` profile in `Project Diablo 2.sh` for testing.
- **Symptom:** Upon launching the game, **the screen went completely black, but background music and combat sounds were clearly audible.**

### Investigation and Discovery of Black Screen Cause:
1. **Weston session script analysis ([`weston-session.sh`](sdcard/ports/projectdiablo2/scripts/weston-session.sh)):**
   - Found the following block:
     ```bash
     weston_args=(-B drm --drm-device card0 --renderer=gl)
     if [[ "$PD2_PROFILE" == opengl ]]; then
       weston_args=(-B headless --renderer=noop);preload=;backendlib=
       export PD2_NATIVE_LIBS="$W/lib_armhf/graphics/gl4es_glxpass:$W/lib_armhf/graphics/crusty_glx:$PD2_NATIVE_LIBS"
       export PD2_NATIVE_PRELOAD="$W/lib_armhf/graphics/crusty_glx/libcrusty.so"
       export CRUSTY_GL4ES=1
     fi
     ```
   - When the `opengl` profile was selected, Weston started in **`headless --renderer=noop`** mode.
   - This mode **never opens `/dev/dri/card0` and drops all rendered frames without sending them to the LCD panel!**
   - Wine and `Game.exe` executed normally in the background, Box86 handled game logic, and audio played directly to speakers via ALSA, but video frames were discarded in memory (noop).
2. **Mali Driver Limitations on ArkOS:**
   - The Mali-G31 GPU driver on ArkOS is 64-bit (AArch64).
   - For 32-bit ARMHF applications, there is no GLX driver with direct KMS scanout. The Weston desktop compositor running in DRM mode (`-B drm --renderer=gl`) is the **only functional display pipeline** capable of showing windows on the physical LCD.
3. **`glGetTexImage` Failure in `cnc-ddraw`:**
   - In `render_ogl.c` of official `cnc-ddraw v7.1.0.0`, an initialization selftest called `glGetTexImage`.
   - On GLES2/GL4ES drivers, this call failed, causing cnc-ddraw to silently fall back to software CPU rendering (GDI).
   - Created a build script [`tools/build_cnc_ddraw_ogl.py`](tools/build_cnc_ddraw_ogl.py) to compile `ddraw.dll` with destructive texture tests removed.
4. **Production Stability Architecture:**
   - Adopted [`Project Diablo 2.sh`](sdcard/ports/Project%20Diablo%202.sh) operating on the **GDI** profile with the DRM compositor (`-B drm`) as the **official, stable production launcher**.
   - Separated experimental OpenGL/GPU workflows into [`Project Diablo 2 - GPU.sh`](sdcard/ports/Project%20Diablo%202%20-%20GPU.sh) with a dedicated GLES2 palette shader.

---

## 6. Phase 5: Initial Audio Stuttering Investigation

### Symptoms Reported by User:
- *"Audio plays, but it stutters severely and ruins gameplay. Could it be duplicated or conflicted due to the workaround?"*

### Initial Hypotheses and Tweaks:
1. **`SDL_AUDIODRIVER` Conflict:** Standard launches defaulted to `SDL_AUDIODRIVER=alsa`, which competed with `winealsa.drv` for `/dev/snd/pcmC0D0p`. Switching to `SDL_AUDIODRIVER=dummy` successfully gave Wine exclusive ALSA access.
2. **DirectSound Registry Tuning:** Tweaked `HelBuflen` and `MaxHardwareChannels` in registry. However, later code inspection showed Wine 8.0 default `HelBuflen` is 65536 bytes (~370 ms), so lowering to 8192 actually tightened the buffer, and `HelBuflen` affects only the DirectSound software emulation buffer, not the kernel ALSA buffer.
3. **Outcome:** While SDL contention was eliminated, stuttering and repeating audio chunks ("echo") remained audible during gameplay.

---

## 7. Phase 6: Performance Optimization (CPU and Memory)

To address Cortex-A35 execution bottlenecks:
1. **Box86 Dynarec Tuning:**
   - `BOX86_DYNAREC_BIGBLOCK=2`: Translates larger basic blocks of game code.
   - `BOX86_DYNAREC_FORWARD=256`: Extends forward jump lookahead.
   - `BOX86_DYNAREC_FASTROUND=1`: Utilizes hardware ARM rounding instructions.
   - `BOX86_DYNAREC_FASTNAN=1`: Fast IEEE NaN handling.
   - `BOX86_DYNAREC_SAFEFLAGS=1`: Preserved safe flags (mandatory for Diablo II JIT stability).
   - `BOX86_DYNAREC_X87DOUBLE=0`: Employs hardware NEON instead of software 80-bit x87 emulation.
2. **RAM and Swap Protection:**
   - Applied `sysctl -w vm.swappiness=10` and `sync; echo 3 > /proc/sys/vm/drop_caches` to avoid microSD swap thrashing on 1 GB RAM.

---

## 8. Phase 7: Audio Telemetry, Route De-bunking, and Dmix Hardening (0.1.18+)

### In-Depth Investigation:
1. **Telemetry Infrastructure Implemented:**
   - Preloaded PCM observer library (`audio_metrics`) capturing real-time ALSA API calls: `period_frames`, `buffer_frames`, `write_calls`, `short_writes`, `recover_calls`, `epipe_results`, `eagain_results`.
   - Kernel hardware PCM telemetry (`audio_hardware_pcm`): samples `/proc/asound/card0/pcm0p/sub0/{hw_params,sw_params,status}` for actual DMA hardware parameters, delay, and pointer offsets.
   - System resource sampler (`metrics`): periodic CPU%, RAM, swap, and temperature logging.
   - Sustained playback gate: requires >=3 consecutive snapshots with audio frames over >=2.0s, distinguishing active gameplay from short 1.5s probes.
2. **"Buffer 160ms" Route De-bunked:**
   - Source inspection of ALSA 1.2.8 (`pcm_plug.c:1293-1298`, `pcm.c:7885`) revealed that `type plug` slave definition (`snd_pcm_slave_conf`) only parses `format`, `channels`, and `rate`.
   - Placing `period_time`/`buffer_time` inside `pcm_slave` triggered `-EINVAL: Unknown field period_time`.
   - `snd_pcm_open("default")` was failing and Wine silently fell back to system default ALSA. All historical "Buffer 160ms" tests were running on stock ALSA configuration!
   - The invalid Buffer launcher was retired and removed.
3. **Dmix Flow Control and Hardening:**
   - Dmix telemetry proved **0 EPIPE** across 125 seconds of gameplay with 4,295 successful writes.
   - The 508 `eagain_results` was non-blocking flow control from Wine when the dmix ring buffer was full, not underruns.
   - Hardened dmix IPC configuration with `ipc_key_add_uid true` and `ipc_perm 0600` to prevent multi-user collisions.
5. **DirectSound Headroom vs Persistent Prefix:**
   - Log 20261018T163650Z confirmed ALSA received 11,118 writes over 113s with 0 EPIPE and 0 lost updates.
   - User confirmed Environmental Effects is locked and OFF, and stutter/echo worsens during combat spells and occurs during Akara's voice.
   - Analysis: persistent wineprefix retaining historical `HelBuflen=8192` (~46 ms) causes DirectSound circular buffer wrapping on any frame taking longer than 46 ms (<22 FPS). Updated Dmix launcher to enforce `PD2_AUDIO_DSOUND=wine` (`HelBuflen=65536`, ~371 ms headroom) with automatic backup and restore.
   - Fixed `PD2_METRICS` preservation in `Project Diablo 2.sh` and prioritized RK817 in `audio_hardware_pcm` with `card` and `device` tracking.

---

## 9. Current Status Summary

- **Display:** 100% stable through the GDI profile with the DRM compositor ([`Project Diablo 2.sh`](sdcard/ports/Project%20Diablo%202.sh)) and the alternative GPU shader profile ([`Project Diablo 2 - GPU.sh`](sdcard/ports/Project%20Diablo%202%20-%20GPU.sh)).
- **Controls:** Complete support for all 17 physical R36S inputs via the virtual Xbox 360 controller.
- **Audio:** Dmix software mixing with hardened IPC, exclusive SDL dummy driver, full PCM/hardware/system telemetry, DirectSound buffer expansion (`HelBuflen=65536`) protecting against producer starvation; hardware test protocol defined in [`docs/AUDIO-FIX-1.md`](docs/AUDIO-FIX-1.md). Buffer route debunked and removed.
- **Performance:** Optimized Box86 Dynarec flags and memory thrashing prevention.
- **Testing:** Comprehensive regression test suite validating layouts, configurations, telemetry, and shell contracts.
