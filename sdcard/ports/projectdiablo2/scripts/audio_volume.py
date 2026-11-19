#!/usr/bin/env python3
"""Hardware and system volume management for PD2.

Ensures game starts at system volume level on Batocera/Knulli rather than
blasting at 100% hardware maximum. Never modifies DAC/digital preamp registers.
Saves initial hardware and system volume state at launch and cleanly restores
it upon game shutdown, ensuring the console master volume is never altered on exit.
"""
import json
import os
from pathlib import Path
import struct
import subprocess
import sys

TARGET_KEYWORDS = ('master', 'playback', 'line out', 'lineout', 'headphone', 'speaker', 'pcm', 'softvol')
EXCLUDE_KEYWORDS = ('capture', 'mic', 'line in', 'input', 'record', 'digital', 'dac')

_cached_controls = None

EV_KEY = 0x01
EV_SIZE = struct.calcsize('llHHI') if struct.calcsize('l') == 4 else struct.calcsize('qqHHI')


def _clean_env():
    """Environment without private ALSA_CONFIG_PATH for system tools like batocera-audio."""
    env = os.environ.copy()
    env.pop('ALSA_CONFIG_PATH', None)
    return env


def get_system_volume():
    """Query system master volume (0-100) on Batocera/Knulli, or None if unavailable."""
    try:
        res = subprocess.run(['batocera-audio', 'getSystemVolume'],
                             capture_output=True, text=True, timeout=1, env=_clean_env())
        if res.returncode == 0:
            out = res.stdout.strip()
            if out.isdigit():
                return max(0, min(100, int(out)))
    except Exception:
        pass

    for conf_path in (Path('/userdata/system/batocera.conf'), Path('/userdata/system/knulli.conf')):
        if conf_path.is_file():
            try:
                for line in conf_path.read_text(encoding='utf-8', errors='ignore').splitlines():
                    line = line.strip()
                    if line.startswith('audio.volume='):
                        val = line.split('=', 1)[1].strip()
                        if val.isdigit():
                            return max(0, min(100, int(val)))
            except Exception:
                pass

    return None


def get_playback_controls(force_refresh=False):
    """Discover active ALSA playback volume controls across target cards.

    Returns list of (card_args, control_name, is_cset).
    Excludes digital DAC preamp controls to preserve volume dynamics.
    """
    global _cached_controls
    if _cached_controls is not None and not force_refresh:
        return _cached_controls

    controls = []
    seen = set()

    # Cards to probe: default card first (respects ALSA_CONFIG_PATH if set),
    # then explicit cards: 0, audiocodec (Allwinner), rk817 (Rockchip)
    card_candidates = [[], ['-c', '0'], ['-c', 'audiocodec'], ['-c', 'rk817']]
    for card_arg in card_candidates:
        try:
            out = subprocess.run(['amixer'] + card_arg + ['scontrols'],
                                 capture_output=True, text=True, timeout=1)
            if out.returncode == 0:
                for line in out.stdout.splitlines():
                    if "'" in line:
                        ctl = line.split("'")[1]
                        ctl_lower = ctl.lower()
                        if any(k in ctl_lower for k in TARGET_KEYWORDS) and not any(x in ctl_lower for x in EXCLUDE_KEYWORDS):
                            key = (tuple(card_arg), ctl)
                            if key not in seen:
                                seen.add(key)
                                controls.append((card_arg, ctl, False))
        except Exception:
            pass

    # Fallback: if no scontrols found, try raw controls (cset)
    if not controls:
        for card_arg in card_candidates:
            try:
                out = subprocess.run(['amixer'] + card_arg + ['controls'],
                                     capture_output=True, text=True, timeout=1)
                if out.returncode == 0:
                    for line in out.stdout.splitlines():
                        if "name='" in line:
                            ctl = line.split("name='")[1].split("'")[0]
                            ctl_lower = ctl.lower()
                            if any(k in ctl_lower for k in TARGET_KEYWORDS) and not any(x in ctl_lower for x in EXCLUDE_KEYWORDS) and 'volume' in ctl_lower:
                                key = (tuple(card_arg), ctl)
                                if key not in seen:
                                    seen.add(key)
                                    controls.append((card_arg, ctl, True))
            except Exception:
                pass

    if controls:
        _cached_controls = controls
    return controls


