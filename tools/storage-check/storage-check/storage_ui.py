#!/usr/bin/env python3
"""Native, dependency-free SDL2 storage viewer for the 640x480 R36S.

Importing this module is safe without SDL or a display. Sizes in the JSON
snapshot are bytes. Physical A/B intentionally reverse SDL's A/B labels.
"""
import ctypes as C
import ctypes.util
import json
import os
import signal
import sys

WIDTH, HEIGHT = 640, 480
MAX_CHARS = 50  # 50 * 12 pixels, plus 20-pixel margins.
PARTITION_ROWS, COMPONENT_ROWS = 6, 5
BG = (14, 20, 29)
TEXT = (235, 240, 245)
DIM = (155, 172, 190)
HOME = (65, 245, 220)
WARN = (255, 195, 95)

# Five vertical columns per glyph, low bit at the top; seven rows, scale 2.
# Deliberately built in: SDL_ttf and system fonts are not required.
_GLYPH_DATA = {
    ' ': '0000000000', '!': '00005f0000', '"': '0007000700',
    '#': '147f147f14', '$': '242a7f2a12', '%': '2313086462',
    '&': '3649552250', "'": '0005030000', '(': '001c224100',
    ')': '0041221c00', '*': '14083e0814', '+': '08083e0808',
    ',': '0050300000', '-': '0808080808', '.': '0060600000',
    '/': '2010080402', ':': '0036360000', ';': '0056360000',
    '<': '0814224100', '=': '1414141414', '>': '0041221408',
    '?': '0201510906', '@': '324979413e', '[': '007f414100',
    '\\': '0204081020', ']': '0041417f00', '^': '0402010204',
    '_': '4040404040', '`': '0001020400', '{': '0008364100',
    '|': '00007f0000', '}': '0041360800', '~': '0804081008',
    '0': '3e5149453e', '1': '00427f4000', '2': '4261514946',
    '3': '2141454b31', '4': '1814127f10', '5': '2745454539',
    '6': '3c4a494930', '7': '0171090503', '8': '3649494936',
    '9': '064949291e', 'A': '7e1111117e', 'B': '7f49494936',
    'C': '3e41414122', 'D': '7f4141221c', 'E': '7f49494941',
    'F': '7f09090901', 'G': '3e4149497a', 'H': '7f0808087f',
    'I': '00417f4100', 'J': '2040413f01', 'K': '7f08142241',
    'L': '7f40404040', 'M': '7f020c027f', 'N': '7f0408107f',
    'O': '3e4141413e', 'P': '7f09090906', 'Q': '3e4151215e',
    'R': '7f09192946', 'S': '4649494931', 'T': '01017f0101',
    'U': '3f4040403f', 'V': '1f2040201f', 'W': '3f4038403f',
    'X': '6314081463', 'Y': '0708700807', 'Z': '6151494543',
}
FONT = {key: tuple(bytes.fromhex(value)) for key, value in _GLYPH_DATA.items()}


def ascii_text(value):
    """Uppercase printable ASCII; never let embedded controls alter layout."""
    return ''.join(ch if 32 <= ord(ch) <= 126 else '?'
                   for ch in str(value).upper())


def elide(value, width=MAX_CHARS, middle=False):
    """Bound a string, optionally preserving both ends of an install path."""
    width = max(0, min(MAX_CHARS, int(width)))
    text = ascii_text(value)
    if len(text) <= width:
        return text
    if width <= 3:
        return '.' * width
    if middle:
        left = (width - 3) // 2
        return text[:left] + '...' + text[-(width - 3 - left):]
    return text[:width - 3] + '...'


def format_size(size):
    """Format byte counts in binary units; None/invalid means unknown."""
    if not isinstance(size, int) or isinstance(size, bool) or size < 0:
        return '--'
    if size >= 1024 ** 3:
        return '{:.1f} GiB'.format(size / float(1024 ** 3))
    return '{:.1f} MiB'.format(size / float(1024 ** 2))


def action_for_button(button):
    """R36S physical A is SDL B(1); physical B is SDL A(0)."""
    return {1: 'toggle', 0: 'exit', 11: 'up', 12: 'down',
            13: 'toggle', 14: 'toggle'}.get(button)


