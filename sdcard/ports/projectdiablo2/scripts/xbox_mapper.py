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
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

EV_SYN, EV_KEY, EV_ABS = 0, 1, 3
SYN_REPORT, SYN_DROPPED = 0, 3
ABS_X, ABS_Y, ABS_Z, ABS_RX, ABS_RY, ABS_RZ = range(6)
ABS_BRAKE = 10
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
    ABS_BRAKE: (0, 255, 0, 0),
    ABS_HAT0X: (-1, 1, 0, 0), ABS_HAT0Y: (-1, 1, 0, 0),
}
STICK_DEADZONE = 8000
# Native long layout: 24 bytes on aarch64, 16 on ARM32.
EVENT = struct.Struct('@llHHi')
EV_SIZE = EVENT.size
UI_SET_EVBIT, UI_SET_KEYBIT, UI_SET_ABSBIT = 0x40045564, 0x40045565, 0x40045567
UI_DEV_CREATE, UI_DEV_DESTROY = 0x5501, 0x5502
AXIS_DEADBAND = 256


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


PORTMASTER_PAD_IDS = {
    (0x484b, 0x1100),  # R36S / OGS / Powkiddy RGB10 MAX
    (0x484b, 0x1101),  # RG353V / RG353P / RG353M / RK3566
    (0x484b, 0x1000),  # Odroid Go Advance / RK2020
    (0x484b, 0x1111),  # Anbernic RG552
    (0x0912, 0x0031),  # Anbernic RG351P / RG351M / RG351V / RG351MP
    (0x0003, 0x0003),  # Gameforce Chi
    (0x8d96, 0x0221),  # GameKiddy Pixel
    (0x0001, 0x0001),  # Anbernic RG35XX H / Plus / SP (Deeplay-keys)
    (0x045e, 0x028e),  # Xbox 360 / XInput Controller
}

PORTMASTER_PAD_NAMES = (
    'retrogame_joypad',
    'anbernic', 'odroidgo', 'gameforce', 'rk2020', 'trimui',
    'rg351', 'rg353', 'rg552', 'rg35xx', 'deeplay', 'gkd', '8bitdo', 'playstation'
)

PORTMASTER_BY_PATH = (
    '/dev/input/by-path/platform-odroidgo3-joypad-event-joystick',
    '/dev/input/by-path/platform-odroidgo2-joypad-event-joystick',
    '/dev/input/by-path/platform-ff300000.usb-usb-0:1.2:1.0-event-joystick',
    '/dev/input/by-path/platform-gameforce-gamepad-event-joystick',
    '/dev/input/by-path/platform-singleadc-joypad-event-joystick',
    '/dev/input/by-path/platform-gamekiddy-joypad-event-joystick',
)


def es_input_devices():
    """Discover configured joystick names and (vid, pid) from EmulationStation."""
    names = set()
    ids = set()
    paths = (
        Path.home() / '.config' / 'emulationstation' / 'es_input.cfg',
        Path('/etc/emulationstation/es_input.cfg'),
        Path('/userdata/system/configs/emulationstation/es_input.cfg'),
        Path('/storage/.config/emulationstation/es_input.cfg'),
        Path('/opt/muos/config/es_input.cfg'),
    )
    for p in paths:
        try:
            if not p.is_file():
                continue
            tree = ET.parse(p)
            for entry in tree.getroot():
                if entry.tag == 'inputConfig' and entry.attrib.get('type') in ('joystick', 'pad'):
                    dev_name = entry.attrib.get('deviceName')
                    if dev_name:
                        names.add(dev_name.strip().lower())
                    guid = entry.attrib.get('deviceGUID', '')
                    if len(guid) >= 20:
                        try:
                            raw = bytes.fromhex(guid[:20])
                            _, _, vid, _, pid = struct.unpack_from('<HHHHH', raw)
                            ids.add((vid, pid))
                        except Exception:
                            pass
        except Exception:
            pass
    return names, ids


