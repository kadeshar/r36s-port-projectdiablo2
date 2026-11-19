#!/usr/bin/env python3
"""Session-only menu on the same authenticated X11 session as the game.

stdout is a fixed three-token protocol (resolution fps loot_filter), not shell code.
Exit 10 means cancel. No settings writes, game files, input logs, sudo,
downloads or persistent writes; the launcher persists the confirmed choice.
The normal launcher prepares PortMaster, Weston and X11 before this runs.
FPS ON selects an automatic render-FPS HUD from the first game frames.
"""
import json
import os
from pathlib import Path
import select
import struct
import sys
import time

RESOLUTIONS = ('default', '640x480', '800x600', '1024x768', 'native')
LABELS = ('640x480', '640x480', '800x600', '1024x768', '1068x600')
EDITIONS = ('pd2', 'vanilla', 'vanilla114')
EDITION_LABELS = ('PROJECT DIABLO 2', 'VANILLA 1.13', 'VANILLA 1.14')
EDITION_LABEL_MAP = {
    'pd2': 'PROJECT DIABLO 2',
    'vanilla': 'VANILLA 1.13',
    'vanilla114': 'VANILLA 1.14',
}
OVERLAY_LEVELS = ('OFF', 'LEVEL 1', 'LEVEL 2', 'LEVEL 3', 'LEVEL 4')
CONTROLLER_MODES = ('auto', 'r36s', 'retrogame', 'rg35xxh', 'manual')
CONTROLLER_LABELS = ('AUTO', 'R36S', 'RETROGAME', 'RG35XX-H', 'MANUAL')
CANCEL = 10
LOOT_FILTER_DEFAULT = 'default'
CALIB_TIMEOUT = 5.0
EVENT = struct.Struct('@llHHi')  # Linux input_event: native timeval (aarch64/ARM32).
PAD_ACTIONS = {0x220: 'up', 0x221: 'down', 0x222: 'left', 0x223: 'right',
               103: 'up', 108: 'down', 105: 'left', 106: 'right',
               0x131: 'accept', 0x130: 'cancel',
               0x13b: 'accept', 0x13a: 'cancel',
               0x2c1: 'accept', 0x2c0: 'cancel', 0x2c4: 'cancel',
               28: 'accept', 57: 'accept', 1: 'cancel'}

STICK_TARGETS = {
    'LS_X': 0,  # ABS_X
    'LS_Y': 1,  # ABS_Y
    'RS_X': 3,  # ABS_RX
    'RS_Y': 4,  # ABS_RY
}

CALIB_TARGETS = (
    ('A', 'A BUTTON'),
    ('B', 'B BUTTON'),
    ('X', 'X BUTTON'),
    ('Y', 'Y BUTTON'),
    ('UP', 'DPAD UP'),
    ('DOWN', 'DPAD DOWN'),
    ('LEFT', 'DPAD LEFT'),
    ('RIGHT', 'DPAD RIGHT'),
    ('TL', 'L1 BUTTON'),
    ('LT', 'L2 BUTTON'),
    ('TR', 'R1 BUTTON'),
    ('RT', 'R2 BUTTON'),
    ('LS_X', 'L-STICK LEFT'),
    ('LS_Y', 'L-STICK UP'),
    ('RS_X', 'R-STICK LEFT'),
    ('RS_Y', 'R-STICK UP'),
    ('SELECT', 'SELECT BUTTON'),
    ('START', 'START BUTTON'),
    ('THUMBL', 'L3 BUTTON'),
    ('THUMBR', 'R3 BUTTON'),
    ('MODE', 'MENU / FN BUTTON'),
)


def get_config_dir():
    port = os.environ.get('PD2_PORT')
    if port:
        return Path(port) / 'config'
    return Path(__file__).resolve().parents[1] / 'config'


def load_controller_mode():
    try:
        path = get_config_dir() / 'controller.json'
        if path.is_file():
            with open(path, 'r', encoding='utf-8') as f:
                mode = json.load(f).get('mode', 'auto')
                if mode in CONTROLLER_MODES:
                    return mode
    except Exception:
        pass
    env_mode = os.environ.get('PD2_CONTROLLER_MODE')
    return env_mode if env_mode in CONTROLLER_MODES else 'auto'


def save_controller_mode(mode):
    try:
        cdir = get_config_dir()
        cdir.mkdir(parents=True, exist_ok=True)
        path = cdir / 'controller.json'
        tmp = path.with_suffix('.tmp')
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump({'mode': mode}, f)
        tmp.replace(path)
    except Exception:
        pass


def save_custom_pad(bindings):
    try:
        cdir = get_config_dir()
        cdir.mkdir(parents=True, exist_ok=True)
        path = cdir / 'custom_pad.json'
        tmp = path.with_suffix('.tmp')
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(bindings, f, indent=2)
        tmp.replace(path)
    except Exception:
        pass


def get_pad_actions():
    if os.environ.get('PD2_SWAP_AB') == '1':
        mapping = dict(PAD_ACTIONS)
        mapping[0x131] = 'cancel'
        mapping[0x130] = 'accept'
        return mapping
    return PAD_ACTIONS