def select_partitions(partitions, limit=PARTITION_ROWS):
    """Keep mounted physical block devices, HOME first and always visible."""
    rows = [row for row in partitions if isinstance(row, dict)
            and row.get('mount')
            and (str(row.get('device', '')).startswith('/dev/') or row.get('home'))]
    rows.sort(key=lambda row: not bool(row.get('home')))
    return rows[:max(0, min(PARTITION_ROWS, limit))]


def format_partition(row):
    label = ('HOME ' if row.get('home') else '') + str(row.get('mount', '?'))
    line = '{}  {}'.format(elide(label, 29), elide(row.get('device', '?'), 19))
    sizes = 'SIZE {}  AVAILABLE {}'.format(format_size(row.get('total')),
                                         format_size(row.get('free')))
    return elide(line), elide(sizes)


def format_component(row):
    name = elide(row.get('name', '?'), 22)
    status = elide(row.get('status', '?'), 12)
    line = '{} {} {}'.format(name, status, format_size(row.get('size')))
    category = {'required': 'REQ', 'support': 'SUP', 'extra': 'EXT', 'old': 'OLD'}.get(
        str(row.get('category', '')).lower(), '---')
    path = '{} {}'.format(category, elide(row.get('path', '?'), 46, middle=True))
    return elide(line), elide(path)


class SDLRect(C.Structure):
    _fields_ = [('x', C.c_int), ('y', C.c_int),
                ('w', C.c_int), ('h', C.c_int)]


class SDLKeysym(C.Structure):
    _fields_ = [('scancode', C.c_int), ('sym', C.c_int),
                ('mod', C.c_uint16), ('unused', C.c_uint32)]


class SDLKeyboardEvent(C.Structure):
    _fields_ = [('type', C.c_uint32), ('timestamp', C.c_uint32),
                ('windowID', C.c_uint32), ('state', C.c_uint8),
                ('repeat', C.c_uint8), ('padding2', C.c_uint8),
                ('padding3', C.c_uint8), ('keysym', SDLKeysym)]


class SDLControllerButtonEvent(C.Structure):
    _fields_ = [('type', C.c_uint32), ('timestamp', C.c_uint32),
                ('which', C.c_int32), ('button', C.c_uint8),
                ('state', C.c_uint8), ('padding1', C.c_uint8),
                ('padding2', C.c_uint8)]


class SDLControllerDeviceEvent(C.Structure):
    _fields_ = [('type', C.c_uint32), ('timestamp', C.c_uint32),
                ('which', C.c_int32)]


class SDLWindowEvent(C.Structure):
    _fields_ = [('type', C.c_uint32), ('timestamp', C.c_uint32),
                ('windowID', C.c_uint32), ('event', C.c_uint8),
                ('padding1', C.c_uint8), ('padding2', C.c_uint8),
                ('padding3', C.c_uint8), ('data1', C.c_int32),
                ('data2', C.c_int32)]


class SDLEvent(C.Union):
    # SDL2's event ABI is 56 bytes on both 32-bit ARM and 64-bit hosts.
    # Pointer member supplies native pointer alignment, not just byte alignment.
    _fields_ = [('type', C.c_uint32), ('key', SDLKeyboardEvent),
                ('cbutton', SDLControllerButtonEvent),
                ('cdevice', SDLControllerDeviceEvent),
                ('window', SDLWindowEvent), ('padding', C.c_uint8 * 56),
                ('alignment', C.c_void_p)]


