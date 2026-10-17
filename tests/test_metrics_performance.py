"""Isolated stdlib tests: no hardware access, system writes or packages."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / 'sdcard/ports/projectdiablo2/scripts/metrics.py'
SPEC = importlib.util.spec_from_file_location('pd2_metrics_performance', SCRIPT)
metrics = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(metrics)


class MetricsPerformanceTests(unittest.TestCase):
    def setUp(self):
        self.root = Path('PRIVATE_FIXTURE_ROOT')
        self.sys = self.root / 'sys'
        self.proc = self.root / 'proc'
        self.files = {}
        clock = patch.object(metrics.time, 'monotonic_ns', return_value=123456000000)
        clock.start()
        self.addCleanup(clock.stop)

        def open_file(path, *args, **kwargs):
            if path not in self.files:
                raise FileNotFoundError(str(path))
            data = self.files[path]
            encoding = kwargs.get('encoding')
            return io.StringIO(data.decode('utf-8' if encoding in (None, 'locale') else encoding))

        def iterdir(path):
            children = set()
            for filename in self.files:
                if path in filename.parents:
                    children.add(path / filename.relative_to(path).parts[0])
            return iter(children)

        for name, replacement in (
            ('open', open_file), ('iterdir', iterdir),
            ('is_symlink', lambda path: False),
            ('stat', lambda path: SimpleNamespace(st_size=len(self.files[path]))),
        ):
            patcher = patch.object(Path, name, replacement)
            patcher.start()
            self.addCleanup(patcher.stop)

    def put(self, relative, value):
        path = self.root / relative
        self.files[path] = value if isinstance(value, bytes) else str(value).encode('ascii')
        return path

    def collect(self, **kwargs):
        return metrics.collect_snapshot(
            'PRIVATE_PORT_PATH', sys_root=self.sys, proc_root=self.proc,
            disk_usage=kwargs.get('disk_usage', lambda _: SimpleNamespace(free=7 * 1048576)))

    def cpu(self, name, value, root='cpufreq/policy0'):
        return self.put('sys/devices/system/cpu/' + root + '/' + name, value)

    def gpu(self, name, current, maximum):
        self.put('sys/class/devfreq/' + name + '/cur_freq', current)
        self.put('sys/class/devfreq/' + name + '/max_freq', maximum)

    def test_complete_snapshot_native_units_and_numeric_privacy(self):
        self.cpu('scaling_cur_freq', '816000\n')
        self.cpu('scaling_max_freq', 1512000)
        self.gpu('00000000.dmc', 999999999, 999999999)
        self.gpu('ff300000.gpu', 400000000, 800000000)
        self.put('proc/meminfo', 'MemTotal: 1048576 kB\nMemAvailable: 524288 kB\n')
        self.put('sys/class/thermal/thermal_zone0/temp', 45000)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            result = self.collect()
        self.assertEqual(out.getvalue(), '')
        self.assertEqual(result, {
            'event': 'metrics', 'sample_monotonic_ms': 123456,
            'disk_mb': 7, 'available_ram_mb': 512,
            'temperature_mc': 45000, 'cpu_freq_khz': 816000,
            'cpu_max_freq_khz': 1512000, 'gpu_freq_hz': 400000000,
            'gpu_max_freq_hz': 800000000})
        self.assertTrue(all(type(v) is int for k, v in result.items() if k != 'event'))
        self.assertNotIn('PRIVATE', json.dumps(result))
        self.assertNotIn('ff300000', json.dumps(result))

    def test_missing_optional_files(self):
        self.assertEqual(self.collect(), {'event': 'metrics', 'sample_monotonic_ms': 123456, 'disk_mb': 7})

    def test_cpu0_and_cpuinfo_fallback(self):
        self.cpu('scaling_cur_freq', 'invalid')
        self.cpu('cpuinfo_cur_freq', 600000, 'cpu0/cpufreq')
        self.cpu('cpuinfo_max_freq', 1512000, 'cpu0/cpufreq')
        result = self.collect()
        self.assertEqual(result['cpu_freq_khz'], 600000)
        self.assertEqual(result['cpu_max_freq_khz'], 1512000)

    def test_policy0_precedes_cpu0(self):
        self.cpu('scaling_cur_freq', 1000000)
        self.cpu('scaling_cur_freq', 600000, 'cpu0/cpufreq')
        self.assertEqual(self.collect()['cpu_freq_khz'], 1000000)

    def test_non_gpu_devfreq_is_not_reported(self):
        for name in ('dmc', 'ddr', 'bus', 'notgpu'):
            self.gpu(name, 600000000, 800000000)
        self.assertEqual(self.collect(), {'event': 'metrics', 'sample_monotonic_ms': 123456, 'disk_mb': 7})

    def test_gpu_identity_from_name_file(self):
        self.gpu('ff300000', 200000000, 800000000)
        self.put('sys/class/devfreq/ff300000/name', 'mali0\n')
        self.assertEqual(self.collect()['gpu_freq_hz'], 200000000)

    def test_gpu_values_are_not_mixed_between_devices(self):
        self.gpu('a.gpu', 200000000, 'invalid')
        self.gpu('b.gpu', 300000000, 800000000)
        result = self.collect()
        self.assertEqual(result['gpu_freq_hz'], 200000000)
        self.assertNotIn('gpu_max_freq_hz', result)

    def test_invalid_and_out_of_range_frequencies_are_omitted(self):
        for invalid in ('', '0', '-1', '1.5', 'nan', 'inf', 'secret/path',
                        '1_000', '10000000001', '9' * 200):
            with self.subTest(value=invalid):
                self.cpu('scaling_cur_freq', invalid)
                self.cpu('scaling_max_freq', invalid)
                self.gpu('gpu', invalid, invalid)
                self.assertEqual(self.collect(), {'event': 'metrics', 'sample_monotonic_ms': 123456, 'disk_mb': 7})
        self.cpu('scaling_cur_freq', 10000001)
        self.assertNotIn('cpu_freq_khz', self.collect())

    def test_inclusive_frequency_limits(self):
        self.cpu('scaling_cur_freq', 1)
        self.cpu('scaling_max_freq', 10000000)
        self.gpu('gpu', 1, 10000000000)
        result = self.collect()
        self.assertEqual(result['cpu_freq_khz'], 1)
        self.assertEqual(result['cpu_max_freq_khz'], 10000000)
        self.assertEqual(result['gpu_freq_hz'], 1)
        self.assertEqual(result['gpu_max_freq_hz'], 10000000000)

    def test_invalid_ram_temperature_and_disk_omitted(self):
        for ram in ('-1', '1.5', '9' * 5000, '1024000000000001'):
            self.put('proc/meminfo', 'MemAvailable: ' + ram + ' kB\n')
            self.put('sys/class/thermal/thermal_zone0/temp', 200001)
            result = self.collect(disk_usage=lambda _: SimpleNamespace(free=-1))
            self.assertEqual(result, {'event': 'metrics', 'sample_monotonic_ms': 123456})

    def test_temperature_boundaries(self):
        for value in (-50000, 200000):
            self.put('sys/class/thermal/thermal_zone0/temp', value)
            self.assertEqual(self.collect()['temperature_mc'], value)

    def test_unreadable_or_non_ascii_data_is_omitted(self):
        self.cpu('scaling_cur_freq', b'\xff')
        self.put('sys/class/thermal/thermal_zone0/temp/child', 'not a sensor')
        with patch.object(metrics.shutil, 'disk_usage', side_effect=OSError('PRIVATE')):
            result = metrics.collect_snapshot('PRIVATE', sys_root=self.sys, proc_root=self.proc)
        self.assertEqual(result, {'event': 'metrics', 'sample_monotonic_ms': 123456})

    def test_snapshot_retains_wire_api(self):
        expected = {'event': 'metrics', 'sample_monotonic_ms': 123456, 'cpu_freq_khz': 800000}
        output = io.StringIO()
        with patch.object(metrics, 'collect_snapshot', return_value=expected) as collect:
            with contextlib.redirect_stdout(output):
                self.assertIsNone(metrics.snapshot('PRIVATE'))
        collect.assert_called_once_with('PRIVATE')
        self.assertEqual(output.getvalue(), 'PD2_EVENT ' + json.dumps(expected) + '\n')

    def test_main_still_takes_one_snapshot_without_pid(self):
        with patch('sys.argv', ['metrics.py', '--port', 'PRIVATE']):
            with patch.object(metrics, 'snapshot') as snapshot:
                with patch.object(metrics.time, 'sleep') as sleep:
                    self.assertEqual(metrics.main(), 0)
        snapshot.assert_called_once_with('PRIVATE')
        sleep.assert_not_called()

    def test_enabled_read_is_bounded_even_if_file_grows_after_stat(self):
        self.put('config/settings.json', '{"metrics":true,"private":"' + 'x' * 65536 + '"}')
        output = io.StringIO()
        with patch.object(Path, 'stat', return_value=SimpleNamespace(st_size=1)):
            with patch('sys.argv', ['metrics.py', '--port', str(self.root), '--enabled']):
                with contextlib.redirect_stdout(output):
                    self.assertEqual(metrics.main(), 0)
        self.assertEqual(output.getvalue(), '0\n')

    def test_enabled_remains_explicit_boolean_opt_in(self):
        for setting, expected in (({}, '0\n'), ({'metrics': False}, '0\n'),
                                  ({'metrics': 'true'}, '0\n'), ({'metrics': True}, '1\n')):
            self.put('config/settings.json', json.dumps(setting))
            output = io.StringIO()
            with patch('sys.argv', ['metrics.py', '--port', str(self.root), '--enabled']):
                with contextlib.redirect_stdout(output):
                    with patch.object(metrics, 'snapshot') as snapshot:
                        self.assertEqual(metrics.main(), 0)
            self.assertEqual(output.getvalue(), expected)
            snapshot.assert_not_called()


if __name__ == '__main__':
    unittest.main()