def _filter_options():
    """User loot filters are read-only listed here; never modified by the menu.

    'DEFAULT' (no filtering) is always index 0; each regular *.filter file in
    port/filters follows in name order. A listing failure degrades to DEFAULT
    only and is reported with a closed enum event, never with a path.
    """
    port = os.environ.get('PD2_PORT')
    if not port:
        return []
    try:
        import layout
        names = layout.filter_listing(port)
    except (ImportError, OSError, ValueError):
        print('PD2_EVENT {"event":"session_probe","phase":"launch","check":"loot_filter","status":"unavailable"}',
              file=sys.stderr, flush=True)
        return []
    return names



def _detect_editions():
    port = os.environ.get('PD2_PORT')
    data_dir = os.environ.get('PD2_DATA')
    if not data_dir and port:
        data_dir = Path(port) / 'gamedata/Diablo II'
    if data_dir:
        try:
            scripts_dir = str(Path(__file__).resolve().parent)
            if scripts_dir not in sys.path:
                sys.path.insert(0, scripts_dir)
            import layout
            detected = layout.detect_available_editions(data_dir)
            if detected:
                return detected
        except (ImportError, OSError, ValueError, AttributeError):
            pass
    return EDITIONS


def _subtitle():
    """Header subtitle 'R36S PORT <version>'.

    The version comes from the layout version pin (single source of truth;
    never hardcoded here). A layout import failure degrades to 'R36S PORT'
    so the menu always draws its header.
    """
    try:
        import layout
        version = str(getattr(layout, 'VERSION', '')).strip()
    except (ImportError, OSError, ValueError, AttributeError):
        version = ''
    return ('R36S PORT ' + version) if version else 'R36S PORT'


