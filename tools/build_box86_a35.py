#!/usr/bin/env python3
"""Source-authenticated Box86 Cortex-A35 side build; never replaces runtime.
Host: python tools/build_box86_a35.py --fetch (or --build)
Container: python3 tools/build_box86_a35.py --inside
Docker image must first be built using tools/box86-a35.Dockerfile.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
COMMIT = 'fa59e748f91cee8542cfc996214bc4d582e4d6dd'
SOURCE_SHA256 = 'ed172675183984cc8d65d3fb8f795c32aae3d85a05511f0f22524cda8f801a26'
SOURCE_SIZE = 3522734
URL = 'https://codeload.github.com/ptitSeb/box86/tar.gz/' + COMMIT
ARCHIVE = ROOT / '.state/box86-a35/source.tar.gz'
DEST = ROOT / 'sdcard/ports/projectdiablo2/compat/box86-a35'
IMAGE = 'pd2-box86-a35-builder'
FLAGS = '-march=armv8-a -mtune=cortex-a35 -mfpu=neon-fp-armv8 -mfloat-abi=hard -marm'
OLD_FLAGS = '-marm -mcpu=cortex-a35 -mfpu=neon-vfpv3 -march=armv8-a+crc+simd+crypto -mfloat-abi=hard'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source():
    if ARCHIVE.is_symlink() or not ARCHIVE.is_file() or ARCHIVE.stat().st_size != SOURCE_SIZE or digest(ARCHIVE) != SOURCE_SHA256:
        raise ValueError('source authentication failed')


def fetch():
    ARCHIVE.parent.mkdir(parents=True, exist_ok=True)
    if ARCHIVE.exists():
        source()
        return
    data = urllib.request.urlopen(URL, timeout=60).read(SOURCE_SIZE + 1)
    if len(data) != SOURCE_SIZE or hashlib.sha256(data).hexdigest() != SOURCE_SHA256:
        raise ValueError('download authentication failed')
    with ARCHIVE.open('xb') as stream:
        stream.write(data)


def output(*command, **kwargs):
    return subprocess.check_output(command, text=True, stderr=subprocess.STDOUT, **kwargs).strip()


def inside():
    source()
    DEST.mkdir(parents=True, exist_ok=True)
    state = ARCHIVE.parent
    with tempfile.TemporaryDirectory(prefix='build-', dir=state) as temporary:
        folder = Path(temporary)
        with tarfile.open(ARCHIVE) as archive:
            for member in archive.getmembers():
                p = Path(member.name)
                if p.is_absolute() or '..' in p.parts or not (member.isfile() or member.isdir()):
                    raise ValueError('unsafe archive member')
            archive.extractall(folder)
        src = folder / ('box86-' + COMMIT)
        cmake = src / 'CMakeLists.txt'
        original = cmake.read_text()
        if original.count(OLD_FLAGS) != 2:
            raise ValueError('source patch anchor changed')
        cmake.write_text(original.replace(OLD_FLAGS, FLAGS))
        # Authenticated archive has no .git. NOGIT alone does not populate git_head.h.
        text = cmake.read_text()
        # Replace only command substitution, preserving upstream CMake escaping.
        if text.count('$(git rev-parse --short HEAD)') != 2:
            raise ValueError('revision anchor changed')
        cmake.write_text(text.replace('$(git rev-parse --short HEAD)', COMMIT[:7]))
        build = folder / 'out'
        configure = ['cmake', '-S', str(src), '-B', str(build), '-DCMAKE_TOOLCHAIN_FILE=' + str(ROOT / 'tools/box86-a35-toolchain.cmake'), '-DGOA_CLONE=ON', '-DCMAKE_BUILD_TYPE=Release', '-DNOGIT=OFF', '-DNO_LIB_INSTALL=ON', '-DNO_CONF_INSTALL=ON']
        subprocess.run(configure, check=True)
        subprocess.run(['cmake', '--build', str(build), '--parallel', '2'], check=True)
        binary = build / 'box86'
        subprocess.run(['arm-linux-gnueabihf-strip', '--strip-unneeded', str(binary)], check=True)
        header = output('arm-linux-gnueabihf-readelf', '-h', str(binary))
        attributes = output('arm-linux-gnueabihf-readelf', '-A', str(binary))
        program = output('arm-linux-gnueabihf-readelf', '-l', str(binary))
        dynamic = output('arm-linux-gnueabihf-readelf', '-d', str(binary))
        versions = output('arm-linux-gnueabihf-readelf', '--version-info', str(binary))
        if 'ELF32' not in header or 'ARM' not in header or 'hard-float ABI' not in header or 'Tag_ABI_VFP_args: VFP registers' not in attributes or '/lib/ld-linux-armhf.so.3' not in program:
            raise ValueError('invalid ARMhf artifact')
        glibc = sorted(set(re.findall(r'GLIBC_(\d+\.\d+(?:\.\d+)?)', versions)), key=lambda s: tuple(map(int, s.split('.'))))
        if not glibc or tuple(map(int, glibc[-1].split('.'))) > (2, 31):
            raise ValueError('glibc floor exceeds bullseye')
        env = dict(os.environ, BOX86_LOG='0', BOX86_NORCFILES='1', BOX86_DYNAREC='0')
        version_smoke = output('qemu-arm', '-L', '/usr/arm-linux-gnueabihf', str(binary), '-v', env=env, timeout=30)
        if COMMIT[:7] not in version_smoke or 'Dynarec' not in version_smoke:
            raise ValueError('built revision or dynarec identity missing')
        # Upstream test01 is a tiny supplied i386 ELF exercising syscall startup.
        smoke = output('qemu-arm', '-L', '/usr/arm-linux-gnueabihf', str(binary), str(src / 'tests/test01'), env=env, timeout=30)
        reference = (src / 'tests/ref01.txt').read_text().strip()
        if smoke != reference:
            raise ValueError('upstream interpreter smoke differs: ' + repr(smoke))
        tools = {name: output(*cmd).splitlines()[0] for name, cmd in {
            'gcc': ['arm-linux-gnueabihf-gcc', '--version'], 'ld': ['arm-linux-gnueabihf-ld', '--version'], 'cmake': ['cmake', '--version'], 'qemu': ['qemu-arm', '--version']}.items()}
        packages = output('dpkg-query', '-W', '-f=${Package}=${Version}\n').splitlines()
        dest = DEST / 'box86'
        shutil.copyfile(binary, dest)
        dest.chmod(0o755)
        shutil.copyfile(src / 'LICENSE', DEST / 'LICENSE.txt')
        manifest = {'schema': 1, 'variant': 'a35', 'file': 'box86', 'size': dest.stat().st_size, 'sha256': digest(dest),
            'source': {'project': 'ptitSeb/box86', 'commit': COMMIT, 'url': URL, 'archive_size': SOURCE_SIZE, 'archive_sha256': SOURCE_SHA256, 'license': 'MIT'},
            'build': {'profile': 'GOA_CLONE with optional ISA extensions removed', 'flags': FLAGS, 'type': 'Release stripped', 'revision': COMMIT[:7], 'toolchain': tools, 'packages': packages,
                'recipe_sha256': {p.name: digest(p) for p in [ROOT / 'tools/build_box86_a35.py', ROOT / 'tools/box86-a35.Dockerfile', ROOT / 'tools/box86-a35-toolchain.cmake']},
                'reproducibility': 'Source and recipe pinned; apt packages recorded, not pinned. Bit-for-bit reproducibility not claimed.'},
            'validation': {'elf': 'ELF32 little-endian ARM EABI5 hard-float', 'interpreter': '/lib/ld-linux-armhf.so.3', 'glibc_versions': glibc,
                'needed': re.findall(r'Shared library: \[(.*?)\]', dynamic), 'attributes': attributes.splitlines(), 'qemu_version': version_smoke, 'qemu_test01': 'passed (interpreter, DYNAREC=0)', 'physical_r36s': 'not run', 'dynarec_device': 'not validated'}}
        (DEST / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
        print(json.dumps({'size': manifest['size'], 'sha256': manifest['sha256'], 'toolchain': tools, 'glibc_max': glibc[-1]}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--fetch', action='store_true')
    group.add_argument('--inside', action='store_true')
    group.add_argument('--build', action='store_true')
    args = parser.parse_args()
    if args.fetch:
        fetch()
    elif args.inside:
        inside()
    else:
        fetch()
        # Inherit stdio: no named-pipe output capture in confined host processes.
        subprocess.run(['docker', 'run', '--rm', '--network=none', '--mount', 'type=bind,src=' + str(ROOT) + ',dst=/project', IMAGE, 'python3', 'tools/build_box86_a35.py', '--inside'], check=True)


if __name__ == '__main__':
    main()
