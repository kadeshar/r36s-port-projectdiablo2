#!/usr/bin/env python3
"""Private, bounded, deny-by-default offline PD2 diagnostics (stdlib only).

Launcher wire grammar: one line ``PD2_EVENT `` followed by a JSON object.
* phase: event="phase", phase=preflight|runtime|launch|game|shutdown|export
* runtime_error: event="runtime_error", reason from REASONS; optional phase,
  rc, library (library is allowed only for reason="missing_library")
* runtime_exit: event="runtime_exit", rc; optional phase, duration_ms
* metrics: event="metrics"; optional phase and one or more numeric metrics
All four accept optional profile (gdi|opengl), port_version, runtime_version,
and machine. Unknown fields invalidate the WHOLE event. Versions must begin
with a digit (optional v), and contain only short version tokens, not names.
Never send messages, arguments, paths, environment, keys or player names.
The logger alone generates the summary event. Unknown process output is counted,
not retained. Export revalidates every row; filenames inside the ZIP are anonymous.

CLI: stream --dir DIR --session ID [--maxbytes BYTES] [--retain COUNT]
     export --dir DIR [--manifest JSON] [--output-dir DIR]
Existing session files are never overwritten. Stream always drains stdin, even
when logging fails or its byte budget is exhausted. Errors are fixed strings.
"""

import argparse
import contextlib
import io
import json
import os
from pathlib import Path
import re
import stat
import sys
import zipfile

