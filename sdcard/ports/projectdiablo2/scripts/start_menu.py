#!/usr/bin/env python3
"""Session-only menu on the same authenticated X11 session as the game.

stdout is a fixed two-token protocol (resolution fps), not shell code. Exit 10 means cancel.
No settings, game files, input logs, sudo, downloads or persistent writes.
The normal launcher prepares PortMaster, Weston and X11 before this runs.
FPS ON selects an automatic render-FPS HUD from the first game frames.
"""
import os
import select
import struct
import sys
import time

RESOLUTIONS = ('default', '640x480', '800x600', '1024x768', 'native')
LABELS = ('LCD 640X480', 'LCD 640X480', '800X600', '1024X768', 'PD2 1068X600')
CANCEL = 10
EVENT = struct.Struct('@llHHi')  # Linux input_event: native timeval (aarch64/ARM32).
PAD_ACTIONS = {0x220: 'up', 0x221: 'down', 0x222: 'left', 0x223: 'right',
               0x131: 'accept', 0x130: 'cancel', 0x2c1: 'accept',
               0x2c0: 'cancel', 0x2c4: 'cancel'}



class Menu:
    def __init__(self):
        # Untouched fields inherit the already resolved main-launcher settings.
        self.row = 2
        self.resolution = 0
        self.fps = False
        self.fps_changed = False
        # Display resolved launcher values without changing the inheritance
        # protocol. Standalone/default sessions use 640x480 and FPS off.
        inherited_resolution = os.environ.get('PD2_GAME_RESOLUTION', '640x480')
        self.inherited_resolution = (inherited_resolution if inherited_resolution in
                                     ('640x480', '800x600', '1024x768', 'native') else '640x480')
        self.inherited_fps = os.environ.get('PD2_FPS', '0') == '1'
        self.result = None

    def action(self, action):
        if self.result is not None:
            return
        if action == 'cancel':
            self.result = 'cancel'
        elif action in ('up', 'down'):
            self.row = (self.row + (-1 if action == 'up' else 1)) % 4
        elif action in ('left', 'right', 'accept'):
            if self.row == 0:
                self.resolution = (self.resolution + (-1 if action == 'left' else 1)) % len(RESOLUTIONS)
            elif self.row == 1:
                self.fps = not (self.fps if self.fps_changed else self.inherited_fps)
                self.fps_changed = True
            elif action == 'accept':
                self.result = 'launch' if self.row == 2 else 'cancel'

    def selection(self):
        if self.result != 'launch':
            raise ValueError('not confirmed')
        return (RESOLUTIONS[self.resolution],
                str(int(self.fps)) if self.fps_changed else 'default')


class KeyDecoder:
    """Ignore keys held on entry, release events and kernel autorepeat."""
    def __init__(self, mapping, held=()):
        self.mapping = mapping
        self.held = set(held)
        self.buffer = b''

    def feed(self, data):
        self.buffer += data
        actions = []
        while len(self.buffer) >= EVENT.size:
            _, _, kind, code, value = EVENT.unpack(self.buffer[:EVENT.size])
            self.buffer = self.buffer[EVENT.size:]
            if kind == 0 and code == 3:  # SYN_DROPPED: do not trust stale state.
                raise OSError('input synchronization lost')
            if kind != 1:
                continue
            if value == 0:
                self.held.discard(code)
            elif value == 1 and code not in self.held:
                self.held.add(code)
                if code in self.mapping:
                    actions.append(self.mapping[code])
        return actions


class Pad:
    def __init__(self):
        self.fd = None
        # Reuse the already verified physical R36S identity/layout, not a
        # virtual Xbox or an arbitrary device. Import is lazy for host tests.
        import fcntl
        import xbox_mapper as mapper
        device = mapper.choose_pad(mapper.physical_devices())
        if device is None:
            return  # X11 keyboard remains usable.
        fd = os.open(device[0], os.O_RDONLY | os.O_NONBLOCK | getattr(os, 'O_NOFOLLOW', 0))
        try:
            mask = fcntl.ioctl(fd, mapper.evread(0x18, 96), bytes(96))
            held = [code for code in PAD_ACTIONS if mask[code // 8] & (1 << (code % 8))]
            self.decoder = KeyDecoder(PAD_ACTIONS, held)
            self.fd = fd
        except BaseException:
            os.close(fd)
            raise

    def actions(self):
        if self.fd is None or not select.select([self.fd], [], [], 0)[0]:
            return []
        data = os.read(self.fd, EVENT.size * 64)
        if not data:
            raise OSError('controller disconnected')
        return self.decoder.feed(data)

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
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


class Screen:
    """Direct core-X11 client: no SDL video backend or native GUI library."""
    def __new__(cls):
        from menu_x11 import Screen as X11Screen
        return X11Screen(FONT, LABELS)


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
        before = (menu.row, menu.resolution, menu.fps, menu.fps_changed)
        for action in pad.actions() + screen.actions():
            menu.action(action)
        if menu.result is None:
            # Static menus need no periodic repaint. Expose recovery is handled
            # by screen.actions(); coalesce input into at most one new frame.
            after = (menu.row, menu.resolution, menu.fps, menu.fps_changed)
            if after != before:
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
