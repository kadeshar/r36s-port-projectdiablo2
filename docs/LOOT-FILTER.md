# Loot Filter Selection (R36S) — Issue #7

This document explains how loot filters are chosen for the Project Diablo 2 (D2 LoD)
port on the R36S, why the launcher menu is the selection point, and the safety rules
that govern filter files.

---

## 1. How the Game Reads Loot Filters

The PD2 engine reads exactly one file: `ProjectD2/default.filter`, resolved from the
game working directory at load time. There is no in-engine "browse" for other filter
files. Selecting a community filter therefore means **copying the chosen file over
`default.filter` before the game starts** — which is what the port's launcher does.

The in-game options "Enable Loot Filter" and "Filter Level" are separate, game-owned
JSON settings (handled by the existing sync pipeline). They do **not** choose which
filter file is used; they only enable/level the filtering feature itself. Leave
"Enable Loot Filter" turned on in the game options for the filter to take effect.

The game reloads the active filter when **Numpad 0** is pressed in-game, so a filter
swapped between sessions is picked up on the next launch, and an edited file can be
re-read without restarting.

## 2. Where User Filters Live

```
/roms2/ports/projectdiablo2/filters/     (port/filters/, read-only to the game)
├── .keep                                # placeholder documenting the drop directory
├── MyFilter.filter                      # drop community filters here
└── ...
```

- The directory is created with a comment-only `.keep` placeholder; it is not a
  filter and is never loaded.
- The original donor `default.filter` stays in `port/defaults/default.filter` and the
  game data (`gamedata/`) is never touched. "DEFAULT" in the menu always means the
  shipped no-filter default.
- A drop copy of any community filter file is placed into this directory. No
  installation step is needed; the menu lists the directory contents at launch.

### File name and size rules

| Rule | Value | Why |
|---|---|---|
| Name | first character `[A-Za-z0-9]`, then up to 127 characters of `[A-Za-z0-9._-]`, ending in `.filter` (total ≤ 135 chars) | Flat names only: no path separators, no hidden files, no directories. Keeps menu labels and shell quoting safe. |
| Type | regular file only | Symlinks, directories and hidden entries are skipped by the listing. |
| Size | **≤ 4 MiB** (`FILTER_LIMIT`) | The old 512 KiB `CONFIG_LIMIT` was the root cause of Issue #7: real community filters are commonly 1–3 MiB and were rejected. Filters are now validated with a dedicated 4 MiB bound; all other configs keep the 512 KiB limit. |
| Encoding | any byte content, **including ANSI (non-UTF-8)** | Many published filters are CP1250/CP1252/ASCII-ANSI mixes. Filter bytes pass through untouched — no decoding, no re-encoding. Only a NUL byte check applies (the game crashes on NUL-padded filter lines). |

## 3. Selecting a Filter in the Launcher Menu

The pre-game launcher menu (the 640×480 X11 screen that appears before launch) has
five rows:

| Row | Item | Controls |
|---|---|---|
| 0 | RESOLUTION | left/right cycles; confirm |
| 1 | PERF OVERLAY | left/right cycles level; confirm toggles |
| 2 | **LOOT FILTER** | left/right/confirm cycles: `DEFAULT` + every file in `port/filters/` (name order) |
| 3 | ENTER SANCTUARY / LAUNCH | confirm starts the game |
| 4 | EXIT TO SYSTEM | confirm cancels |

The menu opens on row 2 (the loot filter row). If the previous session selected a
filter that still exists, the menu opens with that filter highlighted; a stale or
deleted name safely falls back to `DEFAULT`.

Row labels are capped at 16 characters, so long filter names are abbreviated on the
row itself. While a longer name is held on the filter row for about 2 seconds, the
**full name floats in the same row**: the `LOOT FILTER:` prefix stays static while
only the name scrolls (marquee) inside the row's 16-character name window, so the
complete name can be read without leaving the row. The float disappears the moment
you change the row or the selection, and the 2-second timer restarts when you return
to the same long name. Names of 16 characters or fewer never float.

On launch, the confirmed choice is published as `config/default.filter` inside the
port and copied into the volatile game working directory; the choice is stored in
`config/settings.json` under `loot_filter` so the next menu opens on the last pick.
No persistent settings are written by a plain prepare — a session without an explicit
menu selection keeps `settings.json` byte-identical.

If the selected file disappears or is invalid at launch time, the launcher logs a
closed-enum `loot_filter` event with status `missing` and falls back to the shipped
`DEFAULT` filter instead of aborting.

## 4. Event and Log Discipline

Filter activity is reported through the existing `PD2_EVENT` stream with a closed
enum — never file names, paths or contents:

```json
{"event":"session_probe","phase":"preflight","check":"loot_filter","status":"missing"}
{"event":"session_probe","phase":"launch","check":"loot_filter","status":"selected","count":3}
{"event":"session_probe","phase":"launch","check":"loot_filter","status":"default"}
{"event":"session_probe","phase":"launch","check":"loot_filter","status":"unavailable"}
```

- `status`: `selected` | `default` | `missing` | `unavailable` (listing failed).
- `count` (optional, 0..512): number of user filters listed, for `launch`-phase events.
- The three-token launcher menu protocol is `resolution fps loot_filter`; the session
  shell validates each token independently and rejects a fourth token, a missing
  filter file, or a symlink before the game can start.

## 5. Component Map

| Component | Role |
|---|---|
| `scripts/layout.py` | `filter_content()` (4 MiB bound, NUL-only rejection, ANSI passthrough), `filter_listing()` (flat safe-name listing), `apply_loot_filter()` (atomic publish of `config/default.filter`), `prepare(loot_filter=...)` (session override + persistence) |
| `scripts/start_menu.py` | Row 2 cycles `DEFAULT` + listed filters; emits the closed-enum `loot_filter` event; prints the three-token selection; repaints on the loop timer while a long filter name is held so the marquee animates |
| `scripts/menu_x11.py` | Renders the five rows including `LOOT FILTER: <label>` (uppercase, 16-char max); after a 2 s hold the full name scrolls in the row's name window (static prefix, clipped marquee) |
| `scripts/weston-session.sh` | Validates the three tokens (`default` or a safe name that is a regular, non-symlink file under `port/filters/`), exports `PD2_LOOT_FILTER` unconditionally |
| `scripts/safe_log.py` | Accepts only the closed `loot_filter` statuses and the bounded optional count |
| `Project Diablo 2.sh`, `private-launcher.sh` | Guard and forward `PD2_LOOT_FILTER` from the stored choice into the menu session |

## 6. Quick Test Procedure (User)

1. Copy one or more community filters into
   `/roms2/ports/projectdiablo2/filters/` (name ending in `.filter`, ≤ 4 MiB).
2. Launch the port. On the pre-game menu, use left/right on the **LOOT FILTER** row
   to pick a filter (wait ~2 s on a long name: the full name scrolls in the row),
   then **ENTER SANCTUARY / LAUNCH**.
3. In game, ensure **Enable Loot Filter** is on; press **Numpad 0** to reload if
   needed.
4. Relaunch: the menu opens on the previously selected filter.