MAX_BYTES = 2 * 1024 * 1024
MAX_RETAIN = 10
MAX_LINE = 4096
SUMMARY_RESERVE = 512
MAX_COUNT = (1 << 63) - 1
PREFIX = "PD2_EVENT "
SESSION_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z", re.ASCII)
LOG_RE = re.compile(r"pd2-session-([A-Za-z0-9][A-Za-z0-9_-]{0,63})\.jsonl\Z", re.ASCII)
VERSION_RE = re.compile(r"v?[0-9]{1,6}(?:[._][0-9]{1,6}){0,4}(?:[-+](?:alpha|beta|rc|dev|release|git)[0-9]{0,6})?\Z", re.ASCII)
LIB_RE = re.compile(r"(?:[A-Za-z0-9][A-Za-z0-9_.-]{0,95}\.so(?:\.[0-9]{1,6}){0,5}|[A-Za-z0-9][A-Za-z0-9_.-]{0,95}\.dll)\Z", re.ASCII)
PHASES = frozenset(("preflight", "runtime", "launch", "game", "shutdown", "export"))
REASONS = frozenset(("missing_library", "fault", "timeout", "signal", "nonzero_exit", "logger_failure", "unsupported_runtime", "invalid_layout", "insufficient_space", "insufficient_ram", "invalid_profile", "missing_drm_device", "missing_uinput", "display_conflict", "namespace_unavailable", "compositor_failed", "compositor_timeout", "prefix_incomplete", "vc_install_failed", "namespace_isolation_required", "run_isolation_failed", "alias_setup_failed", "tmp_isolation_failed", "volatile_work_failed", "seatd_failed", "seatd_timeout", "x11_probe_failed", "runtime_tool_missing", "namespace_cleanup_failed", "graphics_provider_missing", "graphics_provider_invalid", "egl_init_failed", "gbm_init_failed", "gl_context_failed", "sdl_init_failed", "compositor_module_failed", "driver_access_denied", "x11_socket_failed", "xwayland_exec_failed", "xwayland_start_failed", "xwayland_font_failed", "xauth_prepare_failed"))
MACHINES = frozenset(("armv7l", "aarch64", "x86_64", "i386", "i686", "unknown"))
STAGES = frozenset(('namespace_setup', 'namespace_ready', 'volatile_work_prepare', 'volatile_work_ready', 'library_probe', 'seatd_start', 'seatd_ready', 'weston_start', 'x11_probe', 'x11_ready'))
GRAPHICS_ROLES = frozenset(('sdl', 'egl', 'gles', 'gbm', 'drm'))
GRAPHICS_ARCHES = frozenset(('aarch64', 'armhf'))
GRAPHICS_STATUSES = frozenset(('ready', 'missing', 'invalid', 'probe_failed'))
COMPOSITOR_NOTES = frozenset(('drm_module', 'gl_module', 'shell_module', 'xwayland_module', 'egl_ready', 'gl_ready', 'output_ready', 'root_service', 'xserver_listening', 'xwayland_spawn', 'xwayland_restart', 'xwayland_crash', 'xwayland_software_fallback', 'xwayland_keymap_fallback'))
X11_STATUSES = frozenset(('ready', 'missing', 'denied', 'invalid', 'io_error', 'refused', 'connect_timeout', 'reply_timeout', 'disconnected', 'setup_rejected', 'auth_rejected', 'auth_required', 'auth_missing', 'invalid_reply'))
COMMON = frozenset(("phase", "profile", "port_version", "runtime_version", "machine"))
FREQUENCY_RANGES = {'cpu_freq_khz': 10_000_000, 'cpu_max_freq_khz': 10_000_000, 'gpu_freq_hz': 10_000_000_000, 'gpu_max_freq_hz': 10_000_000_000}
SESSION_METRICS = frozenset(('sample_monotonic_ms', 'system_cpu_pct_x100', 'swap_total_mb', 'swap_free_mb', 'swap_in_pages', 'swap_out_pages', 'system_major_faults', 'game_processes', 'game_cpu_user_ms', 'game_cpu_system_ms', 'game_cpu_pct_x100', 'game_rss_kb', 'game_swap_kb', 'game_major_faults')) | frozenset('pressure_'+resource+'_'+kind+'_'+metric for resource in ('cpu','memory','io') for kind in ('some','full') for metric in ('avg10_x100','total_us'))
SESSION_METRICS = SESSION_METRICS | frozenset(role+'_'+suffix for role in ('compositor','mapper') for suffix in ('processes','cpu_user_ms','cpu_system_ms','cpu_pct_x100','rss_kb','swap_kb','major_faults'))
SETUP_STAGES = frozenset(('initial','prefix_quiesce','prefix_initialize','recover_winebus','recover_audio','recover_dsound','audio_prepare','audio_export','audio_snapshot','audio_select','audio_route','dsound_prepare','dsound_export','dsound_snapshot','dsound_select','dsound_verify','winebus_prepare','winebus_export','winebus_snapshot','winebus_select','game_registry','game_start','prefix_shutdown','graphics_test'))
METRICS = frozenset(("available_ram_mb", "disk_mb", "temperature_mc", "duration_ms")) | FREQUENCY_RANGES.keys() | SESSION_METRICS
AUDIO_PCM_COUNTERS = frozenset(('write_calls','write_frames','short_writes','mmap_begin_calls','mmap_commit_calls','mmap_frames','hw_params_calls','start_calls','prepare_calls','resume_calls','drop_calls','drain_calls','recover_calls','recover_epipe_calls','recover_successes','close_calls','error_results','epipe_results','estrpipe_results','eagain_results','eintr_results','other_error_results'))
AUDIO_PCM_ROLES = frozenset(('game', 'probe', 'server', 'wine', 'unknown', 0, 1, 2, 3, 4))
AUDIO_PCM_FIELDS = AUDIO_PCM_COUNTERS | frozenset(('event','schema','role','source','stream','active','params_valid','rate_hz','channels','access','period_frames','buffer_frames','lost_updates','untracked_opens','sample_monotonic_ms','producer_monotonic_ms'))
AUDIO_HARDWARE_PCM_FIELDS = frozenset(('event', 'state', 'sample_monotonic_ms', 'owner_pid', 'delay', 'avail', 'hw_ptr', 'appl_ptr', 'format', 'access', 'channels', 'rate_hz', 'period_frames', 'buffer_frames', 'avail_min', 'start_threshold', 'stop_threshold', 'card', 'device'))
COUNTS = frozenset(("input_lines", "accepted_events", "omitted_lines", "oversized_lines", "written_events", "limited_events"))
FIELDS = {
    "phase": COMMON | {"event"},
    "runtime_error": COMMON | {"event", "reason", "rc", "library"},
    "runtime_exit": COMMON | {"event", "rc", "duration_ms"},
    "runtime_stage": COMMON | {"event", "stage"},
    "graphics_probe": COMMON | {"event", "role", "arch", "status"},
    "compositor_note": COMMON | {"event", "note"},
    "x11_probe": frozenset(('event', 'phase', 'check', 'status', 'duration_ms', 'mode', 'owner')),
    "session_probe": frozenset(('event', 'phase', 'check', 'status', 'count', 'detail', 'alsa_rc', 'arch', 'node', 'device_kind', 'device_major', 'device_minor', 'syscall_rc', 'fd', 'request')),
    "metrics": COMMON | METRICS | {"event", "game_scope"},
    "setup_stage": frozenset(('event','phase','stage','status')),
    "render_sample": frozenset(('event','backend','frames','duration_ms','width','height')),
    "render_status": frozenset(('event','backend','status','width','height')),
    "graphics_layer": frozenset(('event','schema','probe','stage','status','backend','renderer','frame','code')),
    "audio_pcm": AUDIO_PCM_FIELDS,
    "audio_hardware_pcm": AUDIO_HARDWARE_PCM_FIELDS,
    "summary": frozenset(("event", "counts")),
}
MISSING_SO = re.compile(r"(?:[^\r\n]{1,256}: )?error while loading shared libraries: ([A-Za-z0-9_.-]{1,128}): cannot open shared object file: No such file or directory\Z", re.ASCII)
MISSING_DLL = re.compile(r"(?:[0-9a-f]{1,8}:)?err:module:import_dll Library ([A-Za-z0-9_.-]{1,128}) \(which is needed by [^\r\n]{1,256}\) not found\Z", re.ASCII)
FAULT = re.compile(r"(?:Segmentation fault|Bus error|Illegal instruction)(?: \(core dumped\))?\Z", re.ASCII)
EXIT = re.compile(r"(?:exit|process exited|Process exited)(?: with code)?[: ]+(-?[0-9]{1,5})\Z", re.ASCII)
FORBIDDEN_COMPONENTS = frozenset(("save", "saves", "config", "gamedata", "wineprefix"))


