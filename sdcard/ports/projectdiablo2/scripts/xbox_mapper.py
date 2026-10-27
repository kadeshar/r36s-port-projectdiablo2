#!/usr/bin/env python3
"""Private R36S GO-Super evdev -> Xbox uinput bridge, Python stdlib only.

Linux UAPI: input_id = four u16; uinput_user_dev = 1116 bytes.
UI_SET_*BIT takes an integer (not a pointer), EVIOCGABS is _IOR.
No grabs, global permission changes, raw input logs or SDL dependency.
Physical layout follows the user's 17-step evidence; changes still need XInput retest.
"""
import fcntl
import json
import os
from pathlib import Path
import select
import signal
import stat
import struct
import sys
import tempfile

EV_SYN, EV_KEY, EV_ABS = 0, 1, 3
SYN_REPORT, SYN_DROPPED = 0, 3
ABS_X, ABS_Y, ABS_Z, ABS_RX, ABS_RY, ABS_RZ = range(6)
ABS_HAT0X, ABS_HAT0Y = 16, 17
ABS_MAX, KEY_MAX = 0x3f, 0x2ff
BUS_USB = 3
VXBOX_VENDOR, VXBOX_PRODUCT, VXBOX_VERSION = 0x045e, 0x028e, 0x0104
VXBOX_NAME = b'Microsoft X-Box 360 pad'
# Output codes from linux/input-event-codes.h, NOT the physical GO-Super codes.
XBOX_KEYS = dict(A=0x130, B=0x131, X=0x133, Y=0x134,
                 TL=0x136, TR=0x137, SELECT=0x13a, START=0x13b,
                 MODE=0x13c, THUMBL=0x13d, THUMBR=0x13e)
AXES = {
    ABS_X: (-32768, 32767, 16, 128), ABS_Y: (-32768, 32767, 16, 128),
    ABS_Z: (0, 255, 0, 0), ABS_RX: (-32768, 32767, 16, 128),
    ABS_RY: (-32768, 32767, 16, 128), ABS_RZ: (0, 255, 0, 0),
    ABS_HAT0X: (-1, 1, 0, 0), ABS_HAT0Y: (-1, 1, 0, 0),
}
STICK_DEADZONE = 8000
# Native long layout: 24 bytes on aarch64, 16 on ARM32.
EVENT = struct.Struct('@llHHi')
EV_SIZE = EVENT.size
UI_SET_EVBIT, UI_SET_KEYBIT, UI_SET_ABSBIT = 0x40045564, 0x40045565, 0x40045567
UI_DEV_CREATE, UI_DEV_DESTROY = 0x5501, 0x5502


def evread(nr, size):
    return (2 << 30) | (size << 16) | (ord('E') << 8) | nr


def eviocgabs(code):
    return evread(0x40 + code, 24)


def bits_set(mask, *codes):
    return all(mask & (1 << c) for c in codes)


def bitmap(text, word_bits=64):
    """sysfs prints space-separated unsigned-long words, highest first."""
    value = 0
    for word in text.split():
        value = (value << word_bits) | int(word, 16)
    return value


def probe_event(status, check='controller_mapper'):
    print('PD2_EVENT ' + json.dumps(dict(event='session_probe', phase='launch',
                                       check=check, status=status), separators=(',', ':')),
          flush=True)


def physical_devices(root='/sys/class/input'):
    found = []
    for event in sorted(Path(root).glob('event[0-9]*')):
        # eventN's device symlink points to inputN; metadata is NOT on eventN.
        base = event / 'device'
        try:
            name = (base / 'name').read_text().strip()
            vid = int((base / 'id/vendor').read_text().strip(), 16)
            pid = int((base / 'id/product').read_text().strip(), 16)
            ev = bitmap((base / 'capabilities/ev').read_text(), struct.calcsize('@L') * 8)
            keys = bitmap((base / 'capabilities/key').read_text(), struct.calcsize('@L') * 8)
            axes = bitmap((base / 'capabilities/abs').read_text(), struct.calcsize('@L') * 8)
        except (OSError, ValueError, UnicodeError):
            continue
        if not bits_set(ev, EV_KEY, EV_ABS):
            continue
        if (vid, pid) == (VXBOX_VENDOR, VXBOX_PRODUCT):
            continue
        found.append(('/dev/input/' + event.name, name, vid, pid, keys, axes))
    return found


