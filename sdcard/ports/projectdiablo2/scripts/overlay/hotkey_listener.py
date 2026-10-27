#!/usr/bin/env python3
"""Background gamepad hotkey listener for R36S performance overlay.

Listens to handheld button combinations (default: FN + R1 to switch level,
FN + R2 to reset frametime data) directly via Linux input devices (/dev/input/event*)
with zero external dependencies. Supports R36S ArkOS hardware keycodes,
virtual Xbox uinput pad codes, and keyboard fallbacks for testing.
"""
import glob
import os
import select
import struct
import threading
import time

# Native Linux struct input_event: timeval (2 longs), type (H), code (H), value (i)
EVENT_FORMAT = '@llHHi'
EVENT_SIZE = struct.calcsize(EVENT_FORMAT)
EV_SYN = 0x00
EV_KEY = 0x01
EV_ABS = 0x03

# Physical and virtual keycodes (Linux input standard & R36S hardware)
# FN / Menu / Mode keycodes:
BTN_TRIGGER_HAPPY5 = 0x2c4  # 708: R36S ArkOS Menu / FN hardware button
BTN_MODE = 0x13c            # 316: Guide / Mode (virtual Xbox pad)
KEY_FN = 0x1d0              # 464: Linux standard KEY_FN
BTN_TRIGGER_HAPPY1 = 0x2c0  # 704: Select button on R36S hardware
BTN_SELECT = 0x13a          # 314: Standard Select button

FN_KEYS = {BTN_TRIGGER_HAPPY5, BTN_MODE, KEY_FN, BTN_TRIGGER_HAPPY1, BTN_SELECT}

# R1 / TR (Right Bumper):
BTN_TR = 0x137              # 311: R1 button (R36S hardware & Xbox pad)
KEY_F1 = 59                 # Keyboard F1 (testing fallback)

R1_KEYS = {BTN_TR, KEY_F1}

# R2 / TR2 (Right Trigger):
BTN_TR2 = 0x139             # 313: R2 button (R36S hardware)
ABS_RZ = 0x05               # Axis 5 (Right trigger on Xbox pad)
KEY_F2 = 60                 # Keyboard F2 (testing fallback)

R2_KEYS = {BTN_TR2, KEY_F2}


class HotkeyListener:
    """Monitors gamepad input devices for overlay control hotkeys."""

    def __init__(self, on_switch_level=None, on_reset_data=None, debounce_seconds=0.35):
        self.on_switch_level = on_switch_level
        self.on_reset_data = on_reset_data
        self.debounce_seconds = debounce_seconds

        self.running = False
        self.thread = None
        self.device_fds = {}
        self.held_keys = set()
        self.r2_axis_held = False

        self.last_switch_time = 0.0
        self.last_reset_time = 0.0
        self.switch_level_pending = False
        self.reset_data_pending = False
        self._lock = threading.Lock()
        self._stop_event = threading.Event()

    def start(self):
        """Start listening in a background daemon thread."""
        if self.running:
            return
        self.running = True
        self._stop_event.clear()
        self._scan_devices()
        self.thread = threading.Thread(target=self._run_loop, name='OverlayHotkeyListener', daemon=True)
        self.thread.start()

    def stop(self):
        """Stop background listening and close all input descriptors."""
        self.running = False
        self._stop_event.set()
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=0.2)
        self.thread = None
        self._close_devices()

    def poll_actions(self):
        """Atomically retrieve and clear pending action flags."""
        with self._lock:
            sw = self.switch_level_pending
            rs = self.reset_data_pending
            self.switch_level_pending = False
            self.reset_data_pending = False
        return sw, rs

    def _scan_devices(self):
        """Find and open accessible /dev/input/event* devices non-blocking."""
        for path in sorted(glob.glob('/dev/input/event*')):
            if path not in self.device_fds:
                try:
                    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
                    self.device_fds[path] = fd
                except (OSError, PermissionError):
                    pass

    def _close_devices(self):
        for path, fd in list(self.device_fds.items()):
            try:
                os.close(fd)
            except OSError:
                pass
        self.device_fds.clear()

    def process_data(self, data):
        """Process raw input_event bytes (can be used directly in unit tests)."""
        offset = 0
        while offset + EVENT_SIZE <= len(data):
            _, _, etype, code, val = struct.unpack_from(EVENT_FORMAT, data, offset)
            offset += EVENT_SIZE
            self._handle_event(etype, code, val)

    def _handle_event(self, etype, code, val):
        now = time.monotonic()
        if etype == EV_KEY:
            if val == 1:  # Key down
                self.held_keys.add(code)
                fn_active = any(k in self.held_keys for k in FN_KEYS)

                if fn_active:
                    if code in R1_KEYS:
                        if now - self.last_switch_time >= self.debounce_seconds:
                            self.last_switch_time = now
                            with self._lock:
                                self.switch_level_pending = True
                            if self.on_switch_level:
                                try:
                                    self.on_switch_level()
                                except Exception:
                                    pass
                    elif code in R2_KEYS:
                        if now - self.last_reset_time >= self.debounce_seconds:
                            self.last_reset_time = now
                            with self._lock:
                                self.reset_data_pending = True
                            if self.on_reset_data:
                                try:
                                    self.on_reset_data()
                                except Exception:
                                    pass
                    elif code in FN_KEYS:
                        # FN pressed while R1 or R2 was already held
                        if any(k in self.held_keys for k in R1_KEYS):
                            if now - self.last_switch_time >= self.debounce_seconds:
                                self.last_switch_time = now
                                with self._lock:
                                    self.switch_level_pending = True
                                if self.on_switch_level:
                                    try:
                                        self.on_switch_level()
                                    except Exception:
                                        pass
                        elif any(k in self.held_keys for k in R2_KEYS) or self.r2_axis_held:
                            if now - self.last_reset_time >= self.debounce_seconds:
                                self.last_reset_time = now
                                with self._lock:
                                    self.reset_data_pending = True
                                if self.on_reset_data:
                                    try:
                                        self.on_reset_data()
                                    except Exception:
                                        pass
            elif val == 0:  # Key up
                self.held_keys.discard(code)

        elif etype == EV_ABS and code == ABS_RZ:
            if val >= 128:
                if not self.r2_axis_held:
                    self.r2_axis_held = True
                    fn_active = any(k in self.held_keys for k in FN_KEYS)
                    if fn_active and (now - self.last_reset_time >= self.debounce_seconds):
                        self.last_reset_time = now
                        with self._lock:
                            self.reset_data_pending = True
                        if self.on_reset_data:
                            try:
                                self.on_reset_data()
                            except Exception:
                                pass
            else:
                self.r2_axis_held = False

    def _run_loop(self):
        last_scan = 0.0
        while self.running and not self._stop_event.is_set():
            now = time.monotonic()
            if now - last_scan >= 2.0:
                last_scan = now
                self._scan_devices()

            if not self.device_fds:
                self._stop_event.wait(0.2)
                continue

            try:
                rlist, _, _ = select.select(list(self.device_fds.values()), [], [], 0.05)
            except (ValueError, OSError):
                self._close_devices()
                self._scan_devices()
                continue

            for fd in rlist:
                try:
                    data = os.read(fd, EVENT_SIZE * 32)
                    if data:
                        self.process_data(data)
                except OSError:
                    pass
