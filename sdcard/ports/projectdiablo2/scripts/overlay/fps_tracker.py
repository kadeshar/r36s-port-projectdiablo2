#!/usr/bin/env python3
"""Frame rate and frametime tracker for performance overlay.

Reads frame presentation records from work directory telemetry if available,
or falls back to monotonic timer cadence. Computes instantaneous FPS,
average FPS, min/max, frametime in ms, and a history buffer for graphs.
"""
import collections
import json
import os
import time


class FPSTracker:
    def __init__(self, work_dir=None, history_size=200):
        self.work_dir = work_dir
        self.history_size = history_size
        self.history = collections.deque(maxlen=history_size)
        self.fps = 0
        self.frametime_ms = 0.0
        self.min_fps = 0
        self.max_fps = 0
        self.avg_fps = 0.0

        self.last_check_time = time.monotonic()
        self.recent_frames = collections.deque(maxlen=60)
        self.all_fps_samples = collections.deque(maxlen=100)
        self.telemetry_path = os.path.join(work_dir, 'ProjectD2', 'pd2-present.jsonl') if work_dir else None
        self._file = None

        # Pre-fill history with typical 33.3ms (30 FPS) baseline
        for _ in range(history_size):
            self.history.append(33.3)

    def close(self):
        if self._file:
            try:
                self._file.close()
            except Exception:
                pass
            self._file = None

    def update(self):
        if self.telemetry_path:
            self._read_telemetry(self.telemetry_path)

        return {
            'fps': self.fps,
            'frametime_ms': self.frametime_ms,
            'min_fps': self.min_fps,
            'max_fps': self.max_fps,
            'avg_fps': self.avg_fps,
            'history': list(self.history),
        }

    def record_frame(self, duration_ms):
        if duration_ms <= 0:
            duration_ms = 16.6
        self.frametime_ms = duration_ms
        self.history.append(duration_ms)
        calc_fps = int(1000.0 / duration_ms) if duration_ms > 0 else 0
        self.fps = min(240, max(0, calc_fps))
        self.all_fps_samples.append(self.fps)
        self._update_stats()

    def _read_telemetry(self, path):
        try:
            if self._file is None:
                if not os.path.isfile(path):
                    return False
                self._file = open(path, 'r', encoding='ascii', errors='ignore')

            lines = self._file.readlines()
            if not lines:
                return False

            found = False
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                    # Telemetry schema: event=1 (sample), frames, duration_ms
                    if record.get('event') == 1 and 'frames' in record and 'duration_ms' in record:
                        frames = record['frames']
                        duration = record['duration_ms']
                        if duration > 0 and frames > 0:
                            calc_fps = int(frames * 1000 / duration)
                            ft = float(duration) / frames
                            self.fps = calc_fps
                            self.frametime_ms = round(ft, 1)
                            self.history.append(self.frametime_ms)
                            self.all_fps_samples.append(calc_fps)
                            found = True
                except Exception:
                    continue

            if found:
                self._update_stats()
            return found
        except Exception:
            if self._file:
                try:
                    self._file.close()
                except Exception:
                    pass
                self._file = None
            return False

    def _update_stats(self):
        if not self.all_fps_samples:
            return
        samples = list(self.all_fps_samples)
        self.min_fps = min(samples)
        self.max_fps = max(samples)
        self.avg_fps = round(sum(samples) / len(samples), 1)
