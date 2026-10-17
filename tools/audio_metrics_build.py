#!/usr/bin/env python3
"""Build source-instrumented ALSA 1.2.8 with the proven ARM32 time32 ABI.

--prepare authenticates local source and generates .state/audio-metrics-build.
Then tools/audio_metrics_build.sh runs in pd2-alsa-native-builder Docker image.
--finalize validates ELF/symbol surface against stock and publishes pins/notices.
Never changes stock legacy ALSA, runtime manifests, or shared launch scripts.
"""
import argparse
import bz2
import difflib
import hashlib
import json
from pathlib import Path
import re
import tarfile

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / '.state/audio-metrics-build'
SRC = STATE / 'alsa-lib-1.2.8'
DEST = ROOT / 'sdcard/ports/projectdiablo2/compat/audio-metrics'
SOURCE_SHA = '1ab01b74e33425ca99c2e36c0844fd6888273193bd898240fe8f93accbcbf347'
STOCK_SHA = '899e6f5164ab24fe2863aa22f102f3baa60dc4a0f9978e79ed4588fab57b78f8'
# Exact function names, not textual global replacements. Internal calls keep
# their public names and reach wrappers; TLS suppresses nested plugin counting.
SPECS = {
 'snd_pcm_open': ('pcmp, name, stream, mode', 'open'),
 'snd_pcm_open_lconf': ('pcmp, name, stream, mode, lconf', 'open'),
 'snd_pcm_open_fallback': ('pcmp, root, name, orig_name, stream, mode', 'open'),
 'snd_pcm_close': ('pcm', 'CLOSE'),
 'snd_pcm_hw_params': ('pcm, params', 'params'),
 'snd_pcm_writei': ('pcm, buffer, size', 'WRITE'),
 'snd_pcm_writen': ('pcm, bufs, size', 'WRITE'),
 'snd_pcm_mmap_begin': ('pcm, areas, offset, frames', 'MMAP_BEGIN'),
 'snd_pcm_mmap_commit': ('pcm, offset, frames', 'MMAP_COMMIT'),
 'snd_pcm_start': ('pcm', 'START'),
 'snd_pcm_prepare': ('pcm', 'PREPARE'),
 'snd_pcm_resume': ('pcm', 'RESUME'),
 'snd_pcm_drop': ('pcm', 'DROP'),
 'snd_pcm_drain': ('pcm', 'DRAIN'),
 'snd_pcm_recover': ('pcm, err, silent', 'RECOVER'),
}
MMAP_SPECS = {
 'snd_pcm_mmap_writei': ('pcm, buffer, size', 'WRITE'),
 'snd_pcm_mmap_writen': ('pcm, bufs, size', 'WRITE'),
}


def body_end(text, opening):
    """Find matching C body braces, excluding comments/string/char literals."""
    tokens = re.compile(r'/\*.*?\*/|//[^\n]*|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|[{}]', re.S)
    depth = 0
    for match in tokens.finditer(text, opening):
        if match.group() == '{':
            depth += 1
        elif match.group() == '}':
            depth -= 1
            if depth == 0:
                return match.end()
    raise ValueError('Unbalanced source body')