class Menu:
    def __init__(self, editions=None):
        self.screen = 'main'  # 'main' | 'options' | 'controller' | 'calibrate'
        self.row = 0          # Main screen defaults to row 0: 'START GAME'
        self.resolution = 0
        self.resolution_changed = False
        self.fps = 0
        self.fps_changed = False
        self.editions = tuple(editions) if editions else _detect_editions()
        self.edition_labels = tuple(EDITION_LABEL_MAP.get(e, e.upper()) for e in self.editions)
        inherited_edition = os.environ.get('PD2_EDITION', 'pd2')
        self.edition_index = self.editions.index(inherited_edition) if inherited_edition in self.editions else 0
        # Display resolved launcher values without changing the inheritance
        # protocol. Standalone/default sessions use 640x480 (800x600 for vanilla 1.14) and FPS off.
        raw_res = os.environ.get('PD2_GAME_RESOLUTION')
        self.inherited_resolution_explicit = bool(raw_res and raw_res in ('640x480', '800x600', '1024x768', 'native'))
        if not self.inherited_resolution_explicit:
            inherited_resolution = '800x600' if self.edition == 'vanilla114' else '640x480'
        else:
            inherited_resolution = raw_res
        self.inherited_resolution = inherited_resolution
        inherited_fps = os.environ.get('PD2_FPS', '0')
        self.inherited_fps_level = int(inherited_fps) if inherited_fps in ('0', '1', '2', '3', '4') else 0
        self.inherited_fps = self.inherited_fps_level > 0
        # Loot filter choice: index 0 is always 'DEFAULT' (the shipped no-
        # filter). The previous confirmed choice (PD2_LOOT_FILTER) is selected
        # again so the menu opens on the user's last pick; a stale or missing
        # name safely falls back to DEFAULT.
        self.filters = _filter_options()
        self.filter_index = 0
        inherited_filter = os.environ.get('PD2_LOOT_FILTER', LOOT_FILTER_DEFAULT)
        if inherited_filter in self.filters:
            self.filter_index = self.filters.index(inherited_filter) + 1
        self.controller_mode = load_controller_mode()
        self.result = None

        # Calibration state
        self.calib_step = 0
        self.calib_keys = {}
        self.calib_triggers = {}
        self.calib_axis_map = {}
        self.calib_axis_centers = {}
        self.calib_has_hat_axes = False
        self.calib_held_code = None
        self.calib_held_kind = None
        self.calib_held_peak = 0
        self.calib_held_start = 0.0
        self.calib_deadline = 0.0
        self.calib_last_sec = 5
        self.calib_needs_repaint = False

    @property
    def edition(self):
        return self.editions[self.edition_index]

    @property
    def edition_label(self):
        return self.edition_labels[self.edition_index]

    @property
    def is_vanilla(self):
        return self.edition in ('vanilla', 'vanilla114')

    def edition_token(self):
        return self.edition

    def current_resolution(self):
        if self.resolution_changed and self.resolution in range(len(RESOLUTIONS)):
            res = RESOLUTIONS[self.resolution]
            if self.is_vanilla and res not in ('640x480', '800x600'):
                return '800x600' if self.edition == 'vanilla114' else '640x480'
            return res
        if self.inherited_resolution_explicit:
            return self.inherited_resolution
        if self.edition == 'vanilla114':
            return '800x600'
        return self.inherited_resolution

    @property
    def filter_label(self):
        """Bitmap-font label: uppercase only, truncated to fit one text row."""
        if self.filter_index == 0:
            return 'DEFAULT'
        return self.filters[self.filter_index - 1].upper()[:16]

    @property
    def controller_mode_label(self):
        idx = CONTROLLER_MODES.index(self.controller_mode) if self.controller_mode in CONTROLLER_MODES else 0
        return CONTROLLER_LABELS[idx]

    @property
    def calib_target_label(self):
        if self.calib_step < len(CALIB_TARGETS):
            return CALIB_TARGETS[self.calib_step][1]
        return 'COMPLETE'

    @property
    def calib_seconds_left(self):
        rem = max(0, int(self.calib_deadline - time.monotonic()) + 1)
        return min(5, rem)

    @property
    def calib_total_steps(self):
        return len(CALIB_TARGETS)

    def action(self, action):
        if self.result is not None:
            return

        if self.screen == 'main':
            if action == 'cancel':
                self.result = 'cancel'
            elif action in ('up', 'down'):
                self.row = (self.row + (-1 if action == 'up' else 1)) % 3
            elif action == 'accept':
                if self.row == 0:
                    self.result = 'launch'
                elif self.row == 1:
                    self.screen = 'options'
                    self.row = 0
                elif self.row == 2:
                    self.result = 'cancel'

        elif self.screen == 'options':
            if action == 'cancel':
                self.screen = 'main'
                self.row = 1
            elif action in ('up', 'down'):
                self.row = (self.row + (-1 if action == 'up' else 1)) % 6
            elif action in ('left', 'right', 'accept'):
                if self.row == 0:
                    delta = -1 if action == 'left' else 1
                    self.edition_index = (self.edition_index + delta) % len(self.editions)
                    if self.resolution_changed and self.is_vanilla:
                        cur_val = self.current_resolution()
                        if cur_val not in ('640x480', '800x600'):
                            target = '800x600' if self.edition == 'vanilla114' else '640x480'
                            self.resolution = RESOLUTIONS.index(target)
                elif self.row == 1:
                    opts = ('640x480', '800x600') if self.is_vanilla else RESOLUTIONS[1:]
                    cur_val = self.current_resolution()
                    cur = opts.index(cur_val) if cur_val in opts else 0
                    new_val = opts[(cur + (-1 if action == 'left' else 1)) % len(opts)]
                    self.resolution = RESOLUTIONS.index(new_val)
                    self.resolution_changed = True
                elif self.row == 2:
                    current = self.fps if self.fps_changed else self.inherited_fps_level
                    if isinstance(current, bool):
                        current = 1 if current else 0
                    if action == 'left':
                        self.fps = (current - 1) % len(OVERLAY_LEVELS)
                    elif action == 'right':
                        self.fps = (current + 1) % len(OVERLAY_LEVELS)
                    else:
                        self.fps = 0 if current > 0 else 1
                    self.fps_changed = True
                elif self.row == 3:
                    if not self.is_vanilla:
                        count = len(self.filters) + 1
                        self.filter_index = (self.filter_index + (-1 if action == 'left' else 1)) % count
                elif self.row == 4:
                    if action == 'accept':
                        self.screen = 'controller'
                        self.row = 0
                elif self.row == 5:
                    if action == 'accept':
                        self.screen = 'main'
                        self.row = 1

        elif self.screen == 'controller':
            if action == 'cancel':
                self.screen = 'options'
                self.row = 4
            elif action in ('up', 'down'):
                if self.controller_mode != 'manual':
                    # Only row 0 (MODE) and row 2 (BACK) are selectable when not manual
                    if action == 'down':
                        self.row = 2 if self.row == 0 else 0
                    else:
                        self.row = 0 if self.row == 2 else 2
                else:
                    self.row = (self.row + (-1 if action == 'up' else 1)) % 3
            elif action in ('left', 'right', 'accept'):
                if self.row == 0:
                    cur = CONTROLLER_MODES.index(self.controller_mode) if self.controller_mode in CONTROLLER_MODES else 0
                    self.controller_mode = CONTROLLER_MODES[(cur + (-1 if action == 'left' else 1)) % len(CONTROLLER_MODES)]
                    save_controller_mode(self.controller_mode)
                    if self.controller_mode != 'manual' and self.row == 1:
                        self.row = 0
                elif self.row == 1:
                    if action == 'accept' and self.controller_mode == 'manual':
                        self.start_calibration()
                elif self.row == 2:
                    if action == 'accept':
                        self.screen = 'options'
                        self.row = 4

        elif self.screen == 'calibrate':
            if action in ('cancel', 'accept'):
                self.cancel_calibration()

    def start_calibration(self):
        self.screen = 'calibrate'
        self.row = 0
        self.calib_step = 0
        self.calib_keys = {}
        self.calib_triggers = {}
        self.calib_axis_map = {}
        self.calib_axis_centers = {}
        self.calib_held_code = None
        self.calib_held_kind = None
        self.calib_held_peak = 0
        self.calib_held_start = 0.0
        self.calib_deadline = time.monotonic() + CALIB_TIMEOUT
        self.calib_last_sec = 5
        self.calib_needs_repaint = True

    def cancel_calibration(self):
        self.screen = 'controller'
        self.row = 1
        self.calib_held_code = None
        self.calib_held_kind = None
        self.calib_held_peak = 0
        self.calib_held_start = 0.0
        self.calib_axis_centers.clear()
        self.calib_needs_repaint = True

    def skip_calibration_step(self, pad=None):
        self.calib_step += 1
        self.calib_held_code = None
        self.calib_held_kind = None
        self.calib_held_peak = 0
        self.calib_held_start = 0.0
        self.calib_axis_centers.clear()
        if self.calib_step >= len(CALIB_TARGETS):
            self.finish_calibration(pad=pad)
        else:
            self.calib_deadline = time.monotonic() + CALIB_TIMEOUT
            self.calib_last_sec = 5
        self.calib_needs_repaint = True

    def record_calibration_step(self, code, pad=None):
        if self.calib_step < len(CALIB_TARGETS):
            target_key, _ = CALIB_TARGETS[self.calib_step]
            if target_key == 'LT':
                self.calib_triggers[code] = 2  # ABS_Z
            elif target_key == 'RT':
                self.calib_triggers[code] = 5  # ABS_RZ
            else:
                self.calib_keys[code] = target_key
            self.calib_step += 1
            self.calib_held_code = None
            self.calib_held_kind = None
            self.calib_held_peak = 0
            self.calib_held_start = 0.0
            self.calib_axis_centers.clear()
            if self.calib_step >= len(CALIB_TARGETS):
                self.finish_calibration(pad=pad)
            else:
                self.calib_deadline = time.monotonic() + CALIB_TIMEOUT
                self.calib_last_sec = 5
            self.calib_needs_repaint = True

    def record_calibration_trigger(self, axis_code, pad=None):
        if self.calib_step < len(CALIB_TARGETS):
            target_key, _ = CALIB_TARGETS[self.calib_step]
            if target_key in ('LT', 'RT'):
                out_axis = 2 if target_key == 'LT' else 5
                self.calib_triggers[axis_code] = out_axis
            self.calib_step += 1
            self.calib_held_code = None
            self.calib_held_kind = None
            self.calib_held_peak = 0
            self.calib_held_start = 0.0
            self.calib_axis_centers.clear()
            if self.calib_step >= len(CALIB_TARGETS):
                self.finish_calibration(pad=pad)
            else:
                self.calib_deadline = time.monotonic() + CALIB_TIMEOUT
                self.calib_last_sec = 5
            self.calib_needs_repaint = True

    def record_calibration_hat(self, target_key, code, pad=None):
        if self.calib_step < len(CALIB_TARGETS):
            self.calib_has_hat_axes = True
            self.calib_step += 1
            self.calib_held_code = None
            self.calib_held_kind = None
            self.calib_held_peak = 0
            self.calib_held_start = 0.0
            self.calib_axis_centers.clear()
            if self.calib_step >= len(CALIB_TARGETS):
                self.finish_calibration(pad=pad)
            else:
                self.calib_deadline = time.monotonic() + CALIB_TIMEOUT
                self.calib_last_sec = 5
            self.calib_needs_repaint = True

    def record_calibration_stick(self, target_key, code, pad=None):
        if self.calib_step < len(CALIB_TARGETS):
            target_axis = STICK_TARGETS.get(target_key)
            if target_axis is not None:
                self.calib_axis_map[code] = target_axis
            self.calib_step += 1
            self.calib_held_code = None
            self.calib_held_kind = None
            self.calib_held_peak = 0
            self.calib_held_start = 0.0
            self.calib_axis_centers.clear()
            if self.calib_step >= len(CALIB_TARGETS):
                self.finish_calibration(pad=pad)
            else:
                self.calib_deadline = time.monotonic() + CALIB_TIMEOUT
                self.calib_last_sec = 5
            self.calib_needs_repaint = True

    def handle_calibration_event(self, kind, code, value, pad=None):
        if self.screen != 'calibrate' or self.calib_step >= len(CALIB_TARGETS):
            return

        now = time.monotonic()
        target_key, _ = CALIB_TARGETS[self.calib_step]

        if target_key in STICK_TARGETS:
            if kind == 3:  # EV_ABS
                info = None
                if pad is not None and hasattr(pad, 'axis_info'):
                    info = pad.axis_info(code)

                if info is not None:
                    lo, hi = info[1], info[2]
                    flat = max(16, info[4])
                    span = max(1, hi - lo)
                    center = (lo + hi) // 2
                    push_thresh = max(40, int(span * 0.20))
                    release_thresh = max(flat * 2, max(40, int(span * 0.10)))
                else:
                    if value < 0:
                        center = 0
                    else:
                        if code not in self.calib_axis_centers:
                            self.calib_axis_centers[code] = value
                        center = self.calib_axis_centers[code]
                    push_thresh = 50
                    release_thresh = 30

                delta = abs(value - center)
                if self.calib_held_code is None:
                    if delta >= push_thresh:
                        self.calib_held_code = code
                        self.calib_held_kind = 3
                        self.calib_held_peak = delta
                        self.calib_held_start = now
                        self.calib_needs_repaint = True
                elif self.calib_held_kind == 3 and self.calib_held_code == code:
                    if delta > getattr(self, 'calib_held_peak', 0):
                        self.calib_held_peak = delta
                    peak = getattr(self, 'calib_held_peak', delta)
                    if delta <= release_thresh or delta <= int(peak * 0.35):
                        self.record_calibration_stick(target_key, code, pad=pad)
            return

        if target_key in ('UP', 'DOWN', 'LEFT', 'RIGHT') and kind == 3:  # EV_ABS hat for D-pad
            if code in (16, 17):  # ABS_HAT0X, ABS_HAT0Y
                is_push = (value < 0) if target_key in ('UP', 'LEFT') else (value > 0)
                if is_push:
                    if self.calib_held_code is None:
                        self.calib_held_code = code
                        self.calib_held_kind = 3
                        self.calib_held_start = now
                        self.calib_needs_repaint = True
                elif value == 0:  # Released back to center
                    if self.calib_held_kind == 3 and self.calib_held_code == code:
                        self.record_calibration_hat(target_key, code, pad=pad)
            return

        if kind == 1:  # EV_KEY
            if value == 1:  # Pressed down
                if self.calib_held_code is None:
                    self.calib_held_code = code
                    self.calib_held_kind = 1
                    self.calib_held_start = now
                    self.calib_needs_repaint = True
            elif value == 0:  # Released
                if self.calib_held_kind == 1 and self.calib_held_code == code:
                    self.record_calibration_step(code, pad=pad)

        elif kind == 3 and target_key in ('LT', 'RT'):  # EV_ABS for analog triggers
            if code in (2, 5, 9, 10):  # Trigger axes (ABS_Z, ABS_RZ, ABS_BRAKE, ABS_GAS)
                if value > 100:  # Pulled
                    if self.calib_held_code is None:
                        self.calib_held_code = code
                        self.calib_held_kind = 3
                        self.calib_held_start = now
                        self.calib_needs_repaint = True
                elif value < 30:  # Released
                    if self.calib_held_kind == 3 and self.calib_held_code == code:
                        self.record_calibration_trigger(code, pad=pad)

    def finish_calibration(self, pad=None):
        axis_map = {'0': 0, '1': 1, '3': 3, '4': 4}
        for c, t in self.calib_axis_map.items():
            axis_map[str(c)] = t

        bindings = {
            'layout': 'manual',
            'device_name': getattr(pad, 'device_name', '') if pad else '',
            'vid': getattr(pad, 'vid', 0) if pad else 0,
            'pid': getattr(pad, 'pid', 0) if pad else 0,
            'keys': {str(c): k for c, k in self.calib_keys.items()},
            'triggers': {str(c): t for c, t in self.calib_triggers.items()},
            'axis_map': axis_map,
            'has_hat_axes': getattr(self, 'calib_has_hat_axes', False),
        }
        save_custom_pad(bindings)
        self.controller_mode = 'manual'
        save_controller_mode('manual')
        self.screen = 'controller'
        self.row = 1
        self.calib_held_code = None
        self.calib_held_kind = None
        self.calib_held_peak = 0
        self.calib_held_start = 0.0
        self.calib_axis_centers.clear()
        self.calib_needs_repaint = True

    def tick_calibration(self, pad=None):
        if self.screen != 'calibrate':
            return
        now = time.monotonic()
        if self.calib_held_code is not None:
            # If an analog axis is held, check if it returned to center even if no new evdev event was emitted
            if self.calib_held_kind == 3 and pad is not None and hasattr(pad, 'axis_val'):
                cur_val = pad.axis_val(self.calib_held_code)
                if cur_val is not None:
                    info = pad.axis_info(self.calib_held_code) if hasattr(pad, 'axis_info') else None
                    if info is not None:
                        lo, hi = info[1], info[2]
                        flat = max(16, info[4])
                        span = max(1, hi - lo)
                        center = (lo + hi) // 2
                        release_thresh = max(flat * 2, max(40, int(span * 0.12)))
                    else:
                        center = self.calib_axis_centers.get(self.calib_held_code, 0)
                        release_thresh = 40
                    cur_delta = abs(cur_val - center)
                    peak = getattr(self, 'calib_held_peak', cur_delta)
                    if cur_delta <= release_thresh or cur_delta <= int(peak * 0.35):
                        target_key, _ = CALIB_TARGETS[self.calib_step]
                        if target_key in STICK_TARGETS:
                            self.record_calibration_stick(target_key, self.calib_held_code, pad=pad)
                            return
                        elif target_key in ('LT', 'RT'):
                            self.record_calibration_trigger(self.calib_held_code, pad=pad)
                            return
                        elif target_key in ('UP', 'DOWN', 'LEFT', 'RIGHT'):
                            self.record_calibration_hat(target_key, self.calib_held_code, pad=pad)
                            return

            # Hold safety timeout: if held for over 2.0 seconds, auto-advance so it never freezes
            if (now - getattr(self, 'calib_held_start', now)) > 2.0:
                target_key, _ = CALIB_TARGETS[self.calib_step]
                if target_key in STICK_TARGETS:
                    self.record_calibration_stick(target_key, self.calib_held_code, pad=pad)
                    return
                elif target_key in ('LT', 'RT'):
                    self.record_calibration_trigger(self.calib_held_code, pad=pad)
                    return
                elif target_key in ('UP', 'DOWN', 'LEFT', 'RIGHT') and self.calib_held_kind == 3:
                    self.record_calibration_hat(target_key, self.calib_held_code, pad=pad)
                    return
                elif self.calib_held_kind == 1:
                    self.record_calibration_step(self.calib_held_code, pad=pad)
                    return

            # Keep deadline alive while actively held
            self.calib_deadline = now + CALIB_TIMEOUT
            return

        if now >= self.calib_deadline:
            self.skip_calibration_step(pad=pad)
        else:
            rem = max(0, int(self.calib_deadline - now) + 1)
            if rem != self.calib_last_sec:
                self.calib_last_sec = rem
                self.calib_needs_repaint = True

    def selection(self):
        if self.result != 'launch':
            raise ValueError('not confirmed')
        filter_name = (LOOT_FILTER_DEFAULT if self.filter_index == 0
                       else self.filters[self.filter_index - 1])
        if self.resolution_changed:
            res = self.current_resolution()
        elif self.edition == 'vanilla114' and not self.inherited_resolution_explicit:
            res = '800x600'
        else:
            res = RESOLUTIONS[self.resolution]
        return (res,
                str(int(self.fps)) if self.fps_changed else 'default',
                filter_name,
                self.edition)

    def float_active(self):
        """A long filter name is held on the filter row: its full name
        animates (marquee) in the row and the menu must repaint on a timer."""
        if self.screen != 'options' or self.row != 3 or self.filter_index == 0:
            return False
        return len(self.filters[self.filter_index - 1]) > 16

    def calib_active(self):
        return self.screen == 'calibrate'