def choose_pad(devices):
    # Primary match: R36S / GO-Super Gamepad (0x484b, 0x1100).
    r36s = next((d for d in devices if (d[2], d[3]) == (0x484b, 0x1100)
                 and bits_set(d[4], 0x130, 0x131, 0x133, 0x134)
                 and bits_set(d[5], ABS_X, ABS_Y, ABS_RX, ABS_RY)), None)
    if r36s is not None:
        return r36s
    # RG353V / retrogame_joypad (0x484b, 0x1101):
    rg353 = next((d for d in devices if (d[2], d[3]) == (0x484b, 0x1101)
                  and bits_set(d[4], 0x130, 0x131, 0x133, 0x134)
                  and bits_set(d[5], ABS_X, ABS_Y, ABS_RX, ABS_RY)), None)
    if rg353 is not None:
        return rg353
    # Named built-in handheld controller match (retrogame_joypad):
    return next((d for d in devices if d[1] == 'retrogame_joypad'
                 and bits_set(d[4], 0x130, 0x131, 0x133, 0x134)
                 and bits_set(d[5], ABS_X, ABS_Y, ABS_RX, ABS_RY)), None)


def build_keymap(keybits, absbits):
    if not bits_set(keybits, 0x130, 0x131, 0x133, 0x134):
        raise ValueError('unsupported layout')
    if absbits & ((1 << ABS_Z) | (1 << ABS_RZ)):
        raise ValueError('unexpected axes')

    if bits_set(keybits, 0x2c0, 0x2c1):
        # Physical GO-Super layout confirmed on R36S:
        # BTN_TRIGGER_HAPPY1..5 (0x2c0..0x2c4) are Select, Start, L3, R3, Menu.
        keys = {0x131: 'A', 0x130: 'B', 0x133: 'X', 0x134: 'Y',
                0x136: 'TL', 0x137: 'TR',
                0x220: 'UP', 0x221: 'DOWN', 0x222: 'LEFT', 0x223: 'RIGHT',
                0x2c0: 'SELECT', 0x2c1: 'START', 0x2c2: 'THUMBL',
                0x2c3: 'THUMBR', 0x2c4: 'MODE'}
        triggers = {0x138: ABS_Z, 0x139: ABS_RZ}
        layout = 'standard'
    else:
        # Standard Linux gamepad / retrogame_joypad (RG353V and clones):
        # 0x13a=BTN_SELECT, 0x13b=BTN_START, 0x13d=BTN_THUMBL, 0x13e=BTN_THUMBR, 0x13c=BTN_MODE.
        # D-Pad uses 0x220..0x223 (BTN_DPAD_*) or fallback.
        # Action buttons: 0x130=BTN_SOUTH (B on Nintendo layout, A on Xbox), 0x131=BTN_EAST (A on Nintendo, B on Xbox).
        keys = {0x131: 'A', 0x130: 'B', 0x133: 'X', 0x134: 'Y',
                0x136: 'TL', 0x137: 'TR',
                0x220: 'UP', 0x221: 'DOWN', 0x222: 'LEFT', 0x223: 'RIGHT',
                0x13a: 'SELECT', 0x13b: 'START', 0x13d: 'THUMBL',
                0x13e: 'THUMBR', 0x13c: 'MODE'}
        triggers = {0x138: ABS_Z, 0x139: ABS_RZ}
        layout = 'retrogame'
    return keys, triggers, layout


def axis_info(fd, code):
    return struct.unpack('<6i', fcntl.ioctl(fd, eviocgabs(code), bytes(24)))


def scale(code, value, lo, hi):
    if hi <= lo:
        raise ValueError('invalid range')
    t = max(0.0, min(1.0, (value - lo) / float(hi - lo)))
    if code in (ABS_Z, ABS_RZ):
        return round(t * 255)
    out = round(-32768 + t * 65535)
    return 0 if abs(out) < STICK_DEADZONE else out