def _run_amixer_sset(card_arg, ctl, val):
    """Run amixer sset, trying unmute first and falling back without unmute."""
    res = subprocess.run(['amixer'] + card_arg + ['sset', ctl, val, 'unmute'],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=1)
    if res.returncode != 0:
        res = subprocess.run(['amixer'] + card_arg + ['sset', ctl, val],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=1)
    return res.returncode == 0


def set_volume_pct(vol_pct):
    """Set absolute volume percentage (0-100) on active playback controls and Batocera."""
    vol_pct = max(0, min(100, int(vol_pct)))
    controls = get_playback_controls()
    success = False
    for card_arg, ctl, is_cset in controls:
        try:
            if is_cset:
                res = subprocess.run(['amixer'] + card_arg + ['cset', f"name='{ctl}'", f'{vol_pct}%'],
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=1)
                if res.returncode == 0:
                    success = True
            else:
                if _run_amixer_sset(card_arg, ctl, f'{vol_pct}%'):
                    success = True
        except Exception:
            pass

    # Keep Batocera/Knulli system volume in sync
    try:
        subprocess.run(['batocera-audio', 'setSystemVolume', str(vol_pct)],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=1, env=_clean_env())
    except Exception:
        pass

    return success


def adjust_volume(delta):
    """Adjust hardware volume by delta percentage (+/-5) smoothly on playback controls."""
    sign = '+' if delta > 0 else '-'
    val = f'{abs(delta)}%{sign}'
    controls = get_playback_controls()
    success = False
    for card_arg, ctl, is_cset in controls:
        try:
            if is_cset:
                res = subprocess.run(['amixer'] + card_arg + ['cset', f"name='{ctl}'", val],
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=1)
                if res.returncode == 0:
                    success = True
            else:
                if _run_amixer_sset(card_arg, ctl, val):
                    success = True
        except Exception:
            pass

    # Sync Batocera/Knulli system volume
    try:
        curr = get_system_volume()
        if curr is not None:
            new_vol = max(0, min(100, curr + delta))
            subprocess.run(['batocera-audio', 'setSystemVolume', str(new_vol)],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=1, env=_clean_env())
        else:
            subprocess.run(['batocera-audio', 'setSystemVolume', f'{sign}{abs(delta)}'],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=1, env=_clean_env())
    except Exception:
        pass

    return success


def save_volume_state(path):
    """Snapshot initial system volume and ALSA control states for restoration upon game exit."""
    state = {'system_volume': get_system_volume(), 'controls': []}
    for card_arg, ctl, is_cset in get_playback_controls():
        try:
            cmd = ['amixer'] + card_arg + (['cget', f"name='{ctl}'"] if is_cset else ['sget', ctl])
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=1)
            if res.returncode == 0:
                val = None
                for line in res.stdout.splitlines():
                    if ': values=' in line:
                        val = line.split(': values=', 1)[1].strip()
                        break
                    elif '[' in line and '%]' in line:
                        for token in line.split():
                            if token.startswith('[') and token.endswith('%]'):
                                val = token[1:-1]
                                break
                        if val:
                            break
                state['controls'].append({
                    'card_arg': card_arg,
                    'control': ctl,
                    'is_cset': is_cset,
                    'value': val,
                })
        except Exception:
            pass
    try:
        Path(path).write_text(json.dumps(state, indent=2), encoding='utf-8')
        return True
    except Exception:
        return False


