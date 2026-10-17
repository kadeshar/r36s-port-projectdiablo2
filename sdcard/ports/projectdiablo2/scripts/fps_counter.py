#!/usr/bin/env python3
"""Legacy manual /fps sidecar (not used by the 0.1.17 game launcher).

The active FPS COUNTER option now uses fps_renderer.py and a renderer HUD.
This compatibility tool remains pinned for old explicit test invocations only.

Use Select+R3 or F10 ONLY IN A RUNNING GAME, with chat/text fields closed.
The helper cannot distinguish gameplay from menus: it never types automatically.
Preparation requires a trusted, quiescent port/session tree (as with xinput_result).
"""
import argparse
import hashlib
import os
from pathlib import Path
import stat
import subprocess
import sys
import time

FPS_SIZE = 84480
FPS_SHA256 = 'e6ed9a039039340479d5bedfa17f627e7b00ea43daeeb54313c814124ae0d4ca'


def _linked(info):
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, 'st_file_attributes', 0)
        & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400))


def _absolute(value):
    path = Path(value)
    # Never normalize through potentially linked ancestors.
    if '..' in path.parts:
        raise ValueError('unsafe layout')
    return path if path.is_absolute() else Path.cwd() / path


def _directory(path):
    for item in (*reversed(path.parents), path):
        info = item.lstat()
        if _linked(info) or not stat.S_ISDIR(info.st_mode):
            raise ValueError('unsafe layout')


def _source(path):
    _directory(path.parent)
    info = path.lstat()
    if (_linked(info) or not stat.S_ISREG(info.st_mode)
            or info.st_nlink != 1 or info.st_size != FPS_SIZE):
        raise ValueError('invalid helper')
    return info


def _identity(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)


def prepare_counter(port, work):
    """Authenticate bounded bytes, then exclusively create the fixed session link.

    Reject symlink/reparse ancestors, hardlinked source, and ALL stale target
    entries (including dangling links). Never replace/delete an existing file.
    No config or input content is read. No output/result file is produced.
    """
    source = _absolute(port) / 'compat/fps-hotkey/fps-hotkey.exe'
    directory = _absolute(work) / 'ProjectD2'
    target = directory / 'pd2-fps-hotkey.exe'
    before = _source(source)
    flags = (os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0)
             | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NONBLOCK', 0))
    fd = os.open(source, flags)
    try:
        actual = os.fstat(fd)
        if (not stat.S_ISREG(actual.st_mode) or actual.st_nlink != 1
                or _identity(actual) != _identity(before)):
            raise ValueError('invalid helper')
        with os.fdopen(fd, 'rb') as reader:
            fd = None
            data = reader.read(FPS_SIZE + 1)
        after = _source(source)
        if (_identity(before) != _identity(after) or len(data) != FPS_SIZE
                or hashlib.sha256(data).hexdigest() != FPS_SHA256):
            raise ValueError('invalid helper')
    finally:
        if fd is not None:
            os.close(fd)
    _directory(directory)
    if os.path.lexists(target):
        raise ValueError('stale helper')
    # symlink_to is exclusive: a racing existing entry is refused by the OS.
    target.symlink_to(source)


# A symmetric name for callers already using xinput_result.prepare_probe.
prepare_probe = prepare_counter


def launch_counter(port, work, game_pid, command):
    """Optional owned sidecar; never run on the synchronous game startup path.

    Let the game explorer establish its named desktop first. This is a startup
    grace period, not proof that a slow device already has a visible game window.
    Bound preparation separately, and do not start Wine after the game exits.
    exec preserves the sidecar PID/process group for run-game.sh cleanup.
    """
    if game_pid <= 1 or not command:
        raise ValueError('invalid arguments')
    time.sleep(10)
    os.kill(game_pid, 0)
    subprocess.run([sys.executable, '-B', str(Path(__file__).resolve()),
                    '--prepare', '--port', str(port), '--work', str(work)],
                   timeout=10, check=True, stdout=subprocess.DEVNULL,
                   stderr=subprocess.DEVNULL)
    os.kill(game_pid, 0)
    print('PD2_EVENT {"event":"session_probe","phase":"launch",'
          '"check":"fps_counter","status":"hotkey"}', flush=True)
    os.execvpe(command[0], command, os.environ)


class _Parser(argparse.ArgumentParser):
    def error(self, _message):
        raise ValueError('invalid arguments')


def main(argv=None, stdout=None):
    stdout = sys.stdout if stdout is None else stdout
    parser = _Parser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--prepare', action='store_true')
    mode.add_argument('--launch', action='store_true')
    parser.add_argument('--game-pid', type=int)
    parser.add_argument('--port', required=True)
    parser.add_argument('--work', required=True)
    parser.add_argument('command', nargs=argparse.REMAINDER)
    try:
        args = parser.parse_args(argv)
        if args.launch:
            command = args.command[1:] if args.command[:1] == ['--'] else []
            if args.game_pid is None:
                raise ValueError('invalid arguments')
            launch_counter(args.port, args.work, args.game_pid, command)
        else:
            if args.game_pid is not None or args.command:
                raise ValueError('invalid arguments')
            prepare_counter(args.port, args.work)
        return 0
    except (OSError, ValueError, TypeError, RecursionError, subprocess.SubprocessError):
        stdout.write('PD2_EVENT {"event":"session_probe","phase":"launch",'
                     '"check":"fps_counter","status":"unavailable"}\n')
        stdout.flush()
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