def choose_pad(devices, mode=None):
    if mode is None:
        mode = os.environ.get('PD2_CONTROLLER_MODE')
        if not mode:
            try:
                port = os.environ.get('PD2_PORT')
                cfg_path = (Path(port) if port else Path(__file__).resolve().parents[1]) / 'config/controller.json'
                if cfg_path.is_file():
                    with open(cfg_path, 'r', encoding='utf-8') as f:
                        mode = json.load(f).get('mode', 'auto')
            except Exception:
                mode = 'auto'

    # 0. In manual mode, match saved custom device vid/pid if available
    if mode == 'manual':
        try:
            port = os.environ.get('PD2_PORT')
            custom_path = (Path(port) if port else Path(__file__).resolve().parents[1]) / 'config/custom_pad.json'
            if custom_path.is_file():
                with open(custom_path, 'r', encoding='utf-8') as f:
                    cdata = json.load(f)
                cvid = cdata.get('vid')
                cpid = cdata.get('pid')
                if cvid and cpid:
                    match = next((d for d in devices if (d[2], d[3]) == (cvid, cpid)), None)
                    if match is not None:
                        return match
        except Exception:
            pass

    # 1. PortMaster by-path matches
    for bp in PORTMASTER_BY_PATH:
        if os.path.exists(bp):
            try:
                resolved = os.path.realpath(bp)
                for dev in devices:
                    if dev[0] == resolved and bits_set(dev[4], 0x130, 0x131, 0x133, 0x134) and bits_set(dev[5], ABS_X, ABS_Y, ABS_RX, ABS_RY):
                        return dev
            except OSError:
                pass

    # 2. Primary match: R36S / GO-Super Gamepad (0x484b, 0x1100).
    r36s = next((d for d in devices if (d[2], d[3]) == (0x484b, 0x1100)
                 and bits_set(d[4], 0x130, 0x131, 0x133, 0x134)
                 and bits_set(d[5], ABS_X, ABS_Y, ABS_RX, ABS_RY)), None)
    if r36s is not None:
        return r36s
    # 3. RG353V / retrogame_joypad (0x484b, 0x1101):
    rg353 = next((d for d in devices if (d[2], d[3]) == (0x484b, 0x1101)
                  and bits_set(d[4], 0x130, 0x131, 0x133, 0x134)
                  and bits_set(d[5], ABS_X, ABS_Y, ABS_RX, ABS_RY)), None)
    if rg353 is not None:
        return rg353
    # 4. Recognized PortMaster pad IDs with dual sticks
    for dev in devices:
        if (dev[2], dev[3]) in PORTMASTER_PAD_IDS and (
            (bits_set(dev[4], 0x130, 0x131, 0x133, 0x134) or bits_set(dev[4], 0x130, 0x131, 0x132, 0x133)) and
            (bits_set(dev[5], ABS_X, ABS_Y, ABS_RX, ABS_RY) or bits_set(dev[5], ABS_X, ABS_Y, ABS_Z, ABS_RZ) or bits_set(dev[5], ABS_Z, ABS_RZ, ABS_RX, ABS_RY))
        ):
            return dev
    # 5. Named built-in handheld controller match (retrogame_joypad / PortMaster names):
    for dev in devices:
        name_lower = dev[1].lower()
        if (dev[1] == 'retrogame_joypad' or any(k in name_lower for k in PORTMASTER_PAD_NAMES)) and (
            (bits_set(dev[4], 0x130, 0x131, 0x133, 0x134) or bits_set(dev[4], 0x130, 0x131, 0x132, 0x133)) and
            (bits_set(dev[5], ABS_X, ABS_Y, ABS_RX, ABS_RY) or bits_set(dev[5], ABS_X, ABS_Y, ABS_Z, ABS_RZ) or bits_set(dev[5], ABS_Z, ABS_RZ, ABS_RX, ABS_RY))
        ):
            return dev
    # 6. EmulationStation configured joystick match (covers any CFW handheld configured in ES):
    es_names, es_ids = es_input_devices()
    if es_names or es_ids:
        for dev in devices:
            name_lower = dev[1].lower()
            if ((dev[2], dev[3]) in es_ids or name_lower in es_names) and (
                (bits_set(dev[4], 0x130, 0x131, 0x133, 0x134) or bits_set(dev[4], 0x130, 0x131, 0x132, 0x133)) and
                (bits_set(dev[5], ABS_X, ABS_Y, ABS_RX, ABS_RY) or bits_set(dev[5], ABS_X, ABS_Y, ABS_Z, ABS_RZ) or bits_set(dev[5], ABS_Z, ABS_RZ, ABS_RX, ABS_RY))
            ):
                return dev
    # 7. Generic USB or external controller fallback (active in manual mode):
    if mode == 'manual':
        for dev in devices:
            has_btn = bool(dev[4] & ((1 << 0x130) | (1 << 0x131) | (1 << 0x120) | (1 << 0x121) | (1 << 288) | (1 << 289)))
            has_axis = bool(dev[5] & ((1 << ABS_X) | (1 << ABS_Y)))
            if has_btn and has_axis:
                return dev
    return None


