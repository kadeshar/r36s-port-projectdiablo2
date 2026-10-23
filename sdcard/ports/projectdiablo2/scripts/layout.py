#!/usr/bin/env python3
"""Prepare private runtime/config links; never copy or edit imported game data."""
import argparse
from collections import deque
import hashlib
import json
import os
import pathlib
import re
import shutil
import stat
import tarfile
import tempfile

VERSION = '0.1.18'
CONFIG_LIMIT = 512 * 1024
RUNTIME_LIMIT = 512 * 1024 * 1024
JSON_CONFIGS = ('ProjectDiablo.json', 'SGD2FreeResolution.json', 'BH.json')
WORK_CONFIGS = JSON_CONFIGS + ('ProjectDiablo.cfg', 'default.filter', 'ddraw.ini')
ARTIFACTS = ('wine-8.0-x86.tar.xz', 'box86', 'weston_pkg_0.2.squashfs', 'vc_redist.x86.exe')
CNC_DDRAW_VERSION = '7.1.0.0'
CNC_DDRAW_SIZE = 411648
CNC_DDRAW_SHA256 = '85e0f7d530dfda134793a57cb3e76b0287dcc96892ee57162dd68f47283b03a9'
# Restricted PD2 SGD2 build: fixed in-game vector and parser both force 1068x600.
# Patch only a private generated copy, never the imported asset or an unknown DLL.
SGD2_SOURCE_SIZE = 307200
SGD2_SOURCE_SHA256 = '177242c2afd2df9da93ca1591c4189c6ca014e4ce5e6971e7b26912a146579cf'
SGD2_800_SHA256 = '2e1142d592e733fad1f595ec50fb3b43b931a9e04c8ab6a357c94b8312e9a80b'
SGD2_800_PATCHES = (
    (0x3caa, bytes.fromhex('2c040000'), bytes.fromhex('20030000')),
    (0xc6ab, bytes.fromhex('2c040000'), bytes.fromhex('20030000')),
)
SGD2_1024_SHA256 = 'f79829ab958440aab43a789d4aad43bf2eeaa657642589aee6cb6b6e6cb5656e'
# Verified on the pinned source: C7 45 E0 imm32 / C7 45 E4 imm32
# initialize vector height/width; B8 imm32 followed by CMP/CMOVNE forces
# parser width/height. These are instruction immediates, not adjacent guesses.
SGD2_1024_PATCHES = (
    (0x3ca1, bytes.fromhex('58020000'), bytes.fromhex('00030000')),
    (0x3caa, bytes.fromhex('2c040000'), bytes.fromhex('00040000')),
    (0xc6ab, bytes.fromhex('2c040000'), bytes.fromhex('00040000')),
    (0xc6b5, bytes.fromhex('58020000'), bytes.fromhex('00030000')),
)
SGD2_640_SHA256 = 'b582f3018b75ff1010ce811924f146d7bd8b67b5693c2f338f782695b1b14cec'
SGD2_640_PATCHES = (
    (0x3ca1, bytes.fromhex('58020000'), bytes.fromhex('e0010000')),
    (0x3caa, bytes.fromhex('2c040000'), bytes.fromhex('80020000')),
    (0xc6ab, bytes.fromhex('2c040000'), bytes.fromhex('80020000')),
    (0xc6b5, bytes.fromhex('58020000'), bytes.fromhex('e0010000')),
)
GAME_RESOLUTIONS = ('640x480', '800x600', '1024x768', 'native')
DISPLAY_KEYS = {
    'width': '640', 'height': '480', 'fullscreen': 'true', 'windowed': 'true',
    'maintas': 'true', 'boxing': 'false', 'adjmouse': 'true', 'handlemouse': 'true',
    'border': 'false', 'resizeable': 'false', 'resizable': 'false', 'hook': '4',
    'inject_resolution': '1024x768',
}
DISPLAY_MARKER = '.display-640-v1.json'
SAVE_PATH_MARKER = '.save-path-v1.json'
SAVE_PATH = 'S:\\'


class LayoutError(Exception):
    """Fixed closed error code; never include paths or file contents."""


def no_links(path):
    path = pathlib.Path(path)
    for parent in (path, *path.parents):
        try:
            entry = parent.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(entry.st_mode) or getattr(entry, 'st_file_attributes', 0) & 0x400:
            raise LayoutError('invalid_layout')


def regular(path):
    path = pathlib.Path(path)
    no_links(path)
    if not path.is_file():
        raise LayoutError('invalid_layout')
    return path


def checked_dir(path):
    no_links(path)
    path.mkdir(parents=True, exist_ok=True)
    if not path.is_dir():
        raise LayoutError('invalid_layout')


