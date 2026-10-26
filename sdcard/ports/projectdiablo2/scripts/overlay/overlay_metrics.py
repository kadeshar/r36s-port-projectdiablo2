#!/usr/bin/env python3
"""Hardware and OS performance metrics collector for handheld Linux ports.

Portable across RK3326, RK3566, Allwinner, and generic Linux platforms.
Reads exclusively from standard Linux /proc and /sys kernel interfaces.
No external dependencies, binary tools, or root privileges required.
"""
import glob
import os
import time


class SystemMetrics:
    def __init__(self):
        self.prev_total_cpu = None
        self.prev_cores = {}
        self.last_sample_time = 0.0

        # Cache sysfs paths once at startup to avoid repeated glob.glob filesystem walks
        self.thermal_paths = glob.glob('/sys/class/thermal/thermal_zone*/temp')
        self.devfreq_paths = glob.glob('/sys/class/devfreq/*gpu*') + glob.glob('/sys/class/devfreq/*mali*')
        self.power_supplies = glob.glob('/sys/class/power_supply/*')
        self.cpu_freq_path = None
        for p in ('/sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq',
                  '/sys/devices/system/cpu/cpu0/cpufreq/cpuinfo_cur_freq'):
            if os.path.isfile(p):
                self.cpu_freq_path = p
                break

    def sample(self, level=4):
        # Level 1: Only FPS is displayed. Collect zero metrics for 0% CPU overhead.
        if level == 1:
            return {}

        now = time.monotonic()
        time_delta = now - self.last_sample_time
        self.last_sample_time = now

        need_cores = (level == 4)
        need_cpu_mhz = (level in (3, 4))
        need_cpu_temp = (level in (3, 4))
        need_ram = (level in (2, 3, 4))
        need_swap = (level == 4)
        need_gpu = (level in (2, 3, 4))
        need_battery = (level in (2, 3, 4))

        cpu_total, cpu_cores = self._read_cpu_usage(read_cores=need_cores)
        cpu_mhz = self._read_cpu_freq() if need_cpu_mhz else 1296
        cpu_temp = self._read_cpu_temp() if need_cpu_temp else 0
        ram_used, ram_total, ram_free = self._read_ram() if need_ram else (0, 1024, 0)
        swap_used, swap_total = self._read_swap() if need_swap else (0, 0)
        gpu_pct, gpu_mhz = self._read_gpu() if need_gpu else (0, 500)
        battery_pct, battery_status, battery_volts, plugged = self._read_battery() if need_battery else (100, 'Discharging', 4.1, False)

        return {
            'cpu_total': cpu_total,
            'cpu_cores': cpu_cores,
            'cpu_mhz': cpu_mhz,
            'cpu_temp': cpu_temp,
            'ram_used_mb': ram_used,
            'ram_total_mb': ram_total,
            'ram_free_mb': ram_free,
            'swap_used_mb': swap_used,
            'swap_total_mb': swap_total,
            'gpu_pct': gpu_pct,
            'gpu_mhz': gpu_mhz,
            'battery_pct': battery_pct,
            'battery_status': battery_status,
            'battery_volts': battery_volts,
            'plugged': plugged,
        }

    def _read_cpu_usage(self, read_cores=True):
        total_pct = 0
        cores = []
        cores_pct = []
        try:
            with open('/proc/stat', 'r', encoding='ascii', errors='ignore') as f:
                lines = f.readlines()
            for line in lines:
                parts = line.split()
                if not parts:
                    continue
                label = parts[0]
                if label == 'cpu':
                    vals = [int(v) for v in parts[1:8]]
                    total = sum(vals)
                    idle = vals[3] + (vals[4] if len(vals) > 4 else 0)
                    if self.prev_total_cpu is not None:
                        diff_total = total - self.prev_total_cpu[0]
                        diff_idle = idle - self.prev_total_cpu[1]
                        if diff_total > 0:
                            total_pct = max(0, min(100, int((diff_total - diff_idle) * 100 // diff_total)))
                    self.prev_total_cpu = (total, idle)
                    if not read_cores:
                        break
                elif read_cores and label.startswith('cpu') and label[3:].isdigit():
                    idx = int(label[3:])
                    vals = [int(v) for v in parts[1:8]]
                    total = sum(vals)
                    idle = vals[3] + (vals[4] if len(vals) > 4 else 0)
                    prev = self.prev_cores.get(idx)
                    core_pct = 0
                    if prev is not None:
                        diff_total = total - prev[0]
                        diff_idle = idle - prev[1]
                        if diff_total > 0:
                            core_pct = max(0, min(100, int((diff_total - diff_idle) * 100 // diff_total)))
                    self.prev_cores[idx] = (total, idle)
                    cores_pct.append((idx, core_pct))
            if read_cores and cores_pct:
                cores_pct.sort(key=lambda x: x[0])
                cores = [pct for _, pct in cores_pct]
        except Exception:
            pass
        return total_pct, cores

    def _read_cpu_freq(self):
        if self.cpu_freq_path:
            try:
                with open(self.cpu_freq_path, 'r', encoding='ascii') as f:
                    khz = int(f.read().strip())
                    return khz // 1000
            except Exception:
                pass
        return 1296  # Default nominal clock for RK3326

    def _read_cpu_temp(self):
        for path in self.thermal_paths:
            try:
                with open(path, 'r', encoding='ascii') as f:
                    temp_raw = int(f.read().strip())
                    return temp_raw // 1000 if temp_raw > 1000 else temp_raw
            except Exception:
                continue
        return 0

    def _read_ram(self):
        used_mb, total_mb, free_mb = 0, 1024, 0
        try:
            meminfo = {}
            with open('/proc/meminfo', 'r', encoding='ascii', errors='ignore') as f:
                for line in f:
                    parts = line.split(':')
                    if len(parts) == 2:
                        key = parts[0].strip()
                        val = parts[1].strip().split()[0]
                        if val.isdigit():
                            meminfo[key] = int(val)
            total_kb = meminfo.get('MemTotal', 1048576)
            avail_kb = meminfo.get('MemAvailable', meminfo.get('MemFree', 0) + meminfo.get('Buffers', 0) + meminfo.get('Cached', 0))
            total_mb = total_kb // 1024
            free_mb = avail_kb // 1024
            used_mb = max(0, total_mb - free_mb)
        except Exception:
            pass
        return used_mb, total_mb, free_mb

    def _read_swap(self):
        used_mb, total_mb = 0, 0
        try:
            meminfo = {}
            with open('/proc/meminfo', 'r', encoding='ascii', errors='ignore') as f:
                for line in f:
                    parts = line.split(':')
                    if len(parts) == 2:
                        key = parts[0].strip()
                        val = parts[1].strip().split()[0]
                        if val.isdigit():
                            meminfo[key] = int(val)
            total_kb = meminfo.get('SwapTotal', 0)
            free_kb = meminfo.get('SwapFree', 0)
            total_mb = total_kb // 1024
            used_mb = max(0, total_mb - (free_kb // 1024))
        except Exception:
            pass
        return used_mb, total_mb

    def _read_gpu(self):
        gpu_pct = 0
        gpu_mhz = 500
        # Check devfreq for Mali GPU
        for dev in self.devfreq_paths:
            try:
                freq_file = os.path.join(dev, 'cur_freq')
                if os.path.isfile(freq_file):
                    with open(freq_file, 'r', encoding='ascii') as f:
                        gpu_mhz = int(f.read().strip()) // 1000000
                load_file = os.path.join(dev, 'load')
                if os.path.isfile(load_file):
                    with open(load_file, 'r', encoding='ascii') as f:
                        line = f.read().strip()
                        if '@' in line:
                            gpu_pct = int(line.split('@')[0])
                        elif line.isdigit():
                            gpu_pct = int(line)
                break
            except Exception:
                continue
        return gpu_pct, gpu_mhz

    def _read_battery(self):
        pct = 100
        status = 'Discharging'
        volts = 4.1
        plugged = False
        for s in self.power_supplies:
            name = os.path.basename(s).lower()
            # Check AC / USB charger online state
            if any(k in name for k in ('ac', 'usb', 'charger', 'mains')):
                online_file = os.path.join(s, 'online')
                if os.path.isfile(online_file):
                    try:
                        with open(online_file, 'r', encoding='ascii') as f:
                            if f.read().strip() == '1':
                                plugged = True
                    except Exception:
                        pass

            # Look for battery devices (e.g. axp20x-battery, rk817-battery, battery, BAT0)
            try:
                cap_file = os.path.join(s, 'capacity')
                if os.path.isfile(cap_file):
                    with open(cap_file, 'r', encoding='ascii') as f:
                        pct = int(f.read().strip())
                status_file = os.path.join(s, 'status')
                if os.path.isfile(status_file):
                    with open(status_file, 'r', encoding='ascii') as f:
                        cur_status = f.read().strip()
                        if cur_status:
                            status = cur_status
                            if status.lower() in ('charging', 'full'):
                                plugged = True
                volt_file = os.path.join(s, 'voltage_now')
                if os.path.isfile(volt_file):
                    with open(volt_file, 'r', encoding='ascii') as f:
                        raw = int(f.read().strip())
                        volts = raw / 1000000.0 if raw > 100000 else raw / 1000.0
            except Exception:
                continue
        return pct, status, volts, plugged