def patch_pcm(text, specs=None, core=True):
    specs = SPECS if specs is None else specs
    anchor = '#include "pcm_local.h"'
    if text.count(anchor) != 1:
        raise ValueError('ALSA source include anchor changed')
    header = 'pd2_audio_metrics_core.h' if core else 'audio_metrics_api.h'
    text = text.replace(anchor, anchor + '\n#include "' + header + '"')
    for name, (args, op) in specs.items():
        pattern = r'^(int|snd_pcm_sframes_t)\s+' + name + r'\(([^;{}]*)\)\s*\n\{'
        matches = list(re.finditer(pattern, text, re.M))
        if len(matches) != 1:
            raise ValueError('ALSA function anchor changed: ' + name)
        match = matches[0]
        end = body_end(text, match.end() - 1)
        result_type, signature = match.group(1), match.group(2)
        original = text[match.start():end]
        renamed = 'static ' + original.replace(name + '(', 'pd2_original_' + name + '(', 1)
        if op == 'open':
            action = 'if (pd2_result >= 0 && stream == SND_PCM_STREAM_PLAYBACK) pd2_am_open(*pcmp);'
        else:
            operation = 'PARAMS' if op == 'params' else op
            request = 'size' if op == 'WRITE' else '0'
            recover_error = 'err' if op == 'RECOVER' else '0'
            action = f'pd2_am_result(pcm, PD2_AM_{operation}, pd2_result, {request}, {recover_error});'
            if op == 'params':
                action += '\n        if (pd2_result >= 0) pd2_am_params(pcm, pcm->rate, pcm->channels, pcm->access, pcm->period_size, pcm->buffer_size);'
        wrapper = f'''\n\n/* PD2 metrics: exact public ABI; original function body is unchanged. */
{result_type} {name}({signature})
{{
    int pd2_outer = pd2_am_enter();
    {result_type} pd2_result = pd2_original_{name}({args});
    int pd2_errno = errno;
    if (pd2_outer) {{ {action} }}
    pd2_am_leave();
    errno = pd2_errno;
    return pd2_result;
}}'''
        text = text[:match.start()] + renamed + wrapper + text[end:]
    return text


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepared_inputs():
    return [STATE / 'alsa.tar', *(SRC / 'src/pcm' / name for name in
        ('pcm.c', 'pcm_mmap.c', 'pd2_audio_metrics_core.h', 'audio_metrics_api.h')),
        *(ROOT / 'tools' / name for name in ('audio_metrics_build.py', 'audio_metrics_build.sh',
          'audio_metrics_core.h', 'audio_metrics_api.h', 'audio_metrics_test.c',
          'audio_metrics_abi_test.c', 'alsa_legacy_abi.c'))]


def input_guard():
    return ''.join(sha(path) + '  /src/' + path.relative_to(ROOT).as_posix() + '\n' for path in prepared_inputs())


def prepare():
    archive = ROOT / 'sdcard/ports/projectdiablo2/compat/alsa-legacy-armhf/alsa-lib-1.2.8.tar.bz2'
    if sha(archive) != SOURCE_SHA:
        raise ValueError('ALSA source hash mismatch')
    STATE.mkdir(parents=True, exist_ok=True)
    DEST.mkdir(parents=True, exist_ok=True)
    (STATE / 'alsa.tar').write_bytes(bz2.decompress(archive.read_bytes()))
    # Reject archive traversal; data filter also bounds upstream's include symlinks.
    with tarfile.open(archive) as source:
        for member in source.getmembers():
            if member.name.startswith('/') or '..' in Path(member.name).parts:
                raise ValueError('Unsafe source archive member')
        source.extractall(STATE, filter='data')
    pcm = SRC / 'src/pcm/pcm.c'
    original = pcm.read_text(encoding='utf-8')
    patched = patch_pcm(original)
    pcm.write_text(patched, encoding='utf-8')
    diff = ''.join(difflib.unified_diff(original.splitlines(True), patched.splitlines(True), fromfile='a/src/pcm/pcm.c', tofile='b/src/pcm/pcm.c'))
    mmap = SRC / 'src/pcm/pcm_mmap.c'
    mmap_original = mmap.read_text(encoding='utf-8')
    mmap_patched = patch_pcm(mmap_original, MMAP_SPECS, core=False)
    mmap.write_text(mmap_patched, encoding='utf-8')
    diff += ''.join(difflib.unified_diff(mmap_original.splitlines(True), mmap_patched.splitlines(True), fromfile='a/src/pcm/pcm_mmap.c', tofile='b/src/pcm/pcm_mmap.c'))
    for local, target in (('audio_metrics_core.h', 'pd2_audio_metrics_core.h'), ('audio_metrics_api.h', 'audio_metrics_api.h')):
        (SRC / 'src/pcm' / target).write_bytes((ROOT / 'tools' / local).read_bytes())
        diff += ''.join(difflib.unified_diff([], (ROOT / 'tools' / local).read_text().splitlines(True), fromfile='/dev/null', tofile='b/src/pcm/' + target))
    (DEST / 'source.patch').write_text(diff, encoding='utf-8')
    (DEST / 'LICENSE.txt').write_bytes((SRC / 'COPYING').read_bytes())
    (STATE / 'prepared-inputs.sha256').write_text(input_guard(), encoding='utf-8', newline='\n')
    print('Prepared pinned source. Run Docker build script next.')


