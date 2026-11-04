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
- **On-Screen Keyboard (OSK):** Built-in Diablo II styled virtual keyboard for character creation and text input without physical peripherals. Triggered via **SELECT + X** or **FN + X**, with direct X11 XTEST text injection into Wine.

---

## 🛠️ Installation on R36S Console

### Required Game Files & Season Requirements:
This port requires original base files from **Diablo II: Lord of Destruction** (version 1.13c or 1.14d) plus **Project Diablo 2 (Season 13)**.

> [!WARNING]
> **Important Season Notice (Do NOT use Season 14):**
> **Season 14 is problematic on R36S** ([Issue #9](https://github.com/kadeshar/r36s-port-projectdiablo2/issues/9)). Under Season 14, characters suffer from broken melee hit detection, skill activation stalls (character stands still when pressing attack), skills/spells in slots failing to trigger, and monster targeting/nameplate issues.
> 
> **Use Project Diablo 2 Season 13 (S13P2M2)** — this is the verified, fully working version for R36S. Do not use the official website live launcher, as it installs Season 14.

### 📥 Downloads:
1. **Diablo II & Lord of Destruction Base Game:**
   - **[Diablo II](https://us.shop.battle.net/en-us/product/diablo-ii#optLogin=true)** — classic game on Battle.net (v1.13c or 1.14d; not Diablo II: Resurrected).
   - **[Diablo II: Lord of Destruction](https://us.shop.battle.net/en-us/product/diablo-ii-lord-of-destruction)** — required expansion on Battle.net.
2. **Project Diablo 2 Mod (Season 13):**
   - Download the standalone Season 13 update archive directly:  
     **[ProjectD2-S13P2M2-FullPD2Update.zip](https://github.com/Khazra89/Unofficial-PD2-Client-Mirror/releases/download/s13p2m2/ProjectD2-S13P2M2-FullPD2Update.zip)**  
     *(Mirror repository: [Unofficial PD2 Client Mirror](https://github.com/Khazra89/Unofficial-PD2-Client-Mirror))*.

---

### 📋 Simple Installation Steps:

#### 1. Setup & Test on PC:
1. Install **Diablo II** + **Lord of Destruction** on your PC.
2. Download **`ProjectD2-S13P2M2-FullPD2Update.zip`**.
3. Create a folder named `ProjectD2` inside your PC's `Diablo II` directory.
4. Extract the contents of the ZIP archive directly into `Diablo II\ProjectD2\`.
5. **Run `ProjectD2\Game.exe` on PC to verify that the mod launches and reaches the title screen.**

#### 2. Copy Port to Console SD Card:
Copy the contents of the repository's `sdcard/ports/` directory to your SD card's `ports/` directory:
```
ports/
├── Project Diablo 2.sh
└── projectdiablo2/
```

#### 3. Copy Game Folder to SD Card:
Copy your entire tested **`Diablo II`** folder from PC into:
```
ports/projectdiablo2/gamedata/
```
*(Resulting path on SD card: `ports/projectdiablo2/gamedata/Diablo II/`)*

#### 4. Launch on R36S:
Insert SD card into console, power on, open **Ports** in EmulationStation, and start **Project Diablo 2**!

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

### ⌨️ In-Game Hotkeys & Shortcuts

| Shortcut | Action |
|---|---|
| **FN + X** or **SELECT + X** | **On-Screen Keyboard (OSK)** — toggle virtual keyboard for text input (e.g. character creation) |
| **FN + R1** (or **SELECT + R1**) | **Performance Overlay Level** — toggle in-game performance overlay level (`OFF -> Minimal FPS -> Bar -> Detailed HUD -> Full OSD -> OFF`) |
| **FN + R2** (or **SELECT + R2**) | **Reset Performance Data** — reset frametime graph and performance statistics (`AVG`, `1% LOW`, `0.1%low`) |

---

## ☕ Support

If you enjoy this port, you can support its development by buying me a coffee.

<a href="https://buymeacoffee.com/kadeshar"><img src="https://www.buymeacoffee.com/assets/img/custom_images/orange_img.png" alt="Buy Me A Coffee" width="174" height="41"></a>

---

## 📜 Licenses and Credits

### Original Game

Thank you to **Blizzard North**, part of [Blizzard Entertainment](https://www.blizzard.com/en-us/), for creating Diablo II and Lord of Destruction.

### Project Diablo 2

Thank you to the [Project Diablo 2 team](https://www.projectdiablo2.com/) for maintaining the mod.

### Runtime and Porting Components

Thank you to the maintainers and contributors of the components that make this handheld port possible:

- **Westonpack** (Wayland / Xwayland) — MIT License
- **Box86** by Sébastien Chevalier (ptitSeb) — MIT License
- **Wine** — LGPL v2.1+
- **DSOAL** by Chris Robinson and contributors — LGPL v2.1
- **OpenAL Soft** — LGPL v2+
- **cnc-ddraw** by FunkyFr3sh — GNU General Public License v3.0
- **ALSA Library (alsa-lib)** — LGPL v2.1
