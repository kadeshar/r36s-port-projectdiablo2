#!/usr/bin/env python3
"""Build pinned x86 /MT DSOAL and OpenAL Soft for production WinMM audio.

No deployment, SSH, host playback, or production launcher changes. Run with
Python 3.12+, CMake >=3.21, VS2022 v14.44 and Windows SDK 10.0.22621.0.
"""
from __future__ import annotations

import argparse
import difflib
from datetime import datetime, timezone
import hashlib
import json
import shutil
import struct
import subprocess
import tarfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / '.state/audio-game-ab-build'
DEST = ROOT / 'sdcard/ports/projectdiablo2/compat/dsoal'
PINS = {
    'dsoal': '1cdd8df67f4f93ced64ddf8f9c70882560bbcd41',
    'openal-soft': 'd3875f333fb6abe2f39d82caca329414871ae53b',
}
ORIGINAL = 'ALCdevicePtr aldev{alcOpenDevice(drv_name)};'
REPLACEMENT = 'ALCdevicePtr aldev{alcOpenDevice(nullptr)}; // PD2 WinMM experiment: default output only.'


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def extract(archive: Path, target: Path) -> None:
    """Accept ordinary files/directories only, all below the pinned root."""
    with tarfile.open(archive, 'r:gz') as package:
        for member in package.getmembers():
            relative = Path(member.name)
            if relative.is_absolute() or '..' in relative.parts or ':' in member.name:
                raise RuntimeError(f'Unsafe archive path: {member.name}')
            resolved = (target / relative).resolve()
            if not resolved.is_relative_to(target.resolve()):
                raise RuntimeError(f'Archive escape: {member.name}')
            if not (member.isfile() or member.isdir()):
                raise RuntimeError(f'Unsupported archive member: {member.name}')
        package.extractall(target, filter='data')