def restore_volume_state(path):
    """Restore initial system volume and ALSA controls from saved snapshot."""
    p = Path(path)
    if not p.is_file():
        return False
    try:
        data = json.loads(p.read_text(encoding='utf-8'))
    except Exception:
        return False

    sys_vol = data.get('system_volume')
    if sys_vol is not None:
        try:
            subprocess.run(['batocera-audio', 'setSystemVolume', str(sys_vol)],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=1, env=_clean_env())
        except Exception:
            pass

    for item in data.get('controls', []):
        card_arg = item.get('card_arg', [])
        ctl = item.get('control')
        is_cset = item.get('is_cset', False)
        val = item.get('value')
        if not ctl or val is None:
            continue
        try:
            val_arg = f'{val}%' if (isinstance(val, str) and val.isdigit()) else str(val)
            if is_cset:
                subprocess.run(['amixer'] + card_arg + ['cset', f"name='{ctl}'", val_arg],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=1)
            else:
                _run_amixer_sset(card_arg, ctl, val_arg)
        except Exception:
            pass

    try:
        p.unlink()
    except Exception:
        pass
    return True


def init_volume():
    """Sync system master volume to hardware ALSA controls before game launch."""
    vol = get_system_volume()
    if vol is not None:
        set_volume_pct(vol)
        print('PD2_EVENT ' + json.dumps({'event': 'session_probe', 'phase': 'launch',
                                        'check': 'audio_volume_init', 'status': 'synced',
                                        'level': vol}, separators=(',', ':')), flush=True)
        return True
    print('PD2_EVENT ' + json.dumps({'event': 'session_probe', 'phase': 'launch',
                                    'check': 'audio_volume_init', 'status': 'preserved'},
                                   separators=(',', ':')), flush=True)
    return False


def _bitmap(text, width=64):
    value = 0
    for chunk in text.strip().split():
        for word in chunk.split(':'):
            if word:
                value = (value << width) | int(word, 16)
    return value


def _bits_set(mask, *bits):
    return all(bool(mask & (1 << bit)) for bit in bits)


def find_volume_devices(root='/sys/class/input', exclude_path=None):
    """Find input event devices with KEY_VOLUMEDOWN (114) and KEY_VOLUMEUP (115)."""
    vol_devs = []
    root_path = Path(root)
    for event in sorted(root_path.glob('event[0-9]*')):
        dev_path = '/dev/input/' + event.name
        if dev_path == exclude_path:
            continue
        try:
            base = root_path / event.name / 'device'
            ev = _bitmap((base / 'capabilities/ev').read_text(), struct.calcsize('@L') * 8)
            keys = _bitmap((base / 'capabilities/key').read_text(), struct.calcsize('@L') * 8)
        except (OSError, ValueError, UnicodeError):
            continue
        if _bits_set(ev, EV_KEY) and (keys & ((1 << 114) | (1 << 115))):
            vol_devs.append(dev_path)
    return vol_devs


def main():
    if '--init' in sys.argv:
        init_volume()
        return 0
    if '--save' in sys.argv:
        idx = sys.argv.index('--save')
        if idx + 1 < len(sys.argv):
            save_volume_state(sys.argv[idx + 1])
            return 0
        return 1
    if '--restore' in sys.argv:
        idx = sys.argv.index('--restore')
        if idx + 1 < len(sys.argv):
            restore_volume_state(sys.argv[idx + 1])
            return 0
        return 1
    if '--set' in sys.argv:
        idx = sys.argv.index('--set')
        if idx + 1 < len(sys.argv) and sys.argv[idx + 1].isdigit():
            set_volume_pct(int(sys.argv[idx + 1]))
            return 0
        return 1
    if '--adjust' in sys.argv:
        idx = sys.argv.index('--adjust')
        if idx + 1 < len(sys.argv):
            try:
                adjust_volume(int(sys.argv[idx + 1]))
                return 0
            except ValueError:
                return 1
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