def load_sdl():
    name = ctypes.util.find_library('SDL2')
    if not name:
        raise RuntimeError('SDL2 library not found (find_library SDL2)')
    sdl = C.CDLL(name)
    signatures = {
        'SDL_Init': ([C.c_uint32], C.c_int),
        'SDL_Quit': ([], None),
        'SDL_GetError': ([], C.c_char_p),
        'SDL_GetCurrentVideoDriver': ([], C.c_char_p),
        'SDL_GetRendererOutputSize': ([C.c_void_p, C.POINTER(C.c_int), C.POINTER(C.c_int)], C.c_int),
        'SDL_CreateWindow': ([C.c_char_p, C.c_int, C.c_int, C.c_int,
                              C.c_int, C.c_uint32], C.c_void_p),
        'SDL_DestroyWindow': ([C.c_void_p], None),
        'SDL_CreateRenderer': ([C.c_void_p, C.c_int, C.c_uint32], C.c_void_p),
        'SDL_DestroyRenderer': ([C.c_void_p], None),
        'SDL_RenderSetLogicalSize': ([C.c_void_p, C.c_int, C.c_int], C.c_int),
        'SDL_SetRenderDrawColor': ([C.c_void_p, C.c_uint8, C.c_uint8,
                                    C.c_uint8, C.c_uint8], C.c_int),
        'SDL_RenderClear': ([C.c_void_p], C.c_int),
        'SDL_RenderFillRects': ([C.c_void_p, C.POINTER(SDLRect), C.c_int], C.c_int),
        'SDL_RenderPresent': ([C.c_void_p], None),
        'SDL_PollEvent': ([C.POINTER(SDLEvent)], C.c_int),
        'SDL_Delay': ([C.c_uint32], None),
        'SDL_NumJoysticks': ([], C.c_int),
        'SDL_IsGameController': ([C.c_int], C.c_int),
        'SDL_GameControllerOpen': ([C.c_int], C.c_void_p),
        'SDL_GameControllerClose': ([C.c_void_p], None),
        'SDL_GameControllerGetJoystick': ([C.c_void_p], C.c_void_p),
        'SDL_JoystickInstanceID': ([C.c_void_p], C.c_int32),
        'SDL_RWFromFile': ([C.c_char_p, C.c_char_p], C.c_void_p),
        'SDL_GameControllerAddMappingsFromRW': ([C.c_void_p, C.c_int], C.c_int),
    }
    for symbol, (arguments, result) in signatures.items():
        function = getattr(sdl, symbol)
        function.argtypes = arguments
        function.restype = result
    return sdl


def sdl_error(sdl, operation):
    error = sdl.SDL_GetError()
    return RuntimeError('{}: {}'.format(operation, error.decode('utf-8', 'replace')
                                       if error else 'unknown SDL error'))


def checked(sdl, result, operation):
    if result < 0:
        raise sdl_error(sdl, operation)


def load_controller_mappings(sdl):
    """Load mapping databases before opening any game controllers."""
    paths = [
        '/opt/system/Tools/PortMaster/gamecontrollerdb.txt',
        '/opt/tools/PortMaster/gamecontrollerdb.txt',
        '/roms/ports/PortMaster/gamecontrollerdb.txt',
        '/roms2/ports/PortMaster/gamecontrollerdb.txt',
        '/usr/share/SDL2/gamecontrollerdb.txt',
        os.path.join(os.path.dirname(os.path.abspath(__file__)), 'gamecontrollerdb.txt'),
    ]
    configured = os.environ.get('SDL_GAMECONTROLLERCONFIG_FILE')
    if configured:
        paths.append(configured)
    for path in dict.fromkeys(paths):
        if not os.path.isfile(path):
            continue
        stream = sdl.SDL_RWFromFile(os.fsencode(path), b'rb')
        if not stream:
            raise sdl_error(sdl, 'SDL_RWFromFile ({})'.format(path))
        # freesrc=1: SDL owns and closes the stream, including parse failures.
        checked(sdl, sdl.SDL_GameControllerAddMappingsFromRW(stream, 1),
                'SDL_GameControllerAddMappingsFromRW ({})'.format(path))