class KeyDecoder:
    """Ignore keys held on entry, release events and kernel autorepeat.
    Also handles Hat (EV_ABS 16/17) and analog stick (EV_ABS 0/1) directional input.
    """
    def __init__(self, mapping, held=()):
        self.mapping = mapping
        self.held = set(held)
        self.buffer = b''
        self.hat_x = 0
        self.hat_y = 0
        self.stick_x = 0
        self.stick_y = 0
        self.last_raw = []

    def feed(self, data):
        self.buffer += data
        actions = []
        raw = []
        while len(self.buffer) >= EVENT.size:
            _, _, kind, code, value = EVENT.unpack(self.buffer[:EVENT.size])
            self.buffer = self.buffer[EVENT.size:]
            raw.append((kind, code, value))
            if kind == 0 and code == 3:  # SYN_DROPPED: do not trust stale state.
                raise OSError('input synchronization lost')
            if kind == 1:  # EV_KEY
                if value == 0:
                    self.held.discard(code)
                elif value == 1 and code not in self.held:
                    self.held.add(code)
                    if code in self.mapping:
                        actions.append(self.mapping[code])
            elif kind == 3:  # EV_ABS (Hat and Stick)
                if code == 16:  # ABS_HAT0X
                    new_dir = -1 if value < 0 else (1 if value > 0 else 0)
                    if new_dir != self.hat_x:
                        if new_dir == -1:
                            actions.append('left')
                        elif new_dir == 1:
                            actions.append('right')
                        self.hat_x = new_dir
                elif code == 17:  # ABS_HAT0Y
                    new_dir = -1 if value < 0 else (1 if value > 0 else 0)
                    if new_dir != self.hat_y:
                        if new_dir == -1:
                            actions.append('up')
                        elif new_dir == 1:
                            actions.append('down')
                        self.hat_y = new_dir
                elif code == 0:  # ABS_X (Left analog stick horizontal)
                    new_dir = -1 if value < -16000 else (1 if value > 16000 else 0)
                    if new_dir != self.stick_x:
                        if new_dir == -1:
                            actions.append('left')
                        elif new_dir == 1:
                            actions.append('right')
                        self.stick_x = new_dir
                elif code == 1:  # ABS_Y (Left analog stick vertical)
                    new_dir = -1 if value < -16000 else (1 if value > 16000 else 0)
                    if new_dir != self.stick_y:
                        if new_dir == -1:
                            actions.append('up')
                        elif new_dir == 1:
                            actions.append('down')
                        self.stick_y = new_dir
        self.last_raw = raw
        return actions


