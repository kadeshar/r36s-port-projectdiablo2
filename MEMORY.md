# MEMORY.md — Development History and Knowledge Base for Project Diablo 2 on R36S

This document records the detailed history of engineering work, architectural analysis, diagnosed issues, and implemented solutions throughout the development and optimization of the **Project Diablo 2** port for the **R36S** handheld console (ArkOS / Rockchip RK3326).

---

## Start Menu Header Subtitle — "R36S PORT {VERSION}" (User-Request, 1.3-test.1 Line)

- **User request:** the second header row of the X11 start menu read `LORD OF DESTRUCTION - R36S`; change it to `R36S PORT {VERSION}`.
- **Implementation (no new version pin — rule 7 clean):**
  - [`menu_x11.py`](sdcard/ports/projectdiablo2/scripts/menu_x11.py): `Screen.__init__` gained an optional third parameter `subtitle='R36S PORT'`; stored as `self.subtitle = str(subtitle).upper()[:WIDTH // 18]` (bitmap font is uppercase-only with an 18-px advance; 35-glyph cap keeps any version string on one screen width). `draw()` now renders the subtitle at dynamic centering `x = (WIDTH - len(self.subtitle) * 18) // 2`, `y = 60`, same crimson `(185, 45, 35)`. The old hardcoded `x=86` was the 26-char centering; dynamic centering matches it and adapts to any version length. Two-arg construction (used by tests) keeps working via the default.
  - [`start_menu.py`](sdcard/ports/projectdiablo2/scripts/start_menu.py): new `_subtitle()` reads `layout.VERSION` at runtime (single source of truth — the version string is never hardcoded in the menu, so future user-directed version bumps surface automatically); on any `layout` import failure or empty/blank `VERSION` it degrades to `R36S PORT` so the header always draws. `Screen.__new__` passes `_subtitle()` as the third `X11Screen` argument.
  - Current pin `1.3-test.1` therefore renders as `R36S PORT 1.3-TEST.1` (uppercased for the font).
- **Tests:** [`tests/test_menu_x11.py`](tests/test_menu_x11.py) +2 (default subtitle centered at `(640-9*18)//2` with y/color contract; version subtitle uppercased, centered, and truncation to `WIDTH//18` with a safe non-negative x); [`tests/test_start_menu.py`](tests/test_start_menu.py) +2 (`_subtitle()` resolves the `layout` version pin; fallback without layout / blank version) and the existing direct-X11 provider test now expects the third argument (`m._subtitle()`).
- **Validation:** targeted suites green — test_menu_x11 27 OK (2 opt-in X11 skips), test_start_menu 39 OK (1 bash-harness skip). Full discover run (818 tests): the 327 ERRORs are all `PermissionError [WinError 5]` / `FileNotFoundError` temp-directory failures in `setUp` of 22 unrelated modules (audio/layout/prepare/probe family) — the documented environmental AV/sandbox temp flake on this Windows host (same class reproduces running a single affected module in isolation; none of the 22 erroring modules import menu_x11 or start_menu). Only pre-existing baseline failure remained (`test_present_renderer.ArtifactTests.test_authenticated_x86_release_and_isolation`). `compile()` syntax check on both changed scripts OK.
- **Version pins:** untouched (no user-directed version change).
- **Deployment (2026-10-29 19:28 console time, user-approved):** 2 files uploaded to `/roms2/ports/projectdiablo2/scripts/` — `menu_x11.py`, `start_menu.py`. Backup: `/roms2/ports/projectdiablo2/pre-subtitle-backup-20261029_192829/` (both originals, pre-deploy SHA256: menu_x11 `270946cb…`, start_menu `995a9cc5…`). Remote SHA256 verified both sides (menu_x11 `360567e6…`, start_menu `6602ec5a…`); `python3 -B -m py_compile` OK on console; non-executing `storage_launcher.py --check` PASS (exit 0, "No Wine, compositor or game was executed"). OpenSSH note: sandbox blocks PuTTY registry host-key cache, so plink/pscp pinned via `-hostkey "SHA256:9UNDGASqoxG+1+QvXCKYXwRBzqC8frOyZz38OU3rhKA"` (ssh-ed25519, user-authorized trust). Awaiting user console test (menu header must read `R36S PORT 1.3-TEST.1`).

---

## Loot Filter Selection (Issue #7) — Filters Drop Directory, Menu Selection, 4 MiB Limit

- **Reported Issue (github.com/kadeshar/r36s-port-projectdiablo2/issues/7):**
  - Loot filters could not be used: community filters (commonly 1–3 MiB) were rejected, and there was no way to choose a filter before launch. The engine reads only `ProjectD2/default.filter` from the game working directory.
- **Root Causes (three, all in the launch pipeline):**
  1. **512 KiB `CONFIG_LIMIT`** applied to every published config, including `default.filter` → real community filters failed `invalid_layout` preflight.
  2. **No selection path:** the launcher menu had only RESOLUTION and PERF OVERLAY rows; `default.filter` was always the shipped no-filter donor file.
  3. **UTF-8 validation** on config bytes rejected frequently-published ANSI (CP1250/CP1252) filters.
- **Implemented Design (v0.1.19):**
  - **User filter drop directory** [`sdcard/ports/projectdiablo2/filters/`](sdcard/ports/projectdiablo2/filters/) (comment-only `.keep` placeholder; never a filter). Flat names only: first char `[A-Za-z0-9]`, then ≤127 of `[A-Za-z0-9._-]`, ending `.filter` (≤135 chars). Symlinks/directories/hidden entries skipped. Gamedata untouched (read-only).
  - **Dedicated 4 MiB `FILTER_LIMIT`** + [`filter_content()`](sdcard/ports/projectdiablo2/scripts/layout.py): bounded byte read, NUL-only rejection (game crashes on NUL), **no UTF-8 check — ANSI passes through untouched**. All other configs keep the 512 KiB `CONFIG_LIMIT`.
  - **Menu row 2 "LOOT FILTER"** ([`start_menu.py`](sdcard/ports/projectdiablo2/scripts/start_menu.py), [`menu_x11.py`](sdcard/ports/projectdiablo2/scripts/menu_x11.py)): five rows now (RESOLUTION / PERF OVERLAY / LOOT FILTER / LAUNCH / EXIT), menu opens on row 2; cycles `DEFAULT` + `filter_listing()` in name order; opens on the stored choice when it still exists, stale name → `DEFAULT`.
  - **Floating full name in the SAME row (v0.1.21; replaced the v0.1.20 below-row plaque after user report "nothing floating" — the menu loop repaints only on input, so an idle hold never advanced the float timer):** row labels cap at 16 chars; when a longer name is held on the filter row for 2 s (`FLOAT_DELAY`), the `LOOT FILTER: ` prefix stays **static** while only the full uppercase name scrolls (pixel marquee, `FLOAT_SPEED` 48 px/s) inside the row's 16-char name window (x 316..606, clipped). [`start_menu.py`](sdcard/ports/projectdiablo2/scripts/start_menu.py) gained `Menu.float_active()` (row 2 + non-default + name > 16 chars); the run loop repaints on its 20 ms timer **while `float_active()`** — static menus stay event-driven (idle polls never repaint). Timer restarts on any row/choice change; `_text()` optional `clip=(min_x,max_x)` window (screen-edge clipping unchanged); closed-enum/log/event format untouched. (v0.1.20 plaque geometry — below-row y 216–239, 572 px, centered ≤30 chars / marquee wider — superseded.)
  - **Selection = pre-launch copy:** [`apply_loot_filter()`](sdcard/ports/projectdiablo2/scripts/layout.py) atomically publishes the chosen file as `config/default.filter` (+ volatile work copy); missing/invalid name → closed-enum `loot_filter missing` event + fallback to shipped default (never aborts, stale bytes replaced). Choice persists to `settings.json` `loot_filter` only on explicit session override; plain prepare stays byte-identical and event-free (regression contract).
  - **Three-token protocol** `resolution fps loot_filter` (`print(' '.join(selection))` in start_menu; `read -r menu_resolution menu_fps menu_filter menu_extra` + per-field whitelists + `-f`/`! -L` existence checks + `-z "$menu_extra"` in [`weston-session.sh`](sdcard/ports/projectdiablo2/scripts/weston-session.sh)); `PD2_LOOT_FILTER` exported unconditionally (even `default`) and guarded/forwarded in both launchers.
  - **Closed-enum log discipline** ([`safe_log.py`](sdcard/ports/projectdiablo2/scripts/safe_log.py)): `loot_filter` statuses `selected|default|missing|unavailable`, optional integer `count` 0..512 (listing size), phases `preflight|launch`; names/paths never accepted.
