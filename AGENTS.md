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

### B. Display Safety
- GDI is the only supported game renderer. Weston still uses the Mali GPU for composition and display scaling; this does not imply GPU rendering of the game engine.
- Weston must retain the active DRM compositor. Headless/noop alone does not scan out game frames.
- Earlier OpenGL/GLES2 and Performance experiments were removed. Historical records are not deployment or configuration instructions.

---

## 4. Audio Subsystem (ALSA / DirectSound)

### A. 64-bit Kernel vs 32-bit Userland Library (ENOTTY Error)
- The RK3326 kernel audio driver expects a 32-bit `time_t` in the `snd_pcm_sync_ptr` structure for 32-bit processes (`ioctl 0xC0844123`).
- Modern Linux distribution builds of `libasound.so.2` are compiled with 64-bit `time_t` (time64, `ioctl 0xC0884123`), which the kernel rejected with error `-25 ENOTTY`.
- **Solution:** A dedicated build of `alsa-lib 1.2.8` compiled without time64 flags is provided in `compat/alsa-legacy-armhf/libasound.so.2`, preloaded on the fly into RAM (`$PD2_WORK/.alsa-legacy-armhf`).

### B. Production Audio
- **D2Sound → DSOAL → OpenAL Soft WinMM → Wine waveOut → winealsa → ALSA/RK817**. The [runner](<sdcard/ports/projectdiablo2/scripts/run-game.sh>) selects native-only DLLs after Wine setup; the [helper](<sdcard/ports/projectdiablo2/scripts/audio_dsoal.py>) authenticates/stages them into volatile work and verifies WinMM after shutdown.
- Preserve `ALSOFT_DRIVERS=winmm`, SDL audio `dummy`, baseline ALSA and legacy time32 compatibility. **Environmental Effects / EAX stays disabled.** Required source archives, patches and LGPL notices accompany the DLLs.
- Preserve production config/prefix/saves and separate A/B save backups. Investigation history and rejected approaches belong only in [MEMORY.md](<MEMORY.md>).

---

## 5. CPU Performance Optimization (Box86 Dynarec)

The Cortex-A35 processor is the primary bottleneck. To achieve smooth gameplay in Diablo II (improving over the baseline 10–15 FPS), the production launcher sets:

```bash
export BOX86_DYNAREC=1
export BOX86_DYNAREC_BIGBLOCK=2     # Large JIT translation basic blocks
export BOX86_DYNAREC_SAFEFLAGS=1    # Safe processor flags (do not disable for Diablo!)
export BOX86_DYNAREC_STRONGMEM=0    # Relaxed memory ordering model (no unnecessary barriers)
export BOX86_DYNAREC_CALLRET=0      # Keep unsafe call/return optimization disabled
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
│   └── DIAGNOSTICS-1.md       # Historical diagnostic procedures (tests A–F)
├── MEMORY.md                  # Chronological debugging history and test records
├── README.md                  # Project overview and setup documentation
├── runtime-manifest.json      # Pinned hashes and sizes of downloaded runtimes
├── runtime-lock.json          # Binary file integrity manifest
├── release-files.json         # Distribution files specification
├── sdcard/
│   └── ports/                 # Clean distribution payload for handheld microSD
│       ├── Project Diablo 2.sh              # MAIN PRODUCTION LAUNCHER (GDI + Dynarec)
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
│           │   ├── cnc-ddraw/               # ddraw.dll with glGetTexImage removed
│           │   └── ...
│           └── defaults/                    # Default game configs and gamepad mappings
├── tools/                                   # Compilation, packaging, and diagnostic tools
│   ├── prepare.py                           # Game data importer and validator
│   ├── build_cnc_ddraw_ogl.py               # ddraw.dll build script (MSVC)
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

### Temporary Files and Experimental Work:
- **All new temporary files, downloaded investigation references, synthetic fixtures, build intermediates, scratch reports and experimental port copies MUST be placed under the repository-root `.temp/` directory.** Keep `.temp/` ignored by Git; do not create new temporary artifacts in the root, `.state/`, production `sdcard/ports/`, or unrelated directories.
- **Explicit experimental-work exception:** when the user requests an experimental port under `.temp/`, keep its payload, isolated launchers, copied scripts, tools and tests there. Do not merge experiments into or deploy them as production `sdcard/ports/` files without a separate explicit user request. Never share mutable production config, Wine prefix or saves with an experiment.
- Permanent project documentation still belongs in root `docs/`; disposable experiment notes may live inside `.temp/`. This repository-storage rule does not replace necessary volatile `/tmp` or `/run` paths used by console sessions.
- Existing temporary artifacts elsewhere are not permission to create more there; do not relocate/delete the user's existing files without authorization.

### Documentation Location Standard:
- **No loose `.md` files in `sdcard/ports/`:** Handheld ROM partitions must contain only execution payloads, scripts, runtimes, and configs. All user-facing guides, diagnostic protocols, and changelogs must reside strictly within the root [`docs/`](docs/) directory.

### Port Deployment and SD Card Standard:
- **No `dist/` or ZIP archives:** Never build `dist/` update ZIP packages (`projectdiablo2-port-update.zip`) after completing tasks.
- **Direct `sdcard/` deployment:** Handheld console files must always be taken directly from the `sdcard/ports/` directory (`Project Diablo 2.sh` and `projectdiablo2/`). All changes and additions must be directly made and maintained inside `sdcard/ports/`.

### Fresh Installation Simulation Procedure (R36S Console):
To reliably test clean first-boot scenarios (such as dynamic `state.ext4` image creation, runtime squashfs mounts, and fresh Wine prefix configuration) without risk of data loss:
- **Script Location:** [`tools/simulate_fresh_install.py`](tools/simulate_fresh_install.py)
- **Data Protection Guarantee:**
  - Game saves located across `saves/`, `saves_s14/`, `gamedata/*/Save/`, and `$HOME/.local/share/pd2-r36s/saves/` are scanned and backed up into timestamped `/roms2/ports/projectdiablo2-saves-backup-<timestamp>/` before any removal.
  - Game assets under `gamedata/` remain completely untouched.
  - Active saves in `saves/` and `saves_s14/` are preserved in-place; save counts are verified before and after the procedure.
- **State Cleaned:**
  - Safely detaches any hanging loop device attached to `state.ext4` and unmounts `storage/mounted-state` / `storage/mounted-wine-check`.
  - Removes `storage/state.ext4` and `storage/session.lock`, forcing first-boot generation logic on subsequent launch.
  - Clears `logs/*.log`.
  - Cleans ephemeral runtime caches and temporary prefix data in `$HOME/.local/share/pd2-r36s`.
- **Usage:**
  ```bash
  # Remote execution via SSH (default console 192.168.50.135):
  python tools/simulate_fresh_install.py --dry-run
  python tools/simulate_fresh_install.py

  # Local execution directly on the handheld console:
  python3 tools/simulate_fresh_install.py --local
  ```
- **Post-Reset Verification:** After running the simulation, the console is in a clean first-boot state. As dictated by Rule 7, only the user may initiate the subsequent game test on the console.

### Running Local Tests:
```bash
# Configuration and layout tests:
python -m unittest discover -s tests -p "test_layout.py"

# Full regression suite:
python -m unittest discover -s tests
```

### Rules of Code Integrity:
1. **Never change `SAFEFLAGS=1` to `0` or enable `CALLRET=1` in Box86** — Diablo II contains self-modifying code (in-engine JIT); aggressive Box86 flags lead to immediate crashes during spell casting.
2. **Never install Wine as root** or execute games with root privileges — Westonpack requires user namespace separation (`runuser`).
3. **Never modify `Project Diablo 2.sh` without an explicit user instruction naming that launcher.** A general modernization/conversion plan is not permission. The file must remain the verified, stable production release. Experimental tweaks must use separate launchers and must not alter the default production environment through shared scripts.
4. **Mandatory Caveman Skill in AI Sessions:** Agents must strictly employ the `caveman` skill (`.agents/skills/caveman/SKILL.md`) to conserve context window tokens and maximize operational reasoning capacity.
5. **Preserve Clean SD Card Payload:** Do not add loose `.md` files to `sdcard/ports/` or `sdcard/ports/projectdiablo2/`. Keep all documentation in [`docs/`](docs/).
6. **Direct SD Card Source (No `dist/` builds):** Never build ZIP packages in `dist/` after completing work. All port files, launchers, and scripts are taken directly from `sdcard/ports/`.
7. **Versioning is directed by the user — never automatic:** Agents must never bump or renumber `port_version` on their own. The version pins (`layout.py` `VERSION`, root + port `runtime-manifest.json` `port_version`, both launchers' `port_version` events, `tools/check_update.py`) change only when the user explicitly states a version; then all six pins are updated together with that exact string.
8. **Console game testing is exclusively the user's responsibility:** Only the user may launch and test the actual game on the console. Agents must never start the game or any game launcher on the console, directly or indirectly, including via SSH, smoke tests, start-menu bypasses, background launches, or diagnostics that execute the real game. Requests to diagnose, fix, update, deploy, or run tests do not authorize agent-operated console gameplay tests. Agents must also never automatically launch the real game locally. Limit agent verification to static analysis, unit/regression tests using synthetic fixtures, and checks that do not launch the real game. After deployment, ask the user to launch and test the game themselves; inspect their reported results or logs without initiating another game session.