def atomic_bytes(path, content):
    no_links(path)
    if path.exists():
        regular(path)
    tmp = path.with_name(path.name + '.new')
    no_links(tmp)
    if tmp.exists():
        raise LayoutError('invalid_layout')
    with tmp.open('xb') as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())
    tmp.replace(path)


def atomic_json(path, value):
    atomic_bytes(path, (json.dumps(value, indent=2) + '\n').encode('utf-8'))


def atomic_session_json(path, value):
    """Replace disposable session state without reusing interrupted temp files.

    Persistent configs retain the strict fixed-.new recovery checks above.
    Session state is regenerated under the launcher's session lock each start.
    """
    no_links(path)
    if path.exists():
        regular(path)
    pending = None
    try:
        with tempfile.NamedTemporaryFile(mode='wb', dir=path.parent,
                                         prefix=path.name + '.', suffix='.tmp',
                                         delete=False) as stream:
            pending = pathlib.Path(stream.name)
            stream.write((json.dumps(value, indent=2) + '\n').encode('utf-8'))
            stream.flush()
            os.fsync(stream.fileno())
        pending.replace(path)
    finally:
        if pending is not None:
            try:
                pending.unlink()
            except FileNotFoundError:
                pass


def sha(path):
    digest = hashlib.sha256()
    with regular(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1048576), b''):
            digest.update(chunk)
    return digest.hexdigest()


def link(path, target):
    # The leaf may already be our link; its parent must never be a link.
    no_links(path.parent)
    if path.is_symlink():
        if pathlib.Path(os.readlink(path)) != target:
            path.unlink()
            path.symlink_to(target)
    elif path.exists():
        raise LayoutError('invalid_layout')
    else:
        path.symlink_to(target)


def sgd2_800_bytes(content):
    """Reproducible four-byte delta for ONE known build; no generic DLL patching."""
    return _sgd2_patch(content, SGD2_800_PATCHES, SGD2_800_SHA256)


def sgd2_1024_bytes(content):
    """Pinned 1024x768 vector and parser derivative, including both heights."""
    return _sgd2_patch(content, SGD2_1024_PATCHES, SGD2_1024_SHA256)


def sgd2_640_bytes(content):
    """Pinned 640x480 vector and parser derivative, including both heights."""
    return _sgd2_patch(content, SGD2_640_PATCHES, SGD2_640_SHA256)


def _sgd2_patch(content, patches, expected):
    if len(content) != SGD2_SOURCE_SIZE or hashlib.sha256(content).hexdigest() != SGD2_SOURCE_SHA256:
        raise LayoutError('unsupported_runtime')
    incoming = bytearray(content)
    for offset, previous, replacement in patches:
        if incoming[offset:offset + len(previous)] != previous or len(previous) != len(replacement):
            raise LayoutError('unsupported_runtime')
        incoming[offset:offset + len(previous)] = replacement
    incoming = bytes(incoming)
    if hashlib.sha256(incoming).hexdigest() != expected:
        raise LayoutError('unsupported_runtime')
    return incoming


def _sgd2_bytes(path, expected):
    """Bounded read of one pinned asset; never follows a replaced symlink."""
    path = regular(path)
    if path.stat().st_size != SGD2_SOURCE_SIZE:
        raise LayoutError('unsupported_runtime')
    with path.open('rb') as stream:
        content = stream.read(SGD2_SOURCE_SIZE + 1)
    if len(content) != SGD2_SOURCE_SIZE or hashlib.sha256(content).hexdigest() != expected:
        raise LayoutError('unsupported_runtime')
    return content


def sgd2_800_file(data, state):
    return _sgd2_file(data, state, '800x600', sgd2_800_bytes, SGD2_800_SHA256)


def sgd2_1024_file(data, state):
    return _sgd2_file(data, state, '1024x768', sgd2_1024_bytes, SGD2_1024_SHA256)


def sgd2_640_file(data, state):
    return _sgd2_file(data, state, '640x480', sgd2_640_bytes, SGD2_640_SHA256)


def _sgd2_file(data, state, resolution, patch, expected):
    """Publish a verified local derivative, keeping the original byte-for-byte."""
    directory = pathlib.Path(data) / 'ProjectD2'
    no_links(directory)
    sources = [p for p in directory.iterdir() if p.name.lower() == 'sgd2freeres.dll']
    if len(sources) != 1:
        raise LayoutError('unsupported_runtime')
    incoming = patch(_sgd2_bytes(sources[0], SGD2_SOURCE_SHA256))
    cache = pathlib.Path(state) / ('compat/sgd2-' + resolution + '-v1')
    destination = cache / 'SGD2FreeRes.dll'
    pending = destination.with_name(destination.name + '.new')
    no_links(destination)
    no_links(pending)
    if pending.exists():
        raise LayoutError('invalid_layout')
    if destination.exists():
        _sgd2_bytes(destination, expected)
    else:
        checked_dir(cache)
        atomic_bytes(destination, incoming)
        _sgd2_bytes(destination, expected)
    return destination