def pe_info(path: Path) -> dict:
    """Read PE machine, named exports and direct DLL imports without executing it."""
    data = path.read_bytes()
    pe = struct.unpack_from('<I', data, 0x3c)[0]
    if data[pe:pe+4] != b'PE\0\0':
        raise RuntimeError(f'Not PE: {path}')
    machine, count = struct.unpack_from('<HH', data, pe+4)
    optional_size = struct.unpack_from('<H', data, pe+20)[0]
    optional = pe + 24
    if machine != 0x14c or struct.unpack_from('<H', data, optional)[0] != 0x10b:
        raise RuntimeError(f'Expected PE32 x86: {path}')
    sections = []
    for index in range(count):
        section = optional + optional_size + 40*index
        virtual_size, va, raw_size, raw = struct.unpack_from('<IIII', data, section+8)
        sections.append((va, max(virtual_size, raw_size), raw))
    def offset(rva):
        for va, size, raw in sections:
            if va <= rva < va+size:
                return raw+rva-va
        raise RuntimeError(f'Unmapped RVA {rva:x}')
    def text(rva):
        start = offset(rva)
        return data[start:data.index(b'\0', start)].decode('ascii')
    exports = []
    export_rva = struct.unpack_from('<I', data, optional+96)[0]
    if export_rva:
        directory = offset(export_rva)
        names_count = struct.unpack_from('<I', data, directory+24)[0]
        names = offset(struct.unpack_from('<I', data, directory+32)[0])
        exports = [text(struct.unpack_from('<I', data, names+4*i)[0]) for i in range(names_count)]
    imports = []
    import_rva = struct.unpack_from('<I', data, optional+104)[0]
    if import_rva:
        descriptor = offset(import_rva)
        while any(data[descriptor:descriptor+20]):
            imports.append(text(struct.unpack_from('<I', data, descriptor+12)[0]))
            descriptor += 20
    forbidden = ('vcruntime', 'msvcp', 'ucrtbase', 'api-ms-win-crt', 'msvcr')
    if any(name.lower().startswith(forbidden) for name in imports):
        raise RuntimeError(f'Dynamic CRT import in {path}: {imports}')
    return {'machine': '0x014c', 'format': 'PE32 x86', 'imports': sorted(imports),
            'exports': sorted(exports), 'sha256': digest(path), 'bytes': len(data)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-only', action='store_true')
    args = parser.parse_args()
    STATE.mkdir(parents=True, exist_ok=True)
    sources = DEST / 'sources'
    sources.mkdir(parents=True, exist_ok=True)
    build_utc = datetime.now(timezone.utc).isoformat()
    manifest = {'schema': 1, 'build_utc': build_utc, 'sources': {}, 'commands': [], 'artifacts': {}}
    for name, commit in PINS.items():
        url = f'https://codeload.github.com/kcat/{name}/tar.gz/{commit}'
        archive = sources / f'{name}-{commit}.tar.gz'
        if not archive.exists():
            print(f'Download {url}', flush=True)
            request = urllib.request.Request(url, headers={'User-Agent': 'pd2-audio-game-ab-builder'})
            with urllib.request.urlopen(request, timeout=120) as response:
                payload = response.read(64*1024*1024+1)
            if len(payload) > 64*1024*1024:
                raise RuntimeError('Source archive exceeds size limit')
            archive.write_bytes(payload)
        source = STATE / f'{name}-{commit}'
        if not source.exists():
            extract(archive, STATE)
        if not (source / 'CMakeLists.txt').is_file():
            raise RuntimeError(f'Archive does not contain pinned source root: {source}')
        manifest['sources'][name] = {'commit': commit, 'url': url,
            'archive': archive.name, 'sha256': digest(archive), 'bytes': archive.stat().st_size}
    modifications = [
        {'file': 'src/dsoundoal.cpp', 'original': ORIGINAL, 'replacement': REPLACEMENT},
        {'file': 'src/propset.cpp', 'original': '#include <deque>\n',
         'replacement': '#include <deque>\n#include <string>\n'},
    ]
    patches = []
    for modification in modifications:
        relative = modification['file']
        before, after = modification['original'], modification['replacement']
        source = STATE / f'dsoal-{PINS["dsoal"]}' / relative
        current = source.read_text(encoding='utf-8')
        if after in current:
            if current.count(after) != 1:
                raise RuntimeError(f'Compatibility patch repeated: {relative}')
            original = current.replace(after, before, 1)
            if original.count(before) != 1:
                raise RuntimeError(f'Compatibility patch original not unique: {relative}')
        elif current.count(before) == 1:
            original = current
            current = current.replace(before, after, 1)
            source.write_text(current, encoding='utf-8', newline='\n')
        else:
            raise RuntimeError(f'Compatibility patch expected exactly one original: {relative}')
        patches.append(''.join(difflib.unified_diff(original.splitlines(True), current.splitlines(True),
            fromfile=f'a/{relative}', tofile=f'b/{relative}')))
    (sources / 'dsoal-default-winmm-device.patch').write_text(''.join(patches), encoding='utf-8')
    shutil.copyfile(__file__, sources / Path(__file__).name)
    for name, license_name in [('dsoal', 'LICENSE'), ('openal-soft', 'COPYING')]:
        shutil.copyfile(STATE / f'{name}-{PINS[name]}' / license_name, DEST / f'{name}-LICENSE.txt')
    (DEST / 'NOTICE.txt').write_text(
        'Project Diablo 2 production audio: DSOAL / OpenAL Soft WinMM.\n'
        'DSOAL: Chris Robinson and contributors; LGPL 2.1 (see dsoal-LICENSE.txt).\n'
        'OpenAL Soft: OpenAL Soft authors and contributors; LGPL 2 or later '
        '(see openal-soft-LICENSE.txt and source file notices).\n'
        'Complete pinned upstream source archives, local patch and build script are in sources/.\n'
        f'Local modification: Project Diablo 2 port, {build_utc[:10]} UTC; DSOAL playback opens default\n'
        'OpenAL device instead of MMDevice endpoint GUID, since WinMM cannot accept GUID names.\n'
        'Compatibility fix: src/propset.cpp explicitly includes <string> for std::wstring.\n'
        'Both source changes are recorded in sources/dsoal-default-winmm-device.patch.\n'
        'Playback only: capture endpoint mapping is unchanged. No hardware/game compatibility\n'
        'claim. Users may replace these dynamically loaded DLLs with compatible modified builds.\n'
        'Static /MT refers only to Microsoft CRT; OpenAL remains a replaceable shared DLL.\n', encoding='utf-8')
    if args.source_only:
        (STATE / 'source-manifest.json').write_text(json.dumps(manifest, indent=2)+'\n', encoding='utf-8')
        print(json.dumps(manifest['sources'], indent=2))
        return
    common = ['-G', 'Visual Studio 17 2022', '-A', 'Win32', '-T', 'v143,version=14.44',
              '-DCMAKE_SYSTEM_VERSION=10.0.22621.0', '-DCMAKE_POLICY_VERSION_MINIMUM=3.5',
              '-DCMAKE_POLICY_DEFAULT_CMP0091=NEW', '-DCMAKE_MSVC_RUNTIME_LIBRARY=MultiThreaded']
    oal = ['-DFORCE_STATIC_VCRT=ON', '-DLIBTYPE=SHARED', '-DALSOFT_BUILD_ROUTER=OFF',
           '-DALSOFT_EAX=ON', '-DALSOFT_BACKEND_WINMM=ON', '-DALSOFT_REQUIRE_WINMM=ON',
           '-DALSOFT_BACKEND_WASAPI=OFF', '-DALSOFT_BACKEND_DSOUND=OFF',
           '-DALSOFT_BACKEND_PORTAUDIO=OFF', '-DALSOFT_BACKEND_SDL2=OFF',
           '-DALSOFT_BACKEND_WAVE=OFF', '-DALSOFT_UTILS=OFF', '-DALSOFT_EXAMPLES=OFF',
           '-DALSOFT_CPUEXT_SSE=ON', '-DALSOFT_CPUEXT_SSE2=ON',
           '-DALSOFT_CPUEXT_SSE3=OFF', '-DALSOFT_CPUEXT_SSE4_1=OFF',
           '-DALSOFT_CPUEXT_NEON=OFF', '-DALSOFT_UPDATE_BUILD_VERSION=OFF']
    def run(command):
        manifest['commands'].append(command)
        print(subprocess.list2cmdline(command), flush=True)
        # Inherit stdio: DSH sandbox cannot create captured child-process pipes.
        subprocess.run(command, check=True, cwd=ROOT)
    for name, target, options, output, deployed in [
        ('dsoal', 'dsound', [], 'dsound.dll', 'dsound.dll'),
        ('openal-soft', 'OpenAL', oal, 'OpenAL32.dll', 'dsoal-aldrv.dll')]:
        build = STATE / f'{name}-build'
        run(['cmake', '-S', str(STATE / f'{name}-{PINS[name]}'), '-B', str(build), *common, *options])
        run(['cmake', '--build', str(build), '--config', 'Release', '--target', target, '--parallel', '4'])
        binary = build / 'Release' / output
        info = pe_info(binary)
        required = ({'DirectSoundCreate', 'DirectSoundCreate8'} if name == 'dsoal'
                    else {'alcOpenDevice', 'alcGetProcAddress', 'alGetProcAddress'})
        if name == 'openal-soft':
            # Extension entry points need not be PE exports: DSOAL resolves them
            # through alcGetProcAddress. These requirements need a runtime probe.
            info['runtime_requirements'] = {
                'extensions': ['ALC_EXT_thread_local_context', 'AL_EXT_STATIC_BUFFER'],
                'extension_entry_points': ['alBufferDataStatic'],
                'entry_point_lookup': 'alcGetProcAddress(nullptr, name)',
                'validation': 'not verified by this build-only script',
            }
        if not required.issubset(info['exports']):
            raise RuntimeError(f'Missing required exports: {required-set(info["exports"])}')
        shutil.copyfile(binary, DEST / deployed)
        if digest(DEST / deployed) != info['sha256']:
            raise RuntimeError('Deployment copy digest mismatch')
        manifest['artifacts'][deployed] = {**info, 'built_path': binary.relative_to(ROOT).as_posix()}
    manifest['modification'] = {'changes': modifications,
        'patch': 'sources/dsoal-default-winmm-device.patch',
        'patch_sha256': digest(sources / 'dsoal-default-winmm-device.patch')}
    contract = {'schema_version': 1,
        'artifacts': [{'file': name, 'size': info['bytes'], 'sha256': info['sha256']}
                      for name, info in manifest['artifacts'].items()],
        'sources': [{'name': name, **info} for name, info in manifest['sources'].items()],
        'build_metadata': manifest}
    serialized = json.dumps(contract, indent=2)+'\n'
    (STATE / 'build-manifest.json').write_text(serialized, encoding='utf-8')
    (DEST / 'manifest.json').write_text(serialized, encoding='utf-8')
    print(json.dumps(manifest['artifacts'], indent=2))


if __name__ == '__main__':
    main()
