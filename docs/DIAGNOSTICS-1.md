# Diagnostics-1 — PD2 / R36S

This is an **instrumentation/measurement package, not a promise of increased FPS or an OpenGL fix**. Previous Forward512/FastFlags tests did not improve 10–15 FPS, KMS/Auto remained black screens, and CALLRET failed before reaching gameplay. We are not blindly introducing another set of random flags or new runtimes.

## Installation

Extract `projectdiablo2-diagnostics-2.zip` (or `projectdiablo2-diagnostics-1.zip`) **into the existing ports directory**, overwriting port files. The ZIP contains startup files alongside the `projectdiablo2` directory, without an extra `sdcard` level. Keep your game, key, config, prefix, and saves intact; do not re-import the game. A save backup and a throwaway test character are recommended. Old packages remain available for rollback if needed.

In the Diagnostics-2 package:
- **OpenGL Unlocked (cnc-ddraw)**: Removed destructive `glGetTexImage` selftests in `render_ogl.c`, which under GL4ES on Mali caused an immediate silent fallback to software GDI.
- **Swapping Reduction**: The session adapter temporarily lowers `vm.swappiness=10` and restores it on exit, mitigating latency spikes caused by game memory thrashing to the slow microSD card.

## What to Run

Entries A/B/F launch the game without the port menu, at 800×600, BIGBLOCK=1, without an FPS overlay. Tests C/D/E display synthetic colors only — they do not launch the PD2 engine.

| Ports Entry (after "Project Diablo 2 -" prefix) | Purpose |
|---|---|
| Diag A GDI Stock | Stock cnc-ddraw without HUD, baseline for perceived smoothness. |
| Diag B GDI Measure | Same GDI, lightweight separate renderer: presentation counting in log, without HUD or surface copying. |
| Diag C SDL RGB | Native ARM32 SDL/GLES2 on real libraries, without GL4ES/Crusty and without Wine. |
| Diag D GLX RGB | Native ARM32 GLX through GL4ES/Crusty, still without Wine. |
| Diag E Wine RGB | Synthetic Windows DirectDraw through Wine and cnc-ddraw/OpenGL. |
| Diag F OpenGL Measure | Only if C/D/E display colors: OpenGL game + lightweight counter. |

C/D/E should display **red, green, blue** in sequence for ~2 seconds each, then return to Ports. The graphics process itself has a 15-second deadline + max 2 seconds for forced termination; total session startup and prefix preparation may take longer. C/D do not launch Wine or the mapper. E uses the existing prefix and audio/winebus recovery; it is not a fresh-prefix test.

### First Round

1. Launch **B**, select the same test character and location. 30 s warmup, 60 s standing still, 60 s combat, player count 1. Exit through the game menu. There is **no on-screen counter** — results are recorded in the log.
2. Repeat with **A**, evaluating perceived smoothness and input responsiveness. A intentionally does not provide a new FPS counter; do not mistake its absence of samples for zero FPS. To measure the cost of the old HUD overlay, you can also rerun the existing **Test 1 GDI Baseline** on the same scene after warmup.
3. Launch **C**, **D**, **E**. Record separately which colors you actually saw and which tests were black or failed to return automatically. If C is black, report the result before attempting lengthy F runs.
4. If C/D/E show RGB colors, launch **F**. If the game stays black, wait ~35 s for the diagnostic entry to be written, then exit via standard input methods; the absence of presentation **does not kill the game** and will not save your character for you.
5. Verify **five consecutive launches of B without rebooting the console**, including an immediate launch after graphics tests. Note the outcome of each launch: video, audio, controls, and clean return to Ports. This tests recovery, not benchmark throughput. Do not wipe the prefix between runs.

Do not rerun risky CALLRET/FastFlags on valuable saves. The immediate goal is identifying the bottleneck and the earliest broken graphics layer.

## What to Send

Send a safe log export plus a concise summary: A/B perceived fluidity, C/D/E visible colors vs black screen, F video/audio status, and five B launches: OK/failure. Never send game data, CD keys, wineprefix, or character saves.

Export from the port directory:

```sh
python3 scripts/safe_log.py export --dir logs --manifest runtime-manifest.json
```

This creates `logs/diagnostic-export.zip`. A maximum of 10 sessions are retained — export logs **before** running additional tests; copy the export to your PC before creating another. Describe the test sequence, as the log contains only bounded mode statuses, not character or scene names.

## Interpreting Results

- `setup_stage`: Named initialization stage; `status=failed` isolates the failure point. Setup, registry recovery, and Wine shutdown use conservative flags: BIGBLOCK=1, SAFEFLAGS=1, CALLRET=0. FORWARD512/CALLRET/FastFlags apply strictly to the game process, not prefix setup.
- `render_status=window_ready`: The backend entered the renderer with a valid window handle (OpenGL after context activation). **Does not guarantee a visible window.**
- `render_status=first_present`: First successful call to the presentation API; still does not prove physical pixels on the LCD panel.
- `render_sample`: Number of successful presentations and elapsed QPC duration. Sample FPS = `1000 * frames / duration_ms`. This does not track game logic ticks or display refresh rate. Individual frame time percentiles are not calculated from this.
- `no_presentation`: No successful presentation was observed within 30 seconds. The game is not terminated automatically. `capture_limit` marks the end of bounded sampling, not a game crash. Renderer logs are capped at 256 KiB per process without pixel copying or forced repaints; overhead on the device still requires A/B comparison.
- `graphics_layer`: start → library → context → frame1/2/3 → done or error. `frame` indicates the presentation/fill call returned; for SDL/GLX APIs, buffer swap does not return a visibility confirmation. `renderer=gpu` is merely a classification of the GL string, **not proof of hardware acceleration**. Your RGB visual observation is required to confirm.
- Metrics every 5 seconds: System CPU, RAM/swap, swap-in/out, major page faults, PSI when supported by the kernel; as well as CPU/RSS/swap/faults for verified process trees. `game_*` includes the launched Wine/game process and verified child processes; `mapper_*` covers the mapper; `compositor_*` encompasses Weston and its children, including Xwayland if parent-child tracking holds. **Xwayland is not isolated separately**, and reparented/detached Wine processes are not tracked by name matching. An empty field means unavailable/uncertain, not zero. The sampler terminates upon exit or anchor PID reuse.
- `*_cpu_pct_x100`: 10000 = 100% of a single core for a process or subtree; process values can exceed 10000 on multi-threaded workloads. System CPU is scaled 0..10000 across all cores. System fault/swap/PSI total counters are cumulative — compare their rates of increase. Process totals cover only the active subtree, so they may drop after a child exits; CPU percentage is suppressed until subtree membership stabilizes. CPU/GPU clock frequency is not an index of load; we do not assert GPU utilization that firmware does not expose.

## Scope and Next Steps

Validated on host: x86/MSVC and ARMHF builds, library integrity, schemas and limits, selector restricted to ephemeral runtime directory, isolated dummy mock testing, and recovery procedures. **Physical R36S hardware, Mali drivers, RGB display, and five real back-to-back launches require on-device validation.**

Wine/Box86 versions, system drivers, CPU governors, and frequencies remain unmodified. The standard launcher does not enable new instrumentation by default; improved stages and defensive prefix preparation benefit standard launches as well. Following hardware data: a Cortex-A35 tuned build of the same Box86 commit alongside the existing runtime, followed by testing newer Box86 upstream. WoW64/Box64 or fresh prefixes remain conditional follow-ups, outside the scope of this package.