def native_cast_file(data, state):
    """Cache a pinned local controller fix; never patch the imported DLL."""
    try:
        import native_cast
    except ImportError:
        raise LayoutError('unsupported_runtime') from None

    directory = pathlib.Path(data) / 'ProjectD2'
    no_links(directory)
    sources = [p for p in directory.iterdir() if p.name.lower() == 'projectdiablo.dll']
    if len(sources) != 1:
        raise LayoutError('unsupported_runtime')

    def verified(path, size, expected):
        path = regular(path)
        if path.stat().st_size != size:
            raise LayoutError('unsupported_runtime')
        with path.open('rb') as stream:
            content = stream.read(size + 1)
        if len(content) != size or hashlib.sha256(content).hexdigest() != expected:
            raise LayoutError('unsupported_runtime')
        return content

    source = verified(sources[0], native_cast.SOURCE_SIZE, native_cast.SOURCE_SHA256)
    try:
        incoming = native_cast.native_cast_bytes(source)
    except ValueError:
        raise LayoutError('unsupported_runtime') from None
    cache = pathlib.Path(state) / 'compat/pd2-native-cast-640-v1'
    destination = cache / 'ProjectDiablo.dll'
    pending = destination.with_name(destination.name + '.new')
    no_links(destination)
    no_links(pending)
    if pending.exists():
        raise LayoutError('invalid_layout')
    if not destination.exists():
        checked_dir(cache)
        atomic_bytes(destination, incoming)
    verified(destination, native_cast.TARGET_SIZE, native_cast.TARGET_SHA256)
    return destination


def tar_path(value, link_target=False):
    if not isinstance(value, str) or not value or '\\' in value or ':' in value or any(ord(c) < 32 for c in value):
        raise LayoutError('unsupported_runtime')
    path = pathlib.PurePosixPath(value)
    if path.is_absolute() or (not path.parts and not link_target) or (not link_target and '..' in path.parts):
        raise LayoutError('unsupported_runtime')
    if any(part not in ('.', '..') and part.endswith(('.', ' ')) for part in path.parts):
        raise LayoutError('unsupported_runtime')
    return path


def validate_tar(archive):
    members = archive.getmembers()
    if len(members) > 20000:
        raise LayoutError('unsupported_runtime')
    entries = {}
    symlinks = {}
    total = 0
    for member in members:
        path = tar_path(member.name)
        if path.parts[0] != 'wine-8.0-x86' or str(path) in entries:
            raise LayoutError('unsupported_runtime')
        if len(path.parts) == 1 and not member.isdir():
            raise LayoutError('unsupported_runtime')
        if member.type not in (tarfile.REGTYPE, tarfile.AREGTYPE, tarfile.DIRTYPE, tarfile.SYMTYPE) or member.size < 0:
            raise LayoutError('unsupported_runtime')
        entries[str(path)] = member
        if member.isfile():
            total += member.size
            if total > RUNTIME_LIMIT:
                raise LayoutError('unsupported_runtime')
        if member.issym():
            symlinks[path.parts] = tar_path(member.linkname, link_target=True).parts
    # No regular file or symlink may be an ancestor of another archive entry.
    for name in entries:
        path = pathlib.PurePosixPath(name)
        for parent in path.parents:
            if str(parent) in entries and not entries[str(parent)].isdir():
                raise LayoutError('unsupported_runtime')
    # Resolve targets component-wise, including intermediate archive symlinks.
    # Lexical normalization alone misses escapes such as link/../outside.
    for parts, target in symlinks.items():
        stack = list(parts[:-1])
        pending = deque(target)
        follows = 0
        while pending:
            part = pending.popleft()
            if part == '.':
                continue
            if part == '..':
                if len(stack) <= 1:
                    raise LayoutError('unsupported_runtime')
                stack.pop()
            else:
                stack.append(part)
                alias = symlinks.get(tuple(stack))
                if alias is not None:
                    follows += 1
                    if follows > 40:
                        raise LayoutError('unsupported_runtime')
                    stack.pop()
                    pending.extendleft(reversed(alias))
        if not stack or stack[0] != 'wine-8.0-x86':
            raise LayoutError('unsupported_runtime')
    return members


def config_content(path, json_object=False):
    path = regular(path)
    if path.stat().st_size > CONFIG_LIMIT:
        raise LayoutError('invalid_layout')
    with path.open('rb') as stream:
        content = stream.read(CONFIG_LIMIT + 1)
    if len(content) > CONFIG_LIMIT:
        raise LayoutError('invalid_layout')
    try:
        text = content.decode('utf-8')
        if '\x00' in text:
            raise ValueError()
        if json_object:
            def invalid_constant(_):
                raise ValueError()
            if not isinstance(json.loads(text, parse_constant=invalid_constant), dict):
                raise ValueError()
    except (UnicodeError, ValueError, RecursionError):
        raise LayoutError('invalid_layout') from None
    return content