def _integer(value, low=0, high=MAX_COUNT):
    return type(value) is int and low <= value <= high


def validate_event(value, allow_summary=False):
    """Return a fresh safe object, or None. Never coerce arbitrary strings."""
    if type(value) is not dict or type(value.get("event")) is not str:
        return None
    event = value["event"]
    if event not in FIELDS or (event == "summary" and not allow_summary):
        return None
    if not set(value) <= FIELDS[event]:
        return None
    if event == "summary":
        counts = value.get("counts")
        if type(counts) is not dict or set(counts) != COUNTS:
            return None
        if not all(_integer(n) for n in counts.values()):
            return None
        return {"event": "summary", "counts": dict(counts)}
    if event == 'setup_stage':
        if set(value) != FIELDS[event] or value.get('phase') != 'launch' or type(value.get('stage')) is not str or value['stage'] not in SETUP_STAGES or value.get('status') not in ('begin','failed','ready'):
            return None
    if event in ('render_sample','render_status'):
        if set(value) != FIELDS[event] or value.get('backend') not in ('gdi','opengl','unknown'):
            return None
        if not all(_integer(value.get(k),1,16384) for k in ('width','height')):
            return None
        if event == 'render_sample' and (not _integer(value.get('frames'),0,1000000) or not _integer(value.get('duration_ms'),1,3600000)):
            return None
        if event == 'render_status' and value.get('status') not in ('window_ready','first_present','no_presentation','capture_limit','invalid_capture','unavailable'):
            return None
    if event == 'audio_pcm':
        if set(value) != AUDIO_PCM_FIELDS or type(value.get('schema')) is not int or value['schema'] != 1:
            return None
        if value.get('role') not in AUDIO_PCM_ROLES:
            return None
        bounds = {'source':(1,32),'stream':(1,10**9),'active':(0,1),'params_valid':(0,1),'rate_hz':(0,768000),'channels':(0,256),'access':(0,4),'period_frames':(0,10**9),'buffer_frames':(0,10**9),'lost_updates':(0,10**9),'untracked_opens':(0,10**9),'sample_monotonic_ms':(0,10**15),'producer_monotonic_ms':(0,10**15)}
        for name in AUDIO_PCM_FIELDS - {'event','schema','role'}:
            if not _integer(value[name],*bounds.get(name,(0,10**15))):
                return None
        if value['params_valid'] and (not value['rate_hz'] or not value['channels'] or not value['period_frames'] or value['period_frames'] > value['buffer_frames']):
            return None
        if value['recover_successes'] > value['recover_calls'] or value['recover_epipe_calls'] > value['recover_calls'] or value['short_writes'] > value['write_calls'] or value['error_results'] != sum(value[k] for k in ('epipe_results','estrpipe_results','eagain_results','eintr_results','other_error_results')):
            return None
    if event == 'audio_hardware_pcm':
        if not set(value) <= FIELDS[event] or 'event' not in value or 'state' not in value:
            return None
        if type(value['state']) is not str or value['state'] not in ('RUNNING', 'PREPARED', 'DRAINING', 'XRUN', 'PAUSED', 'SUSPENDED', 'DISCONNECTED', 'OPEN', 'SETUP', 'closed', 'unknown', 'unavailable'):
            return None
        for k in ('sample_monotonic_ms', 'delay', 'avail', 'hw_ptr', 'appl_ptr', 'channels', 'rate_hz', 'period_frames', 'buffer_frames', 'avail_min', 'start_threshold', 'stop_threshold', 'card', 'device'):
            if k in value and not _integer(value[k], 0, 10**18):
                return None
        if 'owner_pid' in value and not _integer(value['owner_pid'], 0, 2147483647):
            return None
        for k in ('format', 'access'):
            if k in value and (type(value[k]) is not str or len(value[k]) > 64):
                return None
    if event == 'metrics' and 'game_scope' in value:
        if value['game_scope'] not in ('verified_subset','partial','unavailable') or type(value['game_scope']) is not str:
            return None
        if value['game_scope'] == 'unavailable' and any(k.startswith('game_') and k != 'game_scope' for k in value):
            return None
    if event == 'graphics_layer':
        if set(value) != FIELDS[event] or value.get('schema') != 1 or type(value.get('schema')) is not int:
            return None
        for name,allowed in (('probe',('sdl','glx','ddraw')),('stage',('start','library','context','frame','done','error')),('status',('ok','failed')),('backend',('unknown','x11','wayland','kmsdrm','directfb','dummy','windows','other')),('renderer',('unknown','gpu','software'))):
            if type(value.get(name)) is not str or value[name] not in allowed:
                return None
        if not _integer(value.get('frame'),0,3) or not _integer(value.get('code'),0,20):
            return None
    if event == 'session_probe':
        check, status = value.get('check'), value.get('status')
        allowed = {
            'saves_directory': ('ready', 'missing', 'unavailable', 'limit'),
            'save_mapping': ('ready', 'invalid', 'unavailable'),
            'game_config': ('ready', 'missing', 'invalid'),
            'save_path': ('canonical', 'missing', 'other', 'unknown'),
            'movement_mode': ('emulated', 'native', 'mixed', 'disabled', 'unknown'),
            'native_cast': ('applied', 'unknown_source'),
            'virtual_gamepad': ('ready', 'missing', 'denied', 'invalid', 'unavailable'),
            'winebus_backend': ('udev', 'restored'),
            'xinput_api': ('ready', 'library_missing', 'entry_missing'),
            'xinput_devices': ('ready', 'missing', 'error'),
            'xinput_buttons': ('changed', 'unchanged', 'unavailable'),
            'xinput_axes': ('changed', 'unchanged', 'unavailable'),
            'controller_mapper': ('ready', 'missing', 'denied', 'invalid', 'fallback'),
            'mapper_layout': ('standard',),
            'render_resolution': ('640x480', '800x600', '1024x768', 'native'),
            'audio_metrics': ('ready', 'unavailable'),
            'audio_metrics_capture': ('ready', 'playback_observed', 'sustained_playback', 'no_playback', 'partial_coverage', 'capture_limit', 'data_lost', 'no_stream', 'invalid_capture', 'unavailable'),
            'audio_metrics_library': ('ready','unavailable'),
            'dynarec_bigblock': ('1', '2'),
            'fps_counter': ('hotkey', 'renderer', 'disabled', 'unavailable', 'overlay'),
            'diagnostic_mode': ('off','present','sdl','glx','ddraw'),
            'presentation_capture': ('ready','unavailable'),
            'graphics_test_result': ('completed','failed','timeout'),
            'start_menu': ('selected', 'failed', 'cancelled'),
            'menu_display': ('connect_failed', 'auth_failed', 'setup_invalid', 'window_failed', 'not_visible', 'protocol_error', 'disconnected', 'timeout', 'input_failed', 'unavailable'),
            'audio_route': ('rk817', 'default', 'missing', 'denied', 'ambiguous', 'busy'),
            'audio_route_profile': ('baseline', 'buffer80', 'buffer160', 'dmix160', 'dmix80'),
            'audio_config_path': ('active', 'default', 'missing'),
            'audio_device': ('ready', 'missing', 'denied'),
            'audio_backend': ('alsa', 'restored'),
            'audio_output': ('dsoal_winmm', 'winmm_opened', 'unconfirmed'),
            'audio_sdl': ('alsa', 'dummy'),
            'audio_variant': ('A', 'B', 'C', 'D', 'buffer', 'dmix', 'stock'),
            'audio_schema': ('v1', 'v2'),
            'dsound_profile': ('off', 'ver2', 'wine'),
            'dsound_backend': ('restored',),
            'dsound_helbuflen': ('8192', '65536'),
            'audio_endpoints': ('ready', 'missing'),
            'audio_open': ('ready', 'missing', 'busy', 'denied', 'unsupported', 'error'),
            'audio_directsound': ('ready', 'missing', 'busy', 'denied', 'unsupported', 'error', 'not_run'),
            'audio_write': ('ready', 'error', 'not_run'),
            'audio_tone': ('completed', 'error', 'not_run'),
            'audio_fallback': ('attempted', 'skipped'),
            'audio_control': ('ready', 'denied', 'missing'),
            'audio_driver': ('loaded', 'failed'),
            'audio_diagnostics': ('capture_v2', 'enum_v3', 'errno_v4', 'native_v5', 'syscalls_v6', 'legacy_v7'),
            'audio_library': ('legacy_armhf', 'unavailable'),
            'audio_native_armhf': ('ready', 'unsupported', 'missing', 'tampered', 'failed', 'timeout', 'library_missing', 'symbol_missing'),
            'audio_native_default': ('ready', 'missing', 'denied', 'busy', 'invalid', 'unsupported', 'other_error'),
            'audio_native_plughw': ('ready', 'not_run', 'missing', 'denied', 'busy', 'invalid', 'unsupported', 'other_error'),
            'audio_native_aarch64': ('ready', 'unsupported', 'missing', 'tampered', 'failed', 'timeout', 'library_missing', 'symbol_missing'),
            'audio_native64_default': ('ready', 'missing', 'denied', 'busy', 'invalid', 'unsupported', 'other_error'),
            'audio_native64_plughw': ('ready', 'not_run', 'missing', 'denied', 'busy', 'invalid', 'unsupported', 'other_error'),
            'audio_syscall_trace': ('complete', 'limited', 'not_observed', 'unavailable', 'denied', 'timeout', 'missing', 'tampered'),
            'audio_syscall_library': ('legacy_armhf', 'system'),
            'audio_syscall_open': ('ready', 'failed'),
            'audio_syscall_ioctl': ('ready', 'failed'),
            'audio_alsa_capture': ('complete', 'limited', 'unavailable'),
            'audio_alsa_endpoint': ('render_seen', 'capture_only', 'not_observed'),
            'audio_test': ('invalid',),
        }
        for stage in ('default', 'plughw', 'control', 'cards', 'devices', 'stream', 'params'):
            allowed['audio_alsa_' + stage] = ('attempted', 'not_observed', 'missing', 'denied', 'busy', 'invalid', 'unsupported', 'other_error')
        button_names = ('a', 'b', 'y', 'x', 'start', 'select', 'menu', 'l1', 'l2', 'l3',
                        'r1', 'r2', 'r3', 'up', 'down', 'left', 'right')
        for name in button_names:
            allowed['xinput_button_' + name] = ('passed', 'pressed', 'not_seen', 'unavailable')
            allowed['physical_button_' + name] = ('passed', 'pressed', 'not_seen', 'multiple', 'unavailable')
        allowed['xinput_button_menu'] += ('unsupported',)
        if type(check) is not str or check not in allowed or type(status) is not str or status not in allowed[check]:
            return None
        fields = {'event', 'phase', 'check', 'status'}
        if check in ('audio_syscall_trace', 'audio_syscall_open', 'audio_syscall_ioctl', 'audio_syscall_library'):
            fields.add('arch')
            if value.get('arch') not in ('armhf', 'aarch64'):
                return None
        if check in ('audio_syscall_open', 'audio_syscall_ioctl'):
            fields.update(('node', 'device_kind', 'syscall_rc'))
            node, kind, code = value.get('node'), value.get('device_kind'), value.get('syscall_rc')
            if node not in ('pcm', 'control', 'unknown') or kind not in ('char', 'block', 'unknown'):
                return None
            if not _integer(code, -4095, 2147483647) or (status == 'ready') != (code >= 0):
                return None
            if kind != 'unknown':
                fields.update(('device_major', 'device_minor'))
                if not all(_integer(value.get(key), 0, 1048575) for key in ('device_major', 'device_minor')):
                    return None
            if check == 'audio_syscall_ioctl' or status == 'ready':
                fields.add('fd')
                if not _integer(value.get('fd'), 0, 1048575):
                    return None
            if check == 'audio_syscall_ioctl':
                fields.add('request')
                if not _integer(value.get('request'), 0, 4294967295):
                    return None
            elif node == 'unknown' or (status == 'ready' and value.get('fd') != code) or (status == 'failed' and kind != 'unknown'):
                return None
        if 'alsa_rc' in value:
            if check not in tuple('audio_alsa_' + stage for stage in ('default', 'plughw', 'control', 'cards', 'devices', 'stream', 'params')) + ('audio_native_default', 'audio_native_plughw', 'audio_native64_default', 'audio_native64_plughw'):
                return None
            code = value['alsa_rc']
            if not _integer(code, -2147483648, -1):
                return None
            expected = {-2: 'missing', -13: 'denied', -16: 'busy', -19: 'missing',
                        -22: 'invalid', -38: 'unsupported', -95: 'unsupported'}.get(code, 'other_error')
            if status != expected:
                return None
            fields.add('alsa_rc')
        if check == 'saves_directory' and status == 'ready':
            fields.add('count')
            if not _integer(value.get('count'), 0, 4096):
                return None
        if check == 'audio_endpoints':
            fields.add('count')
            count = value.get('count')
            if not _integer(count, 0, 256) or (status == 'ready') != (count > 0):
                return None
        if check == 'audio_driver' and status == 'failed':
            fields.add('detail')
            if value.get('detail') not in ('no_log', 'silent', 'libasound', 'load_error', 'alsa_error', 'unknown', 'capture_error', 'capture_timeout'):
                return None
        phases = (('preflight', 'launch') if check == 'native_cast' else
                  ('launch', 'shutdown') if check == 'audio_output' else ('launch',))
        if value.get('phase') not in phases or set(value) != fields:
            return None
    if event == 'x11_probe':
        check, status = value.get('check'), value.get('status')
        if type(check) is not str or type(status) is not str:
            return None
        base = {'event', 'phase', 'check', 'status'}
        if value.get('phase') != 'runtime':
            return None
        if check == 'identity':
            if set(value) != base or status not in ('ready', 'root_forbidden'):
                return None
        elif check == 'socket':
            if status not in ('ready', 'missing', 'denied', 'invalid', 'io_error'):
                return None
            if status == 'ready':
                if set(value) != base | {'mode', 'owner'} or not _integer(value.get('mode'), 0, 0o7777):
                    return None
                if type(value.get('owner')) is not str or value['owner'] not in ('root', 'user', 'other'):
                    return None
            elif set(value) != base:
                return None
        elif check == 'auth':
            if status not in ('ready', 'missing', 'invalid', 'denied') or set(value) != base:
                return None
        elif check in ('filesystem', 'abstract'):
            if status not in X11_STATUSES - {'invalid', 'auth_missing'} or set(value) != base | {'duration_ms'}:
                return None
            if not _integer(value.get('duration_ms'), 0, 120000):
                return None
        else:
            return None
    if event == "graphics_probe":
        for field, allowed in (('role', GRAPHICS_ROLES), ('arch', GRAPHICS_ARCHES), ('status', GRAPHICS_STATUSES)):
            if type(value.get(field)) is not str or value[field] not in allowed:
                return None
    if event == "compositor_note" and (type(value.get('note')) is not str or value['note'] not in COMPOSITOR_NOTES):
        return None
    if event == "runtime_stage" and (type(value.get("stage")) is not str or value["stage"] not in STAGES):
        return None
    if event == "phase" and "phase" not in value:
        return None
    if "phase" in value and (type(value["phase"]) is not str or value["phase"] not in PHASES):
        return None
    if "profile" in value and (type(value["profile"]) is not str or value["profile"] not in ("gdi", "opengl")):
        return None
    if "machine" in value and (type(value["machine"]) is not str or value["machine"] not in MACHINES):
        return None
    for name in ("port_version", "runtime_version"):
        if name in value and (type(value[name]) is not str or len(value[name]) > 48 or not VERSION_RE.fullmatch(value[name])):
            return None
    if event == "runtime_error":
        if type(value.get("reason")) is not str or value["reason"] not in REASONS:
            return None
        if "library" in value and (value["reason"] != "missing_library" or type(value["library"]) is not str or not LIB_RE.fullmatch(value["library"])):
            return None
    if event == "runtime_exit" and "rc" not in value:
        return None
    if "rc" in value and not _integer(value["rc"], -32768, 32767):
        return None
    if event == "metrics" and not (set(value) & METRICS):
        return None
    for field in METRICS & set(value):
        if field in FREQUENCY_RANGES:
            if not _integer(value[field], 1, FREQUENCY_RANGES[field]):
                return None
        elif field in SESSION_METRICS:
            maximum = 10000 if field == 'system_cpu_pct_x100' or field.endswith('_avg10_x100') else 10**18
            if not _integer(value[field], 0, maximum):
                return None
        elif not _integer(value[field], -50000 if field == "temperature_mc" else 0, 200000 if field == "temperature_mc" else 10**12):
            return None
    return dict(value)


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate field")
        result[key] = value
    return result


