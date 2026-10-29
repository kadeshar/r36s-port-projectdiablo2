#!/usr/bin/env python3
"""Session-only menu on the same authenticated X11 session as the game.

stdout is a fixed three-token protocol (resolution fps loot_filter), not shell code.
Exit 10 means cancel. No settings writes, game files, input logs, sudo,
downloads or persistent writes; the launcher persists the confirmed choice.
The normal launcher prepares PortMaster, Weston and X11 before this runs.
FPS ON selects an automatic render-FPS HUD from the first game frames.
"""
import os
import select
import struct
import sys
import time

RESOLUTIONS = ('default', '640x480', '800x600', '1024x768', 'native')
LABELS = ('640x480', '640x480', '800x600', '1024x768', '1068x600')
OVERLAY_LEVELS = ('OFF', 'LEVEL 1', 'LEVEL 2', 'LEVEL 3', 'LEVEL 4')
CANCEL = 10
LOOT_FILTER_DEFAULT = 'default'
EVENT = struct.Struct('@llHHi')  # Linux input_event: native timeval (aarch64/ARM32).
PAD_ACTIONS = {0x220: 'up', 0x221: 'down', 0x222: 'left', 0x223: 'right',
               103: 'up', 108: 'down', 105: 'left', 106: 'right',
               0x131: 'accept', 0x130: 'cancel',
               0x13b: 'accept', 0x13a: 'cancel',
               0x2c1: 'accept', 0x2c0: 'cancel', 0x2c4: 'cancel',
               28: 'accept', 57: 'accept', 1: 'cancel'}


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
    def __init__(self):
        # Untouched fields inherit the already resolved main-launcher settings.
        self.row = 2
        self.resolution = 0
        self.fps = 0
        self.fps_changed = False
        # Display resolved launcher values without changing the inheritance
        # protocol. Standalone/default sessions use 640x480 and FPS off.
        inherited_resolution = os.environ.get('PD2_GAME_RESOLUTION', '640x480')
        self.inherited_resolution = (inherited_resolution if inherited_resolution in
                                     ('640x480', '800x600', '1024x768', 'native') else '640x480')
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
        self.result = None

    @property
    def filter_label(self):
        """Bitmap-font label: uppercase only, truncated to fit one text row."""
        if self.filter_index == 0:
            return 'DEFAULT'
        return self.filters[self.filter_index - 1].upper()[:16]

    def action(self, action):
        if self.result is not None:
            return
        if action == 'cancel':
            self.result = 'cancel'
        elif action in ('up', 'down'):
            self.row = (self.row + (-1 if action == 'up' else 1)) % 5
        elif action in ('left', 'right', 'accept'):
            if self.row == 0:
                self.resolution = (self.resolution + (-1 if action == 'left' else 1)) % len(RESOLUTIONS)
            elif self.row == 1:
                current = self.fps if self.fps_changed else self.inherited_fps_level
                if isinstance(current, bool):
                    current = 1 if current else 0
                if action == 'left':
                    self.fps = (current - 1) % len(OVERLAY_LEVELS)
                elif action == 'right':
                    self.fps = (current + 1) % len(OVERLAY_LEVELS)
                else:  # accept: toggle between off and on/level1
                    self.fps = 0 if current > 0 else 1
                self.fps_changed = True
            elif self.row == 2:
                count = len(self.filters) + 1
                self.filter_index = (self.filter_index + (-1 if action == 'left' else 1)) % count
            elif action == 'accept':
                self.result = 'launch' if self.row == 3 else 'cancel'

    def selection(self):
        if self.result != 'launch':
            raise ValueError('not confirmed')
        filter_name = (LOOT_FILTER_DEFAULT if self.filter_index == 0
                       else self.filters[self.filter_index - 1])
        return (RESOLUTIONS[self.resolution],
                str(int(self.fps)) if self.fps_changed else 'default',
                filter_name)

    def float_active(self):
        """A long filter name is held on the filter row: its full name
        animates (marquee) in the row and the menu must repaint on a timer."""
        if self.row != 2 or self.filter_index == 0:
            return False
        return len(self.filters[self.filter_index - 1]) > 16


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

    def feed(self, data):
        self.buffer += data
        actions = []
        while len(self.buffer) >= EVENT.size:
            _, _, kind, code, value = EVENT.unpack(self.buffer[:EVENT.size])
            self.buffer = self.buffer[EVENT.size:]
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
        return actions


class Pad:
    def __init__(self):
        self.fds = []
        self.fd = None
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
        except Exception:
            pass

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
            return []
        all_actions = []
        for fd in readable:
            data = os.read(fd, EVENT.size * 64)
            if not data:
                raise OSError('controller disconnected')
            all_actions.extend(self.decoder.feed(data))
        return all_actions

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
        # Handle all input from this frame before repainting, but never accept
        # a second action once launch/cancel has already been confirmed.
        before = (menu.row, menu.resolution, menu.fps, menu.fps_changed, menu.filter_index)
        for action in pad.actions() + screen.actions():
            menu.action(action)
        if menu.result is None:
            # Static menus need no periodic repaint. Expose recovery is handled
            # by screen.actions(); coalesce input into at most one new frame.
            after = (menu.row, menu.resolution, menu.fps, menu.fps_changed, menu.filter_index)
            if after != before:
                screen.draw(menu)
            elif menu.float_active():
                # A long filter name is held on the filter row: repaint on the
                # loop timer so its full name keeps scrolling in the row even
                # with no further input.
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
