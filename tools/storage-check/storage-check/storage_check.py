"""Collect as normal user; give only native display UI elevated access."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from storage_data import collect, report


def write_report(target, content, append=False):
    flags = os.O_WRONLY | getattr(os, 'O_NOFOLLOW', 0)
    flags |= os.O_APPEND if append else os.O_CREAT | os.O_TRUNC
    if target.is_symlink():
        raise OSError('Report destination is a symlink')
    with os.fdopen(os.open(str(target), flags, 0o600), 'w', encoding='utf-8') as output:
        output.write(content)


def show(data, log_path):
    with tempfile.TemporaryDirectory(prefix='storage-check-ui-') as temp:
        payload = Path(temp) / 'data.json'
        payload.write_text(json.dumps(data), encoding='utf-8')
        command = [sys.executable, '-B', '-u', str(Path(__file__).with_name('storage_ui.py')), str(payload)]
        if os.getuid() != 0:
            command = ['sudo', '-n'] + command
        # No pipes to leave blocked/orphaned privileged renderers. sudo supervises
        # native UI in foreground and forwards interactive termination signals.
        if log_path.is_symlink():
            raise OSError('UI log destination is a symlink')
        flags = os.O_RDWR | os.O_CREAT | os.O_TRUNC | getattr(os, 'O_NOFOLLOW', 0)
        with os.fdopen(os.open(str(log_path), flags, 0o600), 'w+b') as log:
            result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT)
            if result.returncode:
                log.seek(0)
                raise OSError('Native viewer exited {}:\n{}'.format(
                    result.returncode, log.read().decode('utf-8', errors='replace')[-5000:]))


def main():
    base = Path(sys.argv[1]).resolve()
    target = base / 'storage-check-report.txt'
    try:
        data = collect()
        content = report(data)
        write_report(target, content)
        print(content, end='')
        print('Saved report: {}'.format(target))
        if '--report-only' not in sys.argv[2:]:
            show(data, base / 'storage-check-ui.log')
    except (OSError, ValueError) as exc:
        error = '\nSTORAGE CHECK ERROR: {}\n'.format(exc)
        print(error, file=sys.stderr)
        try:
            write_report(target, error, append=True)
        except OSError:
            pass
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