def _decode_json(text):
    def invalid_constant(_value):
        raise ValueError("invalid number")
    return json.loads(text, object_pairs_hook=_unique_object, parse_constant=invalid_constant)


def parse_line(text):
    """Extract only structured allowlisted events or narrow technical errors."""
    text = text.rstrip("\r\n")
    if text.startswith(PREFIX):
        try:
            return validate_event(_decode_json(text[len(PREFIX):]))
        except (ValueError, TypeError, RecursionError):
            return None
    match = MISSING_SO.fullmatch(text) or MISSING_DLL.fullmatch(text)
    if match and LIB_RE.fullmatch(match.group(1)):
        return {"event": "runtime_error", "reason": "missing_library", "library": match.group(1)}
    if FAULT.fullmatch(text):
        return {"event": "runtime_error", "reason": "fault"}
    match = EXIT.fullmatch(text)
    if match:
        return validate_event({"event": "runtime_exit", "rc": int(match.group(1))})
    return None


def _encode(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n").encode("ascii")


def _symlink(info):
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def _directory(path, create=False):
    """Check every ancestor, not just the last path component."""
    path = Path(os.path.abspath(os.fspath(path)))
    for component in list(reversed(path.parents)) + [path]:
        try:
            info = os.lstat(component)
        except FileNotFoundError:
            if not create:
                raise
            # Python 3.13+ applies a special user-only Windows DACL for 0700.
            # Restricted Windows tokens cannot then access their own directory;
            # inherit its ACL there. POSIX (the R36S target) stays private 0700.
            os.mkdir(component, 0o777 if os.name == "nt" else 0o700)
            info = os.lstat(component)
        if _symlink(info) or not stat.S_ISDIR(info.st_mode):
            raise ValueError("unsafe directory")
    return path


def _regular(path, must_exist=True):
    _directory(Path(path).parent)
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        if must_exist:
            raise
        return None
    if _symlink(info) or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise ValueError("unsafe file")
    return info


def _open(path, flags):
    _regular(path, must_exist=False)
    fd = os.open(path, flags | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0), 0o600)
    try:
        info = os.fstat(fd)
        current = _regular(path)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or (info.st_dev, info.st_ino) != (current.st_dev, current.st_ino):
            raise ValueError("unsafe file")
        if flags & (os.O_WRONLY | os.O_RDWR):
            try:
                os.fchmod(fd, 0o600)
            except (OSError, AttributeError):
                pass
    except BaseException:
        os.close(fd)
        raise
    return fd


