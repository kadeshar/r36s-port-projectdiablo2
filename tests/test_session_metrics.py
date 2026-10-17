"""In-memory proc fixtures: no host process access or tempfile ACL dependencies."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / 'sdcard/ports/projectdiablo2/scripts/metrics.py'
SPEC = importlib.util.spec_from_file_location('pd2_session_metrics', SCRIPT)
metrics = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(metrics)


class SessionMetricsTests(unittest.TestCase):
    def setUp(self):
        self.root = Path('PRIVATE_PROC_FIXTURE')
        self.files = {}
        self.reads = []
        self.now = 1000

        def open_file(path, *args, **kwargs):
            self.reads.append(path)
            if path not in self.files:
                raise FileNotFoundError('PRIVATE')
            return io.StringIO(self.files[path])

        def iterdir(path):
            return iter(sorted({path / p.relative_to(path).parts[0]
                                for p in self.files if path in p.parents}))

        for name, replacement in [('open', open_file), ('iterdir', iterdir)]:
            mock = patch.object(Path, name, replacement)
            mock.start()
            self.addCleanup(mock.stop)
        clock = patch.object(metrics.time, 'monotonic_ns', side_effect=lambda: self.now * 1000000)
        clock.start()
        self.addCleanup(clock.stop)

    def put(self, path, text):
        self.files[self.root / path] = text

    def process(self, pid, parent, start=100, user=10, system=5, faults=2,
                rss=100, swap=3, name='PRIVATE ) process (name)'):
        fields = ['S'] + ['0'] * 21
        for index, value in [(1, parent), (9, faults), (11, user),
                             (12, system), (19, start)]:
            fields[index] = str(value)
        self.put(str(pid) + '/stat', str(pid) + ' (' + name + ') ' + ' '.join(fields))
        status = 'Name:\tPRIVATE\n'
        if rss is not None:
            status += 'VmRSS:\t' + str(rss) + ' kB\n'
        if swap is not None:
            status += 'VmSwap:\t' + str(swap) + ' kB\n'
        self.put(str(pid) + '/status', status)

    def collect(self, sampler=None, pid=None):
        return metrics.collect_snapshot(
            'PRIVATE_PORT', sys_root=self.root / 'sys', proc_root=self.root,
            disk_usage=lambda _: SimpleNamespace(free=0), sampler=sampler, pid=pid)

    def test_only_anchor_descendants_no_identity_leak(self):
        self.process(20, 1, start=100)
        self.process(21, 20, start=101, rss=200)
        self.process(22, 21, start=102, rss=300)
        self.process(80, 1, start=50, rss=999999, name='gamescope')
        self.process(81, 80, start=51, rss=999999, name='wine')
        result = self.collect(metrics.MetricsSampler(20, clock_ticks=100))
        self.assertEqual(result['game_processes'], 3)
        self.assertEqual(result['game_rss_kb'], 600)
        self.assertEqual(result['game_swap_kb'], 9)
        self.assertEqual(result['game_major_faults'], 6)
        self.assertEqual(result['game_cpu_user_ms'], 300)
        self.assertEqual(result['game_cpu_system_ms'], 150)
        self.assertNotIn('game_cpu_pct_x100', result)
        self.assertNotIn(self.root / '80/status', self.reads)
        self.assertNotIn(self.root / '81/status', self.reads)
        encoded = json.dumps(result)
        for secret in ('PRIVATE', 'gamescope', 'wine', 'cmdline', 'environ', 'pid'):
            self.assertNotIn(secret, encoded)
        self.assertTrue(all(type(v) is int for k, v in result.items() if k != 'event'))
        self.assertFalse(any(p.name in ('cmdline', 'environ', 'comm') for p in self.reads))

    def test_no_anchor_means_no_process_scan(self):
        self.process(20, 1)
        result = self.collect()
        self.assertFalse(any(k.startswith('game_') for k in result))
        self.assertFalse(any(p.name in ('stat', 'status') and p.parent.name == '20'
                             for p in self.reads))

    def test_pid_only_snapshot_is_supported(self):
        self.process(20, 1)
        self.assertEqual(self.collect(pid=20)['game_processes'], 1)

    def test_system_cpu_delta_guest_not_double_counted(self):
        sampler = metrics.MetricsSampler()
        self.put('stat', 'cpu 100 0 30 500 10 0 0 0 90 0\ncpu0 1 2 3 4\n')
        self.assertNotIn('system_cpu_pct_x100', self.collect(sampler))
        self.put('stat', 'cpu 150 0 50 520 20 0 0 0 120 0\n')
        self.assertEqual(self.collect(sampler)['system_cpu_pct_x100'], 7000)
        # Reset counters: no false zero or negative percentage.
        self.put('stat', 'cpu 1 0 1 1 0 0 0 0 0 0\n')
        self.assertNotIn('system_cpu_pct_x100', self.collect(sampler))

    def test_game_cpu_interval_and_process_reuse(self):
        sampler = metrics.MetricsSampler(20, clock_ticks=100)
        self.process(20, 1)
        self.process(21, 20, start=101)
        self.collect(sampler)
        self.now += 1000
        self.process(20, 1, user=60, system=5)
        self.process(21, 20, start=101, user=60, system=5)
        self.assertEqual(self.collect(sampler)['game_cpu_pct_x100'], 10000)
        self.now += 1000
        self.process(21, 20, start=999, user=9000, system=9000)
        self.assertNotIn('game_cpu_pct_x100', self.collect(sampler))
        self.now += 1000
        self.assertEqual(self.collect(sampler)['game_cpu_pct_x100'], 0)

    def test_anchor_reuse_permanently_ends_session(self):
        sampler = metrics.MetricsSampler(20, clock_ticks=100)
        self.process(20, 1)
        self.collect(sampler)
        self.process(20, 1, start=900)
        self.process(21, 20, start=901)
        self.assertFalse(any(k.startswith('game_') for k in self.collect(sampler)))
        self.assertTrue(sampler.anchor_ended)
        self.process(20, 1, start=100)
        self.assertNotIn('game_processes', self.collect(sampler))

    def test_missing_anchor_not_zero(self):
        sampler = metrics.MetricsSampler(20, clock_ticks=100)
        self.assertNotIn('game_processes', self.collect(sampler))
        self.assertTrue(sampler.anchor_ended)

    def test_broken_cycles_and_impossible_ancestry_are_excluded(self):
        self.process(20, 1)
        self.process(21, 22)
        self.process(22, 21)
        self.process(23, 999)
        self.process(24, 20, start=99)
        self.assertEqual(self.collect(pid=20)['game_processes'], 1)

    def test_reparented_process_is_dropped(self):
        sampler = metrics.MetricsSampler(20, clock_ticks=100)
        self.process(20, 1)
        self.process(21, 20, start=101)
        self.assertEqual(self.collect(sampler)['game_processes'], 2)
        self.process(21, 1, start=101)
        self.assertEqual(self.collect(sampler)['game_processes'], 1)

    def test_partial_status_omits_aggregate_instead_of_zero(self):
        self.process(20, 1)
        self.process(21, 20, start=101, rss=None, swap=None)
        result = self.collect(pid=20)
        self.assertNotIn('game_rss_kb', result)
        self.assertNotIn('game_swap_kb', result)
        self.assertEqual(result['game_processes'], 2)

    def test_missing_tick_rate_omits_cpu_units(self):
        self.process(20, 1)
        with patch.object(metrics.os, 'sysconf', return_value=None, create=True):
            result = self.collect(pid=20)
        self.assertNotIn('game_cpu_user_ms', result)
        self.assertNotIn('game_cpu_system_ms', result)
        self.assertEqual(result['game_rss_kb'], 100)

    def test_memory_swap_and_pressure_units(self):
        self.put('meminfo', 'MemAvailable: 4096 kB\nSwapTotal: 8192 kB\nSwapFree: 2048 kB\n')
        self.put('vmstat', 'pswpin 21\npswpout 35\npgmajfault 7\n')
        self.put('pressure/memory', 'some avg10=12.34 avg60=1.00 avg300=0.00 total=123456\nfull avg10=0.00 avg60=0.00 avg300=0.00 total=0\n')
        result = self.collect()
        for key, expected in [('sample_monotonic_ms', 1000), ('available_ram_mb', 4),
                              ('swap_total_mb', 8), ('swap_free_mb', 2),
                              ('swap_in_pages', 21), ('swap_out_pages', 35),
                              ('system_major_faults', 7),
                              ('pressure_memory_some_avg10_x100', 1234),
                              ('pressure_memory_some_total_us', 123456),
                              ('pressure_memory_full_avg10_x100', 0),
                              ('pressure_memory_full_total_us', 0)]:
            self.assertEqual(result[key], expected)
        self.assertNotIn('pressure_cpu_some_total_us', result)

    def test_invalid_and_oversized_sources_are_omitted(self):
        self.put('vmstat', 'pswpin -2\npswpout nan\npgmajfault ' + '9' * 20)
        self.put('pressure/io', 'some avg10=100.01 total=-1\nfull avg10=nan total=secret')
        self.put('pressure/cpu', 'some avg10=1.00 total=1\n' + 'x' * 4096)
        self.put('meminfo', 'SwapTotal: -1 kB\nSwapFree: private kB')
        result = self.collect()
        self.assertEqual(result, {'event': 'metrics', 'sample_monotonic_ms': 1000, 'disk_mb': 0})

    def test_process_scan_cap_omits_partial_tree(self):
        self.process(20, 1)
        for pid in range(10000, 14100):
            self.put(str(pid) + '/stat', '')
        self.assertNotIn('game_processes', self.collect(pid=20))

    def test_anchor_identity_race_omits_entire_group(self):
        self.process(20, 1)
        real = metrics._process
        count = [0]
        def racing(root, pid):
            count[0] += 1
            if count[0] == 2:
                self.process(20, 1, start=999)
            return real(root, pid)
        with patch.object(metrics, '_process', side_effect=racing):
            self.assertNotIn('game_processes', self.collect(pid=20))

    def test_cli_reused_anchor_stops_without_second_snapshot(self):
        states = [{'start': 100}, {'start': 999}]
        with patch('sys.argv', ['metrics.py', '--port', 'PRIVATE', '--pid', '20']), \
             patch.object(metrics, '_process', side_effect=states), \
             patch.object(metrics, 'snapshot') as snapshot, \
             patch.object(metrics.time, 'sleep') as sleep:
            self.assertEqual(metrics.main(), 0)
        self.assertEqual(snapshot.call_count, 1)
        sleep.assert_called_once_with(5)

    def test_cli_rejects_non_session_anchor(self):
        for pid in ('0', '1', '-1'):
            with patch('sys.argv', ['metrics.py', '--port', 'PRIVATE', '--pid', pid]), \
                 patch.object(metrics, 'snapshot') as snapshot:
                self.assertEqual(metrics.main(), 1)
                snapshot.assert_not_called()


if __name__ == '__main__':
    unittest.main()
