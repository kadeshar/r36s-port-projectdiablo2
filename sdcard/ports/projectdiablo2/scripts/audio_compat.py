#!/usr/bin/env python3
"""Publish the authenticated session-local ARM32 ALSA library experiment."""
import argparse
import json
import os
from pathlib import Path
import tempfile

from audio_native import artifact_bytes, _checked_work

LIBRARY_PATH = 'compat/alsa-legacy-armhf/libasound.so.2'
LIBRARY_SIZE = 590552
LIBRARY_SHA256 = '899e6f5164ab24fe2863aa22f102f3baa60dc4a0f9978e79ed4588fab57b78f8'
DIRECTORY = '.alsa-legacy-armhf'


def prepare(port, work):
    work = Path(work).absolute()
    _checked_work(work)
    library = artifact_bytes(port, LIBRARY_PATH, LIBRARY_SIZE, LIBRARY_SHA256)
    destination = work / DIRECTORY
    if os.path.lexists(destination):
        raise ValueError('stale library directory')
    with tempfile.TemporaryDirectory(prefix='.alsa-legacy-staging-', dir=work) as temporary:
        staged = Path(temporary) / 'libasound.so.2'
        with staged.open('xb') as output:
            output.write(library)
        staged.chmod(0o400)
        Path(temporary).rename(destination)
    return destination


class Parser(argparse.ArgumentParser):
    def error(self, _message):
        raise ValueError('invalid arguments')


def main(argv=None):
    parser = Parser(description=__doc__)
    parser.add_argument('--port', required=True)
    parser.add_argument('--work', required=True)
    try:
        args = parser.parse_args(argv)
        prepare(args.port, args.work)
        status, rc = 'legacy_armhf', 0
    except (OSError, ValueError, TypeError):
        status, rc = 'unavailable', 1
    print('PD2_EVENT ' + json.dumps(dict(event='session_probe', phase='launch', check='audio_library', status=status), separators=(',', ':')), flush=True)
    return rc


if __name__ == '__main__':
    raise SystemExit(main())