def device_descriptor():
    # struct uinput_user_dev: name, input_id (4*u16), ff_effects_max,
    # absmax[64], absmin[64], absfuzz[64], absflat[64].
    arrays = [[0] * 64 for _ in range(4)]
    for axis, (lo, hi, fuzz, flat) in AXES.items():
        for array, value in zip(arrays, (hi, lo, fuzz, flat)):
            array[axis] = value
    header = struct.pack('<80sHHHHI', VXBOX_NAME, BUS_USB,
                         VXBOX_VENDOR, VXBOX_PRODUCT, VXBOX_VERSION, 0)
    return header + b''.join(struct.pack('<64i', *array) for array in arrays)


def write_exact(fd, data):
    if os.write(fd, data) != len(data):
        raise OSError('short uinput write')


def create_virtual_xbox():
    fd = os.open('/dev/uinput', os.O_WRONLY | os.O_NONBLOCK)
    try:
        for kind in (EV_KEY, EV_SYN, EV_ABS):
            fcntl.ioctl(fd, UI_SET_EVBIT, kind)
        for code in sorted(XBOX_KEYS.values()):
            fcntl.ioctl(fd, UI_SET_KEYBIT, code)
        for code in AXES:
            fcntl.ioctl(fd, UI_SET_ABSBIT, code)
        write_exact(fd, device_descriptor())
        fcntl.ioctl(fd, UI_DEV_CREATE)
        return fd
    except BaseException:
        os.close(fd)
        raise


class ButtonObserver:
    """Test-only physical key cycles, independent of the Xbox mapping.

    The Win32 wizard selects a step. Codes are visible only in its private
    transient report/window; safe logs retain named enum results, never codes.
    Unknown keys are observed but NEVER rebound automatically.
    """
    def __init__(self, directory, held=()):
        self.directory = Path(directory)
        self.step = None
        self.held, self.ignored = set(held), set()
        self.rows = [[0, 0] for _ in range(17)]
        self.candidates = set()
        self.failed = False
        self.pending = False

    def refresh(self):
        if self.failed:
            return
        try:
            request = self.directory / 'pd2-button-step.txt'
            for parent in (self.directory, *self.directory.parents):
                info = parent.lstat()
                if (not stat.S_ISDIR(info.st_mode) or
                        getattr(info, 'st_file_attributes', 0) & 0x400):
                    return
            info = request.lstat()
            if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > 32 or
                    getattr(info, 'st_file_attributes', 0) & 0x400):
                return
            flags = (os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) |
                     getattr(os, 'O_NONBLOCK', 0) | getattr(os, 'O_BINARY', 0))
            fd = os.open(request, flags)
            try:
                actual = os.fstat(fd)
                if (not stat.S_ISREG(actual.st_mode) or actual.st_nlink != 1 or
                        (actual.st_dev, actual.st_ino) != (info.st_dev, info.st_ino)):
                    return
                raw = os.read(fd, 33)
            finally:
                os.close(fd)
            if raw not in tuple(str(i).encode() + b'\n' for i in range(-1, 17)):
                return
            step = int(raw)
            step = step if step >= 0 else None
            changed = step != self.step
            if changed:
                self.step = step
                self.ignored = self.held.copy()
                self.candidates.clear()
            if changed or self.pending:
                self._publish()
        except FileNotFoundError:
            return
        except (OSError, ValueError):
            # Diagnostic failure must not stop the working game controller.
            self.failed = True

    def _publish(self):
        try:
            self.publish()
            self.pending = False
        except OSError:
            # A brief sharing denial must not lose the entire diagnostic session.
            # Retry at the next bounded refresh, never block the input translator.
            self.pending = True

    def publish(self):
        report = self.directory / 'pd2-button-physical.txt'
        payload = 'PD2BUTTON1\n' + ''.join(
            f'{i} {stage} {code}\n' for i, (stage, code) in enumerate(self.rows))
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', encoding='ascii', newline='\n',
                                             prefix='.pd2-buttons-', dir=self.directory,
                                             delete=False) as output:
                temporary = Path(output.name)
                output.write(payload)
            os.replace(temporary, report)
            temporary = None
        finally:
            if temporary is not None:
                # Only this exact file created above, never a caller-supplied path.
                # Python 3.7 on ArkOS has no unlink(missing_ok=...).
                try:
                    temporary.unlink()
                except FileNotFoundError:
                    pass

    def process(self, kind, code, value):
        if kind != EV_KEY or value not in (0, 1) or not 0 <= code <= KEY_MAX:
            return
        was_held = code in self.held
        if value:
            self.held.add(code)
        else:
            self.held.discard(code)
        if self.failed or self.step is None:
            return
        if code in self.ignored:
            if not value:
                self.ignored.discard(code)
            return
        row = self.rows[self.step]
        previous = row.copy()
        if value and not was_held:
            self.candidates.add(code)
            if len(self.candidates) > 1:
                row[0] = 3  # More than one key: retry, do not infer a binding.
            elif row[0] == 0:
                row[:] = [1, code]
        elif not value and was_held and code in self.candidates and row[0] == 1:
            row[0] = 2
        if row != previous:
            self._publish()

    def resync(self, keys):
        self.held = {code for code in range(KEY_MAX + 1) if keys & (1 << code)}
        self.ignored = self.held.copy()
        if not self.failed and self.step is not None:
            self.rows[self.step][0] = 3  # Lost events cannot certify a key cycle.
            self._publish()


