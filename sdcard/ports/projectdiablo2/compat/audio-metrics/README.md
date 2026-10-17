# Bounded in-game PCM observations (ARMhf/time32)

This optional library is a **source-instrumented derivative of the existing
private legacy ALSA 1.2.8 provider**, not an LD_PRELOAD interceptor, replacement
system driver, or sound-quality fix. The stock compatibility library is unchanged.
The same pinned ALSA source/configuration and legacy ARM32 kernel ABI are retained.

## Binding and scope

Box86 obtains native ALSA symbols with `dlsym` on its native library handle.
Preloading wrappers does not reliably intercept that lookup. Here the exported
ALSA functions themselves contain wrappers around their unchanged original bodies.
All original defined/versioned public exports must match the stock library.
Hidden helper functions share bounded bookkeeping across the two modified source
files. The build tests call exported entrypoints through `dlopen`/`dlsym` directly.

Only successful outer playback opens are tracked, up to eight **lifetime opens
per process**; slots are never reused. Capture handles and internal plugin opens
are not counted. Thread-local call nesting excludes recursive plug/hw forwarding
from application-level counters. A source ordinal is assigned by the collector
from a private native PID; no PID, PCM pointer, device name or path is exported.
Ordinal identity is per observed native PID, not a proof that a Windows process
is Game.exe; launcher integration must enable this only for the final game.
DSO reloads (or PID reuse) can restart counters/stream IDs under one source
ordinal; a counter decrease is a reset, not negative streaming activity.

- `write_calls/write_frames`: outer calls/accepted frames from `writei`, `writen`,
  `mmap_writei`, `mmap_writen`. `short_writes` counts nonnegative partial returns.
- `mmap_begin_calls/mmap_commit_calls/mmap_frames`: explicit outer direct-mmap
  calls and frames acknowledged by successful commit results. Sample areas and
  contents are never read by instrumentation. These do not duplicate frames
  submitted through the buffer-write APIs above.
- `hw_params_calls/start_calls/prepare_calls/resume_calls/drop_calls/drain_calls`:
  public outer API invocations; automatic hardware starts and nested calls are
  **not** counted as explicit starts/prepares.
- `recover_calls/recover_epipe_calls/recover_successes`: calls to recover,
  calls whose **input** error is `-EPIPE`, and nonnegative recovery results.
- `error_results` and `epipe_results/estrpipe_results/eagain_results/eintr_results/
  other_error_results`: negative results from the observed APIs, separated by
  fixed errno classes. EAGAIN is a nonblocking result, not necessarily a glitch.
  EPIPE playback results indicate an observed xrun/error path, but **repeated
  errors/recoveries are not unique underrun episodes**. Counters do not infer
  missing game audio, audible stutter, silence, latency, or speaker output.
  Query APIs such as avail/state/delay/wait and software-parameter setters are
  not instrumented; their errors/states are not part of these result totals.
- `rate_hz/channels/access/period_frames/buffer_frames`: negotiated **client-side
  PCM** values following a successful top-level hw_params call. A plug/rate
  conversion slave can have different hardware values. These describe the last
  observed hw_params negotiation, not a continuous state/hw_free monitor.
  `params_valid=0` means absent/rejected/latest hw_params failed; zero is not a
  measured negotiated rate.
- `active=0` and `close_calls` preserve the final closed stream totals.

The negotiated values are observed, never changed. This module does not alter
sample data, buffering, scheduling priority, ALSA routing or mixer settings.

## Boundedness and real-time behavior

Instrumentation uses fixed storage, saturating counters and a single nonblocking
try-lock. No allocation, formatting, sleeping, file operation or blocking lock
is added inside PCM callbacks. The four-byte nesting depth uses initial-exec TLS
so access cannot trigger lazy TLS allocation; library loading still requires
available glibc static TLS space. `lost_updates` is a best-effort lower-bound
count of unsuccessful bookkeeping lock attempts (also including writer snapshot
try-lock); it means observations can be incomplete. `untracked_opens` records opens beyond the slot capacity.
Initialization creates one writer thread, only when the inherited output FD is a
write-only nonblocking pipe. That thread snapshots dirty cumulative totals at
one-second intervals and performs all formatting/writes. Full pipes never block
an audio callback; latest cumulative totals are retried on later ticks. SIGPIPE
is blocked only on the writer thread, never changed globally in the game.

