"""Read-only storage inventory. Never imports or executes game launchers."""
import datetime
import json
import os
from pathlib import Path
import re
import subprocess


def unescape_mount(value):
    return re.sub(r'\\([0-7]{3})', lambda m: chr(int(m.group(1), 8)), value)


def parse_mounts(text):
    """Collapse bind mounts of one block device; retain shortest mountpoint."""
    result = {}
    for line in text.splitlines():
        left, separator, right = line.partition(' - ')
        before, after = left.split(), right.split()
        if not separator or len(before) < 6 or len(after) < 2:
            continue
        device = unescape_mount(after[1])
        if not device.startswith('/dev/') or device.startswith(('/dev/loop', '/dev/ram', '/dev/zram')):
            continue
        record = {'device': device, 'mount': unescape_mount(before[4]),
                  'key': before[2], 'fstype': after[0]}
        old = result.get(record['key'])
        if old is None or len(record['mount']) < len(old['mount']):
            result[record['key']] = record
    return list(result.values())


def space(path):
    usage = os.statvfs(str(path))
    unit = usage.f_frsize or usage.f_bsize
    return {'total': usage.f_blocks * unit, 'free': usage.f_bavail * unit}


def collect_partitions(home, errors):
    mounts = parse_mounts(Path('/proc/self/mountinfo').read_text())
    home_device = os.stat(str(home)).st_dev
    home_found = False
    rows = []
    for mount in mounts:
        try:
            mount.update(space(mount['mount']))
            mount['home'] = os.stat(mount['mount']).st_dev == home_device
            home_found = home_found or mount['home']
            rows.append(mount)
        except OSError as exc:
            errors.append('{}: {}'.format(mount['mount'], exc))
    if not home_found:
        # HOME can live on a non-block filesystem; never omit its capacity.
        row = {'device': 'HOME filesystem', 'mount': str(home), 'home': True}
        row.update(space(home))
        rows.append(row)
    return sorted(rows, key=lambda row: (not row['home'], row['mount']))


def component_info(name, active):
    if name.startswith('runtime-'):
        return 'Wine runtime', 'required' if not active.get('runtime') or name == active['runtime'] else 'old'
    if name.startswith('box86-'):
        return 'Box86 translator', 'required' if not active.get('box') or name == active['box'] else 'old'
    known = {'wineprefix': ('Production Wine prefix', 'required'),
             'compat': ('Compatibility cache', 'support'),
             'game': ('Session workspace', 'support'),
             'wine-launchers': ('Wine adapters', 'support'),
             'session-layout.json': ('Session layout metadata', 'support'),
             'session-layout.json.new': ('Pending layout metadata', 'support'),
             'session.lock': ('Session lock', 'support')}
    return known.get(name, (name, 'extra'))


def measure_paths(paths, errors):
    if not paths:
        return {}
    try:
        result = subprocess.run(['du', '-skx', '--'] + [str(p) for p in paths],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                universal_newlines=True, errors='replace', timeout=30,
                                env=dict(os.environ, LC_ALL='C'))
        sizes = {}
        for line in result.stdout.splitlines():
            size, separator, path = line.partition('\t')
            if separator and size.isdigit():
                sizes[path] = int(size) * 1024
        if result.returncode:
            errors.append('du could not measure every path: ' + result.stderr.strip()[:500])
        return sizes
    except (OSError, subprocess.TimeoutExpired) as exc:
        errors.append('Disk usage unavailable: {}'.format(exc))
        return {}


def collect_components(state, home, errors):
    active = {}
    try:
        layout = json.loads((state / 'session-layout.json').read_text())
        for field, key in (('wine', 'runtime'), ('box', 'box')):
            value = layout.get(field)
            if isinstance(value, str):
                relative = Path(value).relative_to(state)
                if relative.parts:
                    active[key] = relative.parts[0]
    except (OSError, ValueError, TypeError):
        pass
    if not state.is_dir():
        return [{'name': name, 'path': str(state / child), 'status': 'MISSING',
                 'size': None, 'category': 'required'} for name, child in
                (('Wine runtime', 'runtime-*'), ('Box86 translator', 'box86-*'),
                 ('Production Wine prefix', 'wineprefix'))]
    home_device = os.stat(str(home)).st_dev
    paths = sorted(state.iterdir(), key=lambda p: p.name)
    # Never traverse symlinks or live private RAM mounts as HOME disk usage.
    measure = [p for p in paths if not p.is_symlink() and p.lstat().st_dev == home_device]
    sizes = measure_paths(measure, errors)
    rows = []
    for path in paths:
        name, category = component_info(path.name, active)
        if path.is_symlink():
            status = 'LINK'
        elif path.lstat().st_dev != home_device:
            status = 'OTHER FS'
        else:
            status = 'PRESENT'
        rows.append({'name': name, 'path': str(path), 'status': status,
                     'size': sizes.get(str(path)), 'category': category})
    for prefix, label in (('runtime-', 'Wine runtime'), ('box86-', 'Box86 translator')):
        if not any(p.name.startswith(prefix) for p in paths):
            rows.append({'name': label, 'path': str(state / (prefix + '*')), 'status': 'MISSING',
                         'size': None, 'category': 'required'})
    if not any(p.name == 'wineprefix' for p in paths):
        rows.append({'name': 'Production Wine prefix', 'path': str(state / 'wineprefix'),
                     'status': 'MISSING', 'size': None, 'category': 'required'})
    order = {'required': 0, 'support': 1, 'old': 2, 'extra': 3}
    return sorted(rows, key=lambda r: (order[r['category']], r['name'], r['path']))


def collect():
    home = Path(os.environ['HOME']).absolute()
    state = home / '.local/share/pd2-r36s'
    errors = []
    return {'home': str(home), 'state': str(state),
            'utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'partitions': collect_partitions(home, errors),
            'components': collect_components(state, home, errors), 'errors': errors}


def report(data):
    lines = ['STORAGE CHECK', 'UTC: ' + data['utc'], 'HOME: ' + data['home'],
             '', 'MOUNTED STORAGE PARTITIONS (free = available to current user)']
    for row in data['partitions']:
        lines.append('{}{} at {}: total={} free={} bytes'.format(
            '[HOME] ' if row['home'] else '', row['device'], row['mount'], row['total'], row['free']))
    lines.extend(['', 'PD2 HOME COMPONENTS', 'State directory: ' + data['state'],
                  'PRESENT = exists, not a test of compatibility or integrity.',
                  'required = main runtime/prefix; support = generated helpers/cache;',
                  'extra/old = experiments, backups or inactive versions, not needed every launch.',
                  'Sizes: du allocated blocks, do not follow symlinks or cross filesystems.',
                  'Btrfs compression/reflinks can make physical exclusive usage differ.',
                  'Separate entries may share hard-linked data; do not assume sum is exclusive disk use.',
                  'Initial 700 MiB preflight is skipped once wineprefix/.initialized exists.', ''])
    for row in data['components']:
        size = 'unknown' if row['size'] is None else str(row['size']) + ' bytes'
        lines.append('{} | {} | {} | {} | {}'.format(
            row['name'], row['category'], row['status'], size, row['path']))
    lines.extend(['', 'ERRORS:'] + (data['errors'] or ['None']))
    lines.append('Read-only inventory. No game launched, files removed, or settings changed.')
    return '\n'.join(lines) + '\n'