LAST_CUSTOM_AXIS_MAP = None
LAST_CUSTOM_HAS_HAT_AXES = False


def load_custom_config(path):
    """Load user calibrated layout from custom_pad.json."""
    global LAST_CUSTOM_AXIS_MAP, LAST_CUSTOM_HAS_HAT_AXES
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        keys = {int(k): v for k, v in data.get('keys', {}).items()}
        triggers = {}
        for k, v in data.get('triggers', {}).items():
            if isinstance(v, list):
                triggers[int(k)] = tuple(v)
            else:
                triggers[int(k)] = int(v)
        axis_map = {int(k): int(v) for k, v in data.get('axis_map', {}).items()}
        if not axis_map:
            axis_map = {ABS_X: ABS_X, ABS_Y: ABS_Y, ABS_RX: ABS_RX, ABS_RY: ABS_RY}
        LAST_CUSTOM_AXIS_MAP = axis_map
        LAST_CUSTOM_HAS_HAT_AXES = bool(data.get('has_hat_axes', False))
        if keys:
            return keys, triggers, 'manual'
    except Exception:
        pass
    return None


def build_keymap(keybits, absbits, name='', vid=0, pid=0, mode=None, custom_path=None):
    if mode is None:
        mode = os.environ.get('PD2_CONTROLLER_MODE')
        if not mode:
            try:
                port = os.environ.get('PD2_PORT')
                cfg_path = (Path(port) if port else Path(__file__).resolve().parents[1]) / 'config/controller.json'
                if cfg_path.is_file():
                    with open(cfg_path, 'r', encoding='utf-8') as f:
                        mode = json.load(f).get('mode', 'auto')
            except Exception:
                mode = 'auto'

    if mode == 'manual':
        if custom_path is None:
            port = os.environ.get('PD2_PORT')
            custom_path = (Path(port) if port else Path(__file__).resolve().parents[1]) / 'config/custom_pad.json'
        custom = load_custom_config(custom_path)
        if custom is not None:
            return custom

    if mode == 'r36s':
        keys = {0x131: 'A', 0x130: 'B', 0x133: 'X', 0x134: 'Y',
                0x136: 'TL', 0x137: 'TR',
                0x220: 'UP', 0x221: 'DOWN', 0x222: 'LEFT', 0x223: 'RIGHT',
                0x2c0: 'SELECT', 0x2c1: 'START', 0x2c2: 'THUMBL',
                0x2c3: 'THUMBR', 0x2c4: 'MODE'}
        triggers = {0x138: ABS_Z, 0x139: ABS_RZ}
        return keys, triggers, 'standard'

    if mode == 'retrogame':
        keys = {0x131: 'A', 0x130: 'B', 0x133: 'X', 0x134: 'Y',
                0x136: 'TL', 0x137: 'TR',
                0x220: 'UP', 0x221: 'DOWN', 0x222: 'LEFT', 0x223: 'RIGHT',
                0x13a: 'SELECT', 0x13b: 'START', 0x13d: 'THUMBL',
                0x13e: 'THUMBR', 0x13c: 'MODE'}
        triggers = {0x138: ABS_Z, 0x139: ABS_RZ}
        return keys, triggers, 'retrogame'

    if mode == 'rg35xxh':
        keys = {
            0x130: 'A', 0x131: 'B', 0x133: 'X', 0x132: 'Y',
            0x134: 'TL', 0x135: 'TR', 0x136: 'SELECT', 0x137: 'START',
            0x139: 'THUMBL', 0x13c: 'MODE', 0x162: 'MODE',
            0x220: 'UP', 0x221: 'DOWN', 0x222: 'LEFT', 0x223: 'RIGHT',
        }
        triggers = {0x13a: (ABS_Z, ABS_BRAKE), 0x13b: (ABS_RZ,)}
        return keys, triggers, 'rg35xxh'

    name_lower = name.lower()
    is_deeplay = (
        ('rg35xx' in name_lower or 'deeplay' in name_lower or (vid, pid) == (0x0001, 0x0001))
        or (bits_set(keybits, 0x136, 0x137) and bits_set(keybits, 0x134, 0x135) and not bits_set(keybits, 0x2c0, 0x2c1))
        or (bits_set(absbits, ABS_Z, ABS_RZ, ABS_RX, ABS_RY) and not bits_set(absbits, ABS_X, ABS_Y))
    )

    if is_deeplay:
        # RG35XX-H / Deeplay layout (Knulli / Batocera Allwinner H700)
        keys = {
            0x130: 'A',
            0x131: 'B',
            0x133: 'X',
            0x132: 'Y',
            0x134: 'TL',      # L1
            0x135: 'TR',      # R1
            0x136: 'SELECT',  # Select
            0x137: 'START',   # Start
            0x139: 'THUMBL',  # L3
            0x13c: 'MODE',    # R3 -> Map (Archix221 v2)
            0x162: 'MODE',    # FN / Menu
            0x220: 'UP',
            0x221: 'DOWN',
            0x222: 'LEFT',
            0x223: 'RIGHT',
        }
        triggers = {0x13a: (ABS_Z, ABS_BRAKE), 0x13b: (ABS_RZ,)}
        layout = 'rg35xxh'
        return keys, triggers, layout

    if not bits_set(keybits, 0x130, 0x131, 0x133, 0x134):
        raise ValueError('unsupported layout')
    if absbits & ((1 << ABS_Z) | (1 << ABS_RZ)):
        if bits_set(keybits, 0x138, 0x139) and bits_set(absbits, ABS_RX, ABS_RY):
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
    if code in (ABS_Z, ABS_RZ, ABS_BRAKE):
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
    try:
        if os.write(fd, data) != len(data):
            raise OSError('short uinput write')
    except (BlockingIOError, InterruptedError):
        pass


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
    def __init__(self, keys, triggers, ranges, emit, axis_map=None, has_hat_axes=False):
        self.keys, self.triggers, self.ranges, self.emit = keys, triggers, ranges, emit
        self.axis_map = axis_map
        self.has_hat_axes = has_hat_axes
        self.hat = dict(UP=False, DOWN=False, LEFT=False, RIGHT=False)
        self.last_axes = {}
        self.pending_sync = False

    def process(self, kind, code, value):
        if kind == EV_ABS and code in self.ranges:
            if self.axis_map is not None:
                target_axis = self.axis_map.get(code, code)
            else:
                target_axis = ABS_RX if (code == ABS_Z and code not in self.triggers) else (
                    ABS_RY if (code == ABS_RZ and code not in self.triggers) else code)
            if target_axis in AXES:
                scaled = scale(target_axis, value, *self.ranges[code])
                last = self.last_axes.get(target_axis)
                should_emit = False
                if last is None:
                    should_emit = True
                elif target_axis in (ABS_Z, ABS_RZ, ABS_BRAKE):
                    if scaled != last and (scaled in (0, 255) or abs(scaled - last) >= 4):
                        should_emit = True
                else:
                    if scaled != last:
                        if scaled == 0 or last == 0:
                            should_emit = True
                        elif abs(scaled - last) >= AXIS_DEADBAND or scaled in (-32768, 32767):
                            should_emit = True
                if should_emit:
                    self.last_axes[target_axis] = scaled
                    self.emit(EV_ABS, target_axis, scaled)
                    self.pending_sync = True
        elif self.has_hat_axes and kind == EV_ABS and code in (ABS_HAT0X, ABS_HAT0Y):
            clamped = -1 if value < 0 else (1 if value > 0 else 0)
            if self.last_axes.get(code) != clamped:
                self.last_axes[code] = clamped
                self.emit(EV_ABS, code, clamped)
                self.pending_sync = True
        elif kind == EV_KEY and value in (0, 1):
            if code in self.triggers:
                trig = self.triggers[code]
                if isinstance(trig, (tuple, list)):
                    for axis in trig:
                        self.emit(EV_ABS, axis, 255 if value else 0)
                else:
                    self.emit(EV_ABS, trig, 255 if value else 0)
                self.pending_sync = True
            elif code in self.keys:
                target = self.keys[code]
                if target in self.hat:
                    self.hat[target] = bool(value)
                    self.emit(EV_ABS, ABS_HAT0X, int(self.hat['RIGHT']) - int(self.hat['LEFT']))
                    self.emit(EV_ABS, ABS_HAT0Y, int(self.hat['DOWN']) - int(self.hat['UP']))
                    self.pending_sync = True
                elif target in XBOX_KEYS:
                    self.emit(EV_KEY, XBOX_KEYS[target], value)
                    self.pending_sync = True
        elif kind == EV_SYN and code == SYN_REPORT:
            if self.pending_sync:
                self.emit(EV_SYN, SYN_REPORT, 0)
                self.pending_sync = False