# Handheld Vendor:Product IDs and names recognized across PortMaster ecosystem
PORTMASTER_PAD_IDS = {
    (0x484b, 0x1100),  # R36S / OGS / Powkiddy RGB10 MAX
    (0x484b, 0x1101),  # RG353V / RG353P / RG353M / RK3566
    (0x484b, 0x1000),  # Odroid Go Advance / RK2020
    (0x484b, 0x1111),  # Anbernic RG552
    (0x0912, 0x0031),  # Anbernic RG351P / RG351M / RG351V / RG351MP
    (0x0003, 0x0003),  # Gameforce Chi
    (0x8d96, 0x0221),  # GameKiddy Pixel
    (0x045e, 0x028e),  # Xbox 360 / XInput Controller
}

PORTMASTER_PAD_NAMES = (
    'go-super', 'gamepad', 'retrogame_joypad', 'joystick', 'joypad',
    'anbernic', 'odroidgo', 'gameforce', 'rk2020', 'trimui',
    'rg351', 'rg353', 'rg552', 'gkd', 'xbox', '8bitdo', 'playstation'
)

PORTMASTER_BY_PATH = (
    '/dev/input/by-path/platform-odroidgo3-joypad-event-joystick',
    '/dev/input/by-path/platform-odroidgo2-joypad-event-joystick',
    '/dev/input/by-path/platform-ff300000.usb-usb-0:1.2:1.0-event-joystick',
    '/dev/input/by-path/platform-gameforce-gamepad-event-joystick',
    '/dev/input/by-path/platform-singleadc-joypad-event-joystick',
    '/dev/input/by-path/platform-gamekiddy-joypad-event-joystick',
)