def read_object(path):
    try:
        result = json.loads(config_content(path, json_object=True).decode('utf-8'))
    except (ValueError, UnicodeError):
        raise LayoutError('invalid_layout') from None
    return result


def companion_file(port):
    """Authenticate the workdir-only wrapper before prepare mutates anything."""
    directory = port / 'compat/cnc-ddraw'
    manifest = read_object(directory / 'manifest.json')
    try:
        if (manifest['version'] != CNC_DDRAW_VERSION or manifest['file'] != 'ddraw.dll'
                or type(manifest['size']) is not int or manifest['size'] != CNC_DDRAW_SIZE
                or not isinstance(manifest['sha256'], str)
                or not re.fullmatch(r'[0-9a-f]{64}', manifest['sha256'])
                or manifest['sha256'] != CNC_DDRAW_SHA256):
            raise LayoutError('unsupported_runtime')
        wrapper = regular(directory / 'ddraw.dll')
        if wrapper.stat().st_size != manifest['size'] or sha(wrapper) != manifest['sha256']:
            raise LayoutError('unsupported_runtime')
    except (KeyError, TypeError):
        raise LayoutError('unsupported_runtime') from None
    return wrapper


def display_ini(content, keys=None):
    """Change only exact keys in the unique [ddraw] section, keeping other bytes."""
    keys = DISPLAY_KEYS if keys is None else keys
    lines = content.decode('utf-8').splitlines(keepends=True)
    newline = '\r\n' if b'\r\n' in content else '\n'
    section = None
    found = False
    seen = set()
    output = []

    def append_missing():
        missing = [key for key in keys if key not in seen]
        if missing and output and not output[-1].endswith(('\n', '\r')):
            output[-1] += newline
        output.extend(key + '=' + keys[key] + newline for key in missing)

    for line in lines:
        header = re.fullmatch(r'\s*\[([^\]\r\n]+)\]\s*(?:[;#][^\r\n]*)?', line.lstrip('\ufeff').rstrip('\r\n'))
        if header:
            if section == 'ddraw':
                append_missing()
            section = header[1].strip().lower()
            if section == 'ddraw':
                if found:
                    raise LayoutError('invalid_layout')
                found = True
        elif line.lstrip('\ufeff \t').startswith('['):
            raise LayoutError('invalid_layout')
        elif section == 'ddraw':
            entry = re.fullmatch(r'([ \t]*)([^=;#\s]+)([ \t]*=[ \t]*)([^;#\r\n]*?)([ \t]*(?:[;#][^\r\n]*)?)(\r\n|\n|\r)?', line)
            if entry and entry[2].lower() in keys:
                key = entry[2].lower()
                seen.add(key)
                line = ''.join((entry[1], entry[2], entry[3], keys[key], entry[5], entry[6] or ''))
        output.append(line)
    if not found:
        raise LayoutError('invalid_layout')
    if section == 'ddraw':
        append_missing()
    result = ''.join(output).encode('utf-8')
    if len(result) > CONFIG_LIMIT:
        raise LayoutError('invalid_layout')
    return result


def migrate_display(config):
    """One-time display migration; preflight all files before any config/backup write.

    Dedicated backups are immutable across retries and separate from sync backups.
    A crash after replacing one profile simply retries the idempotent transform.
    """
    marker = config / DISPLAY_MARKER
    no_links(marker)
    if marker.exists():
        if read_object(marker) != {'schema_version': 1, 'migration': 'display-640-v1'}:
            raise LayoutError('invalid_layout')
        return
    changes = []
    for name in ('ddraw-gdi.ini', 'SGD2FreeResolution.json'):
        active = config / name
        previous = config_content(active, name in JSON_CONFIGS)
        if name.endswith('.ini'):
            incoming = display_ini(previous)
        else:
            obj = json.loads(previous.decode('utf-8'))
            plugin = obj.get('SlashGaming Diablo II Free Resolution')
            # Only recognize the old shipped 800x600 defaults, not custom values.
            if (isinstance(plugin, dict) and plugin.get('Main Menu Resolution') == '800x600'
                    and plugin.get('Ingame Resolutions') == ['800x600']
                    and plugin.get('Use 800 Interface Bar?') is False):
                plugin.update({'Main Menu Resolution': '1024x768',
                               'Ingame Resolutions': ['1024x768', '800x600'],
                               'Use 800 Interface Bar?': True})
                incoming = (json.dumps(obj, indent=2) + '\n').encode('utf-8')
                if len(incoming) > CONFIG_LIMIT:
                    raise LayoutError('invalid_layout')
            else:
                incoming = previous
        if incoming != previous:
            changes.append((active, incoming, previous))
    backup = config / 'backups'
    no_links(backup)
    if backup.exists() and not backup.is_dir():
        raise LayoutError('invalid_layout')
    for active, _, _ in changes:
        saved = backup / (active.name + '.display-640-v1.bak')
        no_links(saved)
        if saved.exists():
            config_content(saved, active.name in JSON_CONFIGS)
        for path in (active.with_name(active.name + '.new'), saved.with_name(saved.name + '.new')):
            no_links(path)
            if path.exists():
                raise LayoutError('invalid_layout')
    pending_marker = marker.with_name(marker.name + '.new')
    no_links(pending_marker)
    if pending_marker.exists():
        raise LayoutError('invalid_layout')
    if changes:
        checked_dir(backup)
    for active, incoming, previous in changes:
        saved = backup / (active.name + '.display-640-v1.bak')
        if not saved.exists():
            atomic_bytes(saved, previous)
        atomic_bytes(active, incoming)
    atomic_json(marker, {'schema_version': 1, 'migration': 'display-640-v1'})


