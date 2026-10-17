#!/usr/bin/env python3
"""Fetch one pinned MIT companion, never replace imported PD2 assets or execute it."""
import hashlib
import json
import pathlib
import struct
import urllib.request
import zipfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
VERSION = '7.1.0.0'
URL = 'https://github.com/FunkyFr3sh/cnc-ddraw/releases/download/v7.1.0.0/cnc-ddraw.zip'
ARCHIVE_SHA256 = '0b13ab89a64c9918189b1dadd449ef6ed3cb3b7b19cabd96d8adbd95505bb908'
DLL_SHA256 = '85e0f7d530dfda134793a57cb3e76b0287dcc96892ee57162dd68f47283b03a9'
DLL_SIZE = 411648


def publish(path, content):
    # No overwrite or following links, including any parent directory.
    for node in (path, *path.parents):
        if node.is_symlink():
            raise ValueError('Symlink refused')
    if path.exists():
        if not path.is_file() or path.read_bytes() != content:
            raise ValueError('Existing companion mismatch')
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('xb') as stream:
            stream.write(content)


def main():
    archive = ROOT / '.cache/cnc-ddraw-v7.1.0.0.zip'
    for node in (archive, *archive.parents):
        if node.is_symlink():
            raise ValueError('Symlink refused')
    if not archive.exists():
        archive.parent.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(URL, timeout=60) as response:
            content = response.read(4 * 1024 * 1024 + 1)
        if hashlib.sha256(content).hexdigest() != ARCHIVE_SHA256:
            raise ValueError('Archive hash mismatch')
        publish(archive, content)
    if hashlib.sha256(archive.read_bytes()).hexdigest() != ARCHIVE_SHA256:
        raise ValueError('Archive hash mismatch')
    with zipfile.ZipFile(archive) as source:
        info = source.getinfo('ddraw.dll')
        if info.file_size != DLL_SIZE:
            raise ValueError('DLL size mismatch')
        dll = source.read(info)
    if hashlib.sha256(dll).hexdigest() != DLL_SHA256:
        raise ValueError('DLL hash mismatch')
    pe = struct.unpack_from('<I', dll, 60)[0]
    if dll[:2] != b'MZ' or dll[pe:pe+4] != b'PE\0\0' or struct.unpack_from('<H', dll, pe+4)[0] != 0x14c:
        raise ValueError('Not x86 PE')
    out = ROOT / 'sdcard/ports/projectdiablo2/compat/cnc-ddraw'
    manifest = dict(version=VERSION, file='ddraw.dll', size=DLL_SIZE, sha256=DLL_SHA256,
                    archive_sha256=ARCHIVE_SHA256, source_url=URL, license='MIT')
    publish(out / 'ddraw.dll', dll)
    publish(out / 'manifest.json', (json.dumps(manifest, indent=2) + '\n').encode())
    print('Verified cnc-ddraw', VERSION, 'x86:', DLL_SIZE, DLL_SHA256)


if __name__ == '__main__':
    main()
