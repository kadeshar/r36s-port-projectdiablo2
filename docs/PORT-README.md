# Project Diablo 2 on R36S / dArkOSen — Version 0.1.18

## Native 640×480 and controller casting

Fresh settings, settings without `game_resolution`, now default to **640×480 internally**, matching the LCD. Explicit saved resolutions and environment overrides remain respected; `native` still means the original **1068×600**, not LCD-native rendering. The older 800×600-only notes below describe earlier versions.

The R2/A failure at 640×480 was a stale mouse coordinate, not missing trigger input: the native controller could leave game `mouseY=547`. The original attack/skill sender rejects `mouseY > renderHeight - 49`: 547 passes at 600 pixels but fails at 480. On the R36S, changing only the temporary Y coordinate to 240 restored Charged Bolt without movement or a selected monster. The previous coordinate was restored after that diagnostic test.

The [local builder](<../sdcard/ports/projectdiablo2/scripts/native_cast.py>) redirects two native world-action calls through a 79-byte, register/flag-preserving wrapper. Only native controller mode at actual 640×480 changes Y above 431 to 240; Y=431, mouse mode and other resolutions remain unchanged. Original HUD rejection, skill validation and dispatch remain active. No input remapping, render scaling workaround, resident probe or unsafe dynarec flag is introduced.

[Layout preparation](<../sdcard/ports/projectdiablo2/scripts/layout.py>) creates the derivative locally in the user's compatibility cache, only for native input at 640×480. Source size/SHA-256, exact instruction preimages, PE structure and output size/SHA-256 must all match. Unknown sources or corrupted caches fail closed. Imported game DLLs, saves and user configurations are never patched; the payload contains Python source, not proprietary DLLs. Selecting 800×600, 1024×768 or `native` uses the original ProjectDiablo DLL.

Deploy the updated [scripts directory](<../sdcard/ports/projectdiablo2/scripts>) directly from the payload. Do not overwrite user config, game data or saves. After updating: test R2 and A outside town, enter/leave inventory and stash, recheck casting, verify the town restriction, then compare 800×600 and exit normally. The causal cursor test passed on hardware. After manual deployment, the user also confirmed R2 outside town without movement/target, ordinary A attack, and R2 after opening/closing inventory on the R36S. Stash, town restriction and the 800×600 comparison remain recommended additional checks.

### Startup failure with imported engine cache

A startup returning to Ports with `invalid_layout` immediately after `volatile_work_prepare` was reproduced on the R36S: the imported game directory contained `bncache.dat`. Layout preparation linked it as an immutable asset, then correctly rejected that link in its volatile-log safety check. Imported engine cache/log names are now skipped case-insensitively in ProjectD2; volatile sessions let Wine create fresh files in RAM, while nonvolatile preparation retains the separate launcher-managed game-state links. The original imported files and the stale-link rejection remain untouched. No cache deletion, prefix reset or safety-check bypass is needed.

The SSH repair backed up and replaced only the layout script. Isolated on-device preflight passed with the pinned native-cast DLL, unchanged persistent configuration and unchanged imported cache. The subsequent normal session reached `volatile_work_ready`, reported `640x480` and native movement, and entered the game; the user confirmed R2 worked. Thirty-nine layout tests passed, including canonical/mixed-case imported cache/log regressions in both work modes.

## Current deployment and renderer

Deploy directly from `sdcard/ports/`: copy the production launcher and updated `projectdiablo2/` payload into the existing Ports directory. **Do not build an update ZIP, delete game data, reset the prefix, or overwrite user configurations.**

The [regular launcher](<../sdcard/ports/Project Diablo 2.sh>) uses GDI with the visible menu and existing audio defaults. GDI is the only supported game renderer. Earlier GPU/GLES2, Performance GDI/OpenGL, PortMaster GLX and tuning experiments, plus optional A35 runtime selection, were removed. Remove their obsolete launcher copies from existing SD cards; copying an update does not remove old files. Keep game data, settings, prefix and saves.

The verified `CRUSTY_BLOCK_INPUT=0` DRM compositor environment remains required. Weston still handles display composition through the Mali GPU; this is not GPU offloading of the game engine. Test image, controls, sound, inventory/stash, and clean return to Ports after deployment.

## Diagnostics-1 — Current Stage: Measurement Over New Flags

[New tests A–F and log export guide](<DIAGNOSTICS-1.md>). Previous Forward512/FastFlags tests did not improve FPS, KMS/Auto remained black screens, and CALLRET failed before reaching gameplay. The new package introduces a lightweight counter without HUD overhead, granular setup stages, CPU/RAM/swap/PSI metrics, and isolated attempts for SDL → GLX/Crusty → Wine/DirectDraw. The regular launcher does not enable the new counter. We make no claims of performance improvements or working OpenGL without verified hardware testing on the R36S. The legacy tuning-1 notes below remain for historical reference.

## History: Tuning-1 — Removed Experiments

**Historical only. These profiles and test launchers are removed; archived installation, launch, and rollback instructions below do not apply to current payloads.**

Extract the `projectdiablo2-tuning-1.zip` update into the existing `ports` folder with overwrite enabled, without wiping game data, configs, or prefix. The update does not replace Wine/Box86 or game data. The standard launcher continues to work as before. Each new test uses: **800×600, BIGBLOCK=1, FPS ON, bypassing port menu**, with diagnostic sampling every 5 s. Selecting an entry launches the game immediately. To disable the HUD overlay, change `${PD2_FPS:-1}` to `${PD2_FPS:-0}` in the launcher script; always compare identical counter settings.

| Test in Ports | Change relative to baseline |
|---|---|
| **Test 1 GDI Baseline** | Baseline: FORWARD=128, CALLRET=0, SAFEFLAGS=1. |
| **Test 2 GDI Forward512** | Only FORWARD=512: larger lookahead for downstream dynarec blocks. |
| **Test 3 GDI CallRet RISK** | Only CALLRET=1. May conflict with self-modifying code. |
| **Test 4 GDI FastFlags RISK** | Only SAFEFLAGS=0. Can cause silent runtime bugs. |
| **Test 5 OpenGL KMS** | Crusty SDL receives kmsdrm instead of x11; requires functional ARM32 KMS. |
| **Test 6 OpenGL Auto** | Like Test 5, but without forcing SDL_VIDEODRIVER; SDL auto-selects backend. |

**Recommended sequence: 1 → 2 → 5 → 6. Tests 3 and 4 are optional and risky: back up saves/prefix, test only on throwaway characters.** We do not combine CALLRET and FastFlags or enforce them on the standard launcher. We do not alter global governor, clock speeds, device permissions, or x87 precision. We make no guarantees of increased framerates.