class Painter:
    def __init__(self, sdl, renderer):
        self.sdl, self.renderer = sdl, renderer

    def color(self, color):
        checked(self.sdl, self.sdl.SDL_SetRenderDrawColor(
            self.renderer, color[0], color[1], color[2], 255),
            'SDL_SetRenderDrawColor')

    def text(self, x, y, value, color=TEXT):
        self.color(color)
        rectangles = []
        for index, char in enumerate(elide(value)):
            for column, bits in enumerate(FONT.get(char, FONT['?'])):
                for row in range(7):
                    if bits & (1 << row):
                        rectangles.append(SDLRect(x + index * 12 + column * 2,
                                                  y + row * 2, 2, 2))
        if rectangles:
            array = (SDLRect * len(rectangles))(*rectangles)
            checked(self.sdl, self.sdl.SDL_RenderFillRects(
                self.renderer, array, len(array)), 'SDL_RenderFillRects')

    def draw(self, data, screen, offset):
        self.color(BG)
        checked(self.sdl, self.sdl.SDL_RenderClear(self.renderer), 'SDL_RenderClear')
        if screen == 0:
            self.text(20, 22, 'STORAGE CHECK                         1/2', HOME)
            self.text(20, 52, 'MOUNT / DEVICE', DIM)
            rows = select_partitions(data.get('partitions', []))
            if not rows:
                self.text(20, 94, 'NO MOUNTED PARTITIONS', WARN)
            for index, row in enumerate(rows):
                first, second = format_partition(row)
                y = 88 + index * 46
                self.text(20, y, first, HOME if row.get('home') else TEXT)
                self.text(32, y + 20, second, HOME if row.get('home') else DIM)
            self.text(20, 380, 'HOME: ' + elide(data.get('home', '?'), 44, middle=True), HOME)
        else:
            self.text(20, 22, 'PD2 HOME COMPONENTS                  2/2', HOME)
            rows = data.get('components', [])
            end = min(offset + COMPONENT_ROWS, len(rows))
            self.text(20, 52, 'ITEMS {}-{} / {}  UP/DOWN SCROLL'.format(
                offset + 1 if rows else 0, end, len(rows)), DIM)
            if not rows:
                self.text(20, 100, 'NO COMPONENTS REPORTED', WARN)
            for index, row in enumerate(rows[offset:end]):
                first, second = format_component(row)
                y = 90 + index * 58
                self.text(20, y, first)
                self.text(20, y + 22, second, DIM)
        self.text(20, 406, 'STATE: ' + elide(data.get('state', 'UNKNOWN'), 43), DIM)
        errors = data.get('errors', [])
        if errors:
            self.text(20, 428, 'ERRORS {}: {}'.format(len(errors), errors[0]), WARN)
        self.text(20, 456, 'LEFT/RIGHT: PAGE  A: NEXT  B: EXIT', HOME)
        self.sdl.SDL_RenderPresent(self.renderer)


