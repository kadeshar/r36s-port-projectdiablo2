# Performance Overlay (R36S) for Retro Handheld Ports

This document describes the portable, lightweight R36S performance overlay architecture developed for the R36S retro handheld console (Rockchip RK3326 / Mali-G31) and details how to move and reuse it in other PortMaster and Linux ports.

---

## 1. Overview and Overlay Levels

The performance overlay displays real-time telemetry across 5 selectable levels:

| Level | Name | Dimensions | Features / Visible Information |
|---|---|---|---|
| **0** | **OFF** | N/A | Overlay disabled; zero CPU and memory overhead. |
| **1** | **Minimal FPS Pill** | 34 × 16 px | Compact FPS number (e.g. `30`) in top corner. Unobtrusive for immersive gameplay. |
| **2** | **R36S Bar** | 410 × 20 px | Compact horizontal status bar glued to screen top, centered: `FPS 36 │ [~chart~] │ CPU 71% │ GPU 92% │ RAM 412M │ BATT ~ 70%`. Includes live color-coded frametime graph (> 20 FPS green, 15–20 FPS orange, < 15 FPS red), wall plug icon when charging, and distinct section colors. |
| **3** | **Detailed HUD** | 205 × 136 px | Multi-line HUD glued to top-left. GPU, CPU, RAM, BATT with plug icon, FPS + FT ms, Frametime min/max range, and live color-coded frametime line chart (> 20 FPS green, 15–20 orange, < 15 red) across the full width. |
| **4** | **R36S OVERLAY 1.0** | 205 × 226 px | Full R36S performance OSD: Header `Time HH:MM:SS  R36S 1.0`, GPU %, CPU % with frequency and per-core breakdown (CPU0..CPU3), RAM, battery state, min/max frametime, and live color-coded frametime line graph (> 20 FPS green, 15–20 orange, < 15 red). |

---

## 2. Technical Architecture

- **Zero Third-Party Dependencies:** Written in standard Python 3. Does not require Pygame, Tkinter, Xlib, PIL, or binary C wrappers.
- **Direct Core X11 Protocol:** Connects directly to `/tmp/.X11-unix/X0` (or `$DISPLAY`) via AF_UNIX socket. Authenticates with standard `MIT-MAGIC-COOKIE-1` from `$XAUTHORITY`.
- **R36S Theme & Frametime Coloring:** Deep translucent background (`TRANSPARENT_BG`), subtle dark frame, coral red `FPS`/`BATT`, sky blue `CPU`, emerald green `GPU`, orchid pink `RAM`, purple `|` separators, cyan wall AC plug icon `~`, and crisp white values.
- **Frametime Graph Color Coding:**
  - `> 20 FPS` (`< 50.0ms`): Emerald green (`rgb(70, 225, 95)`)
  - `15–20 FPS` (`50.0ms – 66.7ms`): Orange (`rgb(255, 180, 50)`)
  - `< 15 FPS` (`> 66.7ms`): Red (`rgb(255, 75, 75)`)
- **Enlarged 6×9 Bitmap Font:** Custom pixel-crafted `FONT_6X9` font engine with +55% pixel area for effortless readability on 3.5" 640×480 displays.
- **Why GPU Percentage is Low in GDI Mode:** Project Diablo 2 runs in software rasterization (GDI) mode via Box86 on the ARM Cortex-A35 CPU. The Mali-G31 GPU is only used by the Weston compositor to scan out the 2D desktop buffer to DRM/KMS. Therefore, GPU load of 0% to 15% is normal and 100% accurate.
- **Unmanaged Window (`override_redirect`):** Uses X11 `override_redirect = 1` so the window manager or Weston `kiosk-shell` does not steal input focus, resize, or unmap the game window.
- **Double-Buffered Pixmap Rendering:** Renders into an off-screen X11 Pixmap and copies the final frame in a single `XCopyArea` request. Completely eliminates tearing and flickering.
- **Standard Linux Kernel Telemetry:** Reads only from `/proc/stat`, `/proc/meminfo`, `/sys/devices/system/cpu/.../cpufreq`, `/sys/class/thermal/...`, `/sys/class/devfreq/...` and `/sys/class/power_supply/...`. Does not require root privileges.
- **Automatic Lifecycle Management:** Accepts `--pid <GAME_PID>`. When the target game process terminates, the overlay automatically cleans up and exits.

---

## 3. Directory Layout and Moving to Other Ports

The overlay is isolated in `sdcard/ports/projectdiablo2/scripts/overlay/`:

```
scripts/overlay/
├── __init__.py                # Package marker
├── performance_overlay.py     # Main executable CLI and daemon loop
├── overlay_metrics.py         # Kernel /proc and /sys telemetry collector
├── fps_tracker.py             # Frame presentation & frametime history tracker
└── x11_hud.py                 # Pure Python X11 double-buffered HUD renderer
```

### Steps to Move to Another Port:
1. **Copy the folder:** Copy `scripts/overlay/` into your target port's directory (e.g. `myport/overlay/`).
2. **Launch alongside the game:** In your port's bash launcher, after launching your main game executable in the background:
   ```bash
   # Launch game in background
   ./my_game & game_pid=$!

   # Start performance overlay (Level 1..4)
   OVERLAY_LEVEL="${PORT_OVERLAY:-2}"
   if [[ "$OVERLAY_LEVEL" =~ ^[1-4]$ ]]; then
     python3 overlay/performance_overlay.py --level "$OVERLAY_LEVEL" --pid "$game_pid" & overlay_pid=$!
   fi

   # Wait for game to exit
   wait "$game_pid"

   # Cleanup overlay (if still alive)
   [[ -n "$overlay_pid" ]] && kill -TERM "$overlay_pid" 2>/dev/null || true
   ```
3. **CLI / Headless Testing:** You can test the overlay in terminal without an X11 server by adding `--cli`:
   ```bash
   python3 overlay/performance_overlay.py --level 2 --cli
   ```
