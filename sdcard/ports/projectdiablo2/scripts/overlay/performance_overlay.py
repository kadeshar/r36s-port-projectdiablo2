#!/usr/bin/env python3
"""R36S performance overlay for retro handheld Linux ports.

R36S performance overlay with levels:
  0: Off
  1: Minimal FPS counter pill
  2: Compact horizontal status bar
  3: Detailed multi-line performance HUD
  4: Full detailed HUD with live frametime bar graph and per-core CPU stats

Designed to be fully portable and easily drop-in movable to other PortMaster / Linux ports.
Requires only standard Linux kernel interfaces (/proc, /sys) and X11 Unix socket.
"""
import argparse
import os
import signal
import sys
import time

try:
    from .overlay_metrics import SystemMetrics
    from .fps_tracker import FPSTracker
    from .x11_hud import X11HUD
except ImportError:
    from overlay_metrics import SystemMetrics
    from fps_tracker import FPSTracker
    from x11_hud import X11HUD


def _get_log_path():
    try:
        from pathlib import Path
        base = Path(__file__).resolve().parents[2] / 'logs'
        if base.is_dir():
            return str(base / 'overlay.log')
    except Exception:
        pass
    return '/tmp/overlay.log'

LOG_PATH = _get_log_path()


def _log(msg):
    try:
        with open(LOG_PATH, 'a', encoding='utf-8') as f:
            f.write(f'{time.strftime("%H:%M:%S")} {msg}\n')
    except Exception:
        pass


def _pid_alive(pid):
    if pid is None or pid <= 0:
        return True
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError, OSError):
        return False


def run_overlay(level=1, target_pid=None, work_dir=None, display=':0', interval=0.3, cli_mode=False):
    _log(f'Starting performance overlay level={level} pid={target_pid} work={work_dir} display={display}')
    if level <= 0:
        _log('Level is 0, exiting')
        return 0

    metrics = SystemMetrics()
    fps_tracker = FPSTracker(work_dir=work_dir)
    hud = None

    running = True

    def _sig_handler(_signo, _frame):
        nonlocal running
        _log(f'Received signal {_signo}')
        running = False

    try:
        signal.signal(signal.SIGINT, _sig_handler)
        signal.signal(signal.SIGTERM, _sig_handler)
    except Exception as e:
        _log(f'Signal setup warning: {e}')

    if not cli_mode:
        try:
            _log(f'Connecting X11HUD to {display}...')
            hud = X11HUD(level=level, display=display)
            hud.connect()
            _log(f'X11HUD connected successfully! Window={hud.window}')
        except Exception as e:
            _log(f'X11HUD connect failed: {e}')
            sys.stderr.write(f'PD2 overlay X11 connect error: {e}\n')
            sys.stderr.flush()
            cli_mode = True

    if level == 1 and interval < 0.5:
        interval = 0.5

    _log(f'Entering render loop, cli_mode={cli_mode}, interval={interval}')
    try:
        while running:
            if target_pid and not _pid_alive(target_pid):
                _log(f'Target pid {target_pid} exited')
                break

            m = metrics.sample(level=level)
            f = fps_tracker.update()

            if hud and not cli_mode:
                try:
                    hud.render(m, f)
                except Exception as e:
                    _log(f'hud.render failed: {e}')
                    break
            else:
                fps = f.get('fps', 0)
                cpu = m.get('cpu_total', 0)
                gpu = m.get('gpu_pct', 0)
                ram = m.get('ram_used_mb', 0)
                sys.stdout.write(f'\r[Level {level}] FPS: {fps} | CPU: {cpu}% | GPU: {gpu}% | RAM: {ram}MB')
                sys.stdout.flush()

            time.sleep(interval)
    finally:
        _log('Shutting down overlay')
        fps_tracker.close()
        if hud:
            hud.close()
        if cli_mode:
            sys.stdout.write('\n')
            sys.stdout.flush()

    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--level', type=int, default=1, choices=[0, 1, 2, 3, 4],
                        help='Overlay level (0=Off, 1=FPS, 2=Bar, 3=Detailed, 4=Full+Graph)')
    parser.add_argument('--pid', type=int, default=None,
                        help='Target game process ID to monitor; exit when process terminates')
    parser.add_argument('--work', type=str, default=None,
                        help='Port working directory containing frame presentation telemetry')
    parser.add_argument('--display', type=str, default=os.environ.get('DISPLAY', ':0'),
                        help='X11 display socket (default :0)')
    parser.add_argument('--interval', type=float, default=0.35,
                        help='Refresh update interval in seconds')
    parser.add_argument('--cli', action='store_true',
                        help='Output metrics directly to terminal instead of X11 window')

    args = parser.parse_args(argv)
    return run_overlay(
        level=args.level,
        target_pid=args.pid,
        work_dir=args.work,
        display=args.display,
        interval=args.interval,
        cli_mode=args.cli,
    )


if __name__ == '__main__':
    sys.exit(main())
