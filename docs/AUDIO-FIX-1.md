# Audio Testing Protocol on R36S (DirectSound & ALSA Telemetry)

This document describes the testing procedure, telemetry architecture, and diagnostics for evaluating and resolving audio stutter, underruns, and echo on the **R36S** handheld console (Rockchip RK3326, 1GB LPDDR3, ArkOS).

---

## 1. Objective and Architecture

The primary goal is to diagnose and eliminate audio stutter and repeating sound chunks ("echo") while maintaining stable GDI video rendering and conservative Box86 flags (`SAFEFLAGS=1`, `CALLRET=0`).

### Audio Stack on R36S
```
Diablo II (mss32.dll / DirectSound)
       │
       ▼
Wine 8.0 (winealsa.drv)
       │
       ▼
Box86 (JIT x86 -> ARMHF 32-bit)
       │
       ▼
libasound.so.2 (ALSA 1.2.8 time32 legacy compat)
       │
       ├── Dmix (software mixer buffer, non-exclusive)
       └── /dev/snd/pcmC0D0p (Rockchip RK817 I2S codec)
```

---

## 2. Key Findings and Route De-bunking

### A. The "Buffer 160ms" Launcher Was an Illusion
- **Root Cause Confirmed from ALSA 1.2.8 Source:** In [`pcm_plug.c:1293-1298`](../.state/audio-metrics-build/alsa-lib-1.2.8/src/pcm/pcm_plug.c#L1293) and [`pcm.c:7885`](../.state/audio-metrics-build/alsa-lib-1.2.8/src/pcm/pcm.c#L7885), the `type plug` slave definition (`snd_pcm_slave_conf`) only parses `format`, `channels`, and `rate`.
- Inserting `period_time` or `buffer_time` inside `pcm_slave` triggers `-EINVAL: Unknown field period_time`.
- Consequently, `snd_pcm_open("default")` failed to parse `alsa-pd2.conf` and Wine silently fell back to system default ALSA routing. All historical tests of "Buffer 160ms" were running on stock system ALSA.
- **Action Taken:** The bogus `buffer80`/`buffer160` profiles were removed from `audio_config.py` and `Project Diablo 2 - Audio Buffer.sh` was deleted.

### B. Dmix Flow Control vs Dropouts
- Session logs from Dmix testing showed **0 EPIPE** and **4,295 writes across 125 seconds**.
- The `eagain_results = 508` was non-blocking flow control from Wine when the dmix ring buffer was full, not audio dropouts.
- Observer `lost_updates = 1` was triggered by `flush()` trylock contention during rapid logging, not lost audio frames.

### C. Echo / Repeating Chunk Root Causes
Because ALSA received continuous writes without EPIPE in Dmix, "echo/repeating" occurs upstream of ALSA:
1. **Producer Starvation in Wine/DirectSound:** When Box86 dynarec JIT or GDI rendering stalls the CPU, the audio thread misses its refill deadline. The DirectSound circular ring buffer wraps around and replays stale audio chunks (~50–100ms), sounding like an echo or repeating stutter.
2. **Environmental Effects (EAX 3D):** Software reverb emulation in Miles Sound System doubles CPU mixing load and creates literal echo. Must remain **DISABLED** in-game.

---

## 3. Active Diagnostic Matrix

| Launcher | Profile | ALSA Config | DirectSound | SDL Driver | Telemetry |
|---|---|---|---|---|---|
| [`Project Diablo 2.sh`](../sdcard/ports/Project%20Diablo%202.sh) | **Production Baseline** | System default / stock rk817 | Wine default / persistent | `alsa` | Off |
| [`Project Diablo 2 - Audio Dmix.sh`](../sdcard/ports/Project%20Diablo%202%20-%20Audio%20Dmix.sh) | **Dmix Diagnostic** | `dmix160` (160ms ring buffer, hardened IPC) | `wine` (forces HelBuflen=65536) | `dummy` | PCM + Hardware + System |

*The production launcher `Project Diablo 2.sh` remains the verified, stable baseline.*

---

## 4. Installation and Test Protocol on R36S

### Step 1: Direct SD Card Deployment
1. Copy updated files directly from repository [`sdcard/ports/`](../sdcard/ports/) onto the handheld microSD ROM partition (e.g. `roms/ports/` or `roms2/ports/`).
2. Ensure execution permissions: `chmod +x ports/*.sh ports/projectdiablo2/scripts/*.sh`.

### Startup failure: `invalid_profile` before the game

Session `20261018T174656Z-35723` stops immediately after `audio_route_profile=dmix160`, before PCM setup or game execution. The Dmix launcher selects `PD2_AUDIO_DSOUND=wine`, but the old Dmix validation in [`run-game.sh`](<../sdcard/ports/projectdiablo2/scripts/run-game.sh>) only accepted `off`.

The corrected validation accepts `wine` and legacy `off`; SDL must still be `dummy` and the route must be a supported dmix profile. For this startup fix alone, replace `ports/projectdiablo2/scripts/run-game.sh` on the SD card with the repository version, keeping the current Dmix launcher. No game data, saves, prefix or runtime replacement is needed. Then select Dmix again and start the game from the launcher menu. If it exits again, collect the new session log.

This fixes a rejected configuration, not audio quality. The failed session contains no game playback measurements; R36S playback and sound quality still require verification.

### Step 2: In-Game Settings Check
- In Diablo II Options → Sound Options:
  - **Environmental Effects (3D EAX): DISABLED** (Mandatory).
  - Adjust Master Volume, Music Volume, and Sound Effects to comfortable levels.

### Step 3: Structured Test Execution
Run [`Project Diablo 2 - Audio Dmix.sh`](../sdcard/ports/Project%20Diablo%202%20-%20Audio%20Dmix.sh) from the Ports menu:
- **Phase 1: Town (60 seconds):**
  - Walk around Rogue Encampment.
  - Interact with NPCs (Warriv, Akara, Kashya) to trigger speech.
  - Listen for stuttering or repeating voice chunks.
- **Phase 2: Combat (120 seconds):**
  - Exit to Blood Moor / Den of Evil.
  - Engage monsters using primary attack and spells.
  - Use potions and open chests (rapid sound effect triggers).
  - Listen for audio stutter, latency, or repeating clicks.
- **Phase 3: Exit cleanly** via game menu (Save and Exit → Exit Diablo II) to allow log synchronization.

---

## 5. Telemetry and Event Reference

Diagnostics are written in JSON Lines format to:
`ports/projectdiablo2/logs/pd2-session-<TIMESTAMP>-<PID>.jsonl`

### Key Telemetry Events

#### 1. Launch & Route Verification (`session_probe`)
```json
{"event":"session_probe","phase":"launch","check":"audio_route","status":"rk817"}
{"event":"session_probe","phase":"launch","check":"audio_route_profile","status":"dmix160"}
{"event":"session_probe","phase":"launch","check":"audio_config_path","status":"active"}
{"event":"session_probe","phase":"launch","check":"audio_sdl","status":"dummy"}
{"event":"session_probe","phase":"launch","check":"audio_metrics_library","status":"ready"}
{"event":"session_probe","phase":"launch","check":"audio_metrics_capture","status":"sustained_playback"}
```
- `audio_config_path: active`: Confirms `ALSA_CONFIG_PATH` pointed to `alsa-pd2.conf`.
- `audio_metrics_capture: sustained_playback`: Confirms >=3 consecutive snapshots with audio frames over >=2.0s (distinguishes real gameplay from short 1.5s probes).

#### 2. Client PCM Stream Metrics (`audio_pcm`)
Emitted periodically (~1s interval) by the PCM observer library:
```json
{
  "event": "audio_pcm",
  "schema": 1,
  "role": "game",
  "source": 1,
  "stream": 21,
  "active": 1,
  "rate_hz": 48000,
  "channels": 2,
  "period_frames": 960,
  "buffer_frames": 3840,
  "write_calls": 4295,
  "short_writes": 0,
  "recover_calls": 1,
  "recover_epipe_calls": 1,
  "recover_successes": 1,
  "epipe_results": 0,
  "eagain_results": 508,
  "lost_updates": 0
}
```
- `epipe_results`: Number of `-EPIPE` underrun errors returned to Wine.
- `eagain_results`: Number of non-blocking backpressure pauses (normal under dmix).
- `lost_updates`: Observer lock contention count (not dropped audio).

#### 3. Kernel Hardware PCM State (`audio_hardware_pcm`)
Sampled from `/proc/asound/card*/pcm*p/sub*/{hw_params,sw_params,status}` (prioritizing RK817):
```json
{
  "event": "audio_hardware_pcm",
  "state": "RUNNING",
  "card": 2,
  "device": 0,
  "rate_hz": 48000,
  "channels": 2,
  "period_frames": 1920,
  "buffer_frames": 7680,
  "delay": 1820,
  "avail": 5860,
  "hw_ptr": 128400,
  "appl_ptr": 130220,
  "avail_min": 1920,
  "start_threshold": 1,
  "stop_threshold": 7680
}
```
- `card` / `device`: Specific ALSA card and device number being sampled (ensures RK817 is tracked).
- `state`: Kernel PCM state (`RUNNING`, `PREPARED`, `XRUN`, `DRAINING`).
- `buffer_frames` / `period_frames`: Actual kernel DMA ring buffer parameters.
- `delay`: Audio latency in frames between application pointer and hardware read head.

#### 4. System Resource Metrics (`metrics`)
Sampled periodically during gameplay when `PD2_METRICS=1`:
```json
{
  "event": "metrics",
  "cpu_pct": 78,
  "ram_mb": 512,
  "swap_mb": 42,
  "temp_c": 58.5
}
```
- Correlates audio stutters with CPU saturation, memory pressure, swap thrashing, or thermal throttling.