def migrate_save_path(config):
    """Set only the classic save path once; never touch saves or input settings.

    A validated marker ends enforcement: later game/user rewrites are retained.
    An interrupted migration reuses its immutable original backup on retry.
    """
    active = config / 'ProjectDiablo.json'
    marker = config / SAVE_PATH_MARKER
    backup = config / 'backups'
    saved = backup / 'ProjectDiablo.json.save-path-v1.bak'
    previous = config_content(active, json_object=True)
    obj = json.loads(previous.decode('utf-8'))
    classic = obj.get('classic_game_settings')
    if not isinstance(classic, dict) or not isinstance(classic.get('other'), dict):
        raise LayoutError('invalid_layout')
    other = classic['other']
    if 'save_path' in other and not isinstance(other['save_path'], str):
        raise LayoutError('invalid_layout')
    no_links(marker)
    no_links(saved)
    if backup.exists() and not backup.is_dir():
        raise LayoutError('invalid_layout')
    if saved.exists():
        config_content(saved, json_object=True)
    if marker.exists():
        value = read_object(marker)
        if (value != {'schema_version': 1, 'migration': 'save-path-v1'}
                or type(value.get('schema_version')) is not int):
            raise LayoutError('invalid_layout')
        return
    incoming = previous
    if other.get('save_path') != SAVE_PATH:
        other['save_path'] = SAVE_PATH
        incoming = (json.dumps(obj, indent=2) + '\n').encode('utf-8')
        if len(incoming) > CONFIG_LIMIT:
            raise LayoutError('invalid_layout')
    # Preflight every write destination before creating a backup or changing JSON.
    pending = [marker.with_name(marker.name + '.new')]
    if incoming != previous:
        pending.extend((active.with_name(active.name + '.new'),
                        saved.with_name(saved.name + '.new')))
    for path in pending:
        no_links(path)
        if path.exists():
            raise LayoutError('invalid_layout')
    if incoming != previous:
        checked_dir(backup)
        if not saved.exists():
            atomic_bytes(saved, previous)
        atomic_bytes(active, incoming)
    atomic_json(marker, {'schema_version': 1, 'migration': 'save-path-v1'})


def runtime_file(wine, relative):
    # Validated runtime archives may have contained relative symlinks.
    no_links(wine)
    resolved = (wine / relative).resolve()
    if wine.absolute() not in resolved.parents or not resolved.is_file():
        raise LayoutError('unsupported_runtime')
    return resolved


def input_config(content, mode):
    """Session-only input selection; imported and persistent configs stay intact."""
    obj = json.loads(content.decode('utf-8'))
    settings = obj.setdefault('pd2_game_settings', {})
    if not isinstance(settings, dict) or mode not in ('native', 'mapper'):
        raise LayoutError('invalid_profile')
    settings.update(wasd_movement=mode == 'mapper', controller_movement=mode == 'native')
    result = (json.dumps(obj, indent=2) + '\n').encode('utf-8')
    if len(result) > CONFIG_LIMIT:
        raise LayoutError('invalid_layout')
    return result


def restore_input_config(incoming, previous):
    """Do not persist the two launcher-owned session overrides on game exit."""
    obj = json.loads(incoming.decode('utf-8'))
    old = json.loads(previous.decode('utf-8'))
    settings = obj.setdefault('pd2_game_settings', {})
    original = old.get('pd2_game_settings', {})
    if not isinstance(settings, dict) or not isinstance(original, dict):
        raise LayoutError('invalid_layout')
    for key in ('wasd_movement', 'controller_movement'):
        if key in original:
            settings[key] = original[key]
        else:
            settings.pop(key, None)
    if not settings and 'pd2_game_settings' not in old:
        obj.pop('pd2_game_settings', None)
    if obj == old:
        return previous
    result = (json.dumps(obj, indent=2) + '\n').encode('utf-8')
    if len(result) > CONFIG_LIMIT:
        raise LayoutError('invalid_layout')
    return result


