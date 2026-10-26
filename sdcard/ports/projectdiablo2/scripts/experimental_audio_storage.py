"""Narrow audio-staging exception for the ROM-backed experimental port only.

Not a general permission to write below a port directory. Imported game files,
ordinary directories, symlinks, nested mounts and unbounded workspaces reject.
"""
import os
from pathlib import Path
import re

LIMIT = 16 * 1024 * 1024


def mount_types(content=None):
    if content is None:
        content = Path('/proc/self/mountinfo').read_text(encoding='utf-8')
    result = {}
    for line in content.splitlines():
        left, separator, right = line.partition(' - ')
        fields, detail = left.split(), right.split()
        if not separator or len(fields) < 6 or not detail:
            continue
        path = re.sub(r'\\(040|011|012|134)', lambda m: chr(int(m.group(1), 8)), fields[4])
        # Shadowed/duplicate mountpoints are ambiguous: do not grant an exception.
        result[path] = None if path in result else detail[0]
    return result


def accepts_workspace(port, prefix, work):
    """Caller must first apply audio_dsoal.plain/directory/verify_owner checks."""
    state = port / 'storage/mounted-state'
    target = work / 'ProjectD2'
    drive_c = prefix / 'drive_c'
    if (port.name not in ('projectdiablo2', 'projectdiablo2-sd') or prefix != state / 'wineprefix'
            or work != state / 'game'):
        return False
    try:
        uid = os.getuid()
        if uid == 0 or not os.path.ismount(state) or not os.path.ismount(work):
            return False
        for path in (state, target):
            if path.is_symlink():
                return False
        mounts = mount_types()
        if (mounts.get(str(state)) != 'ext4' or mounts.get(str(work)) != 'tmpfs'
                or any(str(p) in mounts or os.path.ismount(p) for p in (prefix, drive_c, target))):
            return False
        owner, pinfo, dinfo, winfo, tinfo, portinfo = [p.stat() for p in (state, prefix, drive_c, work, target, port)]
        if any(info.st_uid != uid for info in (owner, pinfo, dinfo, winfo, tinfo)):
            return False
        if (pinfo.st_dev != owner.st_dev or dinfo.st_dev != owner.st_dev
                or winfo.st_dev in (owner.st_dev, portinfo.st_dev) or tinfo.st_dev != winfo.st_dev):
            return False
        usage = os.statvfs(work)
        total = usage.f_blocks * (usage.f_frsize or usage.f_bsize)
        return 0 < total <= LIMIT and not (usage.f_flag & getattr(os, 'ST_RDONLY', 1))
    except (OSError, AttributeError, ValueError):
        return False