@contextlib.contextmanager
def _private_umask():
    previous = os.umask(0o077)
    try:
        yield
    finally:
        os.umask(previous)


def _owned_logs(directory):
    directory = _directory(directory)
    entries = []
    with os.scandir(directory) as scan:
        for item in scan:
            if not LOG_RE.fullmatch(item.name):
                continue
            # Windows DirEntry.stat may report st_nlink=0 from cached find data;
            # lstat retrieves the actual link count used for hardlink rejection.
            info = os.lstat(directory / item.name)
            if _symlink(info) or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                continue
            entries.append((info.st_mtime_ns, item.name, directory / item.name))
    return sorted(entries, reverse=True)


def _retain(directory, retain, active):
    entries = _owned_logs(directory)
    others = [row for row in entries if row[2] != active]
    for _mtime, _name, path in others[retain - 1:]:
        _regular(path)
        os.unlink(path)


def _lines(stream):
    """Bound per-line memory, drain oversized records without retaining them."""
    while True:
        chunk = stream.readline(MAX_LINE + 1)
        if not chunk:
            return
        newline = b"\n" if isinstance(chunk, bytes) else "\n"
        oversized = len(chunk) > MAX_LINE
        while not chunk.endswith(newline) and len(chunk) >= MAX_LINE + 1:
            oversized = True
            chunk = stream.readline(MAX_LINE + 1)
            if not chunk:
                break
        if oversized:
            yield None
        elif isinstance(chunk, bytes):
            try:
                yield chunk.decode("utf-8", "strict")
            except UnicodeError:
                yield None
        else:
            yield chunk


