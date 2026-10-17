# Project Diablo 2 — R36S Port (ArkOS / PortMaster)

Private, optimized port of **Project Diablo 2 (Diablo II: Lord of Destruction)** tailored for the **R36S** handheld retro gaming console (Rockchip RK3326 SoC, 4x Cortex-A35, 1 GB RAM, ArkOS).

The project combines **PortMaster**, the **Westonpack Wayland/X11** compositor, the **Box86 JIT Dynarec** instruction translator, a **Wine 8.0 x86** layer, and a modified **cnc-ddraw** DirectDraw wrapper.

---

## 🚀 Key Production Features

- **Stable Display on 640×480 LCD:** Weston compositor optimized for DRM/KMS with Mali-G31 GPU acceleration and safe GDI / DirectDraw rendering.
- **Clean Audio Without Stuttering:** Dedicated ALSA time32 library (`compat/alsa-legacy-armhf/libasound.so.2`) eliminating the `ENOTTY` error on the 64-bit kernel, combined with an expanded DirectSound buffer (`HelBuflen=8192`, channel limit set to 16) preventing ALSA underruns.
- **CPU Performance Optimization (Box86 Cortex-A35):** Enabled advanced JIT Dynarec compilation flags (`BIGBLOCK=2`, `FORWARD=256`, `FASTROUND=1`, `FASTNAN=1`, `X87DOUBLE=0`).
- **RAM Protection:** Reduced swappiness (`vm.swappiness=10`) and system buffer cache flushing to prevent memory thrashing on slow microSD storage.
- **Full Gamepad Controls:** Integrated virtual Xbox 360 controller translator supporting all 17 physical R36S buttons and analog sticks (including L3, R3, Select, Start, and FN/Menu).
- **Themed Start Menu:** Diablo II styled start menu with resolution selection (default 800×600 hardware-scaled to 640×480) and optional FPS counter toggle.
- **Experimental GPU Profile (GLES2):** Standalone launcher [`Project Diablo 2 - GPU.sh`](sdcard/ports/Project%20Diablo%202%20-%20GPU.sh) with a dedicated 8-bit palette shader executed directly on the Mali GPU.

---

## 📂 Repository Structure

- **[`AGENTS.md`](AGENTS.md):** Architectural, technical, and operational knowledge base for AI agents and developers (RK3326 SoC specs, runtime stack architecture, rules of code integrity).
- **[`MEMORY.md`](MEMORY.md):** Chronological log of research, diagnostics, and problem-solving (audio missing, black screen, audio underruns, FPS optimizations).
- **[`docs/`](docs/):** Central documentation directory (diagnostic procedures, GPU runtime manuals, and full port documentation).
- **[`sdcard/ports/`](sdcard/ports/):** Clean distribution files intended to be copied to the console's SD card:
  - `Project Diablo 2.sh` — **Official production launcher** (tested on hardware).
  - `Project Diablo 2 - GPU.sh` — Alternative variant with GLES2 hardware palette shader.
  - `Project Diablo 2 - Performance GDI.sh` — Direct GDI launch bypassing the start menu.
  - `projectdiablo2/` — Complete script runtime, compatibility libraries, and configuration files.
- **[`tools/`](tools/):** Build scripts, library compilers (MSVC/GCC), diagnostic tools, and update package generator (`prepare.py`).
- **[`tests/`](tests/):** Clean test suite of unit and integration tests.

---

## 🛠️ Installation on R36S Console

### Required Game Files:
This port requires original game files from **Diablo II: Lord of Destruction** (version 1.13c or 1.14) with the **Project Diablo 2** mod installed.

### Step by Step:
1. Copy the contents of the `sdcard/ports/` directory to the `ports/` directory on your console SD card (`EASYROMS` partition or secondary SD card):
   ```
   roms/ports/
   ├── Project Diablo 2.sh
   ├── Project Diablo 2 - GPU.sh
   ├── Project Diablo 2 - Performance GDI.sh
   └── projectdiablo2/
   ```
2. Place your Diablo II game files and the `ProjectD2` folder into:
   ```
   ports/projectdiablo2/gamedata/Diablo II/
   ```
   *(ensure that `Game.exe`, `.mpq` files, and the `ProjectD2` subfolder are present).*
3. Insert the SD card into your R36S, power on the console, and navigate to the **Ports** section in EmulationStation.
4. Launch **Project Diablo 2**.

---

## 🎮 Controls (R36S Gamepad)

| R36S Button | Diablo II / PD2 Function |
|---|---|
| **Left Analog** | Mouse cursor movement / character |
| **Right Analog** | Free mouse cursor movement |
| **A** | Left Mouse Button (primary attack / pick up item) |
| **X** | Right Mouse Button (spell / secondary attack) |
| **B** | Close windows / Cancel / ESC |
| **Y** | Run / Walk toggle |
| **D-Pad Left / Right** | Potion belt slots (1, 2, 3, 4) |
| **D-Pad Up / Down** | Inventory (I) / Character screen (C) |
| **L1 / R1** | Assigned skill hotkeys (F1, F2...) / Tab switching |
| **L2 / R2** | Show items on ground (ALT) / Map (TAB) |
| **Start** | In-game menu (ESC) / Confirm |
| **Select** | Toggle automap / Additional menu |
| **L3 / R3** | Quick heal / FPS helper |
| **FN / Menu** | Special port key |

---

## 💡 In-Game Performance Tips

1. **Environmental Effects (3D Audio):**
   - In the game options, open **Options -> Sound Options**.
   - Make sure **Environmental Effects is UNCHECKED (disabled)**. Emulating 3D EAX sound effects on ARM CPUs causes severe performance drops.
2. **Resolution:**
   - Default 800×600 resolution offers the optimal balance between Project Diablo 2 UI readability and hardware scaling performance of the Mali GPU on the 640×480 screen.

---

## 📜 Licenses and Credits

This project utilizes Open Source components:
- **Westonpack** (Wayland / Xwayland) — MIT License
- **Box86** by Sébastien Chevalier (ptitSeb) — MIT License
- **Wine** — LGPL v2.1+
- **cnc-ddraw** by FunkyFr3sh — GNU General Public License v3.0
- **ALSA Library (alsa-lib)** — LGPL v2.1