Both new GL tests additionally set upstream `XDG_SESSION_TYPE=x11` (this does not force the SDL backend) and `SDL_VIDEO_EGL_DRIVER` pointing to a verified ARM32 EGL library. Changes apply strictly to Wine/Box/Crusty, not the native mapper/Python or AArch64 Weston. Both GL tests share all other settings, isolating the SDL backend change. Compared to the older Performance OpenGL entry, several items differ: BIGBLOCK/FPS, library verification, and the EGL environment.

Before starting GL, ARM32 SDL/EGL/GLES/GBM/DRM are verified: `graphics_probe` entries with `arch=armhf`. `ready` denotes finding valid library architecture and rejecting proxies, **not the creation of a GPU context**. `client_drm_access` merely verifies that the game user can open `card0`; it does not confirm DRM master status or scanout capability. We never run Wine as root.

Logs report `tuning_profile` and — when exposed by firmware — `cpu_freq_khz`, `cpu_max_freq_khz`, `gpu_freq_hz`, `gpu_max_freq_hz`, temperature, and free RAM. Max values are sysfs-reported limits, not physical clock guarantees. The clock rate alone does not measure load or prove a bottleneck. Missing values indicate an omitted field, not zero. Logs do not record character names or raw traces.

For each variant: same character/zone/player count, 30 s warmup, 60 s stationary, 60 s combat, then a few minutes post-warmup. Note FPS and whether video, gamepad, audio, inventory/stash function properly. Submit the log and test name. If GL remains a black screen, do not modify drivers or wipe the prefix. `xwayland_software_fallback` alone does not prove the game is rendering on CPU — Crusty's direct path is separate.

Rolling back without uninstalling: select the normal entry. Complete code rollback: overwrite with preserved 0.1.18 package and delete only the six new Test entries from Ports (ZIP overwrite does not delete extra files), leaving the game folder untouched. Helper files left after rollback are not invoked by older code.