def _drain(stream):
    try:
        for _line in _lines(stream):
            pass
        return True
    except (OSError, ValueError):
        return False


def stream_log(directory, session, input_stream, maxbytes=MAX_BYTES, retain=MAX_RETAIN):
    """Return 0 on success, 1 on failure; consume input even after write failure."""
    counts = dict.fromkeys(sorted(COUNTS), 0)
    writer = None
    failed = False
    size = 0
    with _private_umask():
        try:
            if not isinstance(session, str) or not SESSION_RE.fullmatch(session):
                raise ValueError("invalid session")
            if not _integer(maxbytes, SUMMARY_RESERVE, MAX_BYTES) or not _integer(retain, 1, MAX_RETAIN):
                raise ValueError("invalid bounds")
            directory = _directory(directory, create=True)
            path = directory / ("pd2-session-" + session + ".jsonl")
            writer = os.fdopen(_open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL), "wb", buffering=0)
            _retain(directory, retain, path)
        except (OSError, ValueError):
            failed = True
        try:
            for line in _lines(input_stream):
                counts["input_lines"] = min(MAX_COUNT, counts["input_lines"] + 1)
                if line is None:
                    counts["oversized_lines"] = min(MAX_COUNT, counts["oversized_lines"] + 1)
                    counts["omitted_lines"] = min(MAX_COUNT, counts["omitted_lines"] + 1)
                    continue
                event = parse_line(line)
                if event is None:
                    counts["omitted_lines"] = min(MAX_COUNT, counts["omitted_lines"] + 1)
                    continue
                counts["accepted_events"] = min(MAX_COUNT, counts["accepted_events"] + 1)
                data = _encode(event)
                if failed or size + len(data) > maxbytes - SUMMARY_RESERVE:
                    counts["limited_events"] = min(MAX_COUNT, counts["limited_events"] + 1)
                    continue
                try:
                    if writer.write(data) != len(data):
                        raise OSError("short write")
                    writer.flush()
                    if not (counts["written_events"] % 20):
                        try:
                            os.fsync(writer.fileno())
                        except OSError:
                            pass
                    size += len(data)
                    counts["written_events"] = min(MAX_COUNT, counts["written_events"] + 1)
                except (OSError, ValueError):
                    failed = True
        except (OSError, ValueError):
            failed = True
        if writer is not None:
            try:
                if not failed:
                    summary = _encode({"event": "summary", "counts": counts})
                    if len(summary) > SUMMARY_RESERVE or size + len(summary) > maxbytes:
                        raise ValueError("summary overflow")
                    if writer.write(summary) != len(summary):
                        raise OSError("short write")
                writer.close()
            except (OSError, ValueError):
                failed = True
                try:
                    writer.close()
                except (OSError, ValueError):
                    pass
    return 1 if failed else 0