def run(data):
    sdl = None
    window = renderer = None
    controllers = {}
    previous_handlers = {}
    cancelled = False

    def request_exit(signum, frame):
        nonlocal cancelled
        cancelled = True

    try:
        for signum in (signal.SIGINT, signal.SIGTERM):
            previous_handlers[signum] = signal.signal(signum, request_exit)
        print('UI: initializing SDL video/controller', file=sys.stderr, flush=True)
        sdl = load_sdl()
        # VIDEO | GAMECONTROLLER (also initializes joystick/events).
        checked(sdl, sdl.SDL_Init(0x20 | 0x2000), 'SDL_Init video/gamecontroller')
        driver = sdl.SDL_GetCurrentVideoDriver()
        print('UI: video driver={}'.format(driver.decode() if driver else '?'), file=sys.stderr, flush=True)
        load_controller_mappings(sdl)

        def open_controller(index):
            if not sdl.SDL_IsGameController(index):
                return
            controller = sdl.SDL_GameControllerOpen(index)
            if not controller:
                print(str(sdl_error(sdl, 'SDL_GameControllerOpen')), file=sys.stderr)
                return
            joystick = sdl.SDL_GameControllerGetJoystick(controller)
            instance = sdl.SDL_JoystickInstanceID(joystick) if joystick else -1
            if instance < 0:
                sdl.SDL_GameControllerClose(controller)
                raise sdl_error(sdl, 'SDL_JoystickInstanceID')
            if instance in controllers:
                sdl.SDL_GameControllerClose(controller)
            else:
                controllers[instance] = controller

        count = sdl.SDL_NumJoysticks()
        checked(sdl, count, 'SDL_NumJoysticks')
        for index in range(count):
            open_controller(index)
        # Fullscreen desktop plus logical size handles native panel orientation/scaling.
        window = sdl.SDL_CreateWindow(b'Storage Check', 0x2FFF0000, 0x2FFF0000,
                                      WIDTH, HEIGHT, 0x1001)
        if not window:
            raise sdl_error(sdl, 'SDL_CreateWindow fullscreen 640x480')
        print('UI: fullscreen window created; trying software renderer', file=sys.stderr, flush=True)
        renderer = sdl.SDL_CreateRenderer(window, -1, 0x1)
        if not renderer:
            print('UI: software unavailable; trying accelerated renderer', file=sys.stderr, flush=True)
            renderer = sdl.SDL_CreateRenderer(window, -1, 0x2)
        if not renderer:
            raise sdl_error(sdl, 'SDL_CreateRenderer software/accelerated')
        output_w, output_h = C.c_int(), C.c_int()
        checked(sdl, sdl.SDL_GetRendererOutputSize(renderer, C.byref(output_w), C.byref(output_h)),
                'SDL_GetRendererOutputSize')
        print('UI: renderer output={}x{}'.format(output_w.value, output_h.value), file=sys.stderr, flush=True)
        checked(sdl, sdl.SDL_RenderSetLogicalSize(renderer, WIDTH, HEIGHT),
                'SDL_RenderSetLogicalSize 640x480')
        painter = Painter(sdl, renderer)
        event = SDLEvent()
        screen, offset, running = 0, 0, True
        first_frame = True
        keys = {27: 'exit', 13: 'toggle', 32: 'toggle',
                1073741904: 'toggle', 1073741903: 'toggle',
                1073741906: 'up', 1073741905: 'down',
                1073741899: 'pageup', 1073741902: 'pagedown'}
        while running and not cancelled:
            while not cancelled and sdl.SDL_PollEvent(C.byref(event)):
                action = None
                if event.type == 0x100:  # SDL_QUIT
                    action = 'exit'
                elif event.type == 0x300:  # SDL_KEYDOWN
                    action = keys.get(event.key.keysym.sym)
                    if event.key.repeat and action in ('toggle', 'exit'):
                        action = None
                elif event.type == 0x651:  # SDL_CONTROLLERBUTTONDOWN
                    action = action_for_button(event.cbutton.button)
                elif event.type == 0x653:  # SDL_CONTROLLERDEVICEADDED: device index
                    open_controller(event.cdevice.which)
                elif event.type == 0x654:  # SDL_CONTROLLERDEVICEREMOVED: instance ID
                    controller = controllers.pop(event.cdevice.which, None)
                    if controller:
                        sdl.SDL_GameControllerClose(controller)
                elif event.type == 0x200:  # SDL_WINDOWEVENT
                    if event.window.event == 14:  # CLOSE
                        action = 'exit'
                if action == 'exit':
                    running = False
                elif action == 'toggle':
                    screen = 1 - screen
                elif screen == 1 and action in ('up', 'down', 'pageup', 'pagedown'):
                    step = {'up': -1, 'down': 1, 'pageup': -COMPONENT_ROWS,
                            'pagedown': COMPONENT_ROWS}[action]
                    new_offset = max(0, min(max(0, len(data.get('components', []))
                                              - COMPONENT_ROWS), offset + step))
                    offset = new_offset
            # KMSDRM backbuffers are not persistent after Present. Keep submitting
            # complete frames, including idle UI, instead of one dirty-only flip.
            if running:
                painter.draw(data, screen, offset)
                if first_frame:
                    print('UI: first frame presented; waiting for input', file=sys.stderr, flush=True)
                    first_frame = False
            sdl.SDL_Delay(33)
        return 0
    finally:
        if sdl is not None:
            for controller in controllers.values():
                sdl.SDL_GameControllerClose(controller)
            if renderer:
                sdl.SDL_DestroyRenderer(renderer)
            if window:
                sdl.SDL_DestroyWindow(window)
            sdl.SDL_Quit()
        for signum, handler in previous_handlers.items():
            signal.signal(signum, handler)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        print('Usage: storage_ui.py SNAPSHOT.json', file=sys.stderr)
        return 2
    try:
        with open(argv[0], 'r', encoding='utf-8') as stream:
            data = json.load(stream)
        if not isinstance(data, dict):
            raise ValueError('snapshot must be a JSON object')
        for key in ('partitions', 'components'):
            if not isinstance(data.get(key, []), list) or any(
                    not isinstance(row, dict) for row in data.get(key, [])):
                raise ValueError('{} must be a list of objects'.format(key))
        if not isinstance(data.get('errors', []), list):
            raise ValueError('errors must be a list')
        return run(data)
    except (OSError, ValueError, RuntimeError, AttributeError) as error:
        print('Storage Check UI: {}'.format(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
