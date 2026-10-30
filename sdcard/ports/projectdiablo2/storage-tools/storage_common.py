"""Validation shared by the unprivileged entry and private-namespace adapter."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile


class StorageError(Exception):
    pass


STAMP_FILE = 'runtime-verify.stamp'
STAMP_SCHEMA = 1
STAMP_MAX_BYTES = 65536


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
    target_size = info.get('state_bytes', 1024**3)
    if state.exists():
        try:
            if state.is_file() and state.stat().st_size == target_size:
                with state.open('rb') as stream:
                    stream.seek(1080)
                    if stream.read(2) == b'\x53\xef':
                        return
        except OSError:
            pass
        # Corrupted, zero-filled or incomplete image from earlier crash
        try:
            state.unlink()
        except OSError as exc:
            raise StorageError(f"Cannot remove invalid state image {state}: {exc}")

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
    tmp_state = state.with_name(state.name + '.tmp')
    if tmp_state.exists():
        try:
            tmp_state.unlink()
        except OSError:
            pass

    feature_candidates = [
        '^64bit,^metadata_csum,^metadata_csum_seed,^orphan_file',
        '^64bit,^metadata_csum,^metadata_csum_seed',
        '^64bit,^metadata_csum',
        '^64bit',
        None,
    ]

    try:
        with open(str(tmp_state), 'wb') as f:
            f.seek(target_size - 1)
            f.write(b'\0')
        last_err = 'mke2fs failed'
        formatted = False
        for feat in feature_candidates:
            cmd = [str(mkfs), '-t', 'ext4', '-F', '-m0']
            if feat:
                cmd.extend(['-O', feat])
            cmd.append(str(tmp_state))
            res = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, universal_newlines=True)
            if res.returncode == 0:
                formatted = True
                break
            err = res.stderr.strip() if res.stderr else f"exit code {res.returncode}"
            last_err = err
            if 'invalid filesystem option' not in err.lower():
                break
        if not formatted:
            raise StorageError(f"mke2fs failed: {last_err}")
        with open(str(tmp_state), 'rb') as f:
            f.seek(1080)
            if f.read(2) != b'\x53\xef':
                raise StorageError("Created state image failed ext superblock verification")
        tmp_state.replace(state)
    except Exception:
        if tmp_state.exists():
            try:
                tmp_state.unlink()
            except OSError:
                pass
        raise


def read_verify_stamp(port):
    """Read the write-verified integrity stamp; raise StorageError if absent."""
    stamp_path = port / 'logs' / STAMP_FILE
    try:
        if stamp_path.is_symlink() or stamp_path.stat().st_size > STAMP_MAX_BYTES:
            raise StorageError('Verification stamp missing or unreadable')
        stamp = json.loads(stamp_path.read_text(encoding='utf-8'))
    except StorageError:
        raise
    except (OSError, ValueError) as exc:
        raise StorageError('Verification stamp missing or unreadable: ' + str(exc))
    if (not isinstance(stamp, dict) or type(stamp.get('schema_version')) is not int
            or stamp['schema_version'] != STAMP_SCHEMA
            or not isinstance(stamp.get('wine'), dict)
            or not isinstance(stamp.get('artifacts'), dict)):
        raise StorageError('Unsupported verification stamp')
    return stamp


def write_verify_stamp(port, info, pins, wine_size):
    """Atomically publish a stamp after a full digest validation."""
    stamp = {
        'schema_version': STAMP_SCHEMA,
        'wine': {'size': wine_size, 'sha256': info.get('wine_sha256')},
        'artifacts': {name: {'size': pin.get('size'), 'sha256': pin.get('sha256')}
                      for name, pin in pins.items()},
        'state_bytes': info.get('state_bytes'),
    }
    stamp_path = port / 'logs' / STAMP_FILE
    stamp_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8',
                                         dir=str(stamp_path.parent),
                                         prefix=STAMP_FILE + '.', suffix='.tmp',
                                         delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(stamp, stream, indent=1, sort_keys=True)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(str(temporary), str(stamp_path))
        temporary = None
    finally:
        if temporary is not None:
            try:
                temporary.unlink()
            except OSError:
                pass


def validated(port, trust_stamp=False, write_stamp=False, trust_fallback_full=False):
    """Validate the storage payload and runtime artifacts.

    trust_stamp: accept a previously write-verified stamp (sizes only).
    trust_fallback_full: on a missing/stale stamp, run the full digest path
    instead of failing (used by in-session preflight; the session adapter
    fails closed because its launcher already validated the same launch).
    write_stamp: publish a fresh stamp after a full digest validation.
    """
    port = no_links(Path(port).absolute())
    if port.name not in ('projectdiablo2', 'projectdiablo2-sd') or not port.is_dir():
        raise StorageError('Expected isolated projectdiablo2 payload')
    info = json.loads(regular(port / 'storage-manifest.json').read_text(encoding='utf-8'))
    if (not isinstance(info, dict) or type(info.get('schema_version')) is not int or info['schema_version'] != 1
            or info.get('wine_file') != 'runtime/wine-8.0-x86.squashfs'
            or info.get('state_file') != 'storage/state.ext4'):
        raise StorageError('Unsupported storage manifest')
    wine = regular(port / info['wine_file'])
    ensure_state_image(port, info)
    state = regular(port / info['state_file'])
    if type(info.get('wine_size')) is not int or wine.stat().st_size != info['wine_size']:
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
    pins = {item['file']: item for item in artifacts}
    # trusted stays False until the stamp is read AND cross-checked against
    # both manifests; anything else falls through to the full digest path.
    trusted = False
    if trust_stamp:
        try:
            stamp = read_verify_stamp(port)
            # The stamp pins the same hashes as the manifests; a stale or
            # tampered stamp can never substitute for a full validation.
            if (stamp['wine'].get('size') != info.get('wine_size')
                    or stamp['wine'].get('sha256') != info.get('wine_sha256')
                    or stamp.get('state_bytes') != info.get('state_bytes')):
                raise StorageError('Verification stamp does not match storage manifest')
            for item in artifacts:
                entry = stamp['artifacts'].get(item['file'])
                if (not isinstance(entry, dict) or entry.get('size') != item.get('size')
                        or entry.get('sha256') != item.get('sha256')):
                    raise StorageError('Verification stamp does not match runtime manifest: ' + item['file'])
            trusted = True
        except StorageError:
            if not trust_fallback_full:
                raise
    if trusted:
        # Trusted fast path: sizes only, no digests. The stamp was written by a
        # full digest validation (storage_launcher --check or first preflight).
        for item in artifacts:
            path = regular(port / 'runtime' / item['file'])
            if path.stat().st_size != item.get('size'):
                raise StorageError('Bundled runtime size failed: ' + item['file'])
    else:
        if digest(wine) != info.get('wine_sha256'):
            raise StorageError('Read-only Wine image integrity failed')
        for item in artifacts:
            path = regular(port / 'runtime' / item['file'])
            if path.stat().st_size != item.get('size') or digest(path) != item.get('sha256'):
                raise StorageError('Bundled runtime integrity failed: ' + item['file'])
    if info.get('source_wine_sha256') != pins['wine-8.0-x86.tar.xz']['sha256']:
        raise StorageError('Wine image source does not match authenticated archive')
    if write_stamp:
        write_verify_stamp(port, info, pins, wine.stat().st_size)
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