def prepare(port, state, data_override=None, volatile_work=False, input_mode=None, game_resolution=None):
    # A supplied session override is strictly whitelisted before any mutation.
    if game_resolution is not None and (type(game_resolution) is not str or game_resolution not in GAME_RESOLUTIONS):
        raise LayoutError('invalid_profile')
    if input_mode not in (None, 'mapper', 'native'):
        raise LayoutError('invalid_profile')
    port = pathlib.Path(port).absolute()
    state = pathlib.Path(state).absolute()
    no_links(port)
    wrapper = companion_file(port)
    checked_dir(state)
    if shutil.disk_usage(state).free < 700 * 1024 * 1024 and not (state / 'wineprefix/.initialized').exists():
        raise LayoutError('insufficient_space')
    probe = state / '.symlink-test'
    if probe.exists() or probe.is_symlink():
        raise LayoutError('invalid_layout')
    try:
        probe.symlink_to(state)
        probe.unlink()
    except OSError:
        raise LayoutError('invalid_layout') from None
    manifest = read_object(port / 'runtime-manifest.json')
    try:
        entries = manifest['artifacts']
        if not isinstance(entries, list) or any(not isinstance(a, dict) for a in entries):
            raise LayoutError('unsupported_runtime')
        artifacts = {a['file']: a for a in entries}
        if len(artifacts) != len(entries):
            raise LayoutError('unsupported_runtime')
        for name in ARTIFACTS:
            entry = artifacts[name]
            path = regular(port / 'runtime' / name)
            if type(entry['size']) is not int or entry['size'] < 0 or not isinstance(entry['sha256'], str) or len(entry['sha256']) != 64:
                raise LayoutError('unsupported_runtime')
            if path.stat().st_size != entry['size'] or sha(path) != entry['sha256']:
                raise LayoutError('unsupported_runtime')
    except (KeyError, TypeError):
        raise LayoutError('unsupported_runtime') from None
    key = artifacts['wine-8.0-x86.tar.xz']['sha256'][:12]
    runtime = state / ('runtime-' + key)
    checked_dir(runtime)
    wine = runtime / 'wine-8.0-x86'
    no_links(wine)
    if not wine.exists():
        stage = runtime / 'extracting'
        no_links(stage)
        if stage.exists():
            raise LayoutError('invalid_layout')
        checked_dir(stage)
        with tarfile.open(port / 'runtime/wine-8.0-x86.tar.xz', 'r:xz') as archive:
            members = validate_tar(archive)
            for member in members:
                destination = stage / member.name
                if member.isdir():
                    destination.mkdir(parents=True, exist_ok=True)
                elif member.isfile():
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    with archive.extractfile(member) as source, destination.open('xb') as output:
                        shutil.copyfileobj(source, output)
                    destination.chmod(member.mode & 0o755)
            for member in members:
                if member.issym():
                    destination = stage / member.name
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.symlink_to(member.linkname)
        (stage / 'wine-8.0-x86').rename(wine)
        stage.rmdir()
    boxdir = state / ('box86-' + artifacts['box86']['sha256'][:12])
    checked_dir(boxdir)
    box = boxdir / 'box86'
    no_links(box)
    if not box.exists():
        shutil.copyfile(regular(port / 'runtime/box86'), box)
        box.chmod(0o700)
    if sha(box) != artifacts['box86']['sha256']:
        raise LayoutError('unsupported_runtime')
    runtime_file(wine, 'bin/wine')
    runtime_file(wine, 'bin/wineserver')
    data = pathlib.Path(data_override).absolute() if data_override else port / 'gamedata/Diablo II'
    no_links(data)
    no_links(data / 'ProjectD2')
    if not data.is_dir() or not (data / 'ProjectD2').is_dir():
        raise LayoutError('invalid_layout')
    required = ('d2data.mpq', 'd2exp.mpq', 'd2char.mpq', 'ProjectD2/Game.exe', 'ProjectD2/ProjectDiablo.dll', 'ProjectD2/pd2data.mpq', 'ProjectD2/pd2monchars.mpq')
    for name in required:
        regular(data / name)
    original_wrappers = [p for p in (data / 'ProjectD2').iterdir() if p.name.lower() == 'ddraw.dll']
    if len(original_wrappers) != 1:
        raise LayoutError('invalid_layout')
    regular(original_wrappers[0])
    config = port / 'config'
    saves = port / 'saves'
    checked_dir(config)
    checked_dir(saves)
    settings = config / 'settings.json'
    no_links(settings)
    if not settings.exists():
        atomic_json(settings, {'schema_version': 1, 'profile': 'gdi', 'swap_ab': False, 'game_resolution': '640x480'})
    opts = read_object(settings)
    if opts.get('schema_version') != 1 or opts.get('profile') not in ('gdi', 'opengl') or type(opts.get('swap_ab')) is not bool:
        raise LayoutError('invalid_profile')
    # Legacy OpenGL settings fall back to GDI in memory, never rewrite user settings.
    opts['profile'] = 'gdi'
    # Existing prefixes keep their file byte-identical; a missing key takes the
    # LCD-native default. Preserve explicit choices, including 800x600.
    # Validate persisted settings even with an override.
    resolution = opts.get('game_resolution', '640x480')
    if type(resolution) is not str or resolution not in GAME_RESOLUTIONS:
        raise LayoutError('invalid_profile')
    if game_resolution is not None:
        resolution = game_resolution
    active_names = JSON_CONFIGS + ('ProjectDiablo.cfg', 'default.filter', 'ddraw-gdi.ini')
    for name in active_names:
        active = config / name
        no_links(active)
        if not active.exists():
            atomic_bytes(active, config_content(port / 'defaults' / name, name in JSON_CONFIGS))
        config_content(active, name in JSON_CONFIGS)
    migrate_display(config)
    migrate_save_path(config)
    prefix = state / 'wineprefix'
    checked_dir(prefix)
    checked_dir(prefix / 'drive_c')
    checked_dir(prefix / 'dosdevices')
    work = state / 'game'
    checked_dir(work)
    checked_dir(work / 'ProjectD2')
    # Preflight the pinned 4:3 copy before any work mutation; native bypasses
    # it so a broken or missing resolution DLL still falls back to the asset.
    sgd2_cache = None
    if resolution == '640x480':
        sgd2_cache = sgd2_640_file(data, state)
    elif resolution == '800x600':
        sgd2_cache = sgd2_800_file(data, state)
    elif resolution == '1024x768':
        sgd2_cache = sgd2_1024_file(data, state)
    cast_cache = (native_cast_file(data, state)
                  if resolution == '640x480' and input_mode == 'native' else None)
    for directory, destination in ((data, work), (data / 'ProjectD2', work / 'ProjectD2')):
        for source in directory.iterdir():
            no_links(source)
            if source.is_dir():
                continue
            if destination == work / 'ProjectD2' and (
                    source.name in WORK_CONFIGS
                    or source.name.lower() in ('bncache.dat', 'bnetlog.txt', 'dsound.dll', 'dsoal-aldrv.dll')):
                # Imported engine cache/logs are not immutable assets. Wine must
                # create fresh files in RAM; persistent mode uses game-state below.
                # Audio DLLs are staged exclusively by audio_dsoal into volatile work.
                continue
            regular(source)
            target = source
            if destination == work / 'ProjectD2' and source.name.lower() == 'sgd2freeres.dll' and sgd2_cache is not None:
                target = sgd2_cache
            elif destination == work / 'ProjectD2' and source.name.lower() == 'projectdiablo.dll' and cast_cache is not None:
                target = cast_cache
            elif destination == work / 'ProjectD2' and source.name.lower() == 'ddraw.dll':
                target = wrapper
            link(destination / source.name, target)
    for lng in ('D2.LNG', 'd2.lng'):
        if (data / lng).is_file() and not (work / 'ProjectD2' / lng).exists():
            link(work / 'ProjectD2' / lng, data / lng)
    for name in WORK_CONFIGS:
        active_name = 'ddraw-' + opts['profile'] + '.ini' if name == 'ddraw.ini' else name
        active = config / active_name
        destination = work / 'ProjectD2' / name
        if volatile_work:
            # Wine may replace these by rename; links to persistent config break it.
            content = config_content(active, name in JSON_CONFIGS)
            if name == 'ProjectDiablo.json' and input_mode is not None:
                content = input_config(content, input_mode)
            if name == 'ddraw.ini':
                # Use a clean known template; user game-specific INI sections
                # can override global keys. Never sync this session template to config.
                content = config_content(port / 'defaults/ddraw-gdi.ini', False)
                content = display_ini(content, {
                    'renderer': 'gdi', 'shader': 'Nearest neighbor',
                    'maxfps': '30', 'minfps': '0', 'vsync': 'false',
                    'singlecpu': 'false', 'maxgameticks': '-1',
                    'inject_resolution': resolution if resolution != 'native' else '1068x600',
                })
            if not destination.exists() or config_content(destination, name in JSON_CONFIGS) != content:
                atomic_bytes(destination, content)
        else:
            link(destination, active)
    if volatile_work:
        # Caller mounts a fresh tmpfs here. Refuse persistent legacy log links
        # even if an incorrect caller reused an old work directory.
        for name in ('bncache.dat', 'BnetLog.txt'):
            no_links(work / 'ProjectD2' / name)
    else:
        mutable = config / 'game-state'
        checked_dir(mutable)
        for name in ('bncache.dat', 'BnetLog.txt'):
            active = mutable / name
            no_links(active)
            if not active.exists():
                active.touch()
            regular(active)
            link(work / 'ProjectD2' / name, active)
    link(prefix / 'drive_c/Diablo II', work)
    link(prefix / 'dosdevices/c:', prefix / 'drive_c')
    link(prefix / 'dosdevices/s:', saves)
    z = prefix / 'dosdevices/z:'
    if z.is_symlink():
        z.unlink()
    elif z.exists():
        raise LayoutError('invalid_layout')
    result = {'wine': str(wine), 'box': str(box), 'prefix': str(prefix), 'work': str(work), 'profile': opts['profile'], 'swap_ab': opts['swap_ab'], 'game_resolution': resolution, 'volatile_work': bool(volatile_work)}
    if input_mode is not None:
        result['input_mode'] = input_mode
    atomic_session_json(state / 'session-layout.json', result)
    return result


