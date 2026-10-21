# Project Diablo 2 — R36S Port (PortMaster)

Port of **Project Diablo 2 (Diablo II: Lord of Destruction)** tailored for the **R36S** handheld retro gaming console (Rockchip RK3326 SoC, 4x Cortex-A35, 1 GB RAM).

The project combines **PortMaster**, the **Westonpack Wayland/X11** compositor, the **Box86 JIT Dynarec** instruction translator, a **Wine 8.0 x86** layer, and a modified **cnc-ddraw** DirectDraw wrapper.

---

## 🚀 Key Production Features

- **Verified OS Compatibility:** Start menu and game launch confirmed on all three tested systems: ArkOS, dArkOS, and dArkOSen.
- **Stable Display on 640×480 LCD:** Weston compositor uses DRM/KMS with Mali-G31 acceleration for composition; game rendering remains safe GDI / DirectDraw.
- **CPU Performance Optimization:** Box86 production dynarec settings (`BIGBLOCK=2`, `SAFEFLAGS=1`, `STRONGMEM=0`, `CALLRET=0`); conservative `BIGBLOCK=1` during setup and recovery.
- **RAM Protection:** Reduced swappiness (`vm.swappiness=10`) and system buffer cache flushing prevent memory thrashing on slow microSD storage.
- **Full Gamepad Controls:** Bundled Xbox 360 translator maps all 17 physical R36S buttons and analog sticks, including L3, R3, Select, Start, and FN/Menu.
- **Smooth Audio:** DSOAL + OpenAL Soft routes sound through Wine's waveOut backend, with lag-free playback confirmed in gameplay testing on R36S.
- **Themed Start Menu:** Diablo II-styled X11 menu; default internal resolution is `640x480`, with `800x600`, `1024x768`, and `native` (`1068x600`) choices plus optional FPS toggle.

---

## 🛠️ Installation on R36S Console

### Required Game Files:
This port requires original game files from **Diablo II: Lord of Destruction** (version 1.13c or 1.14) with the **Project Diablo 2** mod installed.

### Step by Step:
1. Copy the contents of the `sdcard/ports/` directory to the `ports/` directory on your console SD card (`EASYROMS` partition or secondary SD card):
   ```
   roms/ports/
   ├── Project Diablo 2.sh
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

## 📂 Repository Structure

- **[`AGENTS.md`](AGENTS.md):** Architectural, technical, and operational knowledge base for AI agents and developers (RK3326 SoC specs, runtime stack architecture, rules of code integrity).
- **[`MEMORY.md`](MEMORY.md):** Chronological log of research, diagnostics, and problem-solving (audio missing, black screen, audio underruns, FPS optimizations).
- **[`docs/`](docs/):** Central documentation directory (diagnostic procedures and full port documentation).
- **[`sdcard/ports/`](sdcard/ports/):** Clean distribution files intended to be copied to the console's SD card:
  - `Project Diablo 2.sh` — **Official production launcher** (tested on hardware).
  - `projectdiablo2/` — Complete script runtime, compatibility libraries, and configuration files.
- **[`tools/`](tools/):** Build scripts, library compilers (MSVC/GCC), diagnostic tools, and donor data importer (`prepare.py`).
- **[`tests/`](tests/):** Clean test suite of unit and integration tests.

---

## 🎮 Controls (R36S Gamepad)

The production launcher uses **PD2's native controller support** through a virtual Xbox 360 controller. Gameplay bindings are managed by PD2, not by the keyboard/mouse fallback profile.

| R36S Input | Virtual Controller Input |
|---|---|
| **Left / Right Analog** | Left / Right stick |
| **D-Pad** | D-Pad |
| **A / B / X / Y** | Controller face buttons |
| **L1 / R1** | Left / Right shoulder |
| **L2 / R2** | Left / Right trigger |
| **Select / Start** | Back / Start |
| **L3 / R3** | Left / Right stick click |
| **FN / Menu** | Guide button; firmware may reserve this input |

---

## ☕ Support

If you enjoy this port, you can support its development by buying me a coffee.

<a href="https://buymeacoffee.com/kadeshar"><img src="https://www.buymeacoffee.com/assets/img/custom_images/orange_img.png" alt="Buy Me A Coffee" width="174" height="41"></a>

---

## 📜 Licenses and Credits

This project utilizes Open Source components:
- **Westonpack** (Wayland / Xwayland) — MIT License
- **Box86** by Sébastien Chevalier (ptitSeb) — MIT License
- **Wine** — LGPL v2.1+
- **DSOAL** by Chris Robinson and contributors — LGPL v2.1
- **OpenAL Soft** — LGPL v2+
- **cnc-ddraw** by FunkyFr3sh — GNU General Public License v3.0
- **ALSA Library (alsa-lib)** — LGPL v2.1
