"""Synthetic storage inventory/UI tests; never open display or launch game."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
HELPERS = ROOT / 'tools/storage-check/storage-check'


def load(name):
    spec = importlib.util.spec_from_file_location(name, HELPERS / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


data = load('storage_data')
ui = load('storage_ui')


class StorageCheckTests(unittest.TestCase):
    def test_mounts_exclude_virtual_and_deduplicate_binds(self):
        text = ('1 0 179:2 / / rw - btrfs /dev/mmcblk0p2 rw\n'
                '2 0 0:1 / /tmp rw - tmpfs tmpfs rw\n'
                '5 0 7:0 / /tmp/mounted-runtime rw - squashfs /dev/loop0 ro\n'
                '3 0 179:9 / /roms2 rw - exfat /dev/mmcblk1p1 rw\n'
                '4 0 179:9 /Tools /opt/system/Tools rw - exfat /dev/mmcblk1p1 rw\n')
        rows = data.parse_mounts(text)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1]['mount'], '/roms2')

    def test_mount_path_escaping(self):
        rows = data.parse_mounts('1 0 1:2 / /my\\040disk rw - ext4 /dev/sda1 rw')
        self.assertEqual(rows[0]['mount'], '/my disk')

    def test_available_space_excludes_reserved_blocks(self):
        usage = SimpleNamespace(f_frsize=4096, f_bsize=4096, f_blocks=1000,
                                f_bfree=900, f_bavail=100)
        with mock.patch.object(data.os, 'statvfs', return_value=usage, create=True):
            self.assertEqual(data.space('/synthetic'), {'total': 4096000, 'free': 409600})

    def test_home_partition_sorted_first(self):
        text = ('1 0 179:2 / / rw - btrfs /dev/root rw\n'
                '2 0 179:9 / /roms2 rw - exfat /dev/sdcard rw\n')
        def device(path):
            return SimpleNamespace(st_dev=2 if str(path).replace('\\', '/') in ('/', '/home/test') else 9)
        with mock.patch.object(Path, 'read_text', return_value=text), \
                mock.patch.object(data.os, 'stat', side_effect=device), \
                mock.patch.object(data, 'space', return_value={'total': 100, 'free': 50}):
            rows = data.collect_partitions(Path('/home/test'), [])
        self.assertTrue(rows[0]['home'])
        self.assertEqual(rows[0]['mount'], '/')
        self.assertFalse(rows[1]['home'])

    def test_component_roles_distinguish_backups_and_production(self):
        self.assertEqual(data.component_info('wineprefix', {}), ('Production Wine prefix', 'required'))
        self.assertEqual(data.component_info('audio-stream-prefix-v1', {})[1], 'extra')
        self.assertEqual(data.component_info('runtime-old', {'runtime': 'runtime-current'})[1], 'old')
        self.assertEqual(data.component_info('runtime-current', {'runtime': 'runtime-current'})[1], 'required')
        self.assertEqual(data.component_info('compat', {})[1], 'support')

    def test_missing_installation_is_reported(self):
        with mock.patch.object(Path, 'read_text', side_effect=FileNotFoundError), \
                mock.patch.object(Path, 'is_dir', return_value=False):
            rows = data.collect_components(Path('/home/test/.local/share/pd2-r36s'), Path('/home/test'), [])
        self.assertEqual(len(rows), 3)
        self.assertTrue(all(r['status'] == 'MISSING' and r['size'] is None for r in rows))

    def test_du_arguments_are_read_only_and_do_not_follow_links(self):
        result = SimpleNamespace(returncode=0, stdout='123\t/synthetic/a\n', stderr='')
        with mock.patch.object(data.subprocess, 'run', return_value=result) as run:
            sizes = data.measure_paths([Path('/synthetic/a')], [])
        self.assertEqual(sizes['/synthetic/a'], 123 * 1024)
        self.assertEqual(run.call_args.args[0], ['du', '-skx', '--', str(Path('/synthetic/a'))])

    def test_du_failure_is_unknown_not_zero(self):
        errors = []
        with mock.patch.object(data.subprocess, 'run', side_effect=OSError('synthetic failure')):
            self.assertEqual(data.measure_paths([Path('/synthetic')], errors), {})
        self.assertTrue(errors)

    def test_shell_not_in_production_payload(self):
        script = ROOT / 'tools/storage-check/Storage Check.sh'
        self.assertNotIn(b'\r', script.read_bytes())
        self.assertFalse((ROOT / 'sdcard/ports/Project Diablo 2 - Storage Check.sh').exists())

    def test_physical_face_buttons_corrected(self):
        self.assertEqual(ui.action_for_button(1), 'toggle')
        self.assertEqual(ui.action_for_button(0), 'exit')
        self.assertEqual(ui.action_for_button(11), 'up')
        self.assertEqual(ui.action_for_button(12), 'down')

    def test_home_always_visible_in_limited_partition_page(self):
        rows = [{'device': '/dev/sda' + str(i), 'mount': '/disk' + str(i), 'home': False}
                for i in range(10)]
        rows.append({'device': 'HOME filesystem', 'mount': '/home/test', 'home': True})
        visible = ui.select_partitions(rows)
        self.assertEqual(len(visible), 6)
        self.assertTrue(visible[0]['home'])
        self.assertNotEqual(ui.HOME, ui.TEXT)

    def test_ui_rows_fit_screen_and_include_presence_size_and_path(self):
        row = {'name': 'Wine runtime', 'status': 'PRESENT', 'size': 285 * 1024**2,
               'category': 'required', 'path': '/home/ark/.local/share/pd2-r36s/runtime-' + 'a' * 64}
        first, second = ui.format_component(row)
        self.assertIn('PRESENT', first)
        self.assertIn('285.0', first)
        self.assertIn('REQ', second)
        self.assertLessEqual(len(first), 50)
        self.assertLessEqual(len(second), 50)
        self.assertEqual(ui.format_size(None), '--')

    def test_native_viewer_redraws_idle_frames_and_closes_resources(self):
        sdl = mock.Mock()
        sdl.SDL_Init.return_value = 0
        sdl.SDL_GetCurrentVideoDriver.return_value = b'synthetic'
        sdl.SDL_NumJoysticks.return_value = 0
        sdl.SDL_CreateWindow.return_value = 1
        sdl.SDL_CreateRenderer.return_value = 2
        sdl.SDL_RenderSetLogicalSize.return_value = 0
        sdl.SDL_GetRendererOutputSize.return_value = 0
        calls = iter([0, 0, 1, 0])
        def poll(pointer):
            result = next(calls)
            if result:
                ui.C.cast(pointer, ui.C.POINTER(ui.SDLEvent)).contents.type = 0x100
            return result
        sdl.SDL_PollEvent.side_effect = poll
        with mock.patch.object(ui, 'load_sdl', return_value=sdl), \
                mock.patch.object(ui, 'load_controller_mappings'), \
                mock.patch.object(ui, 'Painter') as painter:
            self.assertEqual(ui.run({'components': [], 'partitions': []}), 0)
        self.assertEqual(painter.return_value.draw.call_count, 2)
        self.assertEqual(sdl.SDL_CreateRenderer.call_args.args[2], 1)
        sdl.SDL_DestroyRenderer.assert_called_once_with(2)
        sdl.SDL_DestroyWindow.assert_called_once_with(1)
        sdl.SDL_Quit.assert_called_once()

    def test_ui_init_failure_cleans_up_sdl(self):
        sdl = mock.Mock()
        sdl.SDL_Init.return_value = -1
        sdl.SDL_GetError.return_value = b'synthetic failure'
        with mock.patch.object(ui, 'load_sdl', return_value=sdl):
            with self.assertRaisesRegex(RuntimeError, 'synthetic failure'):
                ui.run({})
        sdl.SDL_Quit.assert_called_once()
        sdl.SDL_CreateWindow.assert_not_called()

    def test_report_explains_present_not_integrity_verified(self):
        value = {'utc': 'test', 'home': '/home/test', 'state': '/home/test/state',
                 'partitions': [], 'components': [], 'errors': []}
        self.assertIn('not a test of compatibility or integrity', data.report(value))


if __name__ == '__main__':
    unittest.main()