def sync_config(port, state):
    """Commit only six bounded valid config files from volatile work, never logs."""
    port = pathlib.Path(port).absolute()
    state = pathlib.Path(state).absolute()
    no_links(port)
    no_links(state)
    session = read_object(state / 'session-layout.json')
    work = state / 'game'
    if session.get('work') != str(work) or session.get('profile') != 'gdi' or session.get('volatile_work') is not True:
        raise LayoutError('invalid_layout')
    no_links(work)
    config = port / 'config'
    no_links(config)
    if not config.is_dir():
        raise LayoutError('invalid_layout')
    changes = []
    # Complete preflight before touching any persistent config or backup.
    for name in WORK_CONFIGS:
        incoming = config_content(work / 'ProjectD2' / name, name in JSON_CONFIGS)
        active_name = 'ddraw-' + session['profile'] + '.ini' if name == 'ddraw.ini' else name
        active = config / active_name
        previous = config_content(active, name in JSON_CONFIGS)
        if name == 'ddraw.ini':
            continue  # Never persist the session-only GDI template.
        if name == 'ProjectDiablo.json' and session.get('input_mode') in ('native', 'mapper'):
            incoming = restore_input_config(incoming, previous)
        if incoming != previous:
            changes.append((active, incoming, previous))
    backup = config / 'backups'
    no_links(backup)
    if backup.exists() and not backup.is_dir():
        raise LayoutError('invalid_layout')
    for active, _, _ in changes:
        old_backup = backup / active.name
        no_links(old_backup)
        if old_backup.exists():
            config_content(old_backup, active.name in JSON_CONFIGS)
        for path in (active.with_name(active.name + '.new'), old_backup.with_name(old_backup.name + '.new')):
            no_links(path)
            if path.exists():
                raise LayoutError('invalid_layout')
    if changes:
        checked_dir(backup)
    for active, incoming, previous in changes:
        atomic_bytes(backup / active.name, previous)
        atomic_bytes(active, incoming)
    return len(changes)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', required=True)
    parser.add_argument('--state', required=True)
    parser.add_argument('--data')
    parser.add_argument('--volatile-work', action='store_true')
    parser.add_argument('--sync-config', action='store_true')
    parser.add_argument('--get', choices=['wine', 'box', 'prefix', 'work', 'profile', 'swap_ab', 'input_mode', 'game_resolution'])
    args = parser.parse_args(argv)
    try:
        if args.sync_config:
            if args.get or args.volatile_work or args.data:
                raise LayoutError('invalid_layout')
            sync_config(pathlib.Path(args.port), pathlib.Path(args.state))
        elif args.get:
            result = read_object(pathlib.Path(args.state).absolute() / 'session-layout.json')
            value = result[args.get]
            print('1' if value is True else '0' if value is False else value)
        else:
            prepare(pathlib.Path(args.port), pathlib.Path(args.state), args.data, args.volatile_work,
                    input_mode=os.environ.get('PD2_INPUT_MODE', 'mapper'),
                    game_resolution=os.environ.get('PD2_GAME_RESOLUTION'))
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, tarfile.TarError, LayoutError) as error:
        reason = str(error) if isinstance(error, LayoutError) else 'invalid_layout'
        if reason not in ('invalid_layout', 'invalid_profile', 'insufficient_space', 'unsupported_runtime'):
            reason = 'invalid_layout'
        print('PD2_EVENT ' + json.dumps({'event': 'runtime_error', 'reason': reason, 'phase': 'preflight'}))
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