Each process stops sample output after at most 262144 bytes and attempts a
numeric limit marker. The collector bounds all input to 262144 bytes, lines to
2048 bytes, sources to 32 and sample events to 4096, draining excess without
saving raw content. All on-wire values must be exact bounded integers; unknown
keys, duplicate keys, strings, floats and inconsistent counters are rejected.
Only a closed `audio_pcm` schema and fixed status enums reach safe logging.

Normal non-exec fork children disable this observer because the writer thread
cannot survive fork. Raw fork syscalls bypassing atfork handlers also cannot emit
observations; a native owner-PID guard prevents joining a nonexistent writer on
child exit. Exec children initialize independently. Abrupt exit or missing pipe
inheritance can omit observations. `no_stream` means **no valid observed stream**,
not verified zero playback. Pipe readiness proves transport setup, not that Wine
loaded this library or that hardware sound is smooth.

## Integration contract (no shared files modified by this module)

1. Stop/quiesce Wine **after setup** before selecting this library. Existing
   processes may already have the stock ALSA mapped and lack the output FD.
2. From the private volatile game work directory, invoke:
   `python3 -B scripts/audio_metrics.py prepare --port PORT --work WORK`.
   The authenticated library is copied read-only to
   `WORK/.alsa-audio-metrics/libasound.so.2`. Unsafe/stale destinations fail closed.
3. Prepend `WORK/.alsa-audio-metrics` to the final game's ARMhf native library
   search path, ahead of the stock private legacy ALSA path. Keep the stock
   library/path as the explicit uninstrumented fallback. Refresh the Box86 child
   environment; do not expose ARMhf libraries to native AArch64 Python/Weston.
4. Wrap **only** the actual final game command:
   `python3 -B scripts/audio_metrics.py run -- FINAL_COMMAND ARG...`.
   It creates an anonymous nonblocking pipe, passes its write FD to that child
   using `pass_fds`, and sets `PD2_AUDIO_METRICS_FD` only in its environment.
   The wrapper remains in the parent's game process group. No extra collector
   PID or FIFO cleanup is necessary. Child stdout/stderr are not parsed here.
5. Keep the wrapper alive through game lifetime. It never times out/signals the
   game; it returns its exit status and drains for up to two seconds after the
   launched child exits. The game's launcher must wait for the real game rather
   than merely spawning a detached desktop helper.
6. Extend the common safe logger with the documented exact event schema and
   fixed `audio_metrics_library` / `audio_metrics_capture` status checks. The
   module deliberately does not edit the shared logger, launchers or allowlists.

## Build and validation

Build source/recipes and synthetic tests are in the repository's tools directory.
Prepare using `python -B tools/audio_metrics_build.py --prepare`; run the existing
`pd2-alsa-native-builder` container with `sh /src/tools/audio_metrics_build.sh`;
then finalize with `python -B tools/audio_metrics_build.py --finalize`.

The container asserts `time_t=4`, `sizeof(snd_pcm_sync_ptr)=132` and legacy ioctl
`0xc0844123`, checks ELF hard-float and exact stock public versioned exports,
runs sustained fixed-memory mock accounting on native/ARMhf, and calls actual
exported instrumented ALSA entrypoints on synthetic null PCM under QEMU. These
are **not** R36S streaming, audible-quality, or complete Box86/Wine tests.
Inherited pipe transport through the actual Wine game-launch chain remains a
runtime integration condition; it must produce valid `audio_pcm` events before
any in-game counts are claimed.

The original pinned source archive plus this directory's patch provide the
corresponding modified source. LGPL-2.1-or-later license text is bundled. Builder
package revisions are not fully pinned, so bit-reproducible builds are not claimed.
