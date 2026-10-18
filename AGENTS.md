# AGENTS.md — Project Diablo 2 Port for R36S Console

This document serves as an architectural, technical, and operational knowledge base for AI agents and developers working on the **Project Diablo 2 (Diablo II: Lord of Destruction)** port for the **R36S** retro handheld console.

---

## 1. Hardware Specification of Target Device (R36S)

The R36S console is a budget handheld based on the Rockchip RK3326 platform. All engineering decisions must take the following hardware constraints into account:

| Component | Specification | Architectural Impact |
|---|---|---|
| **SoC** | Rockchip RK3326 | 64-bit chip from 2018 |
| **CPU** | 4x ARM Cortex-A35 @ 1.30 GHz | Low-power ARMv8-A cores (in-order execution, shallow speculative execution, small L1/L2 caches). Every CPU cycle is precious. |
| **GPU** | ARM Mali-G31 MP2 (Bifrost v1) | OpenGL ES 2.0 / 3.0, Vulkan 1.0 support. **No hardware desktop OpenGL (GLX)** in 32-bit userland. |
| **RAM** | 1024 MB LPDDR3 (shared) | Extremely tight memory budget. Between the OS, Weston, Xwayland, and Wine, approx. 500–600 MB remains for the game. Swapping to a slow microSD card destroys frame pacing. |
| **Display** | 3.5" IPS LCD, 640×480 (4:3) | MIPI DSI interface, framebuffer controlled via `/dev/dri/card0` (Direct Rendering Manager). |
| **Audio** | Rockchip RK817 (I2S Codec) | ALSA device nodes: `/dev/snd/pcmC0D0p` and `/dev/snd/controlC0`. Requires compatibility with the 64-bit kernel driver. |
| **Inputs** | Integrated Gamepad (evdev) | 2 analog sticks, D-Pad, A/B/X/Y, L1/R1, L2/R2, Select, Start, L3, R3, Menu. Hardware evdev codes: Select `0x2C0`, Start `0x2C1`, L3 `0x2C2`, R3 `0x2C3`, Menu `0x2C4`. |
| **OS / Kernel** | ArkOS / Linux 4.4.189+ aarch64 | 64-bit kernel, hybrid userland (AArch64 system libraries and multiarch ARMHF 32-bit). PortMaster runtime environment. |

---

## 2. Software Architecture (Runtime Stack)

The game is a 32-bit Windows x86 application. Native ARM compilation is impossible due to proprietary Blizzard / PD2 source code. The entire runtime stack relies on efficient userland emulation on Linux:

```
[ Game: Game.exe -ddraw (Win32 x86) ]
          │
          ▼
[ DirectDraw Wrapper: cnc-ddraw (ddraw.dll x86) ]
          │
          ▼
[ Wine 8.0 x86 (WoW64 / Win32 API) ]
          │
          ▼
[ Box86 (JIT Dynarec x86 -> ARMHF 32-bit) ]
          │
    ┌─────┴─────────────────────────┐
    ▼                               ▼
[ Graphics ]                    [ Audio ]
Wine X11 Window                 winealsa.drv
    │                               │
Xwayland (DISPLAY=:0)           compat/alsa-legacy-armhf
    │                           (libasound.so.2 time32)
Weston (wp_weston kiosk)            │
(-B drm card0 --renderer=gl)    /dev/snd/pcmC0D0p (rk817)
    │
Mali-G31 GPU / KMS DRM
    │
[ 640x480 LCD Panel ]
```

---

## 3. Graphics Subsystem and Display Rules

### A. Why the GDI Profile is the Official Production Mode
- In **GDI** mode ([`Project Diablo 2.sh`](sdcard/ports/Project%20Diablo%202.sh)):
  1. `weston-session.sh` launches the compositor with flags:
     `-B drm --drm-device card0 --renderer=gl`
     along with the pre-installed `crusty_gbm` library.
  2. The Weston compositor assumes the role of **DRM Master** on `/dev/dri/card0` and utilizes the 64-bit Mali GPU driver to display the image on the LCD panel.
  3. The game and `cnc-ddraw` render frames in software into a DIB buffer (GDI), which is passed through X11/Xwayland to Weston. Weston scales the buffer in hardware to 640×480 and outputs it to the display.
  4. **This mode ALWAYS guarantees a stable, tear-free image.**

### B. Critical Bug: Black Screen with OpenGL Profile
- **Observed Behavior:** Selecting the `opengl` profile resulted in the game starting and audio playing normally, but the screen stayed completely black.
- **Root Cause in Code:** In `weston-session.sh`, the `opengl` profile enforced:
  `weston_args=(-B headless --renderer=noop);preload=;backendlib=`
  The `headless` mode with a `noop` renderer **does not open the DRM display device and drops all presented frames**.
