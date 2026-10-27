#!/usr/bin/env python3
"""R36S performance overlay for retro handheld Linux ports.

R36S performance overlay with levels:
  0: Off
  1: Minimal FPS counter pill
  2: Compact horizontal status bar
  3: Detailed multi-line performance HUD
  4: Full detailed HUD with live frametime bar graph and per-core CPU stats

Gamepad hotkey controls during gameplay:
  FN + R1 : Switch overlay level (cycles 0 -> 1 -> 2 -> 3 -> 4 -> 0)
  FN + R2 : Reset frametime graph and statistical metrics (FPS/AVG/1% Low/0.1% Low)

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
    from .hotkey_listener import HotkeyListener
except ImportError:
    from overlay_metrics import SystemMetrics
    from fps_tracker import FPSTracker
    from x11_hud import X11HUD
    from hotkey_listener import HotkeyListener


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


def run_overlay(level=1, target_pid=None, work_dir=None, display=':0', interval=0.35, cli_mode=False):
    _log(f'Starting performance overlay initial_level={level} pid={target_pid} work={work_dir} display={display}')

    current_level = max(0, min(4, level))
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
            _log(f'Connecting X11HUD to {display} (initial_level={current_level})...')
            hud = X11HUD(level=current_level, display=display)
            hud.connect()
            _log(f'X11HUD connected successfully! Window={hud.window}')
        except Exception as e:
            _log(f'X11HUD connect failed: {e}')
            sys.stderr.write(f'PD2 overlay X11 connect error: {e}\n')
            sys.stderr.flush()
            cli_mode = True

    # Setup gamepad hotkey listener
    level_switch_pending = False
    reset_data_pending = False

    def on_switch_level():
        nonlocal level_switch_pending
        level_switch_pending = True

    def on_reset_data():
        nonlocal reset_data_pending
        reset_data_pending = True

    hotkey_listener = HotkeyListener(
        on_switch_level=on_switch_level,
        on_reset_data=on_reset_data,
        debounce_seconds=0.35,
    )
    try:
        hotkey_listener.start()
        _log('HotkeyListener started successfully (FN+R1 switch level, FN+R2 reset data)')
    except Exception as e:
        _log(f'HotkeyListener start warning: {e}')

    _log(f'Entering render loop, current_level={current_level}, cli_mode={cli_mode}, interval={interval}')
    try:
        while running:
            if target_pid and not _pid_alive(target_pid):
                _log(f'Target pid {target_pid} exited')
                break

            # Process hotkey inputs
            sw, rs = hotkey_listener.poll_actions()
            if sw or level_switch_pending:
                level_switch_pending = False
                current_level = (current_level + 1) % 5
                _log(f'Hotkey action: Switched overlay level to {current_level}')
                if hud and not cli_mode:
                    try:
                        hud.set_level(current_level)
                    except Exception as e:
                        _log(f'hud.set_level error: {e}')

            if rs or reset_data_pending:
                reset_data_pending = False
                _log('Hotkey action: Reset overlay telemetry metrics and frametime graph')
                fps_tracker.reset()

            m = metrics.sample(level=current_level)
            f = fps_tracker.update()

            if hud and not cli_mode:
                if current_level > 0:
                    try:
                        hud.render(m, f)
                    except Exception as e:
                        _log(f'hud.render failed: {e}')
                        break
            else:
                if current_level > 0:
                    fps = f.get('fps', 0)
                    avg = f.get('avg_fps', 0.0)
                    l1 = f.get('low_1pct', 0.0)
                    l01 = f.get('low_01pct', 0.0)
                    cpu = m.get('cpu_total', 0)
                    gpu = m.get('gpu_pct', 0)
                    ram = m.get('ram_used_mb', 0)
                    sys.stdout.write(f'\r[Level {current_level}] FPS: {fps} (AVG:{avg:.0f} 1%Low:{l1:.0f} 0.1%Low:{l01:.0f}) | CPU: {cpu}% | GPU: {gpu}% | RAM: {ram}MB')
                    sys.stdout.flush()
                else:
                    sys.stdout.write('\r[Level 0: OFF] Press FN+R1 to activate overlay...                     ')
                    sys.stdout.flush()

            time.sleep(interval)
    finally:
        _log('Shutting down overlay')
        hotkey_listener.stop()
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