class Translator:
    """Translate events without retaining or logging raw physical input."""
    def __init__(self, keys, triggers, ranges, emit):
        self.keys, self.triggers, self.ranges, self.emit = keys, triggers, ranges, emit
        self.hat = dict(UP=False, DOWN=False, LEFT=False, RIGHT=False)

    def process(self, kind, code, value):
        if kind == EV_ABS and code in self.ranges:
            self.emit(EV_ABS, code, scale(code, value, *self.ranges[code]))
        elif kind == EV_KEY and value in (0, 1):
            if code in self.triggers:
                self.emit(EV_ABS, self.triggers[code], 255 if value else 0)
            elif code in self.keys:
                target = self.keys[code]
                if target in self.hat:
                    self.hat[target] = bool(value)
                    self.emit(EV_ABS, ABS_HAT0X, int(self.hat['RIGHT']) - int(self.hat['LEFT']))
                    self.emit(EV_ABS, ABS_HAT0Y, int(self.hat['DOWN']) - int(self.hat['UP']))
                else:
                    self.emit(EV_KEY, XBOX_KEYS[target], value)
        elif kind == EV_SYN and code == SYN_REPORT:
            self.emit(EV_SYN, SYN_REPORT, 0)


def snapshot(fd, translator):
    keys = int.from_bytes(fcntl.ioctl(fd, evread(0x18, 96), bytes(96)), 'little')
    for code in translator.keys.keys() | translator.triggers.keys():
        translator.process(EV_KEY, code, int(bool(keys & (1 << code))))
    for code in translator.ranges:
        translator.process(EV_ABS, code, axis_info(fd, code)[0])
    translator.process(EV_SYN, SYN_REPORT, 0)
    return keys