- **Architectural Takeaway:** On the R36S console, the Weston compositor **must never run in headless/noop mode**, unless a verified native KMS scanout renderer exists. Because ArkOS lacks 32-bit GLX drivers for the Mali GPU, standard OpenGL in cnc-ddraw cannot render to the screen without an active DRM compositor.

### C. Advanced GPU Variant (GLES2)
- The `compat/gles2-renderer/` directory contains an experimental `ddraw.dll` build optimized for GLES2 / GLSL 1.10 shaders (launched via [`Project Diablo 2 - GPU.sh`](sdcard/ports/Project%20Diablo%202%20-%20GPU.sh)).
- It offloads 8-bit palette color conversion to the GPU, relieving the CPU from calculating color transforms per-frame in software.

---

## 4. Audio Subsystem (ALSA / DirectSound)

### A. 64-bit Kernel vs 32-bit Userland Library (ENOTTY Error)
- The RK3326 kernel audio driver expects a 32-bit `time_t` in the `snd_pcm_sync_ptr` structure for 32-bit processes (`ioctl 0xC0844123`).
- Modern Linux distribution builds of `libasound.so.2` are compiled with 64-bit `time_t` (time64, `ioctl 0xC0884123`), which the kernel rejected with error `-25 ENOTTY`.
- **Solution:** A dedicated build of `alsa-lib 1.2.8` compiled without time64 flags is provided in `compat/alsa-legacy-armhf/libasound.so.2`, preloaded on the fly into RAM (`$PD2_WORK/.alsa-legacy-armhf`).

### B. Audio Stutter / Underruns Issue and Its Solution
- Initial workarounds routed ALSA directly to the raw hardware node:
  `slave.pcm "hw:CARD=rk817...,DEV=0"`
- The raw `hw:` node has a tiny hardware buffer (~20 ms). Under high Box86 emulation load, the buffer ran dry, causing crackling, stutter, and underruns.
- **Key fixes implemented in `run-game.sh`:**
  1. `export SDL_AUDIODRIVER=dummy` — prevents SDL2 companion libraries from locking the ALSA node away from Wine.
  2. Wine DirectSound registry tuning:
     - `HelBuflen = 8192` (DirectSound emulation buffer increased to ~90 ms headroom).
     - `MaxHardwareChannels = 16` (capped mixed software channels from 32/64 down to 16, saving up to 40% CPU load).
     - `DefaultSampleRate = 44100` (matches native sample rate, eliminating on-the-fly software resampling).
  3. Inside the game options, **Environmental Effects (EAX 3D)** must remain **DISABLED**.

---

## 5. CPU Performance Optimization (Box86 Dynarec)

The Cortex-A35 processor is the primary bottleneck. To achieve smooth gameplay in Diablo II (improving over the baseline 10–15 FPS), the production launcher sets:

```bash
export BOX86_DYNAREC=1
export BOX86_DYNAREC_BIGBLOCK=2     # Large JIT translation basic blocks
export BOX86_DYNAREC_FORWARD=256    # Deep forward jump lookahead
export BOX86_DYNAREC_FASTROUND=1    # Hardware ARM rounding instructions
export BOX86_DYNAREC_FASTNAN=1      # Fast IEEE NaN handling
export BOX86_DYNAREC_SAFEFLAGS=1    # Safe processor flags (do not disable for Diablo!)
export BOX86_DYNAREC_STRONGMEM=0    # Relaxed memory ordering model (no unnecessary barriers)
export BOX86_DYNAREC_X87DOUBLE=0    # Hardware NEON usage instead of 80-bit x87 emulation
```

Additionally, memory swappiness is lowered before launching the game:
```bash
sysctl -w vm.swappiness=10
sync; echo 3 > /proc/sys/vm/drop_caches
```
This prevents the operating system from stalling due to swapping RAM pages out to the slow microSD card.

---

## 6. Repository File Structure