def finalize():
    artifact = DEST / 'libasound.so.2'
    content = artifact.read_bytes()
    if (STATE / 'prepared-inputs.sha256').read_text() != input_guard():
        raise ValueError('Prepared inputs changed after build')
    proof = (STATE / 'verified-artifact.sha256').read_text().split()
    if not proof or proof[0] != sha(artifact):
        raise ValueError('Artifact has not passed complete build tests')
    # ELF32 little-endian ARM EABI5 hard-float. Header flags hard-float bit 0x400.
    if content[:5] != b'\x7fELF\x01' or content[5] != 1 or int.from_bytes(content[18:20], 'little') != 40 or not int.from_bytes(content[36:40], 'little') & 0x400:
        raise ValueError('Wrong ELF ABI')
    stock = ROOT / 'sdcard/ports/projectdiablo2/compat/alsa-legacy-armhf/libasound.so.2'
    if sha(stock) != STOCK_SHA:
        raise ValueError('Stock compatibility provider changed')
    # Docker writes complete versioned defined-symbol lists; require equality.
    before = (STATE / 'stock-symbols.txt').read_text().splitlines()
    after = (STATE / 'metrics-symbols.txt').read_text().splitlines()
    if not before or set(before) != set(after):
        raise ValueError('Public ALSA versioned symbol surface mismatch')
    abi = (STATE / 'abi-test.txt').read_text()
    if 'PD2_AUDIO_ABI_OK' not in abi:
        raise ValueError('Missing ARM32 time32 ABI test')
    manifest = dict(schema=1, file='libasound.so.2', size=len(content), sha256=sha(artifact),
        upstream=dict(project='alsa-lib', version='1.2.8', source_sha256=SOURCE_SHA,
          source_url='https://www.alsa-project.org/files/pub/lib/alsa-lib-1.2.8.tar.bz2', license='LGPL-2.1-or-later'),
        base_provider=dict(file='compat/alsa-legacy-armhf/libasound.so.2', sha256=STOCK_SHA,
          relationship='Same pinned ALSA source and configure/time32 ABI, source-instrumented derivative; stock binary unchanged'),
        build=dict(command='python -B tools/audio_metrics_build.py --prepare; docker run --rm -v ROOT:/src pd2-alsa-native-builder sh /src/tools/audio_metrics_build.sh; python -B tools/audio_metrics_build.py --finalize',
          inputs_sha256={p: sha(ROOT / 'tools' / p) for p in ('audio_metrics_build.py','audio_metrics_build.sh','audio_metrics_core.h','audio_metrics_api.h','audio_metrics_test.c','audio_metrics_abi_test.c')},
          prepared_inputs_sha256=sha(STATE / 'prepared-inputs.sha256'), cflags='-Os -fno-ident (identical to stock compatibility provider)',
          source_patch_sha256=sha(DEST / 'source.patch'), abi='ELF32 ARM hard-float; time_t=4; sync_ptr=132; ioctl=0xc0844123',
          reproducibility='Sources/options pinned; existing builder apt toolchain packages are not bit-reproducibly pinned'),
        capture=dict(version=1, slots_per_process=8, bytes_per_process=262144, interval_ms=1000,
          transport='Inherited O_NONBLOCK write-only anonymous pipe; dedicated writer thread',
          scope='Top-level public ALSA playback PCM APIs in processes loading this library; nested plugin calls suppressed; first 8 successful opens per process',
          caveats=['Client-side negotiated PCM parameters, not necessarily hardware-slave parameters', 'EPIPE results and recover(-EPIPE) calls are observations, not unique underrun episodes', 'No audio samples, audible-quality verdict, or missing-data inference', 'Non-exec fork children disabled; exec loads initialize independently', 'Skipped try-lock updates/capacity tracked; abrupt termination can omit last snapshot']),
        tests=dict(arm_abi='passed', versioned_exports='identical to stock', r36s='not run'))
    (DEST / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(dict(size=len(content),sha256=sha(artifact))))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepare', action='store_true')
    parser.add_argument('--finalize', action='store_true')
    args = parser.parse_args()
    if args.prepare == args.finalize:
        parser.error('choose exactly one action')
    prepare() if args.prepare else finalize()