def main():
    pfd = ufd = None
    stop = False

    def on_signal(_signum, _frame):
        nonlocal stop
        stop = True

    signal.signal(signal.SIGTERM, on_signal)
    signal.signal(signal.SIGINT, on_signal)
    try:
        pad = choose_pad(physical_devices())
        if pad is None:
            probe_event('missing')
            return 1
        pfd = os.open(pad[0], os.O_RDONLY | os.O_NONBLOCK)
        keys, triggers, layout = build_keymap(pad[4], pad[5])
        ranges = {}
        for code in (ABS_X, ABS_Y, ABS_RX, ABS_RY):
            _v, lo, hi, _fuzz, _flat, _resolution = axis_info(pfd, code)
            if hi <= lo:
                raise ValueError('invalid range')
            ranges[code] = (lo, hi)
        ufd = create_virtual_xbox()

        def emit(kind, code, value):
            write_exact(ufd, EVENT.pack(0, 0, kind, code, value))

        translator = Translator(keys, triggers, ranges, emit)
        initial_keys = snapshot(pfd, translator)
        observer = None
        if os.environ.get('PD2_CONTROLLER_TEST') == '1' and os.environ.get('PD2_WORK'):
            observer = ButtonObserver(Path(os.environ['PD2_WORK']) / 'ProjectD2',
                                      (code for code in range(KEY_MAX + 1)
                                       if initial_keys & (1 << code)))
        probe_event('ready')
        probe_event(layout, 'mapper_layout')
        dropped = False
        held_physical = {c for c in range(KEY_MAX + 1) if initial_keys & (1 << c)}
        while not stop:
            if observer is not None:
                observer.refresh()
            ready, _, _ = select.select([pfd], [], [], 0.05 if observer is not None else 0.5)
            if not ready:
                continue
            try:
                data = os.read(pfd, EV_SIZE * 128)
            except BlockingIOError:
                continue
            if not data or len(data) % EV_SIZE:
                raise OSError('physical stream ended')
            if observer is not None:
                observer.refresh()
            for _sec, _usec, kind, code, value in EVENT.iter_unpack(data):
                if kind == EV_SYN and code == SYN_DROPPED:
                    dropped = True
                elif dropped:
                    if kind == EV_SYN and code == SYN_REPORT:
                        current_keys = snapshot(pfd, translator)
                        if observer is not None:
                            observer.resync(current_keys)
                        dropped = False
                else:
                    if observer is not None:
                        observer.process(kind, code, value)
                    else:
                        if kind == EV_KEY:
                            if value == 1:
                                held_physical.add(code)
                            elif value == 0:
                                held_physical.discard(code)
                        is_osk_trigger = False
                        if kind == EV_KEY and value == 1:
                            # Select+X (0x2c0+0x133 or 0x13a+0x133) or Fn+X (0x2c4+0x133 or 0x13c+0x133)
                            is_select_down = (0x2c0 in held_physical or 0x13a in held_physical or
                                              0x2c4 in held_physical or 0x13c in held_physical)
                            if (code == 0x133 and is_select_down) or \
                               (code in (0x2c0, 0x13a, 0x2c4, 0x13c) and 0x133 in held_physical):
                                is_osk_trigger = True
                            # L3+R3 (0x2c2+0x2c3 or 0x13d+0x13e)
                            elif (code in (0x2c3, 0x13e) and (0x2c2 in held_physical or 0x13d in held_physical)) or \
                                 (code in (0x2c2, 0x13d) and (0x2c3 in held_physical or 0x13e in held_physical)):
                                is_osk_trigger = True
                            # Select+D-Pad Down (0x2c0+0x221 or 0x13a+0x221)
                            elif (code == 0x221 and is_select_down) or \
                                 (code in (0x2c0, 0x13a) and 0x221 in held_physical):
                                is_osk_trigger = True
                        if is_osk_trigger:
                            for xcode in XBOX_KEYS.values():
                                emit(EV_KEY, xcode, 0)
                            emit(EV_SYN, SYN_REPORT, 0)
                            try:
                                import osk
                                osk.show_osk(pfd=pfd)
                            except Exception:
                                pass
                            current_keys = snapshot(pfd, translator)
                            held_physical = {c for c in range(KEY_MAX + 1) if current_keys & (1 << c)}
                            continue
                    translator.process(kind, code, value)
        return 0
    except PermissionError:
        probe_event('denied')
        return 2
    except (OSError, ValueError):
        probe_event('invalid')
        return 4
    finally:
        if ufd is not None:
            try:
                fcntl.ioctl(ufd, UI_DEV_DESTROY)
            except OSError:
                pass
            os.close(ufd)
        if pfd is not None:
            os.close(pfd)


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception:
        # Unexpected failures must not leak tracebacks/paths through the log pipe.
        probe_event('invalid')
        sys.exit(4)