```
.
├── .agents/                   # Custom agent configurations and skills
│   └── skills/
│       └── caveman/           # Mandatory caveman token efficiency skill (SKILL.md)
├── AGENTS.md                  # This architectural guide and AI operational contract
├── docs/                      # Central documentation directory (no loose .md in sdcard/ports)
│   ├── README.md              # Documentation index and overview
│   ├── PORT-README.md         # Detailed port manual and historical changelog
│   ├── DIAGNOSTICS-1.md       # Diagnostic test suite procedures (tests A–F)
│   └── GPU-RUNTIME-1.md       # GPU GLES2 runtime test documentation
├── MEMORY.md                  # Chronological debugging history and test records
├── README.md                  # Project overview and setup documentation
├── runtime-manifest.json      # Pinned hashes and sizes of downloaded runtimes
├── runtime-lock.json          # Binary file integrity manifest
├── release-files.json         # Distribution files specification
├── sdcard/
│   └── ports/                 # Clean distribution payload for handheld microSD
│       ├── Project Diablo 2.sh              # MAIN PRODUCTION LAUNCHER (GDI + Dynarec)
│       ├── Project Diablo 2 - Performance GDI.sh
│       ├── Project Diablo 2 - GPU.sh        # Alternative GLES2 shader launcher
│       ├── Project Diablo 2 - Performance OpenGL.sh
│       └── projectdiablo2/
│           ├── port.json                    # PortMaster package metadata
│           ├── gameinfo.xml                 # EmulationStation metadata and description
│           ├── scripts/                     # Orchestration scripts (Bash, Python)
│           │   ├── run-game.sh              # Wine, registry preparation and game execution
│           │   ├── weston-session.sh        # Wayland/Weston compositor orchestration
│           │   ├── layout.py                # Path validation, prefix and INI verification
│           │   ├── audio_config.py          # ALSA routing configuration
│           │   └── ...
│           ├── compat/                      # Compatibility binaries and helper libraries
│           │   ├── alsa-legacy-armhf/       # libasound.so.2 (time32)
│           │   ├── box86-a35/               # Cortex-A35 tuned Box86 build
│           │   ├── cnc-ddraw/               # ddraw.dll with glGetTexImage removed
│           │   ├── gles2-renderer/          # ddraw.dll with GPU palette offloading
│           │   └── ...
│           └── defaults/                    # Default game configs and gamepad mappings
├── tools/                                   # Compilation, packaging, and diagnostic tools
│   ├── prepare.py                           # Game data importer and validator
│   ├── build_cnc_ddraw_ogl.py               # ddraw.dll build script (MSVC)
│   ├── build_box86_a35.py                   # Box86 A35 build script
│   └── ...
└── tests/                                   # Regression and validation test suite
```

---

## 7. Operational Instructions for Developers and Agents

### Mandatory AI Agent Protocol: Caveman Skill Usage
**All AI agent sessions operating in this repository MUST activate and strictly adhere to the `caveman` skill (`.agents/skills/caveman/SKILL.md`).**
- **Token Efficiency & Brevity:** Eliminate conversational filler, pleasantries, hedging, and unnecessary verbiage. Deliver terse, dense, technically sound communication.
- **Accuracy & Integrity:** Retain 100% technical accuracy, code syntax, exact error strings, command arguments, and markdown links. Code blocks and commit messages are never mangled.
- **Persistence:** The caveman mode remains continuously active across all turns within the agent session unless the user explicitly requests normal mode.

### Documentation Location Standard:
- **No loose `.md` files in `sdcard/ports/`:** Handheld ROM partitions must contain only execution payloads, scripts, runtimes, and configs. All user-facing guides, diagnostic protocols, and changelogs must reside strictly within the root [`docs/`](docs/) directory.

### Port Deployment and SD Card Standard:
- **No `dist/` or ZIP archives:** Never build `dist/` update ZIP packages (`projectdiablo2-port-update.zip`) after completing tasks.
- **Direct `sdcard/` deployment:** Handheld console files must always be taken directly from the `sdcard/ports/` directory (`Project Diablo 2.sh` and `projectdiablo2/`). All changes and additions must be directly made and maintained inside `sdcard/ports/`.

### Running Local Tests:
```bash
# Configuration and layout tests:
python -m unittest discover -s tests -p "test_layout.py"

# Launcher and menu tests:
python -m unittest discover -s tests -p "test_opengl_entry_fix.py"

# GPU profile tests:
python -m unittest discover -s tests -p "test_gpu_runtime.py"
```

### Rules of Code Integrity:
1. **Never change `SAFEFLAGS=1` to `0` or enable `CALLRET=1` in Box86** — Diablo II contains self-modifying code (in-engine JIT); aggressive Box86 flags lead to immediate crashes during spell casting.
2. **Never install Wine as root** or execute games with root privileges — Westonpack requires user namespace separation (`runuser`).
3. **Never modify `Project Diablo 2.sh` without an explicit user instruction naming that launcher.** A general modernization/conversion plan is not permission. The file must remain the verified, stable production release. Experimental tweaks must use separate launchers and must not alter the default production environment through shared scripts.
4. **Mandatory Caveman Skill in AI Sessions:** Agents must strictly employ the `caveman` skill (`.agents/skills/caveman/SKILL.md`) to conserve context window tokens and maximize operational reasoning capacity.
5. **Preserve Clean SD Card Payload:** Do not add loose `.md` files to `sdcard/ports/` or `sdcard/ports/projectdiablo2/`. Keep all documentation in [`docs/`](docs/).
6. **Direct SD Card Source (No `dist/` builds):** Never build ZIP packages in `dist/` after completing work. All port files, launchers, and scripts are taken directly from `sdcard/ports/`.