Sources: [WestonPack — ArkOS/Mali modes, headless, and SDL/Crusty](https://github.com/binarycounter/Westonpack/wiki), [Box86 — Option documentation and risks](https://github.com/ptitSeb/box86/blob/fa59e74/docs/USAGE.md). These references describe the stack on similar hardware, not game-specific benchmarks. Local test passes do not substitute for R36S hardware validation.

## History: 0.1.18 — Removed Experimental Performance Profiles

**Historical only. Both Performance launchers and their profiles were removed. Following notes describe past releases, not current instructions.**

This update adds two separate entries in Ports; the normal `Project Diablo 2.sh` retains existing behavior. We do not promise an increase from 10–15 to 25/30 FPS without R36S hardware measurement.

- **Project Diablo 2 - Performance GDI.sh** — Existing GDI path, default 800×600, FPS OFF, and experimental larger Box86 blocks (`BIGBLOCK=2`). Start with this variant.
- **Project Diablo 2 - Performance OpenGL.sh** — Same CPU settings and full OpenGL profile (including matching Weston/Crusty), with Nearest Neighbor scaling. It may reduce presentation load, but could also run slower, yield a black screen, or cause cursor/color glitches. It does not guarantee GPU offloading or move the game engine to the GPU.

In both variants, the menu still allows changing resolution and toggling FPS. Recommended settings for normal play: **800X600 / FPS OFF**; the counter copies the surface on every frame and incurs overhead. Performance renderer settings are session-only, built from the port template without writing to the user INI. Other game settings save normally. Audio, controller mapping, Wine/Box86 runtimes, game data, and saves are not replaced or reset.

`BIGBLOCK=2` over previous `1` is an experiment: potential increased memory consumption and instability with self-modifying code. Revert to the standard launcher in case of crashes. To test backend changes without BIGBLOCK=2, change `${PD2_BIGBLOCK:-2}` to `${PD2_BIGBLOCK:-1}` in the Performance launcher. Risky flags such as `SAFEFLAGS=0`, `CALLRET=1`, aligned mutexes, and relaxed x87 precision remain disabled. Dynarec was already enabled by default previously.

### Installation and Rollback

1. Close the game and make a backup of your character saves.
2. Extract the 0.1.18 ZIP into the **same ports directory** with overwrite. Do not delete the game folder, configuration, prefix, or runtime. The update contains no game assets.
3. Launch **Performance GDI**, then **Performance OpenGL**. The normal entry provides an immediate rollback without editing settings.
4. Full code rollback: extract preserved 0.1.17 ZIP. The two new Performance entries remain after simple overwrite — remove those two launcher scripts, not the game folder.

### Comparison on R36S

For the regular entry and both Performance variants, choose **800X600 and FPS ON**. Use the same throwaway character, same zone, player count 1: 30 s warmup, then 60 s standing still and 60 s combat. Record FPS range and stability; verify inventory, stash, mouse cursor, analog sticks, and audio. Then play a few minutes with FPS OFF to monitor temperature and stability under sustained load. To isolate renderer changes, re-run both Performance profiles with BIGBLOCK=1.

If game visual settings are not already set low: disable perspective and blended shadows, set lighting quality to low; do not change arbitrary JSON values blindly. The port template already applies these low values. 640×480 is strictly display output, not internal game resolution. We do not inject risky 640×480 UI patches. Do not decrease `maxgameticks` — it alters game simulation speed, rather than fixing framerates. Presentation cap remains 30, not a forced target.

Safe logs include `performance_profile=off/gdi/opengl` and `dynarec_bigblock=1/2`; the selected profile does not prove hardware acceleration. If issues arise, provide log export and screenshot. No overclocking, global governor alterations, or driver modifications are introduced.

References: [Box86](https://github.com/ptitSeb/box86/blob/fa59e74/docs/USAGE.md), [cnc-ddraw 7.1](https://github.com/FunkyFr3sh/cnc-ddraw/blob/v7.1.0.0/src/config.c).

The following section covers the base launcher and 0.1.17 history.

## Main Game Launcher — Project Diablo 2.sh

In version **0.1.17**, the single entry point in `ports/` is `Project Diablo 2.sh`.
The launcher starts a themed Diablo II menu (`PROJECT DIABLO II / LORD OF DESTRUCTION - R36S`):

- **RESOLUTION:** explicitly displays **800X600** on launch (or another resolved launcher setting). The first option inherits launcher configuration without overriding; subsequent options allow choosing NATIVE 1068X600, 800X600, and 1024X768.
- **FPS COUNTER:** default **OFF**. When set to **ON**, the counter appears in the top-left corner without hotkeys or chat commands. It tracks renderer frames, not game logic ticks or display refresh rate. It initially displays `FPS: --`, updating with numbers once the first sample window elapses. OFF keeps the original, unmodified renderer.
- **Stable Display:** retains off-screen composition and single-copy blits; the menu avoids clearing or redrawing when idle.
- **ENTER SANCTUARY / LAUNCH:** immediate game start with chosen options.
- **EXIT TO SYSTEM:** returns to PortMaster / system shell.
- **Working ALSA Audio:** modified ARM32 ALSA path with rk817 routing runs in the background by default, without manual setup and without opening the audio probe window (`pd2-audio-probe.exe`). Only `Game.exe` is launched.

**D-Pad/Arrows**: row navigation and value toggle. **A/Start/Enter**: confirm. **B/Select/Esc**: cancel and return to Ports. Release buttons after entering.

From 0.1.17 onward, no background keyboard helper or secondary Wine virtual desktop is started. The optional cnc-ddraw build with FPS overlay is authenticated and staged only within the ephemeral session directory before game launch. The original library, assets, and saves are unmodified. If staging fails, the game falls back to the stock renderer, logging `fps_counter=unavailable`.

The counter does not require waiting 10 s or pressing **Select+R3/F10**. It does not send `/fps` to chat, nor capture gamepad or keyboard input. 1024×768 renders ~64% more pixels than 800×600. Performance impact of the overlay requires on-hardware confirmation.

The **Test mode always presents the menu and awaits user selection** before starting the game. The menu is an X11 core protocol client implemented in Python (without SDL, Xlib, pygame, or Qt dependencies), running against the private Xwayland/Weston session. It confirms window mapping before processing inputs. Release the entry button from Ports, select your options, and press **A/Start/Enter** on LAUNCH. **There is no automatic launch, timeout, or silent error fallback.** Cancel exits without launching; errors halt execution and record a bounded code. Default RES/FPS inherit main launcher settings.

## Audio Testing Without Prefix Reset

`Project Diablo 2.sh` defaults to working audio using a local ARM32 ALSA library and background rk817 routing. Audio test options and synthetic tone tests have been removed from the menu — the game starts directly with sound enabled. A grayed-out Sound Settings menu indicates missing Wine audio endpoints rather than an intentional mute. Successful registry keys or accessible device nodes do not guarantee audible output.

AUDIO TEST ON additionally records: `audio_driver` (`loaded` indicates ALSA channel activity, not verified playback — logs with `WINEDEBUG=+alsa` to RAM with size caps, not writing to SD; failure carries bounded `detail`: `no_log`/`silent`/`libasound`/`load_error`/`alsa_error`/`unknown`/`capture_error`/`capture_timeout`), `audio_control` (/dev/snd/controlC* access), and `audio_fallback`. If initial rk817 routing fails, fallback is logged as `attempted` and retried via default routing; success logs `skipped`. Operations are strictly diagnostic — without mixer, permission, or system file modifications.

Revision is tracked via event `audio_diagnostics: legacy_v7`. AUDIO TEST ON selects local ARM32 alsa-lib 1.2.8 with legacy time32/SYNC_PTR ABI (132 bytes, ioctl `0xC0844123`, replacing rejected `0xC0884123`). The library is SHA-256 authenticated, copied to private RAM, and prepended to ARM32 library search paths after stopping Wine. It is used by native ARM32 probes and Wine/Box86; AArch64 tests retain 64-bit libraries. `audio_library: legacy_armhf` confirms activation; `unavailable` indicates existing paths were kept. System libraries, kernel, and mixer remain untouched.

`audio_syscall_library` with `arch: armhf` and `status: legacy_armhf` confirms observed runtime opening under strace without exporting filesystem paths. Source code and license are bundled in `compat/alsa-legacy-armhf/alsa-lib-1.2.8.tar.bz2` and `licenses/LICENSE-alsa-lib.txt`. Requires ARM32 glibc >= 2.29.

Both attempts (rk817 and optional default fallback) capture `+alsa`. The collector writes up to 256 KiB in RAM, draining excess output. Results are parsed after Wine terminates, with a 3 s collector join timeout. `capture_timeout` and `capture_error` denote diagnostic issues rather than confirmed driver crashes. `silent` requires an explicit marker. Node access alone does not prove audible sound.

Before Wine execution, a small native ARM32 binary runs directly (without Box86) under the same user, namespace, `ALSA_CONFIG_PATH`, and ARM32 paths. It loads `libasound.so.2` dynamically and invokes nonblocking `snd_pcm_open` for `default` and detected `plughw`. Successful opens close immediately without setting hardware parameters or writing PCM data. Execution timeout is 8 s. The binary is verified via SHA-256 and run from RAM.

- `audio_native_armhf: ready` indicates the test loaded the library and returned a report — not that PCM opening succeeded. Other statuses: `timeout`, `failed`, `missing`, `tampered`, `library_missing`, `symbol_missing`, `unsupported`.
- `audio_native_default` and `audio_native_plughw`: `ready` indicates successful PCM open; failures report error class and `alsa_rc`. `not_run` for plughw denotes ambiguous card/device detection.
- If native ARM32 also yields `-25`, the issue reproduces outside Box86. If ARM32 opens PCM while Wine fails, the root cause is isolated to Wine/Box86 or ALSA usage patterns. Successful PCM open still does not prove audible playback.

The same test is run as native AArch64 with 64-bit libraries: `audio_native_aarch64`, `audio_native64_default`, `audio_native64_plughw`. Baseline results run without tracing. A secondary run of each architecture under strace 6.1 tracks `open`, `openat`, `ioctl`, `close`. The AArch64 tracer receives a 64-bit environment, passing ARM32 paths only to children. Each run has an 8 s limit.

- `audio_syscall_trace`: field `arch` (`armhf`/`aarch64`) and status `complete`, `limited`, `not_observed`, `denied`, `unavailable`, `timeout`, `missing`, or `tampered`. ptrace denial does not denote audio failure and does not block gameplay.
- `audio_syscall_open`: requested path category `node` (`pcm`/`control`), `syscall_rc`, and file descriptor `fd` upon success.
- `audio_syscall_ioctl`: `arch`, `node`, `fd`, numeric `request`, `syscall_rc` (e.g., `-25`), and device attributes. `node: unknown` indicates ambiguous descriptor association.

Raw traces are held strictly in an in-memory ring buffer (256 KiB); logs record at most 64 unique observations per trace. Full paths, PIDs, addresses, and buffer payloads are excluded. Unmodified strace source is included in `compat/alsa-native/strace-6.1.tar.xz` with notice in `licenses/LICENSE-strace.txt`.

Wine 8.0 enumeration diagnostics (per probe report):
- `audio_alsa_capture`: `complete` / `limited` / `unavailable`.
- `audio_alsa_default` and `audio_alsa_plughw`: observed open attempts or failure classes.
- `audio_alsa_control`, `audio_alsa_cards`, `audio_alsa_devices`: access warnings for control and card/device enumeration.
- `audio_alsa_stream` and `audio_alsa_params`: PCM stream open and parameter configuration errors.
- `audio_alsa_endpoint`: `render_seen` / `capture_only` / `not_observed` — trace of endpoint naming in winealsa, not verification of Windows audio registration.

Error classes: `busy`, `denied`, `missing`, `invalid`, `unsupported`, `other_error`. Recognized numeric ALSA codes are logged under `alsa_rc` (signed 32-bit integer). Unrecognized codes are not set to zero. `not_observed` means no message matched, not confirmed absence of devices. Card indices, device strings, and message text remain in RAM only.

Test FPS ON + AUDIO TEST OFF first, then FPS OFF + AUDIO TEST ON. Verify audio output and Sound Settings; if grayed out, send the latest log from the port's logs directory. Do not wipe the prefix or remove configs.

The main `ports` directory should contain only `Project Diablo 2.sh`. When updating an existing installation, remove obsolete launchers: `Project Diablo 2 - Native Controller.sh`, `Project Diablo 2 - Controller Test.sh`, `Project Diablo 2 - Native 800x600.sh`, `Project Diablo 2 - Native 1024x768.sh`, and `Project Diablo 2 - Audio Test.sh`. Extracting the ZIP does not delete obsolete files automatically. Do not delete `projectdiablo2` or its helper scripts.

Gamepad mappings from 0.1.13 remain unchanged. Video settings are managed within the Test menu; older instructions below are preserved for historical context.

## History: 0.1.13 Fix — Select, Start, L3, R3, and Menu

Screenshots and logs from 0.1.12 confirmed all 17 physical presses and releases. In XInput, Select, Start, L3, R3, and Menu were missing. The root cause was incorrect or missing mappings in the mapper; physical hardware events fired correctly.

| Button | Confirmed Physical Code | Target Xbox Button |
|---|---|---|
| Select | `0x2c0` | Back |
| Start | `0x2c1` | Start |
| L3 | `0x2c2` | Left Thumb |
| R3 | `0x2c3` | Right Thumb |
| Menu/FN | `0x2c4` | Guide |

Only these five inputs were modified. A/B/X/Y, L1/R1, L2/R2, D-Pad, analog sticks, test tools, and runtime remained identical. **XInput behavior requires on-device validation.** No system Start+Select hotkey was added.

## Button Test — Step-by-Step Verification

Controller Test from 0.1.12 guides sequentially through **A, B, Y, X, Start, Select, Menu, L1, L2, L3, R1, R2, R3, Up, Down, Left, Right**. The test does not alter or store mapping profiles. Version 0.1.13 introduces the five mapper corrections described above.

1. Close the port, back up saves, and extract current ZIP 0.1.17 to the same `ports` directory with overwrite. Do not delete game files, saves, configurations, or prefix.
2. Launch **Project Diablo 2 - Controller Test**. Release all buttons initially.
3. Read the **STEP** line: you have **6 seconds** per button for each of the 17 inputs. Press and release **only the specified button**; do not press multiple buttons together. The test progresses automatically.
4. **L3/R3 is clicking the left/right analog stick**, not tilting. If an analog does not click physically, do not force it and report accordingly. **Menu** corresponds to the dedicated Menu/FN button, not Start/Select. Test Up/Down/Left/Right via D-Pad, not analog.
5. After 102 seconds, **SUMMARY** displays for ~**20 seconds**. Take a clear photo of the table; the test terminates automatically after ~**122 seconds**. Send the photo and latest safe log. If multiple buttons were pressed during a single step, rerun the test.

Each row features independent columns:
- **Physical** — Whether the physical pad registered press and release during the step; also catches unhandled codes without guessing mappings.
- **XInput** — Whether the expected Windows button pressed and released during the step. Physical=passed and XInput=not_seen indicates a missing or misconfigured translation, not broken hardware.

Results: **passed** = pressed and released; **pressed** = detected press without release; **not_seen** = no fresh press observed; **multiple** = multiple keys or lost events, ambiguous; **unavailable** = missing data. **unsupported** next to Menu indicates lack of XInput Guide extension (ordinal 100), not broken Menu input.

Hex codes shown on screen are purely visual aids to identify unknown mappings. Safe logs retain only closed enums for named inputs (`physical_button_*`, `xinput_button_*`), without raw event streams. Under gptokeyb fallback, Physical column may show unavailable. The bundled mapper does not include a Start+Select combo; exit via game menus.

The 45-second test instructions below pertain to legacy versions.

## Controls 0.1.11 — Built-in evdev→uinput Mapper (Controller Test Fix)

User testing on 0.1.10 showed `XINPUT1_4.dll: ready`, `Connected now: 1/4`, and `Movement: left yes`, but buttons/right/triggers remained `no` despite input activity. This confirmed device detection and left analog input, but incomplete XInput mapping.

0.1.11 introduced the bundled [xbox_mapper.py](<scripts/xbox_mapper.py>) mapper (Python standard library): bypassing SDL, reading `GO-Super Gamepad` (`484b:1100`) evdev events, and creating a virtual `Microsoft X-Box 360 pad` (`045e:028e` v`0104`) via `/dev/uinput`. The downstream winebus→Wine XInput path remained intact.

Standard mapping specification:

| Gamepad Input | XInput |
|---|---|
| A (`0x131`) / B (`0x130`) / X (`0x133`) / Y (`0x134`) | A / B / X / Y |
| L1 (`0x136`) / R1 (`0x137`) | LB / RB |
| L2 (`0x138`) / R2 (`0x139`) — digital | Z/RZ axes → LT/RT: released 0, pressed 255 |
| Select (`0x13a`) / Start (`0x13b`) | Back / Start |
| D-pad (`0x220–0x223`) | Digital hat |
| FN (`0x2c0`) | Guide (MODE) |
| Left / Right analog | Left / Right stick (full range, deadzone ±8000 of ±32767) |

If the bundled mapper fails to initialize (e.g., `/dev/uinput` permission denied), the port records `controller_mapper=fallback` and reverts to PortMaster gptokeyb. Diagnostic probes, the 45-second test, and cleanup routines remained unchanged; the standard **Project Diablo 2** keyboard/mouse entry was unaffected.

### Legacy 45s Test Instructions (Current 17-Button Test Described Above)

1. Close the port, back up saves, and extract the update ZIP into the same `ports` directory with overwrite. Do not wipe `gamedata`, runtime, configs, prefix, or saves.
2. Launch **Project Diablo 2 - Controller Test**.
3. Over **45 seconds**, press and release **each button individually**: A, B, X, Y, L1, R1, L2, R2, Select, Start, and FN; test each D-Pad direction, both analog axes, and triggers. Expected results: `XINPUT1_4.dll: ready`, `Connected now: 1/4`, `Seen: device yes / buttons yes`, `Movement: left yes / right yes`, and LT/RT toggling 0↔255. Verify physical input alignment with the table, absence of stuck inputs, and stick centering.
4. Photo the window, await automatic exit to Ports, and submit the photo with the latest log from `projectdiablo2/logs`. `controller_mapper=ready` + `mapper_layout=standard` denotes mapper readiness, **not verification of input mapping or physical layout**; `controller_mapper=fallback` denotes gptokeyb execution.
5. Only after confirming inputs, run **Project Diablo 2 - Native Controller** and test navigation, movement, loot, and casting on a throwaway character; exit via in-game menu.

The built-in mapper **does not implement Start+Select as a system exit shortcut**. Controller Test exits automatically after 45 s; exit games via in-game menus.

Safe `session_probe` events (phase `launch`):

| check | status | Description |
|---|---|---|
| `controller_mapper` | `ready` | Built-in mapper active: virtual Xbox pad created directly from evdev stream. |
| `controller_mapper` | `missing` | Supported GO-Super physical pad not detected. |
| `controller_mapper` | `denied` | Permission denied accessing pad or `/dev/uinput`. |
| `controller_mapper` | `invalid` | Unrecognized layout or read error. |
| `controller_mapper` | `fallback` | Built-in mapper failed; port falls back to gptokeyb. |
| `mapper_layout` | `standard` | Active GO-Super input codes. |

No global permissions modifications, root Wine execution, or driver installations. Probing logic and winebus flags remain unchanged. **Rollback:** after full session shutdown, overwrite port with preserved [0.1.10 ZIP](<../../../dist/projectdiablo2-port-update-0.1.10-rollback.zip>), keeping data, runtime, configs, prefix, and saves. SHA-256: `05c067f7a4025791a99fc286d1089814cb9caf77c33bd04869d4d2481d03e355`.

## History: Controls 0.1.10 — Real Windows XInput Test

Console reporting confirmed `GO-Super Gamepad` (`484b:1100`), four axes, SDL GUID `1900bb3e4b4800000011000000010000`, O_RDWR access, and controller detection in SDL. The user previously ran PD2 with functional pad controls through LineageOS/Winlator on this hardware. This diagnostic investigated the Linux/Wine/Box86 pipeline rather than assuming game incompatibility.

### What the Test Changed

Native Controller and Controller Test generated a virtual Xbox pad via gptokeyb prior to Wine initialization. Then they explicitly selected Wine's private evdev/udev backend: `HKLM\System\CurrentControlSet\Services\winebus`, DWORD `Enable SDL=0`, `DisableInput=0`, `DisableUdevd=1`. The latter selects an inotify monitor without depending on the host udev daemon inside the mount namespace. Restarting prefix wineserver is necessary, as flags are evaluated at winebus startup. Disabling SDL was deliberate — bundled Wine lacks the SDL backend.

Previous DWORDs (or their absence) were preserved before modification. Following game/test exit, the port restored them, restarted wineserver, and cleared the marker upon success. If cleanup was interrupted, subsequent runs re-attempted restoration. Do not manually edit or remove `pd2-winebus-restore.reg` in the private prefix. Before rolling back to older code, launch and close standard 0.1.10 to finalize any pending restores.

Safe `session_probe` event definitions:

| check | status | Description |
|---|---|---|
| `virtual_gamepad` | `ready` | New virtual Xbox exists and is accessible in Linux; not yet proof of XInput. |
| `winebus_backend` | `udev` / `restored` | Backend configured and Wine restarted / old flags restored. |
| `xinput_api` | `ready` / `library_missing` / `entry_missing` | Library and entry point loaded / missing library / missing export. |
| `xinput_devices` | `ready` / `missing` / `error` | At least one connected slot / no slots / API error. |
| `xinput_buttons`, `xinput_axes` | `changed` / `unchanged` / `unavailable` | Input changed from initial sample / unchanged / device absent. |

Summaries are created in the ephemeral session directory, validated against a strict schema, and routed to the safe log. **Host PC testing with synthetic DLLs does not validate Wine/ARM or R36S hardware.** Standard **Project Diablo 2** remains the fallback keyboard/mouse mapper with L1=Alt.

## History: Controls 0.1.9 — Virtual Xbox 360 via udev

In 0.1.8, native pad input failed in user testing. Bundled Wine 8 includes a udev backend, but **lacks the compiled SDL controller backend**. In 0.1.9, **Project Diablo 2 - Native Controller** launched `gptokeyb xbox360`: physical R36S pad → PortMaster SDL mapping → virtual Xbox 360 → Wine/udev → PD2.

### How It Was Tested on R36S

1. Back up saves, close port, and extract update ZIP to the same `ports` directory. Do not delete prefix, config, or game files. Requires PortMaster gptokeyb with `xbox360` support and user access to uinput and pad events.
2. Launch **Project Diablo 2 - Controller Test**. Opens the Wine `joy.cpl` applet in the same prefix/environment as PD2, **without starting the game**. Navigation mapper was active only in the panel: right analog moves cursor, A clicks, B = Esc, Start = Enter, R2 slows cursor.
3. Check if list displays **Microsoft X-Box 360 pad** (or equivalent Xbox pad name in Wine). Select it, open Properties/Test, and test analog sticks and buttons. Presence on HID/DirectInput list does not prove XInput operation.
4. Close test, then launch **Project Diablo 2 - Native Controller**. On a throwaway character, test movement, L1 for loot display, and spell direction changes.
5. If port returns to menu prior to opening panel or list is empty, submit latest log and photo. In logs, `session_probe / virtual_gamepad` indicates: `ready` — virtual Xbox pad exists in Linux and can be opened O_RDWR; `missing` — not created within 5 s; `denied` — access denied; `invalid` / `unavailable` — preflight failure. **`ready` does not prove Wine enumeration or XInput functioning.** Do not use `chmod 666` or run Wine as root.

The virtual Xbox device is created before the first Wine process; the port waits up to 5 s and halts if checks fail. The probe does not record button inputs or event streams. The device unregisters when the mapping process exits.

**Rollback:** launch standard **Project Diablo 2** (mapper, L1=Alt); no need to modify JSON or delete prefix. **Select+Start** performs an emergency session shutdown with risk of losing unsaved progress.

Mechanism derived from [gptokeyb](https://github.com/PortsMaster/gptokeyb#use); [Xbox device implementation](https://github.com/PortsMaster/gptokeyb/blob/main/src/xbox360.cpp). Similar Box86/Wine behavior documented in [#809](https://github.com/ptitSeb/box86/issues/809).

## History: Controls 0.1.8 — Two Distinct Ports Entries

* **Project Diablo 2 - Native Controller**: Experimental native PD2 pad mode. Session flags `controller_movement=true`, `wasd_movement=false`; mapper generates no WASD, clicks, or cursor motion. Movement, loot, and casting directions are managed by the engine. Wine global configuration, drivers, and device permissions remain unmodified. Native pad detection in Wine/PD2 **requires R36S hardware testing**, and does not follow from SDL mapper operation. `swap_ab` applies solely to the mapper, not native pads.
* **Project Diablo 2**: Traditional keyboard/mouse mapper and straightforward fallback without editing JSON. **L1 = hold Alt to display loot labels** (replaces former F1). Spells target the cursor position rather than native directional targeting.

Extract update into the same `ports` directory, overwriting port files; retain game assets, config, prefix, and saves. Refresh Ports list if the second entry does not show. Back up saves and test on a throwaway character. Run Native Controller, test menu navigation, movement, L1 over dropped items, and spell aim following direction changes. Lack of response indicates failed native input test, not reason to delete prefix. **Select+Start** acts as emergency exit for this session, risking unsaved progress. If unresponsive, use firmware reset hotkey. Next launch with standard entry reverts to mapper.

Movement flags are overridden solely in the ephemeral session copy; synchronization preserves original values in persistent JSON, writing other game setting changes normally. Log `movement_mode` records the active mode, **not XInput device detection**.

## Video 0.1.7 — Experimental True 4:3 (800×600)

In 0.1.6, saves and menu functionality were verified, but gameplay rendered in widescreen letterbox with black bars, with in-game resolution selection unavailable. Byte-level analysis of bundled `SGD2FreeRes.dll` confirmed this build **forces 1068×600 internally** (fixed resolution vector and enforcing parser); `Ingame Resolutions`/`Ingame Resolution Mode` keys in `SGD2FreeResolution.json` are nonfunctional in this build, making JSON edits ineffective.

Version 0.1.7 created a **locally hashed, pinned copy** of the DLL with two 4-byte modifications (changing width 1068 → 800 in two constants) in private device storage, mounting this copy into the session directory instead of the original. **Original game data, saves, and prefix were untouched**; the update ZIP **contained no game DLLs**. On every 800×600 launch, the port verified the original via size and SHA-256, rejecting unknown versions before launching the game.

Display pipeline: **game 800×600 → cnc-ddraw 7.1.0.0 → 640×480**, full 4:3 without black bars. Before updating, back up saves and test on a new character: verify inventory, stash, vendor menus, skills, potion belt, and cursor click alignment.

**Reverting to 1068×600 with black bars without reset:** in `config/settings.json`, set `"game_resolution": "native"` (leaving other keys untouched) and exit the port before launching. Does not require clearing cache or resetting prefix; original DLL remains intact. Full code rollback: [0.1.6 ZIP](<../../../dist/projectdiablo2-port-update-0.1.6-rollback.zip>).

## History: Saves 0.1.6 — Confirmed Working

User feedback confirmed correct scaling in 0.1.5, along with working analog sticks, A/B, and X/Y. After deploying 0.1.6, the user confirmed **saves were visible and menus operated correctly**.

Version 0.1.6 **did not modify video rendering, wrapper, or controller mappings**. It unified save location resolution: set registry `Save Path` to `S:\` in existing prefix and migrated `classic_game_settings.other.save_path` to `S:\` in the active JSON once. Backups of modified JSON were retained in `config/backups/ProjectDiablo.json.save-path-v1.bak` without overwriting WASD/controller flags. Marker `config/.save-path-v1.json` tracks completed migration. Character saves are never copied, converted, or relocated by the updater.

The game launches on the same virtual desktop `PD2Native,640x480`, with explicit working directory enforced via `start.exe /d ... /exec ...`.

Save file visibility was confirmed by the user following this update.

## History: Video Update 0.1.5

User screenshots confirmed reaching the PD2 menu, but with cropped visuals. This version maintained **1024×768** game rendering while utilizing standalone **cnc-ddraw 7.1.0.0** to downscale to **640×480** before Wine/Xwayland/Weston. The Wine virtual desktop and Crusty were updated to 640×480.

On first launch, display configurations for both profiles underwent one-time migration with backups. Game files, original DirectDraw libraries, saves, and prefix were not deleted or overwritten. The standalone library was placed in [compat](<compat/cnc-ddraw/manifest.json>), linked only within the session work directory.

### History of Early Fixes (0.1.0–0.1.4)

**This is not an official ARM port or approved PortMaster release.** It is a private launcher: Box86 ARM32 → Wine 8.0 x86 → PD2 `Game.exe -ddraw`, utilizing WestonPack/Xwayland. Initial user testing on R36S exited back to EmulationStation prior to the Wine/game phase. Version 0.1.1 addressed unsupported `seatd -s`, isolated the default socket in private `/run`, and added setup stages to the safe log. Version 0.1.2 addressed cwd mount blocking, verified genuine SDL/EGL and their architectures, allowed upstream library naming, isolated SDL from unconfigured DISPLAY/Wayland, and executed the compositor as root per WestonPack standards (Wine/Box86/Windows game remain standard unprivileged user). Log records only enums of library probes and Weston stages, without raw traces or paths. Version 0.1.4 added private Xauthority with session-scoped MIT-MAGIC-COOKIE-1 for root Xwayland and a local protocol response test executed as the game user, distinguishing file and abstract sockets instead of depending on Xlib's `xdpyinfo`. It isolated permissions, refusal, timeout, authentication, invalid responses, and lazy Xwayland start/crash. Only private root-owned X0 socket receives user group and 0660 mode; compositor runtime remains 0700. Log 0.1.3 confirmed rejection of empty authentication by active Xwayland; 0.1.4 passed private cookie. Update strictly via port ZIP; never re-copy game files or runtime, and do not reset prefix.

## 1. Initial Installation — Game Data One-Time Setup

1. Update PortMaster on dArkOSen. Required: aarch64 OS with ARMHF support, Python 3, sudo, mount/squashfs, unshare, runuser, timeout, flock, and DRM/uinput access. Firmware should provide ARMHF SDL2/ALSA/udev/freetype. The port installs no system packages or binfmt handlers.
2. Exit the game and back up existing characters. The PC preparation copy **does not import Windows saves or accounts**.
3. Copy the **contents of `sdcard/ports` from the prepared package** into the `ports` directory on the ROM partition (EASYROMS; `/roms/ports` or `/roms2/ports`). This creates the [launcher](<../Project%20Diablo%202.sh>) and neighboring `projectdiablo2` directory. Do not copy tools, tests, cache, or `.state` directories from PC.
4. Game data in `gamedata/Diablo II` is copied once from a legitimate Diablo II + LoD + PD2 installation. Do not relocate it. Never distribute game data or CD keys.
5. In the **Ports** menu, launch Project Diablo 2 as standard firmware user (`ark`). Do not run the launcher as root. On exFAT, execute permissions are handled by firmware mount flags; on ext4, ensure execute permissions are set on the launcher.
6. The initial launch extracts runtimes into private Linux storage, initializes the win32 prefix, and installs signed VC++ x86. This may take several minutes. **Do not power off the device.** Subsequent launches skip installation.
7. Select **Single Player**, create a new character, and verify gameplay before transferring valuable saves. Do not use Battle.net, .NET launcher, PD2 updater, or PlugY.

Maintain at least ~1 GB free space in Linux storage for runtime/prefix, plus reserve SD space for saves. The prefix requires Linux/ext4 filesystem semantics and symlinks: **do not move it to FAT/exFAT**. The runtime is bundled in initial installation; no further downloads on device are needed.

## 2. Data and Settings Locations

| Component | Device Path |
|---|---|
| Single copy of EXE/DLL/MPQ and CD keys | `ports/projectdiablo2/gamedata/Diablo II` |
| Active configuration | `ports/projectdiablo2/config` |
| Characters, stash, and maps | `ports/projectdiablo2/saves` — mapped in Wine as drive `S:` |
| Bounded diagnostic logs | `ports/projectdiablo2/logs` |
| Wineprefix and extracted runtime | `$HOME/.local/share/pd2-r36s` |

During gameplay, game data is mounted **read-only**. The working directory contains symlinks to the single data copy, avoiding duplicated MPQ sets. Engine diagnostic dumps in the working directory route to a bounded 16 MiB tmpfs, discarded upon session exit. Only six validated configuration files synchronize back; one previous version is archived in `config/backups`. Saves on `S:` are persistent and do not depend on tmpfs.

The prefix is private Wine state — it contains the registry and installer artifacts. It is not intended for redistribution. Do not modify directories or settings while the game is running.

## 3. Historical Video and Performance (0.1.7)

**Archived settings below are not current configuration instructions. Current launches use GDI only; the old `opengl` profile and OpenGL template were removed. See current deployment above.**

Defaults from 0.1.7: **800×600** game rendering (local copy of SGD library; see above), Wine desktop / Crusty / output **640×480** (R36S 4:3 screen), **GDI** renderer, presentation cap **30 FPS**, no shaders. cnc-ddraw 7.1.0.0 handles borderless downscaling: `windowed=true`, `fullscreen=true`, `maintas=true`, `adjmouse=true`, `inject_resolution=1024x768`. `maintas` preserves aspect ratio, filling the 4:3 screen, while original DLL (~16:9, 1068×600) letterboxes. `adjmouse` recalculates cursor positioning for scaling. In this PD2 build, in-game resolution selection is inactive, and `SGD2FreeResolution.json` does not affect gameplay — display output is governed by `game_resolution` in `config/settings.json`. Compatibility of 800×600 and framerates require hardware validation. The limit is not a 30 FPS guarantee and does not alter Diablo II simulation ticks. No Vulkan, DXVK, or D2GL.

Following initial start, `config/settings.json` supports:

```json
{
  "schema_version": 1,
  "profile": "gdi",
  "swap_ab": false,
  "game_resolution": "800x600",
  "metrics": false
}
```

* `game_resolution: "800x600"` — Default in 0.1.7; full 4:3 via locally pinned SGD library copy.
* `game_resolution: "native"` — Original game data DLL; 1068×600 letterboxed image. Revert without clearing cache or resetting prefix.
* `profile: "opengl"` — Alternative experimental GL4ES/Crusty GLX + headless Weston; test only after GDI. A black screen does not indicate corrupt game data. Reverting to `gdi` does not reset prefix or saves.
* `swap_ab: true` — Swaps A/B functionality if firmware mapping is reversed. Does not alter firmware settings.
* `metrics: true` — Appends numeric metrics every 5 seconds: available RAM, storage, and temperature when exposed. A single startup measurement occurs even if `false`.

Templates for [GDI](<defaults/ddraw-gdi.ini>) and [OpenGL](<defaults/ddraw-opengl.ini>) are copied when configuration is generated. One-time 0.1.5 migration altered only designated video keys in `[ddraw]` across active profiles, preserving comments and sections with backups. The normal entry sets `wasd_movement=true` and `controller_movement=false` for the session, while Native Controller sets the inverse; both modes are never enabled simultaneously.

## 4. Controls

Button identifiers reference SDL/PortMaster mappings; dArkOSen may already swap A/B. Fn/R3 serve as firmware hotkeys.

**The table below applies to the standard launcher entry (mapper), not Native Controller.** It emulates keyboard and mouse inputs rather than PD2's native pad mode. D-Pad is mapped to potion slots, not menu button navigation. B triggers right click, so spells target the mouse cursor; hiding the cursor does not redirect spells to the analog stick. From 0.1.8 onward, Native Controller isolates native pad experiments from the mapper.

| Button | Function |
|---|---|
| Left analog | WASD, character movement |
| Right analog | Mouse cursor |
| A / B | Left / right mouse click |
| X / Y | Inventory / automap |
| D-pad Up, Right, Down, Left | Potions 1, 2, 3, 4 |
| L1 / R1 | Alt (loot labels, hold) / skill F2 |
| L2 / R2 | Shift (stand/attack) / slow cursor |
| Start | Enter |
| Select+B | Escape, menu; **save and exit from game menu** |
| Select+X / Select+Y | Character stats / skill tree |
| Select+A | Alt, item names |
| Select+L1 / Select+R1 | F3 / F4 |
| Select+L2 / Select+R2 | Town Portal T / toggle run R |
| Start+Select | Emergency exit for current session; unsaved progress may be lost |

**Character Name Input:** click the character name field, then press **Start+D-pad Down**. Up/Down cycles letters, Right advances to next character, Left deletes; L1/R1 skips 13 characters. Start or A confirms, Select cancels. Test input on a new character. [Standard mapping](<defaults/controls.gptk>) / [A-B swapped](<defaults/controls-swap.gptk>).

## 5. Updates — Excluding Game Data and Saves

Close the game. Extract `projectdiablo2-port-update.zip` **into the same `ports` directory**, overwriting port files. Do not delete the old folder or substitute an empty directory.

The update ZIP contains the launcher, scripts, default templates, metadata, documentation, licenses, and the **standalone MIT cnc-ddraw 7.1.0.0 wrapper**. It is no longer a text-only package. **It does not contain gamedata, CD keys, active config, saves, logs, prefix, cache, or the large Wine/Box86/Weston/VC++ runtimes.** These runtimes remain from the initial installation. The original `ddraw.dll` inside PD2 game data is not overwritten. Do not re-copy game assets.

You can overwrite the port as often as needed; active data and settings are excluded from the update ZIP. Always back up your saves prior to updating.

**Rolling back if a new wrapper fails to launch:** close the port, overwrite with preserved 0.1.4 ZIP, and restore earlier profiles from `.display-640-v1.bak` backups if present. The legacy launcher will re-bind the original PD2 DLL and 1024×768 desktop (cropping may return). Do not wipe game assets or prefix.

**Rolling back from 0.1.6:** after closing the port, overwrite code with preserved 0.1.5 ZIP. Scaling remains unchanged. If you also wish to revert the save path change in JSON, restore `.save-path-v1.bak` without moving character saves.

**Rolling back from 0.1.7 (display):** simply set `"game_resolution": "native"` in `config/settings.json` after closing the port — the original library (1068×600 with letterboxing) will be used without resetting prefix or cache. Full code rollback: overwrite with [0.1.6 ZIP](<../../../dist/projectdiablo2-port-update-0.1.6-rollback.zip>). The local library copy in `.local/share/pd2-r36s` can remain.

## 6. Safe Logging and Diagnostic Submission

From 0.1.6 onward, `session_probe` reports only:
* `saves_directory`: Accessibility and count of standard `.d2s` files in the persistent saves folder (scans max 4096 entries). Does not read character data or log character names.
* `save_mapping`: Whether `S:` correctly points to the persistent folder; does not log filesystem paths.
* `game_config`: Whether the configuration file in the working directory is valid JSON.
* `save_path`: `canonical` / `missing` / `other` / `unknown`, without logging unexpected paths.
* `movement_mode`: `emulated` / `native` / `mixed` / `disabled` / `unknown` based on the two config flags. This does not confirm pad detection or in-game configuration reading.
* From 0.1.11: `controller_mapper` (`ready` / `missing` / `denied` / `invalid` / `fallback`) — state of built-in evdev→uinput mapper in native mode, and `mapper_layout` (`standard`) — active GO-Super mapping enum. Events contain no button or axis values.

`count>0`, `save_mapping=ready`, `game_config=ready`, `save_path=canonical` confirm file preparation on the wrapper side, but do not prove the game engine accepted the character saves.

JSONL logs record only bounded phases, error categories, exit codes, missing library names, and numeric metrics. From 0.1.4, `x11_probe` events log `identity/socket/filesystem/abstract` tests, status, duration in ms, and socket permissions/owner category `root/user/other` — without UID/username, filesystem paths, cookie strings, or server responses. MIT cookies are random, ephemeral, session-private, and excluded from logs/exports. `connect_timeout` denotes connection timeout, `reply_timeout` missing X11 response, `denied/refused/missing` transport error, `setup_rejected` general setup failure, `auth_rejected` rejection with auth notice, `auth_required` auth challenge, `ready` complete Setup reply. Socket state `ready` indicates file existence; server readiness requires transport verification. Xwayland startup/exec/font errors and safe fallbacks are bounded categories. Unrecognized stdout/stderr is **dropped**, not captured as plain text. No environment dumps, memory dumps, or command-line captures; Box86/Wine tracing and core dumps are disabled. Cap: **10 sessions of max 2 MiB each**. Loggers drain pipes after reaching size limits or upon write errors. Telemetry is never sent automatically.

After closing the game, run from the console terminal within `ports/projectdiablo2`:

```bash
python3 scripts/safe_log.py export --dir logs --manifest runtime-manifest.json
```

This generates `logs/diagnostic-export.zip`, containing re-validated logs with anonymized filenames and runtime version projections. **Share only this export archive**, never the entire directory, raw D2 files, Windows configs, wineprefix, CD keys, or character saves. Report: launcher name, whether menu displayed, video/audio status, gamepad responsiveness, and the moment of failure.

Common error categories:
* `missing_library`: Required ARMHF library absent; follow recommendations for your firmware/PortMaster version.
* `missing_drm_device`, `missing_uinput`, `namespace_unavailable`: System resource/permission mismatch or kernel feature missing. The port does not alter system devices or auto-repair OS configurations.
* `display_conflict`: Existing X11 session running; exit other ports or reboot the console. Do not kill arbitrary Wine/Weston processes.
* `compositor_failed`, `compositor_timeout`: Display pipeline failed to start; retain GDI during investigation and submit log export.
* `x11_probe_failed`, `x11_socket_failed`: Wine has not started yet; provide log with version 0.1.4 and `x11_probe` events. Do not wipe prefix or re-copy game files.
* `prefix_incomplete`: Previous setup was interrupted. Do not delete game files or saves. After full session shutdown, back up and rename **only** the private `wineprefix` directory; a fresh prefix will generate on the next launch.
* `invalid_layout`, `unsupported_runtime`: Check initial installation directory layout, runtime completeness, and available storage. Updates without game data do not replace initial setup.

## 7. R36S Validation Checklist

1. Menu display and character creation; name input via interactive keyboard helper.
2. WASD movement, targeting, clicks, potion usage, inventory, and skills.
3. Complete menu visibility (including bottom buttons), all four screen borders, cursor click alignment, inventory and HUD bars: full 4:3 — game 800×600 scaled to 640×480 screen without black bars. Interface readability (no clipping/overlap), audio stability, and frame rate over a ~10 minute session.
4. Saving game and returning cleanly to Ports; relaunching and loading character save.
5. In standard keyboard/mouse entry, test Start+Select return to menu on a test character. The built-in native mapper (0.1.11) does not implement this hotkey — exit via game menu; Controller Test exits after 45 s. Do not hard power off to test.
6. Overwriting with port code, preserving configs, and reloading saves.
7. Export diagnostics if GDI fails; do not switch to removed renderer profiles.

## Sources and Licenses

[dArkOSen-R36S Firmware](<https://github.com/djparentx/dArkOSen-R36S>) · [PortMaster](<https://github.com/PortsMaster/PortMaster-New/tree/main/ports>) · [PD2 — Game.exe/-ddraw Execution](<https://raw.githubusercontent.com/Project-Diablo-2/PD2Launcher/master/PD2Shared/Helpers/LaunchGameHelpers.cs>) · [gptokeyb](<https://github.com/PortsMaster/gptokeyb>) · [Wine Builds](<https://github.com/Kron4ek/Wine-Builds>) · [WestonPack](<https://github.com/binarycounter/Westonpack/wiki>).

[Runtime Manifest](<runtime-manifest.json>) · [License Notices](<licenses/THIRD-PARTY-NOTICES.md>). This package is a private experimental port, not an official PortMaster release.