- **Versioning (USER-DIRECTED, never automatic — new AGENTS.md rule 7):** agent auto-bumps 0.1.18 → 0.1.19 (filter feature) → 0.1.20 (floating name) → 0.1.21 (in-row float + animation repaints) are superseded; user then directed **`1.3-test.1`** (exact string) in all six pins: [`layout.py`](sdcard/ports/projectdiablo2/scripts/layout.py) `VERSION`, root + port `runtime-manifest.json`, both launcher `port_version` events, [`tools/check_update.py`](tools/check_update.py). From now on pins change ONLY on explicit user command.
- **Release zip (user-requested, v1.3-test.1):** `.temp/release/projectdiablo2-port-1.3-test.1.zip` — 180.1 MB, 121 files, root = `Project Diablo 2.sh` + `projectdiablo2/` (extract over SD card `ports/`); `__pycache__`/`*.pyc` excluded; in-zip SHA256 of `layout.py` + launcher verified against local; in-zip `VERSION = '1.3-test.1'`; gamedata stays user-supplied (repo `gamedata/` is the import placeholder).
- **Console deployment 1.3-test.1 (2026-10-29 17:25, user-directed "console = ZIP"):** user chose ZIP→console direction after 1:1 audit found 4 version files + 4 content files diverged (repo had been stale-vs-console in the opposite direction than first assumed). Backup: `/roms2/ports/projectdiablo2/pre-1.3-test.1-backup-20261029_172504/` (flat, 8 files). Uploaded 8 files ZIP→console: launcher, `private-launcher.sh`, port `runtime-manifest.json`, `layout.py`, `run-game.sh`, `xbox_mapper.py`, `ddraw-gdi.ini`, `storage_common.py` — all 8 SHA256-verified both sides; version pins grepped `1.3-test.1` (both launchers, manifest, `layout.py`); `py_compile` + `bash -n` OK; storage check PASS (`CHECK_RC=0`, no game executed). Re-audit: **120/121 ZIP files byte-identical on console** (119 in scan + `filters/.keep` `bcffecd0…`; only `gamedata/HERE PUT Diablo II folder` intentionally absent — user's real D2 data there); console extras = saves (25), `__pycache__` (9, py_compile byproduct), `state.ext4`+`session.lock`. Console content changes from this sync: `storage_common.py` now has the fixed `feature_candidates` mke2fs fallback (console previously had the OLD hardcoded `-O …^orphan_file` version — fresh-install bug fixed on console); `xbox_mapper.py` now R36S-only (console previously had multi-device choose_pad incl. RG353V/retrogame_joypad — harmless on R36S, built-in GO-Super `0x484b:0x1100`); `ddraw-gdi.ini` now `devmode=true` (was `false` — watch for display changes in user test); `run-game.sh` now redirects game stdout/stderr to `logs/wine-game.log` (was unredirected).
- **Tests:** new coverage in [`tests/test_layout.py`](tests/test_layout.py) (4 MiB bound, ANSI passthrough, NUL reject, listing rules, apply/persist/missing-fallback, `--get loot_filter`, plain-prepare byte-identity), [`tests/test_start_menu.py`](tests/test_start_menu.py) (row 2 cycling/wrap, 3-token protocol, closed-enum `main()` event, bash harness with real temp filters dir incl. symlink/missing/named cases, `float_active()` matrix + marquee repaints only while a long name is held), [`tests/test_menu_x11.py`](tests/test_menu_x11.py) (five-row labels, bounds, in-row floating full-name marquee: 2 s hold timer, static `LOOT FILTER: ` prefix, clipped marquee geometry in the row's name window, restart on row/choice change, ≤16-char names never float), [`tests/test_safe_log.py`](tests/test_safe_log.py) (closed statuses, bounded count, dynamic-field rejection).
- **Validation:** full local suite on Windows: 814 tests, 129 skips (0.1.21 run); only pre-existing baseline failures (fps_counter, fps_renderer, present_renderer) + moving `PermissionError [WinError 5]` rename flakes in wine-extraction tests (environmental, AV/rename race — different victim test each run, verified against `.temp/baseline` A/B from git HEAD `654e206`). Console deploys (0.1.19, 0.1.20, 0.1.21) verified by SHA256 comparison, version-pin grep and non-executing `storage_launcher.py --check` PASS each time.
- **Docs:** [docs/LOOT-FILTER.md](docs/LOOT-FILTER.md).
- **Deploy notes:** user drops filters into `/roms2/ports/projectdiablo2/filters/`; in-game keep "Enable Loot Filter" on; Numpad 0 reloads the active filter. Deployed files (0.1.19, then 0.1.20): `Project Diablo 2.sh`, `private-launcher.sh`, `scripts/{layout.py,safe_log.py,start_menu.py,menu_x11.py,weston-session.sh}`, `filters/.keep`, port + root `runtime-manifest.json`, launcher `port_version` events; 0.1.21 re-uploaded `Project Diablo 2.sh`, `private-launcher.sh`, port `runtime-manifest.json`, `scripts/{layout.py,menu_x11.py,start_menu.py}` (all SHA256-verified, py_compile OK on console, storage check PASS). Console backups: `pre-0.1.19-backup-20261029_115732/`, `pre-0.1.20-backup-20261029_141522/`, `pre-0.1.21-backup-20261029_144026/` (6 files: both launchers, port manifest, layout.py, menu_x11.py, start_menu.py). First user filter copied from donor `C:\Program Files (x86)\Diablo II\ProjectD2\filters\online\Hiim_Crafting_Sorceress_Focused.filter` (455 KiB, SHA256 `f04b8bb9…e8561ed`, hash-verified on console, listed by the deployed `filter_listing()`). Every deploy verified by SHA256 comparison + non-executing `storage_launcher.py --check` PASS. Awaiting user console test; crashes/FPS-drops follow-up deferred to after user testing.

---

## Fresh Installation Failure Diagnosis & Fix (ArkOS mke2fs 1.45.3)

- **Reported Issue:**
  - Fresh installation on ArkOS failed; game/start menu did not appear after launcher click.
- **Root Cause Analysis:**
  - Inspected console log /roms2/ports/projectdiablo2/logs/storage-session.log:
    [ERROR] Validation failed: mke2fs failed: mke2fs 1.45.3 (14-Jul-2019)
    Invalid filesystem option set: ^64bit,^metadata_csum,^metadata_csum_seed,^orphan_file
  - When state.ext4 does not exist (fresh installation or after reset), nsure_state_image() in storage_common.py creates and formats state.ext4 using mke2fs.
  - The command hardcoded -O ^64bit,^metadata_csum,^metadata_csum_seed,^orphan_file.
  - ArkOS runs Linux 4.4.189 and ships with mke2fs 1.45.3 (14-Jul-2019). The orphan_file feature was only added in e2fsprogs 1.47.0 (2023). Passing ^orphan_file caused mke2fs to fail immediately with Invalid filesystem option set, aborting before the compositor, start menu, or game could execute.
- **Code Fix ([sdcard/ports/projectdiablo2/storage-tools/storage_common.py](sdcard/ports/projectdiablo2/storage-tools/storage_common.py)):**
  - Added multi-candidate feature fallback in nsure_state_image():
    1. ^64bit,^metadata_csum,^metadata_csum_seed,^orphan_file (modern e2fsprogs 1.47+)
    2. ^64bit,^metadata_csum,^metadata_csum_seed (ArkOS e2fsprogs 1.45.3)
    3. ^64bit,^metadata_csum
    4. ^64bit
    5. Default (no extra -O)
  - If mke2fs fails with 'invalid filesystem option' in stderr, it attempts the next candidate. If failure is due to a real error (disk full, permissions), it aborts without trying further feature sets.
- **Validation:**
  - Added unit tests 	est_ensure_state_image_fallbacks_when_option_unsupported and 	est_ensure_state_image_stops_on_unrelated_error_without_fallback in [	ests/test_storage_common.py](tests/test_storage_common.py). All 6 unit tests pass.
  - Deployed updated storage_common.py to console /roms2/ports/projectdiablo2/storage-tools/storage_common.py.
  - Verified storage check on console: state.ext4 formatted and mounted successfully in private namespace.
  - Executed 	ools/simulate_fresh_install.py to leave console in a clean first-boot state ready for user verification.

---

## Release 1.2-test.2 — Input Subsystem Compatibility (RG353V + Multi-device)

- **Issue #2 Follow-up Diagnosis (RG353V Start Menu Unresponsive Controls):**
  - Reporter `rattusludus-jpg` confirmed build boots to selection menu on RG353V, but controls do not react.
  - Root Cause:
    1. In [`start_menu.py`](sdcard/ports/projectdiablo2/scripts/start_menu.py), `Pad.__init__` solely called `mapper.choose_pad(mapper.physical_devices())`. In `xbox_mapper.py`, `choose_pad` explicitly checks for R36S hardware vendor/product `(0x484b, 0x1100)`. On RG353V, built-in controls register as generic platform/gpio devices (`0x0001:0x0001` or `0x0000:0x0000`), so `choose_pad` returned `None`, leaving `Pad.fd = None` with zero inputs polled.
    2. Event mapping lacked standard Linux gamepad codes: `BTN_START` (`0x13b` / 315), `BTN_SELECT` (`0x13a` / 314), and keyboard directional keys (`103`, `108`, `105`, `106`).
    3. `KeyDecoder.feed()` discarded all `kind != 1` (`EV_KEY`). On RG353V and many other PortMaster-compatible handhelds, D-pad and analog sticks emit `kind == 3` (`EV_ABS`) Hat events (`ABS_HAT0X` 16, `ABS_HAT0Y` 17) or stick events (`ABS_X` 0, `ABS_Y` 1).
- **Code Fixes:**
  - **Input Discovery Fallback ([`start_menu.py`](sdcard/ports/projectdiablo2/scripts/start_menu.py)):**
    - Checks `mapper.choose_pad()` first (preserving verified R36S physical path). If `None`, scans `/dev/input/event*` and opens candidate event devices non-blocking with multi-fd `select.select()` polling.
  - **Hat (`EV_ABS`) & Stick Support ([`start_menu.py`](sdcard/ports/projectdiablo2/scripts/start_menu.py)):**
    - `KeyDecoder.feed()` processes `EV_ABS`:
      - D-Pad Hats (`ABS_HAT0X` 16, `ABS_HAT0Y` 17) mapped to left/right/up/down.
      - Analog Sticks (`ABS_X` 0, `ABS_Y` 1 with deadzone ±16000) mapped to left/right/up/down.
  - **Extended Gamepad Actions ([`start_menu.py`](sdcard/ports/projectdiablo2/scripts/start_menu.py)):**
    - Added `0x13b` (`BTN_START` -> accept), `0x13a` (`BTN_SELECT` -> cancel), `103`/`108`/`105`/`106` (arrow keys), `28`/`57` (Enter/Space), `1` (Esc).
    - Integrated `PD2_SWAP_AB` environment support into `get_pad_actions()`.
- **Validation & Test Suite:**
  - Added `test_rg353v_standard_gamepad_hat_and_stick_inputs` in [`tests/test_start_menu.py`](tests/test_start_menu.py) (all 29 tests pass).
  - Verified `tests/test_layout.py` (all 44 tests pass).
  - Verified live Pad enumeration on console via SSH (`PAD FDS: 1`).
- **Release Package 1.2-test.2:**
  - Built [`.temp/release/Project Diablo 2 R36S port 1.2-test.2.zip`](file:///c:/src/r36s-port-projectdiablo2/.temp/release/Project%20Diablo%202%20R36S%20port%201.2-test.2.zip) (189,079,057 bytes, SHA256: `bf16bd6f5678b49bd2856e61a36e252078a513a9c565ac5b321fb715ada4ca56`).
- **Console Deployment:**
  - Deployed updated `start_menu.py` to console `/roms2/ports/projectdiablo2/scripts/start_menu.py`.

---

## Release 1.2-test.1 — Multi-device Compatibility (RG353V + R36S)

- **Production Code Updates (`sdcard/ports/`):**
  - **Weston Wayland Preload & Xwayland Isolation (`scripts/weston-session.sh`):**
    - Preloaded `$W/lib_aarch64/libwayland-server.so.0:$W/lib_aarch64/libwayland-client.so.0:$preload` for `wp_weston` to bypass Mali Bifrost G52 driver stub collisions with Wayland symbols on RG353V (dArkOS Trixie).
    - Injected `export LD_PRELOAD=` into `$R/bin/Xwayland` wrapper to prevent Xwayland from inheriting `libcrusty.so`.
    - Sanitized `XWAYLAND_LD_LIBRARY_PATH="${xwayland_gl:+$xwayland_gl:}$W/lib_aarch64"` removing `$backendlib` (`crusty_gbm`) to avoid fake EGL symbol collisions in `libepoxy`.
  - **Preflight Layout Self-Healing (`scripts/layout.py`):**
    - Unlinks stale regular files at target config/dat paths before calling `link(destination, active)`, preventing `LayoutError('invalid_layout')` if a previous session was interrupted.
    - Verified all 44 unit tests pass in `tests/test_layout.py`.
  - **Storage Tools Robustness (`storage-tools/storage_common.py`):**
    - Added missing `shutil` and `subprocess` imports.
- **Release Package 1.2-test.1:**
  - Built [`.temp/release/Project Diablo 2 R36S port 1.2-test.1.zip`](file:///c:/src/r36s-port-projectdiablo2/.temp/release/Project%20Diablo%202%20R36S%20port%201.2-test.1.zip) (188,274,792 bytes, SHA256: `e7f5ef580de29acbf33f3166911638d4d04b1b1a7ab4147f947a4ac182741e06`).
  - Standard PortMaster distribution structure: contains `Project Diablo 2.sh` and `projectdiablo2/` tree.
- **Console Deployment & Fresh Installation Simulation:**
  - Executed `tools/simulate_fresh_install.py` on console `192.168.50.135`:
    - Backed up 32 save files to `/roms2/ports/projectdiablo2-saves-backup-20261026_155122`.
    - Cleaned `storage/state.ext4`, session locks, logs, and home state cache. Verified post-reset integrity (32/32 saves intact, `Game.exe` verified).
  - Deployed updated files to console:
    - `/roms2/ports/Project Diablo 2.sh` (`d1306ac7...`)
    - `/roms2/ports/projectdiablo2/scripts/layout.py` (`16cc51ba...`)
    - `/roms2/ports/projectdiablo2/scripts/weston-session.sh` (`3c957ae2...`)
    - `/roms2/ports/projectdiablo2/storage-tools/storage_common.py` (`9bdbfc0d...`)
    - `/roms2/ports/Project Diablo 2 R36S port 1.2-test.1.zip` (`e7f5ef58...`)
- **Testing Standard:** In compliance with AGENTS.md rule 7, game launch on the console remains exclusively reserved for the user. Console is in clean first-boot state ready for user manual launch test.

---

## Issue #6 & Fresh Installation Simulation Procedure

- **Issue #6 Diagnosis:**
  - In Issue #3, user reported `insufficient_space` on R36H (ArkOS/darkosen). An experimental SD storage fix was sent via Google Drive (`Project-Diablo-2-SD-Storage-Experimental.zip`). That build included a pre-formatted 1GB `storage/state.ext4` image inside the ZIP. It worked because the image had valid ext4 superblock magic `0xEF53` (`\x53\xef`).
  - In commit `02f6dc8` (Release 1.0), `state.ext4` was omitted from distribution to prevent 1GB archive bloat. `ensure_state_image()` was added to `sdcard/ports/projectdiablo2/storage-tools/storage_common.py` to create and format `state.ext4` on first run via `mke2fs`.
  - Fatal bug in `ensure_state_image()`: missed `import shutil` and `import subprocess`. On first launch, it created a 1GB sparse zero-filled file, then crashed with `NameError: name \x27subprocess\x27 is not defined`.
  - On subsequent launches, `state.exists()` was True, so `ensure_state_image()` was skipped; validation checked magic at offset 1080, found `0x00 0x00` instead of `0x53 0xef`, and raised `StorageError: State image is not an ext filesystem`.
- **Issue #6 Fix & Verification:**
  - Fixed `sdcard/ports/projectdiablo2/storage-tools/storage_common.py`:
    - Added missing `import shutil` and `import subprocess`.
    - Made `ensure_state_image()` atomic: formats into temporary `.tmp` image, verifies ext superblock magic (`0xEF53` / `\x53\xef`), and atomically renames.
    - Added self-healing: if an incomplete, corrupted, or zeroed `state.ext4` already exists on disk from a previous interrupted run, it detects invalid magic/size, deletes the broken file, and recreates cleanly.
  - Added unit test suite `tests/test_storage_common.py` covering valid image skip, corrupted/zeroed image healing, missing image creation, and `.tmp` cleanup on error. (4/4 passed).
  - Executed fresh installation simulation on console via SSH:
    - All 32 save files safely backed up to `/roms2/ports/projectdiablo2-saves-backup-20261026_145626/`.
    - Removed `state.ext4`, `session.lock`, logs, and temporary home state.
    - Post-reset integrity verified 32/32 saves intact and `Game.exe` untouched.
  - Deployed fixed `storage_common.py` (`9bdbfc0ddbd3...`) to `/roms2/ports/projectdiablo2/storage-tools/storage_common.py` on console `192.168.50.135`. Verified remote sha256 checksum and clean bytecode compilation.
  - Tested non-game validation via `storage_launcher.py --check` on console:
    - Successfully auto-created and formatted fresh 1GB `state.ext4` on device (23s).
    - Mounted ext4 and Wine squashfs in private namespace with 1,005,211,648 available bytes.
    - Exited cleanly with code 0.
  - Reset console back to clean first-boot state via `tools/simulate_fresh_install.py` with 32/32 saves intact, ready for user manual launch test.

- **Release Package 1.1-test.1:**
  - Built `.temp/release/Project Diablo 2 R36S port 1.1-test.1.zip` (188,208,676 bytes, SHA256: `7c3a3329f75cfadd8b22d7e003c8cf5e37656154da17a7c6eeb7a2018d0cdceb`).
  - Package structure strictly analogous to release 1.0 (contains root `Project Diablo 2.sh` and `projectdiablo2/` tree).
  - Excludes ephemeral `storage/state.ext4`, session locks, logs, save data, and `__pycache__` bytecode.
  - Contains updated `storage-tools/storage_common.py` with missing imports fix, atomic `.tmp` creation, and auto-healing for corrupted zero-filled images.

- **Fresh Installation Simulation Tool (`tools/simulate_fresh_install.py`):**
  - Created to simulate a clean first-boot install on the target R36S console without affecting game saves or game data.
  - Recursively locates and counts all save files across `saves/`, `saves_s14/`, `gamedata/*/Save/`, and `$HOME/.local/share/pd2-r36s/saves/`.
  - Backs up all saves to a timestamped backup directory (`/roms2/ports/projectdiablo2-saves-backup-<timestamp>/`).
  - Cleans first-run state: detaches loop devices, unmounts private mountpoints, deletes `storage/state.ext4` and `session.lock`, clears `logs/*.log`, and clears runtime caches in `$HOME/.local/share/pd2-r36s`.
  - Verifies post-reset integrity: ensures `state.ext4` is removed, all 32 save files remain intact, and game executable is present.
  - Supports `--dry-run`, remote execution via SSH (`plink`/`ssh`), and `--local` execution on device.
  - Documented procedure in `AGENTS.md`.

---

## Issue #2 — RG353V dArkOS Weston & Xwayland Fix Candidate (v3)

- **Problem Diagnosis (Issue #2 / RG353V dArkOS Trixie):**
  - Original issue: `wp_weston` exited with `rc 139` (SIGSEGV) on `weston_start` due to Mali Bifrost G52 driver stub collisions with Wayland symbols.
  - Candidate fix 1 (`rg353v-wayland-fix-1.zip`): Preloaded `libwayland-server.so.0` and `libwayland-client.so.0` before `wp_weston`. Weston successfully booted (`drm_module`, `gl_module`, `egl_ready`, `gl_ready`, `output_ready`, `xwayland_module`, `xserver_listening`). However, `x11_probe` failed with `xwayland_crash` (SIGABRT) on client connection. Root cause: `wp_weston` passed inherited `LD_PRELOAD` containing `libcrusty.so` down to Xwayland, while `XWAYLAND_LD_LIBRARY_PATH` also contained `$backendlib` (`crusty_gbm`). When Xwayland's `libepoxy` queried EGL extensions, Crusty intercepted it without `libCRU.so`, triggering `abort()` inside `libepoxy`.
  - Candidate fix 2 (`rg353v-wayland-fix-2.zip`): Reporter saw immediate exit to EmulationStation with no log. Cause: `launch.sh` dropped `/..` when updating from base `Project Diablo 2.sh`, setting `BASE=$(cd -- "$(dirname -- "$0")" && pwd -P)`. Because `launch.sh` resides in `projectdiablo2-rg353v-fix/`, `BASE` pointed to the fix subdirectory instead of `ports/`, making `$PD2_PORT` invalid and failing namespace mountpoint checks immediately before logging started.
- **Architectural Solution (Candidate v3):**
  - **Launch Path Correction (`launch.sh`):** Restored `BASE=$(cd -- "$(dirname -- "$0")/.." && pwd -P)` and `FIX="$BASE/projectdiablo2-rg353v-fix"`. Preserved alignment with base port 02f6dc8 (sd-storage, overlay).
  - **Compositor Preload (`weston-session.sh`):** Maintained preloading of `$W/lib_aarch64/libwayland-server.so.0:$W/lib_aarch64/libwayland-client.so.0:$preload` for `wp_weston` to bypass Mali Wayland stubs.
  - **Xwayland Isolation (`weston-session.sh`):**
    - Injected `export LD_PRELOAD=` into `$R/bin/Xwayland` wrapper to prevent Xwayland from inheriting `libcrusty.so`.
    - Sanitized `XWAYLAND_LD_LIBRARY_PATH="${xwayland_gl:+$xwayland_gl:}$W/lib_aarch64"`, removing `$backendlib` (`crusty_gbm`) so Xwayland never loads Crusty's fake EGL/GBM/DRM shims.
  - **Resolution of `insufficient_space` Regression (Candidate v3.1):**
    - User verified Candidate v3 on R36S: Weston, Xwayland, and start menu succeeded (`start_menu status: selected`).
    - Failure occurred at `volatile_work_prepare` (`layout.py --volatile-work`) with `insufficient_space`. Root cause: `launch.sh` previously defined `PD2_EXPERIMENT_STATE="$HOME/.local/share/pd2-rg353v-wayland-fix"`. In a fresh state directory, `wineprefix/.initialized` does not exist, triggering `layout.py`'s check requiring 700 MB free space on `$HOME` (`/dev/mmcblk0p2` on R36S only had 372 MB free).
    - Fixed by unifying `PD2_STATE` with existing production state `$HOME/.local/share/pd2-r36s` where `wineprefix/.initialized` already exists (bypassing the 700 MB requirement and reusing existing extracted Wine runtime).
    - Removed wrapper's shared flock on `session.lock` so `launch.sh` cleanly acquires the exclusive lock on `pd2-r36s/session.lock`. Mutable game data (`config/`, `saves/`, `logs/`) remains completely isolated under `projectdiablo2-rg353v-fix/` via namespace bind-mounts.
  - **Resolution of `invalid_layout` Stale Config Symlink Collision (Isolated Fix):**
    - If a previous game session or manual CLI test terminated before unlinking regular files from `state/game/ProjectD2/`, non-volatile preflight `layout.py` raised `invalid_layout` because `link()` refused to overwrite existing non-symlink files.
    - Added self-healing `layout.py` directly inside `projectdiablo2-rg353v-fix/scripts/layout.py`.
    - `Project Diablo 2 - RG353V Fix.sh` bind-mounts `$FIX/scripts/layout.py` onto `$PORT/scripts/layout.py` strictly inside the candidate's private mount namespace, leaving the production `projectdiablo2/` tree completely untouched on disk.
- **Packaging & Deployment:**
  - Packaged update into `.temp/rg353v-wayland-fix-3.zip` (minimal add-on) and `.temp/projectdiablo2-rg353v.zip` (complete standalone port).
  - Standalone full port archive [`.temp/projectdiablo2-rg353v.zip`](file:///c:/src/r36s-port-projectdiablo2/.temp/projectdiablo2-rg353v.zip) (188 MB, SHA256: `dd808baf71a59afd6734c966e098e49192153bf142397f5b351f14ab878b09a4`):
    - Contains full port payload completely isolated under `projectdiablo2-rg353v/` and launchers `Project Diablo 2 - RG353V.sh` / `Project Diablo 2 - RG353V Fix.sh`.
    - Bundles all runtimes (`wine-8.0-x86.squashfs`, `weston_pkg_0.2.squashfs`, `box86`, `vc_redist.x86.exe`, `wine-8.0-x86.tar.xz`), `compat/`, `defaults/`, `licenses/`, and `storage-tools/`.
    - Incorporates RG353V Wayland preload + Xwayland isolation in `scripts/weston-session.sh` and layout self-healing in `scripts/layout.py`.
    - Completely standalone; zero overlap or dependency on production `projectdiablo2/`.
  - Reverted console `/roms2/ports/projectdiablo2/scripts/layout.py` back to pristine git release (`3115b7ca...`).
  - Deployed `Project Diablo 2 - RG353V Fix.sh` and `projectdiablo2-rg353v-fix/` (`launch.sh`, `weston-session.sh`, `scripts/layout.py`) to `/roms2/ports/` on target console `192.168.50.135`.
  - User verified on R36S console: game starts and runs properly.
- **Testing Standard:** In compliance with AGENTS.md rule 7, game launch on the console remains exclusively reserved for the user. Local validation confirmed bash syntax and clean library loading without crash.

---

## Issue #2 — compositor-only diagnostic v2

- Reporter [v1 response](https://github.com/kadeshar/r36s-port-projectdiablo2/issues/2#issuecomment-6389765216): plain/Crusty `--version` both rc0, providers ready, no truncation. Constructor-only crash not reproduced; actual DRM/SDL/EGL startup remains unproven. User requests next diagnostic for reporter; no RG353V available locally.
- Added separate [v2 entry](<sdcard/ports/Project Diablo 2 - Weston Check v2.sh>), [orchestrator](<sdcard/ports/projectdiablo2/scripts/weston_startup_check.py>) and [allowlist sanitizer](<sdcard/ports/projectdiablo2/scripts/weston_startup_log.py>). Reuses unchanged constructor helper/pinned SquashFS; private mount+PID namespace, private /run+/tmp with host-run links, private seatd, production-like DRM/GL/Crusty baseline then optional debug/verified-strace ioctl-only attempt. Xwayland deny shim; no real Xwayland client, Wine, game, mapper or production-launcher execution. Eight seconds/attempt, overall deadlines, process-group cleanup and PID namespace containment. Game session lock prevents collisions.
- Raw native captures stay in verified tmpfs,1MiB cap/coreoff; persist only fixed enums/function tokens/numeric ioctl request+errno/signals/counts. Snapshot capture length before diagnostic TERM/KILL so cleanup signals do not masquerade as crashes; always KILL remaining process group even after leader exit. Independent review found these two cleanup/evidence issues, both fixed with regressions and rechecked.
- [Reporter guide](<docs/ISSUE-2-WESTON-V2.md>): extract diagnostic ZIP at SD root, run Weston Check v2, return `logs/pd2-weston-startup-v2.json` plus exact device/firmware, visible behavior and return/hang timing. Blank screen expected during compositor takeover; no gameplay claim from alive-at-deadline or X11 listener.
- Validation:35 v2 synthetic tests+11 existing graphics-provider tests PASS; Bash syntax PASS. No actual native compositor/console/game executed. Production launcher/adapter/runner, runtime binaries, configs/saves and unrelated performance-overlay work left untouched. This is a diagnostic handoff, not a hardware fix or full-regression claim.

## Issue #2 — one-run complete diagnostic package

- V2 reporter result [issue comment](https://github.com/kadeshar/r36s-port-projectdiablo2/issues/2#issuecomment-6397900110): baseline and instrumented compositor both rc -11 before X11; provider discovery ready; no truncation; sanitizer discarded nearly all unknown lines. Immediate return was expected crash behavior.
- Replaced repeated diagnostic iterations with one [Complete Check launcher](<sdcard/ports/Project Diablo 2 - Complete Check.sh>) and [PL/EN guide](<docs/ISSUE-2-WESTON-COMPLETE.md>). One report runs fixed 11-case matrix: production-like baseline/repeat, signal guard, independent ptrace watcher, SDL discovery/GLES2 + KMSDRM, Crusty KMSDRM/GLES31, native DRM GL/Pixman when explicit module exists, debug ioctl trace. No Wine, Xwayland client, menu, mapper or game.
- Added actual authenticated AArch64 guard/selftest/watcher payload under [compat/weston-check](<sdcard/ports/projectdiablo2/compat/weston-check/manifest.json>), reproducibly built by pinned Zig0.15.2 (official SHA in manifest). Guard and watcher use separate inherited RAM FD (`PD2_FAULT_FD`), bounded PC/FP/maps protocol; watcher catches faults after application replaces handlers. Complete parser emits module roles/file offsets, fixed tokens, stage results, coverage, partial/truncation flags and hypothesis-only `next_actions`; never persists absolute addresses, paths or raw driver text. Native identity hashes have fixed budget and no path output.
- Two review fixes: always kill remaining process group after leader exit; snapshot capture lengths before diagnostic TERM/KILL. Pixman case skips unless explicit staged module mapping exists; native artifacts stage into private executable tmpfs and reverify bytes before exec; report keeps prior cases on timeout/interrupt and marks `partial_report`.
- Synthetic validation: complete suite52/52, fault guard/watcher19/19, v2/startup35/35, v3 parser included in complete suite. Actual device/game/compositor never run by agent. Final ZIP should be sent once; future diagnostic only if this report is partial or introduces new hardware fact.

## Performance Overlay — FPS Color Thresholds & R36S Naming Standardization

- **FPS Color Thresholds (`scripts/overlay/x11_hud.py`):**
  - Updated frametime graph coloring logic:
    - `> 20 FPS`: Green (`C_CHART_OK`, `(70, 225, 95)`, frametime `< 50.0ms`).
    - `15–20 FPS`: Orange (`C_CHART_WARN`, `(255, 180, 50)`, frametime `50.0ms – 66.7ms`).
    - `< 15 FPS`: Red (`C_CHART_BAD`, `(255, 75, 75)`, frametime `> 66.7ms`).
  - Implemented standalone `get_chart_color(frametime_ms)` helper with float conversion and edge-case handling (`val <= 0` defaults green).
  - Adjusted chart ceiling `max_ms = 80.0` (when `show_y_scale=False`) to avoid flatline ceiling clamping above 60.0ms; frametimes down to 12.5 FPS remain visually distinct.
  - Adjusted subtle chart target guideline to 20 FPS (`50.0ms`).
- **R36S Naming Standardization:**
  - Removed all unrelated "Steam Deck" and "steamdeck" references across `scripts/overlay/` (`__init__.py`, `performance_overlay.py`, `x11_hud.py`), `tests/test_performance_overlay.py`, `docs/PERFORMANCE-OVERLAY.md`, and `docs/README.md`.
  - Standardized all terminology to R36S (`R36S Bar`, `R36S OVERLAY 1.0`).
- **Unit Testing & Validation:**
  - Added `test_chart_color_thresholds` in `tests/test_performance_overlay.py` covering all threshold boundaries (16.6ms, 33.3ms, 40ms, 49.9ms, 50.0ms, 55.0ms, 60.0ms, 66.6ms, 66.7ms, 66.8ms, 70.0ms, 100.0ms, <=0ms). 16/16 overlay tests PASS; 43/43 layout tests PASS.

---

## Performance Overlay — Zero-Overhead Level 1 Optimization & Selective Metrics Collection

- **Diagnostic Investigation:**
  - On RK3326 Cortex-A35, `SystemMetrics.sample()` was taking ~8.0ms per sample (~26ms per second) due to repeated directory walks (`glob.glob`) and multi-file `/proc` and `/sys` parsing.
  - In Level 1, all system metrics (CPU, RAM, GPU, thermal, battery) were collected even though Level 1 only displays the FPS number.
  - `pd2-present.jsonl` was reopened and closed on every loop tick.
  - HUD was redrawing on every tick even when the FPS value was completely unchanged.
- **Architectural & Performance Optimizations:**
  - **Level-Selective Collection (`overlay_metrics.py`):**
    - `sample(level=1)` returns `{}` immediately: dropped sampling cost from **7.98 ms down to 0.0018 ms** (4400× speedup, 0.00% CPU).
    - `level=2` collects only aggregate CPU, RAM, GPU %, and Battery (skips per-core CPU, CPU MHz, thermal zone, and swap).
    - `level=3` collects what Level 3 displays (skips per-core CPU and swap).
    - Cached sysfs paths (`thermal_paths`, `devfreq_paths`, `power_supplies`, `cpu_freq_path`) in `__init__` once, completely eliminating per-tick directory walks.
  - **Persistent Telemetry Stream (`fps_tracker.py`):**
    - Retains open file handle on `pd2-present.jsonl` across loop iterations; reads newly appended lines without opening, closing, or re-stating file size every tick.
  - **Redraw Throttling in Level 1 (`x11_hud.py`):**
    - If FPS value is unchanged between frames, `render()` skips X11 drawing requests completely.
    - Throttled window restacking (`ConfigureWindow`) from every frame to once every 30 frames.
    - Removed debug loop logging to prevent flash/microSD disk writes during gameplay.
- **Deployment & Verification:** Deployed to `192.168.50.135`. Unit tests (15/15) pass. Console benchmark confirmed 0.0018ms per sample in Level 1.

---

## Performance Overlay — Launcher Fix for Level 1 & Level 4 Chart Legend Removal

- **Level 1 Overlay Launcher Fix (`run-game.sh`):**
  - Previously, `run-game.sh` routed level 1 through legacy `fps_renderer.py`, replacing `ddraw.dll` with an old companion that rendered hardcoded `"FPS: XX"`.
  - Updated launcher pattern from `^[2-4]$` to `^[1-4]$` for both `present_renderer.py` and `performance_overlay.py`. Level 1 now properly launches the new minimal pill showing only the clean white number (e.g. `36`).
- **Level 4 Graph Legend Removal (`x11_hud.py`):**
  - Disabled Y-axis legend scale (`50`, `40`, `30`, `20`, `10`, `0`) and ticks from Level 4 chart (`show_y_scale=False`).
  - Graph now spans the full chart width inside the slate border cleanly matching Level 3 aesthetics.
- **Deployment & Verification:** Deployed `run-game.sh` and `overlay/*.py` to `192.168.50.135`. Regression tests pass.

---

## Performance Overlay — Level 1 FPS-Only Pill & Level 3 CPU/GPU Layout Alignment

- **Level 1 Minimal Number-Only Pill (`x11_hud.py`):**
  - Removed "FPS" label per hardware screenshot reference (`media_1792927131570_05bc8c8c.jpg`).
  - Dimensions compacted to `34 × 16 px`, positioned top-left (`x=8, y=0`).
  - Displays only the cool white FPS number (`C_VAL_FPS`) on semi-transparent dark charcoal backing (`C_BG_ALPHA = 175`).
- **Level 3 GPU & CPU Layout Alignment:**
  - Updated GPU and CPU sections to match Level 4 structure:
    - GPU: `GPU  XX%  XX°C` line + `XX MHz` clock line below.
    - CPU: `CPU  XX%  XX°C` line + `XX MHz` clock line below.
  - Dimensions adjusted to `205 × 136 px` to fit the multi-line layout with full-width framed frametime chart.
- **Deployment & Verification:** Deployed to console `192.168.50.135`. Unit tests (12/12) and console verification pass.

---

## Performance Overlay — Steam Deck Level 4 Replica (Live Line Graph with Y Scale & Core Stats)

- **Exact Level 4 Styling (`x11_hud.py`):**
  - Dimensions: `205 × 226 px`, glued to top-left edge with 32-bit ARGB semi-transparent background (`C_BG_ALPHA = 175`).
  - Top header: `Time HH:MM:SS` with `R36S 1.0` right aligned.
  - GPU: `GPU  XX%  XX°C` and `500 MHz` line. Added degree symbol `°` to `FONT_6X9`.
  - CPU: `CPU  XX%  XX°C` and `1296 MHz` line.
  - Per-Core CPU breakdown: Individual lines for `CPU0`, `CPU1`, `CPU2`, `CPU3` with utilization % and frequency.
  - RAM: `RAM  used_mb M / total_mb M`.
  - Battery: `BATT  XX%  [~]  X.XV` with charging plug indicator.
  - Gamescope: `GAMESCOPE  XX FPS  XX.Xms`.
  - Frametime: `Frametime  min: XXms, max: XXms`.
  - **Frametime Live Line Graph with Right Y-Scale:**
    - Live fluctuating green line across subtle horizontal grid ticks.
    - Right-side Y-axis scale numbers: `50`, `40`, `30`, `20`, `10`, `0` ms in `C_MUTED`.
    - 0..50ms scaled chart.
  - Footer: `Display Hz  60`.
- **Deployment & Verification:** Deployed to console `192.168.50.135`. Regression tests pass.

---

## Performance Overlay — 32-bit ARGB Hardware Transparency, Lowercase Font & Frametime Chart Box

- **True 32-bit ARGB Hardware Alpha Transparency (`x11_hud.py`):**
  - Eliminated 1-bit SHAPE dither which punched holes into 1-pixel font glyphs.
  - Implemented dynamic scan of X11 server connection setup reply for depth 32 TrueColor visual (`class == 4`).
  - Allocated dedicated 32-bit Colormap via `CreateColormap` (Opcode 78).
  - Created 32-bit ARGB `override_redirect` window with premultiplied alpha (`C_BG_ALPHA = 175` ~68% opacity).
  - Top-level `override_redirect` surface composites smoothly over running game via Weston's GPU OpenGL ES renderer (`gl-renderer.so`).
- **Font Lowercase Glyph Definitions (`FONT_6X9`):**
  - Added full 26-letter lowercase alphabet (`a` through `z`).
  - Fixed `'mIN'` and `'mAX'`: previous font table only had lowercase `'m'`, `'s'`, `'c'`, causing missing `'i, n, a, x'` to fallback to uppercase. Now renders exact lowercase `'min:'` and `'max:'`.
- **Frametime Chart Layout & Framing:**
  - Added `with_border` parameter to `draw_chart` with slate frame (`C_BORDER`).
  - Stretched frametime line horizontally across all inner columns: `n_samples` interpolated across full inner width.
  - Chart fills full remaining vertical height (`chart_y = 86`, `chart_h = self.height - chart_y - 4 = 30px`) down to bottom border.
  - Increased `history_size` from 32 to 200 samples in `fps_tracker.py`.
- **Deployment & Verification:**
  - Deployed to console `192.168.50.135:/roms2/ports/projectdiablo2/scripts/overlay/`.
  - Static tests and console test suite passed.

---

## Performance Overlay — Level 3 Scale (1/4 Screen Height) & Full-Width Chart

- **Scale & Dimensions Adjusted:**
  - Expanded height from 74px to **120px** (exactly 1/4 of device height: 480 / 4 = 120px).
  - Width set to **190px** (`190 × 120 px`).
  - Row spacing adjusted to 14px advance for comfortable legibility.
  - **Full-Width Frametime Graph:** The live green line chart stretches across the full width of the box (`chart_x = 6`, `chart_w = 178`, `chart_h = 24`) with a 6px border on each side.
- **Transparency Bugfix:**
  - In `ShapeMask` request, fixed wire format from `<IBB2xhhI` (which incorrectly placed window first, triggering X11 `BadWindow 0x0`) to `<BB2xIhhI` (`SHAPE_OP`, `SHAPE_KIND`, pad, `WINDOW`, `X`, `Y`, `PIXMAP`).
  - Fixed `try_reparent_to_game` packing (`int(child)`, `int(self.x)`, `int(self.y)`).
- **Verification & Deployment:** Tested on device (`192.168.50.135`). Deployed to `/roms2/ports/projectdiablo2/scripts/overlay/`.

---

## Performance Overlay — Steam Deck Level 3 Alignment & Height Optimization

- **Level 3 Redesign:**
  - Matched Steam Deck hardware screenshot layout:
    - Row 1: `GPU` (emerald green `#3cd773`) `XX%` `gpu_mhz MHz`
    - Row 2: `CPU` (dodger blue `#379bff`) `XX%` `cpu_mhz M` `temp°C`
    - Row 3: `RAM` (orchid pink `#dc69c3`) `ram_used M` `/ ram_total M`
    - Row 4: `BATT` (salmon coral `#f2645a`) `bat_pct %` `~` (cyan plug when charging) `bat_volts V`
    - Row 5: `GAMESCOPE` (salmon coral `#f2645a`) `fps FPS` `ft ms`
    - Row 6: `Frametime` (salmon coral `#f2645a`) `min-max ms`
    - Row 7: Frametime live emerald green line graph (`draw_chart`)
  - **Height Compacted:** Reduced height from 100px to **74px** (width 175px). Snug fit around content with zero wasted dead space below the graph.
- **Transparency Bugfix:**
  - Resolved socket timeout in `_setup_shape_transparency`:
    - `CreateGC` wire format previously packed 4 uint32s instead of 3, leaving 4 dangling bytes in the socket.
    - Resource IDs allocated cleanly via client bitmask (`bit3`, `bit4`).
    - `_roundtrip()` updated to only read `extra_units` when `reply[0] == 1`, preventing socket desynchronization on errors.
- **Verification & Deployment:** Tested on target device (`192.168.50.135`). Unit tests pass (12/12). Deployed to `/roms2/ports/projectdiablo2/scripts/overlay/`.

---

## Performance Overlay — Steam Deck Level 2 Replica & Visual Polish

- **Exact Steam Deck Level 2 Styling:**
  - Upgraded font to custom 6×9 pixel-crafted bitmap font (`FONT_6X9`) with +55% pixel area for enhanced legibility on 3.5" 640×480 screen.
  - Matched exact Steam Deck MangoHUD colors from hardware screenshot:
    - `FPS`: Salmon/coral red (`#f2645a`)
    - FPS value: Cool white (`#ebf5ff`)
    - Separators `|`: Purple/violet (`#825f91`)
    - Frametime chart: Emerald green line (`#46e15f`)
    - `CPU`: Dodger/sky blue (`#379bff`), value in white (CPU frequency removed from Level 2 per request)
    - `GPU`: Emerald green (`#3cd773`), value in white
    - `RAM`: Orchid pink (`#dc69c3`), value in white
    - `BATT`: Salmon/coral red (`#f2645a`), value in white
    - Wall plug icon: Bright cyan AC plug glyph `~` displayed next to `BATT` when device is charging or on wall power (`/sys/class/power_supply/*/online == 1` or `status in ('Charging', 'Full')`).
  - Added live horizontal frametime line graph (42×9 px) in Level 2 between `FPS` and `CPU` replacing frame latency number.
  - Semi-transparent background support (`TRANSPARENT_BG = True`) using X11 50% stipple shape mask with graceful fallback to solid black.
- **Verification & Deployment:** Tested on target console (`192.168.50.135`). Unit tests pass (12/12). Deployed to `/roms2/ports/projectdiablo2/scripts/overlay/`.

---

## Performance Overlay (Steam Deck / MangoHUD style) — Visual Polish & Telemetry Fix

- **Telemetry Root Cause:** When `fps_enabled` was set to levels 2, 3, or 4, `run-game.sh` previously skipped invoking `present_renderer.py`. In normal sessions, `ddraw.dll` was the default upstream cnc-ddraw, which does not emit `pd2-present.jsonl`. Without telemetry, `FPSTracker` saw no updates and displayed `0 FPS`. Fixed by invoking `present_renderer.py` in `run-game.sh` when `fps_enabled =~ ^[2-4]$`.
- **GPU Usage Clarification:** In GDI mode, Diablo II executes via software rasterization in Box86 on the ARM Cortex-A35 CPU. The Mali-G31 GPU is only used by the Weston compositor to scan out the 2D surface to DRM/KMS. Low GPU load (typically 0% to 15%) is normal and accurate for GDI 2D games on RK3326.
- **Accurate Steam Deck Theme:**
  - Background set to pure black (`rgb(0, 0, 0)`) with subtle dark border (`rgb(40, 46, 56)`).
  - Labels (`FPS`, `CPU`, `GPU`, `RAM`, `BAT`) styled in Steam Deck muted slate grey (`rgb(135, 148, 162)`).
  - Values styled in crisp white (`rgb(245, 245, 250)`), FPS in bright neon lime green (`rgb(95, 225, 115)`), accents in cyan (`rgb(110, 195, 255)`), and battery in yellow (`rgb(240, 220, 85)`).
- **Positioning & Configuration:**
  - Glued to top edge (`y = 0`) for levels 2, 3, 4 (`OVERLAY_TOP_Y = 0`).
  - Level 2 compacted to 380×18 px, centered horizontally by default (`(SCREEN_WIDTH - width) // 2` -> 130).
  - Layout constants declared at the top of [x11_hud.py](sdcard/ports/projectdiablo2/scripts/overlay/x11_hud.py) for easy modification by developers and agents (`LEVEL2_ALIGN`, `LEVEL2_WIDTH`, etc.).
  - Level 4 header renamed from `STEAM DECK OVERLAY [L4]` to `R36S OVERLAY 1.0`.
- **Namespace Cleanliness:** Renamed `scripts/overlay/metrics.py` to `overlay_metrics.py` to eliminate python module shadowing with the root diagnostic `scripts/metrics.py`.
- **Deployment:** Deployed directly to target console `192.168.50.135` via SCP. All local unit tests pass.

---

## Issue #2 — RG353V / dArkOS early Weston SIGSEGV

- [Issue #2](https://github.com/kadeshar/r36s-port-projectdiablo2/issues/2), firmware `dArkOS_RG353v_trixie_08282026`, port0.1.18. Downloaded attachment contains only20 sanitized JSONL lines: native providers ready, seatd_ready, weston_start, rc139, compositor_failed. No module/X11/Wine/game stage;40 raw lines omitted. Early Crusty/native initialization suspected, not established. No backtrace; provider ready validates discovery/load/ELF, not graphics initialization. Previous R36S input-block regression is a different later rc1 failure.
- Upstream dArkOS builds use chipset libMali plus custom SDL; “trixie” alone does not establish Mesa/GLVND. Do not globally replace providers, change renderer or reset prefix/saves on this evidence.
- Added manually invoked [constructor check](<sdcard/ports/projectdiablo2/scripts/weston_check.py>) and [procedure](<docs/ISSUE-2-RG353V.md>). Private read-only SquashFS mount; only `wp_weston --version` plain/Crusty, no real compositor session or game. Native children use sanitized environments, bounded256KiB verified tmpfs capture,10s deadline, process-group cleanup, core dumps disabled. Report contains fixed enums/rc/signals, never raw paths/loader text. Matching production constructor failure is actionable evidence; both checks passing is explicitly inconclusive.
- Production launcher, shared runtime scripts, runtime binaries, game/config/prefix/saves untouched. No actual console/runtime/game check executed by agent. User/reporter must manually provide affected-device diagnostic JSON before a hardware fix can be justified. Initial full Linux regression:759 tests OK,4 skipped (560.438s). Windows initial run hit temporary-fixture permission errors, so Linux verification used instead.
- User has no affected device; requested handoff-ready diagnostic version. Added optional [Ports entry](<sdcard/ports/Project Diablo 2 - Weston Check.sh>), no production-launcher delegation, saves only sanitized `logs/pd2-weston-check.json`. Helper now standalone, mirrors production ELF/provider discovery and authenticates SquashFS against pinned size/SHA256 before execution. Reporter copies two files, runs optional Ports entry, returns JSON plus exact device/firmware; no ZIP or complete port replacement. Final targeted Linux tests:diagnostic15/15, graphics-provider11/11; Bash syntax and protected-production diff checks pass. Full suite above predates final handoff changes; no claim of another full run.

## Season 14 native-cast compatibility and future-season fallback

- SSH failures `20261023T181009Z-32050` / `20261023T181036Z-33035`: `unsupported_runtime` in preflight, before Wine. Imported S14 ProjectDiablo.dll changed to 5252096 bytes / SHA256 `41d49d63d531050bb0c89db9efd191fefd322378683159be5dc059498ae1e424`; S13-only native-cast authentication rejected it. SGD2FreeRes.dll remained the existing pinned build.
- User requested optional binary fixes stop blocking unknown seasonal DLLs, plus a proper S14 patch. [Builder](<sdcard/ports/projectdiablo2/scripts/native_cast.py>) now recognizes two exact builds; unknown bytes are never patched. [Layout](<sdcard/ports/projectdiablo2/scripts/layout.py>) falls back to the imported ProjectDiablo DLL and emits fixed `session_probe/native_cast/unknown_source`; stale cached work links reset to the current original. Known target corruption, unsafe paths and runtime artifact validation still fail closed. No production-launcher changes.
- Offline normalized disassembly establishes S14 callsites RVA `0x29BBC5` (`e8963e0500`) / `0x29C0FF` (`e85c390500`) → original stdcall sender `0x2EFA60`. Native-mode byte `0x4AC2FE`; width/height/mouseY pointer slots `0x5D6F08` / `0x5D6E20` / `0x5D6E2C`. Sender, native dispatch and global-reference contexts compared with S13; no blind fixed-offset shift or runtime pattern search. Same 79-byte PIC wrapper, native+640×480 guards, signed Y>431→240, register/flag preservation, original sender once/ret4.
- S14 derivative 5252608 bytes / SHA256 `22901728b35ca2a8054fe8e97b5a84a32f5aa5bfae6eabbf1edf35d1ff1de58e`, cache `compat/pd2-native-cast-640-s14-v1`. S13 derivative/cache remain byte-for-byte unchanged. Private source DLLs only downloaded for analysis; no proprietary DLL added to the distribution. Actual builds independently checked for source pins, call targets, PE structure and permitted mutation scope (23 changed original bytes plus appended section).
- Synthetic S13/S14 tests cover both callsites, source/target pins, PE guards, ABI, relocation bases and native/resolution/signed-Y guards; layout tests cover future builds, stale links, per-build caches and corrupted known outputs. Safe logger accepts only fixed native-cast statuses `applied`/`unknown_source` in preflight/launch. Hardware gameplay acceptance must separately verify S14 R2/A outside town, inventory/stash reopen, town restriction, 800×600 and clean exit.
- Validation: 36 native-cast/forward-compatibility tests, 40 safe-log tests and 43 layout tests all pass on a private native Linux filesystem (119 total). Full WSL regression ran 747 tests with 5 skips and one Windows-backed filesystem directory-rename PermissionError; Windows full run likewise hit fixture rename errors. Focused native-Linux rerun avoids those filesystem problems. Pure synthetic S13/S14 tests and independent review pass; no user hardware acceptance claimed.
- User subsequently established the permanent rule in [AGENTS.md](<AGENTS.md#L184>): only the user launches/tests the real game on the console. No further agent game/launcher execution, including SSH smoke tests; future verification is synthetic/static plus analysis of user-provided logs. The earlier agent-started SSH session `20261023T185050Z-17595` reached `game` and exited with game/runtime/shutdown rc0 and `winmm_opened`; this is not user gameplay acceptance and must not be repeated.
- Deployed only layout/native_cast/safe_log helpers under the production session lock; deployed originals matched repository HEAD. Backup `/home/ark/.local/share/pd2-r36s/season14-code-backup-20261023`; deployment report confirms all 29 protected config/save/registry/launcher/imported-DLL files unchanged. Both real source→target builds verified again on ARM, S14 authenticated cache created. No Wine/game run during deployment. Subsequent SSH smoke launch uses only session-local normal PATH and `PD2_START_MENU=0` (SSH's default PATH omits runuser); preflight `native_cast=applied`, GDI/Weston/X11 and volatile-work preparation pass.

## Production audio promoted from user-validated Audio B

- User confirmed Audio B waveOut works correctly without lag, then explicitly requested production promotion, cleanup of unnecessary uncommitted experiments, and removal of README Known Issues. Normal Game.exe now uses D2Sound → DSOAL → OpenAL Soft WinMM → Wine waveOut → winealsa/ALSA. Same Wine8/Box86/GDI/Weston/native controls and SAFEFLAGS1/CALLRET0. Main launcher, Weston adapter and layout unchanged; shared runner intentionally updated for production.
- Implementation: [helper](<sdcard/ports/projectdiablo2/scripts/audio_dsoal.py>), [builder](<tools/build_dsoal_audio.py>). Native-only dsound/dsoal-aldrv (no builtin fallback), ALSOFT_DRIVERS=winmm, HRTFoff/linear resampler/rt-prio0, SDLdummy, DSOALerrors-only. DLLs authenticate before staging into fresh private tmpfs, after Wine setup. Prefix/config/saves stay production's existing originals; test saves are never silently promoted or deleted.
- DSOAL1cdd8df67f4f93ced64ddf8f9c70882560bbcd41 and OpenALSoft1.23.1d3875f333fb6abe2f39d82caca329414871ae53b, PE32x86/staticCRT. DSOAL default alcOpenDevice(nullptr) patch required for WinMM name matching, plus explicit <string> for MSVC. Complete source archives/patch/builder/LGPL licenses retained in compat/dsoal, added to release allowlist. DLL bytes unchanged from user-validated B.
- [Manifest](<sdcard/ports/projectdiablo2/compat/dsoal/manifest.json>) canonical LF SHA256 9b2a8e0abc29d5adceafbf0585c7cce9ecaeb6571a2c1fd1eb318f9513bb5ce0; CRLF SHA256 b1cea47159b4ce1cdcdebfc5249fd33e406dc5fc8475a4586fc0e47a1923cf48; dsound.dll 7b6c2fbbf843dc29cd69936aa75e6d8b8cbce485788baac7965daf6cf8ce09f6; dsoal-aldrv.dll fc68b06ed47895a88717dc8a90d089818febf8baab860a8961676da6159e6d7c. DirectSound ordinals1/2 verified on console. alBufferDataStatic resolved through alcGetProcAddress, not a required PE export. Layout excludes imported dsound/dsoal-aldrv DLLs from work linking to prevent staging collisions.
- Production logs live in prefix/drive_c/pd2-audio/<session>. Collect only after successful Wine quiescence; bounded1MiB/log, forbid mutable hardlinks/symlinks. winmm_opened requires actual WinMM init/playback selection/device creation. Missing proof records unconfirmed and fails session, no false success from driver request alone. Safe logger accepts closed audio_output enums only.
- Removed uncommitted A/B, Dmix and Audio Layers launchers, duplicated orchestration, standalone diagnostic probes/tools/tests and superseded draft docs. Unrelated staged PortMaster reference preserved. Audio-fix guides and the obsolete investigation plan subsequently removed at user request; this section retains the findings and production procedure. Private ~/.local/share/pd2-r36s-audio-ab/{wine,waveout} states/saves remain as backups; user may have newer progress there, so do not overwrite either copy automatically.
- D2sound.dll actually imports DSOUND ordinals1/2, no verified Miles/MSS path. sound_mixer=0 semantics unknown, unchanged. Earlier claims about Miles and Wine MaxHardwareChannels/DefaultSampleRate as effective Wine8 fixes were unsupported. Wine8 reads HelBuflen; it is not direct evidence of output buffering or the proven root cause.
- Failed dmix160+HelBuflen65536+SDLdummy produced no improvement. Do not repeat as a new fix. Standalone prior native20s xruns0; waveOut20s had pollgap286ms/cursorstall1; builtinDirectSound aborted9.387s with XRUN/cursor_ambiguous1. User thought tones clean; not an all-pass. DSOAL/WinMM loader null recheck later passed5.071s/500refills/api_errors0 after an initial cursor-ambiguous run; null is not hardware sound/timing evidence. Positive gameplay listening feedback is separate user evidence, not a quantified FPS benchmark.
- Promotion validation: Windows regression suite705 tests OK,129 skipped (Linux-only/etc); 3 additional production payload/logger contracts PASS. On real R36S Linux: DSOAL29/29 PASS; runner81 covered (75 initial PASS, 6 hit the old15s test harness limit on A35). Raised only synthetic fixture deadline to45s, replaced fragile duration assertion with explicit held-child completion marker, cleaned only exact-nonce mock processes. Six failures and seven new integration cases rerun13/13 PASS; safe_log39/39 and production payload4/4 PASS. Actual runtime deadlines unchanged. Independent integration review found no blocking bugs.
- SSH reconnected and deployed14 exact-hash code/payload files directly under /roms2/ports with the common session lock held. Atomic runner switch after payload verification; no Wine/game/mixer execution. Production launcher/layout/Weston hashes unchanged. Production config/saves/registry and both A/B save/config copies compared before/after and preserved byte-for-byte.
- Removed4 experimental menu entries,6 copied orchestration/helpers and2 obsolete compat directories from active console port; retired code kept in /home/ark/.local/share/pd2-r36s/production-audio-backup-7142a6fd3b784307856658d9475d23fc with original changed code, preservation snapshot and deployment report. Test prefixes/saves remain untouched in ~/.local/share/pd2-r36s-audio-ab. User should now launch normal Project Diablo 2; first post-promotion gameplay is still user acceptance, not an automatically performed hardware test.

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
- **Audio:** Production uses DSOAL / OpenAL Soft WinMM / Wine waveOut with SDL dummy and legacy time32 ALSA. User validated lag-free Audio B before promotion. Dmix/HelBuflen experiments and their guides are retired; findings and validation retained at the top of this memory.
- **Performance:** Optimized Box86 Dynarec flags and memory thrashing prevention.
- **Testing:** Comprehensive regression test suite validating layouts, configurations, telemetry, and shell contracts.
- **Steam Deck Performance Overlay:** Replaced basic binary FPS counter in start menu with 5-tier Steam Deck performance overlay (Levels: Off, 1, 2, 3, 4). Built modular, zero-dependency X11 HUD in `scripts/overlay/` using core X11 `override_redirect` double-buffered Pixmap and `/proc`/`/sys` telemetry, easily portable to other PortMaster ports.

---

## 10. Issue #3 — SD Storage Experimental Launcher Preflight Logging & Menu Diagnostics

### Problem Reported:
- Issue #3 reporter (`gundamf890`) on R36H with dArkOSen reported:
  *"the game doesn't boot up, and it doesn't create any logs at all"*
- Earlier, reporter hit `insufficient_space` because production launcher placed the ~700 MB wineprefix into `$HOME/.local/share/pd2-r36s` on the rootfs rather than the SD card ROMs partition.
- Experimental SD storage port was provided, but failed before producing session logs.

### Root Cause Analysis:
1. **Preflight Logging Void:**
   - In `Project Diablo 2 - SD Storage Experimental.sh` and `storage_launcher.py`, no log file was opened until line 65 (`storage-session.log`), which was only used as output redirection for `subprocess.run(command)`.
   - Any exception during preflight (`sys.platform != 'linux'`, `os.getuid() == 0`, missing system tools, integrity check mismatch, `box86` `noexec` permission error, missing game data, or lock contention) raised `StorageError` or `OSError`.
   - The exception handler in `main()` printed to `sys.stderr`, which was swallowed by EmulationStation without redirection or console screen output. Result: 0 bytes written to `logs/`, immediate silent exit.
2. **Game Data Detection Restriction:**
   - `source_data(port)` strictly expected game data at `port.parent / 'projectdiablo2/gamedata'`.
   - If the user extracted `projectdiablo2-sd` alone or placed `Diablo II` directly into `projectdiablo2-sd/gamedata`, `source_data()` raised `StorageError` before launch.
3. **Menu Display Timeout & Input Fallback:**
   - `menu_x11.py` had a 5.0s `TIMEOUT` for core X11 connection, window creation, mapping, and expose event loop. On RK3326 Cortex-A35 during heavy startup I/O, this could time out and fail before the menu was visible.
   - `start_menu.py` `Pad.__init__` did not wrap device access in a try-except fallback block, risking hard failure on input permission issues.
4. **PortMaster Location:**
   - `private-launcher.sh` checked `/roms/ports/PortMaster`, `/opt/system/Tools/PortMaster`, etc., but omitted `/roms2/ports/PortMaster`.

### Implementation:
1. **Early Real-Time Diagnostic Logging (`storage_launcher.py` & `.sh`):**
   - Creates `logs/` directory immediately.
   - Opens `logs/storage-session.log` from step 1, logging UTC timestamps, platform, user UID, tool verification, manifest validation, Box86 permissions, game data path, and lock status.
   - Real-time streaming of adapter subprocess output into `storage-session.log`.
   - Added `fixed_message()` routing to `/dev/tty0` and `/dev/tty1` so error notifications appear on the physical console screen.
   - Any fatal preflight error writes a timestamped `[FATAL]` message and traceback to `storage-session.log`.
2. **Dual-Path Game Data Resolution (`storage_common.py` & `storage_session.py`):**
   - Supports local `projectdiablo2-sd/gamedata` (no bind-mount required) and external `projectdiablo2/gamedata` (bind-mounted ro).
   - Case-insensitive search for `ProjectD2/Game.exe`.
   - Descriptive error message on failure pointing to expected paths.
3. **Menu Robustness & Visibility (`menu_x11.py`, `start_menu.py`, `weston-session.sh`):**
   - Increased `menu_x11.py` `TIMEOUT` from 5.0s to 20.0s for RK3326 headroom.
   - Added graceful fallback and logging in `start_menu.py` `Pad` initialization.
   - Added user-facing console message (`/dev/tty0`) if the start menu fails to display.
4. **PortMaster Path Addition (`private-launcher.sh`):**
   - Added `/roms2/ports/PortMaster` to `controlfolder` candidates.
5. **Release Packaging (`package_user_zip.py`):**
   - Repackaged `releases/Project-Diablo-2-SD-Storage-Experimental.zip` with `--force` flag support, verifying 144 entries, 115 files, 0o755 executable attributes, and SHA-256 manifest.
   - All 50 synthetic test suite cases pass. Production payload in `sdcard/ports/projectdiablo2` remains untouched.

---

## 11. Issue #3 — Production Merge of SD Storage Architecture & Console Deployment

### Context & Confirmation:
- User `gundamf890` confirmed experimental SD storage fix solved boot issues: *"i can get into the game now, thanks"*.
- User requested merge of SD storage architecture into official production payload and deployment to physical R36S console (`192.168.50.135`).

### Architecture & Production Merging:
1. **Self-Wrapping Production Launcher (`sdcard/ports/Project Diablo 2.sh`):**
   - Outer run (`PD2_EXPERIMENT_ACTIVE != sd-storage-v1`): checks python3 availability, logs to `storage-session.log`, and executes `storage-tools/storage_launcher.py`.
   - Inner run (`PD2_EXPERIMENT_ACTIVE == sd-storage-v1`): executes the full production launcher body in the isolated mount namespace with `PD2_STATE="$PD2_EXPERIMENT_STATE"`, satisfying all PortMaster contracts and regression test suites.
2. **Storage Tools Integration (`sdcard/ports/projectdiablo2/storage-tools/`):**
   - Merged `storage_common.py`, `storage_launcher.py`, and `storage_session.py`.
   - Supports dual port names (`projectdiablo2` and `projectdiablo2-sd`).
   - Dual game data resolution (local in `gamedata/` or bind-mounted from external port directory).
   - Manages `state.ext4` mount and `wine-8.0-x86.squashfs` mount in private unshared namespace.
3. **Audio DSOAL Path Acceptance (`scripts/audio_dsoal.py` & `scripts/experimental_audio_storage.py`):**
   - Updated `audio_dsoal.py` and `experimental_audio_storage.py` to accept workspace under `projectdiablo2/storage/mounted-state`.
   - Dynamic fallback import ensuring module resolution both from parent repo tests and child runtime.
4. **Release Tracking (`release-files.json`):**
   - Added `storage-tools/*`, `storage-manifest.json`, `private-launcher.sh`, `experimental_audio_storage.py`.

### Test Verification:
- `tests/test_storage_check.py`: 15/15 PASS.
- `tests/test_layout.py`: 43/43 PASS.
- `tests/test_start_menu.py`: 28/28 PASS.
- `tests/test_controller_mode.py`: 18/18 PASS.
- `tests/test_runtime_fix.py`: 6/6 PASS.
- `tests/test_fetch_metrics.py`: 9/9 PASS.
- `tests/test_menu_x11.py`: 21/21 PASS.
- `tests/test_audio_dsoal.py`: 30/30 PASS.
- `tests/test_payload_cleanup.py`: 4/4 PASS.

### Physical Device Deployment (`192.168.50.135`):
- Uploaded `Project Diablo 2.sh` to `/roms2/ports/`.
- Uploaded `private-launcher.sh`, `storage-manifest.json`, `storage-tools/`, and updated `scripts/` to `/roms2/ports/projectdiablo2/`.
- Copied `wine-8.0-x86.squashfs` (74 MB) and `state.ext4` (1 GB) from `/roms2/ports/projectdiablo2-sd/` to `/roms2/ports/projectdiablo2/`.
- Validated on-device via non-executing check:
  `python3 -B /roms2/ports/projectdiablo2/storage-tools/storage_launcher.py --port /roms2/ports/projectdiablo2 --check` -> PASS (Exit 0, 732 MB available, no wine/game execution).

---

## 12. Non-Production Diagnostic Payloads Cleanup

- Relocated all non-production diagnostic check launchers and helpers out of the production tree into `.temp/projectdiablo2-weston-complete/`:
  - Launchers: `sdcard/ports/Project Diablo 2 - Complete Check.sh`, `sdcard/ports/Project Diablo 2 - Weston Check v2.sh`
  - Orchestration & sanitizers: `sdcard/ports/projectdiablo2/scripts/weston_check.py`, `weston_startup_check.py`, `weston_startup_log.py`, `weston_complete_check.py`, `weston_complete_log.py`
  - Native fault-guard compat: `sdcard/ports/projectdiablo2/compat/weston-check/`
  - Build tools: `tools/build_weston_fault_guard.py`, `tools/weston_fault_guard.c`, `tools/weston_fault_watch.c`
  - Synthetic diagnostic tests: `tests/test_weston_check.py`, `tests/test_weston_startup_check.py`, `tests/test_weston_startup_log.py`, `tests/test_weston_complete_check.py`, `tests/test_weston_complete_log.py`, `tests/test_weston_fault_guard.py`
  - Leftover test root fixture: `safe-log-test-*` moved into `.temp/`
- Pruned all diagnostic entries from `release-files.json`.
- Restored `tests/test_payload_cleanup.py` (`test_only_production_launcher_is_distributed`) to assert strictly single launcher `Project Diablo 2.sh`.
- Test verification: `tests/test_payload_cleanup.py` 4/4 PASS.

---

## 13. Deployment of Project Diablo 2 R36S port 1.0.zip via SSH

- Uploaded `.temp/release/Project Diablo 2 R36S port 1.0.zip` (187,902,050 bytes, SHA256: `7869a603e1f9413574cfb3bcaeff8d032a3bff48eda7bb5d63ea718e1d95c166`) directly to target console (`192.168.50.135:/roms2/ports/`) via PSCP.
- Verified checksum and file size matching bit-for-bit on-device.
- Extracted package cleanly into `/roms2/ports/` via `unzip -o`. User data (`saves/`, `config/`, `gamedata/Diablo II/`, and `storage/state.ext4`) remained untouched.
- Ran non-executing verification on device:
  `python3 -B /roms2/ports/projectdiablo2/storage-tools/storage_launcher.py --port /roms2/ports/projectdiablo2 --check` -> PASS (Exit 0, ext4 image and read-only Wine mounted in private namespace, no Wine or game executed).
- Full local layout regression tests passed (43/43 PASS).

---

## 14. In-Game Performance Overlay Hotkey Controls & Dedicated FPS Telemetry Sections

- **Background Gamepad Hotkey Listener (`scripts/overlay/hotkey_listener.py`):**
  - Monitors `/dev/input/event*` devices non-blocking via Python standard library (`select`, `struct`, `threading`).
  - Implements in-game hotkey combinations:
    - **FN + R1** (`0x2c4` + `0x137` / `BTN_TR`): Dynamically cycles overlay levels (`0 -> 1 -> 2 -> 3 -> 4 -> 0`).
    - **FN + R2** (`0x2c4` + `0x139` / `BTN_TR2` or `ABS_RZ >= 128`): Resets the frametime graph and recalculates `AVG`, `1% LOW`, and `0.1%low` fresh.
    - Also accepts Select (`0x2c0` / `0x13a`) and virtual Xbox Mode (`0x13c`) as secondary alias modifiers.
  - Edge-triggered with 0.35s debouncing to prevent accidental multi-triggers.
  - Responsive instant thread shutdown via `threading.Event`.

- **Dedicated FPS Telemetry Sections Replacing GAMESCOPE:**
  - Replaced the single `GAMESCOPE` section in Level 3 and Level 4 with four distinct telemetry rows:
    - `FPS`: Instantaneous / current frame rate.
    - `AVG`: Average frame rate accumulated since last reset.
    - `1% LOW`: Average of the lowest 1% of frame times converted to FPS.
    - `0.1%low`: Average of the lowest 0.1% of frame times converted to FPS.
    - Followed by `Frametime` in ms and the color-coded live frametime graph.
  - Updated layout dimensions:
    - Level 3 (Detailed HUD): 205 × 176 px (increased from 136 px to accommodate 4 FPS rows).
    - Level 4 (Full OSD): 205 × 266 px (increased from 226 px to accommodate 4 FPS rows).

- **`FPSTracker` Statistical Engine (`scripts/overlay/fps_tracker.py`):**
  - Added tracking for `low_1pct` and `low_01pct` percentiles.
  - Added `reset()` method to clear `history` (frametime graph) and reset `all_fps_samples`, `avg_fps`, `min_fps`, `max_fps`, `low_1pct`, and `low_01pct`.

- **Dynamic HUD Level Switching (`scripts/overlay/x11_hud.py`):**
  - Added `set_level(new_level)` to dynamically resize and reposition the unmanaged override-redirect X11 window using `ConfigureWindow` (opcode 12).
  - Frees and recreates the backbuffer pixmap (opcode 54 / 53) to match new dimensions without reconnecting or dropping X11 connection.
  - Supports Level 0 as hidden/unmapped window (`UnmapWindow` opcode 10) with zero rendering overhead, seamlessly mapping window (`MapWindow` opcode 8) when cycling to Level 1..4.

- **Verification & Testing:**
  - `tests/test_performance_overlay.py`: 20/20 PASS.
  - Tested synthetic hotkey event processing, debouncing, 1% and 0.1% low calculation, reset behavior, and HUD resizing.
  - Fixed Level 2 centering regression on dynamic switch: `_get_default_x` previously used stale `self.width` (from Level 1, 34px) instead of target level width (410px), resulting in `x=303` instead of `x=115`. Fixed by explicitly passing target `width=new_w` to `_get_default_x`. Regression tested and confirmed centered at `(640-410)//2 = 115`.
  - Executed fresh installation simulation via `tools/simulate_fresh_install.py`:
    - 32/32 saves backed up to `/roms2/ports/projectdiablo2-saves-backup-20261027_080605`.
    - Removed `storage/state.ext4`, session locks, runtime caches, and logs.
    - Verified all 32 saves preserved in place and `Game.exe` intact.
    - Console reset to clean first-boot state ready for user manual launch test.





