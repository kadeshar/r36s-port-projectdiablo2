#!/usr/bin/env python3
"""Read-only aggregate checks. Never open saves or emit paths/player names."""
import argparse
import json
import os
from pathlib import Path
import stat

LIMIT = 4096
CONFIG_LIMIT = 512 * 1024


def no_links(path):
    for node in (path, *path.parents):
        if stat.S_ISLNK(node.lstat().st_mode):
            raise ValueError()


def event(check, status, **fields):
    return dict(event='session_probe', phase='launch', check=check, status=status, **fields)


def save_directory(path):
    try:
        no_links(path)
        count = 0
        with os.scandir(path) as entries:
            for total, entry in enumerate(entries, 1):
                if total > LIMIT:
                    return event('saves_directory', 'limit')
                if entry.name.lower().endswith('.d2s') and entry.is_file(follow_symlinks=False):
                    count += 1
        return event('saves_directory', 'ready', count=count)
    except FileNotFoundError:
        return event('saves_directory', 'missing')
    except (OSError, ValueError):
        return event('saves_directory', 'unavailable')


def mapping(path, expected):
    try:
        no_links(path.parent)
        if not path.is_symlink():
            return event('save_mapping', 'invalid')
        no_links(expected)
        ready = path.resolve(strict=True) == expected.resolve(strict=True) and expected.is_dir()
        return event('save_mapping', 'ready' if ready else 'invalid')
    except (OSError, ValueError, RuntimeError):
        return event('save_mapping', 'unavailable')


def config_events(path):
    try:
        no_links(path)
        if not stat.S_ISREG(path.lstat().st_mode):
            raise ValueError()
        fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0))
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise ValueError()
            content = os.read(fd, CONFIG_LIMIT + 1)
        finally:
            os.close(fd)
        if len(content) > CONFIG_LIMIT:
            raise ValueError()
        obj = json.loads(content.decode('utf-8'))
        if not isinstance(obj, dict):
            raise ValueError()
        other = obj.get('classic_game_settings', {}).get('other', {})
        mode = obj.get('pd2_game_settings', {})
        if not isinstance(other, dict) or not isinstance(mode, dict):
            raise ValueError()
        save_path = other.get('save_path')
        status = 'canonical' if save_path == 'S:\\' else 'missing' if save_path is None else 'other'
        wasd, controller = mode.get('wasd_movement'), mode.get('controller_movement')
        movement = 'unknown'
        if type(wasd) is bool and type(controller) is bool:
            movement = 'mixed' if wasd and controller else 'emulated' if wasd else 'native' if controller else 'disabled'
        return [event('game_config', 'ready'), event('save_path', status), event('movement_mode', movement)]
    except FileNotFoundError:
        status = 'missing'
    except (OSError, ValueError, TypeError, AttributeError, RecursionError):
        status = 'invalid'
    return [event('game_config', status), event('save_path', 'unknown'), event('movement_mode', 'unknown')]


def snapshot(port, state):
    return [save_directory(port / 'saves'),
            mapping(state / 'wineprefix/dosdevices/s:', port / 'saves'),
            *config_events(state / 'game/ProjectD2/ProjectDiablo.json')]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=Path, required=True)
    parser.add_argument('--state', type=Path, required=True)
    args = parser.parse_args()
    for value in snapshot(args.port.absolute(), args.state.absolute()):
        print('PD2_EVENT ' + json.dumps(value, separators=(',', ':')), flush=True)


if __name__ == '__main__':
    main()
