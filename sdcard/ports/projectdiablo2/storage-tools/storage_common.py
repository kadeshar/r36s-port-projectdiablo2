"""Validation shared by the unprivileged entry and private-namespace adapter."""
import hashlib
import json
import os
from pathlib import Path
import stat


class StorageError(Exception):
    pass


def no_links(path):
    path = Path(path)
    for item in (path, *path.parents):
        try:
            mode = item.lstat().st_mode
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(mode):
            raise StorageError('Symlink in storage path: ' + str(item))
    return path


def regular(path):
    path = no_links(path)
    if not path.is_file():
        raise StorageError('Missing regular file: ' + str(path))
    return path


def digest(path):
    result = hashlib.sha256()
    with regular(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def ensure_state_image(port, info):
    state = port / info['state_file']
    if not state.exists():
        mkfs = None
        for candidate in ('/sbin/mke2fs', '/sbin/mkfs.ext4', '/usr/sbin/mke2fs', '/usr/sbin/mkfs.ext4'):
            if os.path.exists(candidate):
                mkfs = candidate
                break
        if not mkfs:
            mkfs = shutil.which('mke2fs') or shutil.which('mkfs.ext4')
        if not mkfs:
            raise StorageError(f"Missing state image {state} and mke2fs not found to create it.")
        state.parent.mkdir(parents=True, exist_ok=True)
        target_size = info.get('state_bytes', 1024**3)
        with open(str(state), 'wb') as f:
            f.seek(target_size - 1)
            f.write(b'\0')
        cmd = [str(mkfs), '-t', 'ext4', '-F', '-m0',
               '-O', '^64bit,^metadata_csum,^metadata_csum_seed,^orphan_file',
               str(state)]
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def validated(port):
    port = no_links(Path(port).absolute())
    if port.name not in ('projectdiablo2', 'projectdiablo2-sd') or not port.is_dir():
        raise StorageError('Expected isolated projectdiablo2 payload')
    info = json.loads(regular(port / 'storage-manifest.json').read_text(encoding='utf-8'))
    if (not isinstance(info, dict) or type(info.get('schema_version')) is not int or info['schema_version'] != 1
            or info.get('wine_file') != 'runtime/wine-8.0-x86.squashfs'
            or info.get('state_file') != 'storage/state.ext4'):
        raise StorageError('Unsupported storage manifest')
    wine = regular(port / info['wine_file'])
    state = port / info['state_file']
    if not state.exists():
        ensure_state_image(port, info)
    state = regular(state)
    if (type(info.get('wine_size')) is not int or wine.stat().st_size != info['wine_size']
            or digest(wine) != info.get('wine_sha256')):
        raise StorageError('Read-only Wine image integrity failed')
    if type(info.get('state_bytes')) is not int or not 1024**3 <= info['state_bytes'] <= 8 * 1024**3:
        raise StorageError('Unsupported state image size')
    if state.stat().st_size != info['state_bytes']:
        raise StorageError('State image size mismatch; refusing to mount')
    with state.open('rb') as stream:
        stream.seek(1080)
        if stream.read(2) != b'\x53\xef':
            raise StorageError('State image is not an ext filesystem')
    manifest = json.loads(regular(port / 'runtime-manifest.json').read_text(encoding='utf-8'))
    artifacts = manifest.get('artifacts') if isinstance(manifest, dict) else None
    names = {'wine-8.0-x86.tar.xz', 'box86', 'weston_pkg_0.2.squashfs', 'vc_redist.x86.exe'}
    if (not isinstance(artifacts, list) or len(artifacts) != 4
            or any(not isinstance(a, dict) for a in artifacts)
            or {a.get('file') for a in artifacts} != names):
        raise StorageError('Unsupported runtime manifest')
    pins = {}
    for item in artifacts:
        name = item['file']
        path = regular(port / 'runtime' / name)
        if path.stat().st_size != item.get('size') or digest(path) != item.get('sha256'):
            raise StorageError('Bundled runtime integrity failed: ' + name)
        pins[name] = item
    if info.get('source_wine_sha256') != pins['wine-8.0-x86.tar.xz']['sha256']:
        raise StorageError('Wine image source does not match authenticated archive')
    return port, info, pins


def check_game_exe(base):
    if not base.is_dir():
        return None
    for sub in ('Diablo II', 'diablo ii', 'diablo II', ''):
        folder = base / sub if sub else base
        if not folder.is_dir():
            continue
        for psub in ('ProjectD2', 'projectd2', 'projectD2', ''):
            pfolder = folder / psub if psub else folder
            if not pfolder.is_dir():
                continue
            for name in ('Game.exe', 'game.exe', 'GAME.EXE'):
                candidate = pfolder / name
                if candidate.is_file():
                    return regular(candidate)
    return None


def source_data(port):
    port = no_links(Path(port).absolute())
    # 1. Check local gamedata inside projectdiablo2-sd
    local = port / 'gamedata'
    if local.is_dir() and check_game_exe(local):
        return None
    # 2. Check adjacent production port projectdiablo2/gamedata
    adjacent = port.parent / 'projectdiablo2/gamedata'
    if adjacent.is_dir() and check_game_exe(adjacent):
        return no_links(adjacent)
    raise StorageError(
        f"Diablo II game files not found. Place 'Diablo II' into '{port / 'gamedata'}' "
        f"or '{adjacent}' (must contain ProjectD2/Game.exe)"
    )