def _manifest_projection(path):
    path = Path(path)
    if path.suffix.lower() != ".json" or any(part.lower() in FORBIDDEN_COMPONENTS or part.lower().endswith(".key") for part in path.parts):
        raise ValueError("unsafe manifest")
    if _regular(path).st_size > 65536:
        raise ValueError("manifest too large")
    with os.fdopen(_open(path, os.O_RDONLY), "rb") as reader:
        raw = reader.read(65537)
    if len(raw) > 65536:
        raise ValueError("manifest too large")
    value = _decode_json(raw)
    if type(value) is not dict:
        raise ValueError("invalid manifest")
    projection = {}
    for name in ("port_version", "runtime_version", "profile", "machine"):
        if name in value and validate_event({"event": "phase", "phase": "runtime", name: value[name]}) is not None:
            projection[name] = value[name]
    return projection


def _export_rows(path):
    if _regular(path).st_size > MAX_BYTES:
        return b""
    with os.fdopen(_open(path, os.O_RDONLY), "rb") as reader:
        data = reader.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        return b""
    result = bytearray()
    for line in _lines(io.BytesIO(data)):
        if line is None:
            continue
        try:
            event = validate_event(_decode_json(line), allow_summary=True)
        except (ValueError, TypeError, RecursionError):
            continue
        if event is not None:
            encoded = _encode(event)
            if len(result) + len(encoded) <= MAX_BYTES:
                result.extend(encoded)
    return bytes(result)