class Pad:
    def __init__(self):
        self.fds = []
        self.fd = None
        self.device_name = ''
        self.vid = 0
        self.pid = 0
        # Reuse the already verified physical R36S identity/layout when available.
        # Fall back to opening candidate event devices for other handhelds (RG353V, etc.).
        import fcntl
        actions_map = get_pad_actions()
        device_paths = []
        try:
            import xbox_mapper as mapper
            dev = mapper.choose_pad(mapper.physical_devices())
            if dev is not None:
                device_paths = [dev[0]]
                self.device_name = dev[1]
                self.vid = dev[2]
                self.pid = dev[3]
        except Exception:
            pass

        if not device_paths:
            # 1. Check PortMaster known by-path device symlinks
            for bp in PORTMASTER_BY_PATH:
                if os.path.exists(bp):
                    try:
                        resolved = os.path.realpath(bp)
                        if resolved not in device_paths:
                            device_paths.append(resolved)
                    except OSError:
                        pass

        if not device_paths:
            # 2. Check PortMaster recognized vendor/product IDs and device names
            from pathlib import Path
            devices = []
            for p in sorted(Path('/sys/class/input').glob('event[0-9]*')):
                base = p / 'device'
                try:
                    name = (base / 'name').read_text().strip()
                    id_dir = base / 'id'
                    vid = int((id_dir / 'vendor').read_text(), 16)
                    pid = int((id_dir / 'product').read_text(), 16)
                    devices.append(('/dev/input/' + p.name, name, vid, pid))
                except Exception:
                    continue

            for dev in devices:
                if dev[0] in device_paths:
                    continue
                name_lower = dev[1].lower()
                if (dev[2], dev[3]) in PORTMASTER_PAD_IDS or any(k in name_lower for k in PORTMASTER_PAD_NAMES):
                    device_paths.append(dev[0])

        if not device_paths:
            # Fallback: scan /dev/input/event*
            from pathlib import Path
            for p in sorted(Path('/dev/input').glob('event[0-9]*')):
                device_paths.append(str(p))

        if not device_paths:
            return  # X11 keyboard remains usable.

        all_held = set()
        open_fds = []
        try:
            for path in device_paths:
                try:
                    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | getattr(os, 'O_NOFOLLOW', 0))
                except OSError:
                    continue
                try:
                    # EVIOCGKEY(96) = 0x80604518
                    ioctl_cmd = 0x80604518
                    try:
                        import xbox_mapper as mapper
                        ioctl_cmd = mapper.evread(0x18, 96)
                    except Exception:
                        pass
                    mask = fcntl.ioctl(fd, ioctl_cmd, bytes(96))
                    for code in actions_map:
                        if mask[code // 8] & (1 << (code % 8)):
                            all_held.add(code)
                    open_fds.append(fd)
                except Exception:
                    if len(device_paths) == 1:
                        # Dedicated chosen device must propagate permission/driver error
                        os.close(fd)
                        raise
                    open_fds.append(fd)
        except BaseException:
            for fd in open_fds:
                try:
                    os.close(fd)
                except OSError:
                    pass
            raise

        if not open_fds:
            return
        self.fds = open_fds
        self.fd = open_fds[0]
        self.decoder = KeyDecoder(actions_map, all_held)

    def actions(self):
        if not self.fds:
            return []
        readable, _, _ = select.select(self.fds, [], [], 0)
        if not readable:
            self.decoder.last_raw = []
            return []
        all_actions = []
        for fd in readable:
            data = os.read(fd, EVENT.size * 64)
            if not data:
                raise OSError('controller disconnected')
            all_actions.extend(self.decoder.feed(data))
        return all_actions

    def raw_events(self):
        res = getattr(self.decoder, 'last_raw', [])
        self.decoder.last_raw = []
        return res

    def axis_info(self, code):
        """Query (value, min, max, fuzz, flat, res) for axis code via EVIOCGABS."""
        import fcntl, struct
        for fd in self.fds:
            try:
                # EVIOCGABS(code) = 0x80184540 + code
                val = struct.unpack('<6i', fcntl.ioctl(fd, 0x80184540 + code, bytes(24)))
                if val[2] > val[1]:
                    return val
            except Exception:
                pass
        return None

    def axis_val(self, code):
        """Query current instantaneous value for axis code."""
        info = self.axis_info(code)
        return info[0] if info else None

    def close(self):
        for fd in self.fds:
            try:
                os.close(fd)
            except OSError:
                pass
        self.fds = []
        self.fd = None


# Built-in 5x7 font: no native GUI library, fonts or package installation.
FONT = dict(zip('ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 -:/<>.', (
    '0E11111F111111', '1E11111E11111E', '0F10101010100F', '1E11111111111E',
    '1F10101E10101F', '1F10101E101010', '0F10101711110F', '1111111F111111',
    '0E04040404040E', '0101010111110E', '11121418141211', '1010101010101F',
    '111B1515111111', '11191513111111', '0E11111111110E', '1E11111E101010',
    '0E11111115120D', '1E11111E141211', '0F10100E01011E', '1F040404040404',
    '1111111111110E', '11111111110A04', '11111115151B11', '11110A040A1111',
    '11110A04040404', '1F01020408101F', '0E11131519110E', '040C040404040E',
    '0E11010204081F', '1E01010601011E', '02060A121F0202', '1F10101E01011E',
    '0E10101E11110E', '1F010204080808', '0E11110E11110E', '0E11110F01010E',
    '00000000000000', '0000001F000000', '00040000000400', '01020404081010',
    '02040810080402', '08040201020408', '00000000000C0C')))
FONT['x'] = '0000110A040A11'


class Screen:
    """Direct core-X11 client: no SDL video backend or native GUI library."""
    def __new__(cls):
        from menu_x11 import Screen as X11Screen
        return X11Screen(FONT, LABELS, _subtitle())


def run(screen, pad, sleep=time.sleep):
    menu = Menu()
    screen.draw(menu)
    # Let the menu become visible and discard the Ports launch key. Starting
    # the game always requires a NEW press after this initial release barrier.
    sleep(0.35)
    pad.actions()
    screen.actions()
    while menu.result is None:
        before = (menu.screen, menu.row, menu.resolution, menu.fps, menu.fps_changed, menu.filter_index, menu.controller_mode, menu.edition_index)
        pad_actions = pad.actions()
        screen_actions = screen.actions()
        if menu.screen == 'calibrate':
            if 'cancel' in screen_actions:
                menu.cancel_calibration()
            else:
                held_keys = getattr(getattr(pad, 'decoder', None), 'held', set())
                # Cancel only if Select AND Start chord is held simultaneously for > 0.4s
                has_select = any(c in held_keys for c in (0x2c0, 0x13a, 0x136))
                has_start = any(c in held_keys for c in (0x2c1, 0x13b, 0x137))
                if has_select and has_start:
                    if getattr(menu, '_cancel_chord_since', 0.0) == 0.0:
                        menu._cancel_chord_since = time.monotonic()
                    elif time.monotonic() - menu._cancel_chord_since >= 0.4:
                        menu.cancel_calibration()
                else:
                    menu._cancel_chord_since = 0.0
                    raw_events = getattr(pad, 'raw_events', lambda: [])()
                    for kind, code, value in raw_events:
                        menu.handle_calibration_event(kind, code, value, pad=pad)
                    menu.tick_calibration(pad=pad)
        else:
            for action in pad_actions + screen_actions:
                menu.action(action)
        if menu.result is None:
            after = (menu.screen, menu.row, menu.resolution, menu.fps, menu.fps_changed, menu.filter_index, menu.controller_mode, menu.edition_index)
            if after != before:
                screen.draw(menu)
            elif menu.screen == 'calibrate' and menu.calib_needs_repaint:
                menu.calib_needs_repaint = False
                screen.draw(menu)
            elif menu.float_active():
                screen.draw(menu)
            sleep(0.02)
    return menu.selection() if menu.result == 'launch' else None


def main(screen_factory=Screen, pad_factory=Pad, stdout=None, stderr=None):
    stdout = sys.stdout if stdout is None else stdout
    stderr = sys.stderr if stderr is None else stderr
    screen = pad = None
    try:
        screen = screen_factory()
        pad = pad_factory()
        selection = run(screen, pad)
        if selection is None:
            return CANCEL
        # Closed enum audit trail; the count is the number of listed user
        # filters, never a name or path.
        count = len(_filter_options())
        status = 'selected' if selection[2] != LOOT_FILTER_DEFAULT else 'default'
        print('PD2_EVENT {"event":"session_probe","phase":"launch","check":"loot_filter","status":"'
              + status + '","count":' + str(count) + '}', file=stderr, flush=True)
        # Whitelisted protocol only. No eval/source or persistent settings.
        print(' '.join(selection), file=stdout, flush=True)
        return 0
    except (OSError, ValueError, ImportError, AttributeError) as exc:
        # Only public fixed codes enter the existing safe-log stream. Never
        # report authentication bytes, X11 reply contents or exception strings.
        allowed = {'connect_failed', 'auth_failed', 'setup_invalid', 'window_failed',
                   'not_visible', 'protocol_error', 'disconnected', 'timeout', 'input_failed'}
        code = getattr(exc, 'code', 'input_failed' if screen is not None else 'unavailable')
        if code not in allowed:
            code = 'unavailable'
        print('PD2_EVENT {"event":"session_probe","phase":"launch","check":"menu_display","status":"' + code + '"}', file=stderr, flush=True)
        print('PD2: launcher menu unavailable; game NOT started.', file=stderr)
        return 1
    except KeyboardInterrupt:
        return CANCEL
    finally:
        if pad is not None:
            pad.close()
        if screen is not None:
            screen.close()


if __name__ == '__main__':
    raise SystemExit(main())