def snapshot(fd, translator):
    keys = int.from_bytes(fcntl.ioctl(fd, evread(0x18, 96), bytes(96)), 'little')
    for code in translator.keys.keys() | translator.triggers.keys():
        translator.process(EV_KEY, code, int(bool(keys & (1 << code))))
    for code in translator.ranges:
        translator.process(EV_ABS, code, axis_info(fd, code)[0])
    if translator.has_hat_axes:
        for code in (ABS_HAT0X, ABS_HAT0Y):
            try:
                translator.process(EV_ABS, code, axis_info(fd, code)[0])
            except Exception:
                pass
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
        keys, triggers, layout = build_keymap(pad[4], pad[5], name=pad[1], vid=pad[2], pid=pad[3])
        ranges = {}
        if layout == 'rg35xxh':
            axis_map = {ABS_Z: ABS_X, ABS_RX: ABS_Y, ABS_RY: ABS_RX, ABS_RZ: ABS_RY}
            stick_axes = (ABS_Z, ABS_RX, ABS_RY, ABS_RZ)
        elif layout == 'manual' and LAST_CUSTOM_AXIS_MAP:
            axis_map = LAST_CUSTOM_AXIS_MAP
            stick_axes = tuple(axis_map.keys())
        else:
            axis_map = None
            stick_axes = (ABS_X, ABS_Y, ABS_RX, ABS_RY) if bits_set(pad[5], ABS_RX, ABS_RY) else (ABS_X, ABS_Y, ABS_Z, ABS_RZ)
        ranges = {}
        for code in stick_axes:
            try:
                _v, lo, hi, _fuzz, _flat, _resolution = axis_info(pfd, code)
                if hi > lo:
                    ranges[code] = (lo, hi)
                else:
                    ranges[code] = (-1800, 1800)
            except Exception:
                ranges[code] = (-1800, 1800)
        ufd = create_virtual_xbox()

        def emit(kind, code, value):
            write_exact(ufd, EVENT.pack(0, 0, kind, code, value))

        has_hat_axes = bool(bits_set(pad[5], ABS_HAT0X, ABS_HAT0Y) or (layout == 'rg35xxh') or LAST_CUSTOM_HAS_HAT_AXES)
        translator = Translator(keys, triggers, ranges, emit, axis_map=axis_map, has_hat_axes=has_hat_axes)
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
                            if layout == 'manual':
                                SELECT_FN = {c for c, tgt in keys.items() if tgt in ('SELECT', 'MODE')}
                                X_BUTTONS = {c for c, tgt in keys.items() if tgt in ('X', 'Y')}
                                DOWN_BUTTONS = {c for c, tgt in keys.items() if tgt == 'DOWN'}
                                L3_R3 = ({c for c, tgt in keys.items() if tgt == 'THUMBL'},
                                         {c for c, tgt in keys.items() if tgt == 'THUMBR'})
                            elif layout == 'rg35xxh':
                                SELECT_FN = {0x136, 0x13c, 0x162}
                                X_BUTTONS = {0x133, 0x132}
                                DOWN_BUTTONS = {0x221}
                                L3_R3 = ({0x139}, {0x13c})
                            else:
                                SELECT_FN = {0x2c0, 0x13a, 0x2c4, 0x13c}
                                X_BUTTONS = {0x133, 0x134}
                                DOWN_BUTTONS = {0x221, 108}
                                L3_R3 = ({0x2c2, 0x13d}, {0x2c3, 0x13e})

                            is_select_down = bool(held_physical & SELECT_FN)
                            # Select + X or Select + Y
                            if code in X_BUTTONS and is_select_down:
                                is_osk_trigger = True
                            elif code in SELECT_FN and bool(held_physical & X_BUTTONS):
                                is_osk_trigger = True
                            # L3+R3
                            elif L3_R3[0] and L3_R3[1] and (
                                (code in L3_R3[1] and bool(held_physical & L3_R3[0])) or
                                (code in L3_R3[0] and bool(held_physical & L3_R3[1]))
                            ):
                                is_osk_trigger = True
                            # Select + D-Pad Down
                            elif code in DOWN_BUTTONS and is_select_down:
                                is_osk_trigger = True
                            if is_osk_trigger:
                                for xcode in XBOX_KEYS.values():
                                    emit(EV_KEY, xcode, 0)
                                emit(EV_SYN, SYN_REPORT, 0)
                                try:
                                    import osk
                                    osk.show_osk(pfd=pfd)
                                except Exception as err:
                                    sys.stderr.write(f'PD2 OSK error: {err}\n')
                                    sys.stderr.flush()
                                current_keys = snapshot(pfd, translator)
                                held_physical = {c for c in range(KEY_MAX + 1) if current_keys & (1 << c)}
                                continue
                    translator.process(kind, code, value)
        return 0
    except PermissionError:
        probe_event('denied')
        return 2
    except (OSError, ValueError) as exc:
        try:
            with open('/tmp/xbox_mapper_err.log', 'a') as f:
                f.write(f'OSError/ValueError: {exc}\n')
                traceback.print_exc(file=f)
        except Exception:
            pass
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
    except Exception as exc:
        try:
            with open('/tmp/xbox_mapper_err.log', 'a') as f:
                f.write(f'Fatal Exception: {exc}\n')
                traceback.print_exc(file=f)
        except Exception:
            pass
        probe_event('invalid')
        sys.exit(4)