def export_logs(directory, output_directory=None, manifest=None):
    """Export only up to ten own, bounded, schema-reparsed logs and projection."""
    temporary = None
    with _private_umask():
        try:
            directory = _directory(directory)
            output_directory = _directory(output_directory or directory, create=True)
            destination = output_directory / "diagnostic-export.zip"
            _regular(destination, must_exist=False)
            projection = _manifest_projection(manifest) if manifest is not None else None
            # An exclusive private temporary file; never open/truncate an existing ZIP.
            import secrets
            temporary = output_directory / ("diagnostic-export-" + secrets.token_hex(8) + ".tmp")
            with os.fdopen(_open(temporary, os.O_RDWR | os.O_CREAT | os.O_EXCL), "w+b") as writer:
                with zipfile.ZipFile(writer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                    index = 0
                    for _mtime, _name, path in _owned_logs(directory)[:MAX_RETAIN]:
                        data = _export_rows(path)
                        if data:
                            index += 1
                            archive.writestr("logs/session-%03d.jsonl" % index, data)
                    if projection is not None:
                        archive.writestr("runtime-manifest.json", _encode(projection))
            _regular(destination, must_exist=False)
            os.replace(temporary, destination)
            temporary = None
            return 0
        except (OSError, ValueError, TypeError, RecursionError, zipfile.BadZipFile):
            return 1
        finally:
            if temporary is not None:
                try:
                    _regular(temporary)
                    os.unlink(temporary)
                except (OSError, ValueError):
                    pass


class _Parser(argparse.ArgumentParser):
    def error(self, _message):
        raise ValueError("invalid arguments")


def main(argv=None, stdin=None, stderr=None):
    stdin = stdin if stdin is not None else getattr(sys.stdin, "buffer", sys.stdin)
    stderr = stderr if stderr is not None else sys.stderr
    parser = _Parser(description="Bounded nonsecret offline PD2 diagnostics")
    modes = parser.add_subparsers(dest="mode", required=True, parser_class=_Parser)
    stream = modes.add_parser("stream")
    stream.add_argument("--dir", required=True)
    stream.add_argument("--session", required=True)
    stream.add_argument("--maxbytes", type=int, default=MAX_BYTES)
    stream.add_argument("--retain", type=int, default=MAX_RETAIN)
    export = modes.add_parser("export")
    export.add_argument("--dir", required=True)
    export.add_argument("--manifest")
    export.add_argument("--output-dir")
    try:
        args = parser.parse_args(argv)
    except ValueError:
        _drain(stdin)
        stderr.write("safe_log: invalid arguments\n")
        return 2
    if args.mode == "stream":
        rc = stream_log(args.dir, args.session, stdin, args.maxbytes, args.retain)
    else:
        rc = export_logs(args.dir, args.output_dir, args.manifest)
    if rc:
        stderr.write("safe_log: operation failed\n")
    return rc


if __name__ == "__main__":
    sys.exit(main())
