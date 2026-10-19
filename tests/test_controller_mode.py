"""Controller overlays: synthetic config I/O only, no game or mapper execution."""
import copy
import json
import os
from pathlib import Path
import unittest
from unittest import mock

import test_layout as fixtures

layout = fixtures.layout
ROOT = Path(__file__).resolve().parents[1]
PORTS = ROOT / 'sdcard/ports'
PORT = PORTS / 'projectdiablo2'
FLAGS = ('wasd_movement', 'controller_movement')


def encoded(value):
    return (json.dumps(value, indent=4) + '  \n').encode('utf-8')


def config():
    return {
        'classic_game_settings': {'other': {'save_path': 'S:\\'}, 'volume': 37},
        'pd2_game_settings': {
            'wasd_movement': False, 'controller_movement': False,
            'quickcast': True, 'controller_sensitivity': 73,
            'custom': {'bindings': ['attack', 'loot']},
        },
        'unrelated': {'controller_movement': 'not a launcher flag'},
    }


class InputTransformTests(unittest.TestCase):
    def test_modes_are_exclusive_and_change_only_two_flags(self):
        for mode in ('mapper', 'native'):
            for wasd in (False, True):
                for controller in (False, True):
                    with self.subTest(mode=mode, wasd=wasd, controller=controller):
                        original = config()
                        original['pd2_game_settings'].update(
                            wasd_movement=wasd, controller_movement=controller)
                        content = encoded(original)
                        expected = copy.deepcopy(original)
                        expected['pd2_game_settings'].update(
                            wasd_movement=mode == 'mapper', controller_movement=mode == 'native')
                        result = layout.input_config(content, mode)
                        self.assertIsInstance(result, bytes)
                        self.assertEqual(json.loads(result), expected)
                        self.assertEqual(content, encoded(original))
                        self.assertEqual(layout.input_config(result, mode), result)

    def test_restore_original_flags_and_preserve_updated_unrelated_settings(self):
        previous = encoded(config())
        for mode in ('native', 'mapper'):
            with self.subTest(mode=mode):
                incoming = json.loads(layout.input_config(previous, mode))
                incoming['pd2_game_settings'].update(quickcast=False, controller_sensitivity=91)
                incoming['classic_game_settings']['volume'] = 12
                incoming['new_game_setting'] = ['persist', 42]
                expected = copy.deepcopy(incoming)
                for flag in FLAGS:
                    expected['pd2_game_settings'][flag] = False
                self.assertEqual(json.loads(layout.restore_input_config(encoded(incoming), previous)), expected)

    def test_missing_flags_and_missing_section_restore_exact_previous_bytes(self):
        for missing in (('wasd_movement',), ('controller_movement',), FLAGS, ('pd2_game_settings',)):
            for mode in ('native', 'mapper'):
                with self.subTest(missing=missing, mode=mode):
                    original = config()
                    if missing == ('pd2_game_settings',):
                        del original['pd2_game_settings']
                    else:
                        for key in missing:
                            del original['pd2_game_settings'][key]
                    previous = encoded(original)
                    incoming = layout.input_config(previous, mode)
                    self.assertEqual(layout.restore_input_config(incoming, previous), previous)

    def test_missing_section_retains_new_unrelated_pd2_settings(self):
        original = config()
        del original['pd2_game_settings']
        previous = encoded(original)
        incoming = json.loads(layout.input_config(previous, 'native'))
        incoming['pd2_game_settings'].update(quickcast=False, controller_sensitivity=44)
        expected = copy.deepcopy(original)
        expected['pd2_game_settings'] = {'quickcast': False, 'controller_sensitivity': 44}
        self.assertEqual(json.loads(layout.restore_input_config(encoded(incoming), previous)), expected)

    def test_invalid_modes_and_pd2_section_types_are_rejected(self):
        for mode in (None, '', 'Native', 'keyboard', True, 1, [], {}):
            with self.subTest(mode=mode):
                with self.assertRaisesRegex(layout.LayoutError, '^invalid_profile$'):
                    layout.input_config(encoded(config()), mode)
        for invalid in (None, [], '', 0, True):
            original = config()
            original['pd2_game_settings'] = invalid
            with self.subTest(section=invalid):
                with self.assertRaisesRegex(layout.LayoutError, '^invalid_profile$'):
                    layout.input_config(encoded(original), 'native')
                for incoming, previous in ((encoded(original), encoded(config())),
                                           (encoded(config()), encoded(original))):
                    with self.assertRaisesRegex(layout.LayoutError, '^invalid_layout$'):
                        layout.restore_input_config(incoming, previous)


class ControllerLayoutTests(unittest.TestCase):
    # Reuse synthetic assets/authentication pins, not the existing test methods.
    setUp = fixtures.LayoutTests.setUp

    def prepare_mode(self, mode=None, volatile=True):
        def fake_link(path, target):
            layout.no_links(path.parent)
            self.links[str(path)] = str(target)

        def fake_probe(path, target, **kwargs):
            path.touch(exist_ok=False)

        with mock.patch.object(layout, 'link', side_effect=fake_link), \
                mock.patch.object(Path, 'symlink_to', new=fake_probe), \
                mock.patch.object(layout.shutil, 'disk_usage', return_value=mock.Mock(free=2 * 1024 ** 3)):
            # Controller-only fixtures use 800x600; their minimal PE lacks native 640 cast signatures.
            return layout.prepare(self.port, self.state, volatile_work=volatile, input_mode=mode,
                                  game_resolution='800x600')

    def seed(self):
        return fixtures.write(self.port, 'config/ProjectDiablo.json', encoded(config()))

    def test_prepare_overlay_is_volatile_only_and_preserves_persistent_and_imported(self):
        active = self.seed()
        previous = active.read_bytes()
        for mode in ('native', 'mapper'):
            with self.subTest(mode=mode):
                result = self.prepare_mode(mode)
                expected = layout.input_config(previous, mode)
                self.assertEqual((self.state / 'game/ProjectD2/ProjectDiablo.json').read_bytes(), expected)
                self.assertEqual(active.read_bytes(), previous)
                self.assertEqual(result['input_mode'], mode)
                session = json.loads((self.state / 'session-layout.json').read_bytes())
                self.assertEqual(session['input_mode'], mode)
                self.assertEqual(fixtures.digest_tree(self.data), self.original_data)

    def test_optional_mode_leaves_volatile_config_unchanged(self):
        active = self.seed()
        result = self.prepare_mode()
        self.assertNotIn('input_mode', result)
        self.assertEqual((self.state / 'game/ProjectD2/ProjectDiablo.json').read_bytes(), active.read_bytes())

    def test_nonvolatile_mode_uses_persistent_link_without_transform(self):
        active = self.seed()
        previous = active.read_bytes()
        with mock.patch.object(layout, 'input_config', wraps=layout.input_config) as transform:
            self.prepare_mode('native', volatile=False)
        transform.assert_not_called()
        self.assertEqual(self.links[str(self.state / 'game/ProjectD2/ProjectDiablo.json')], str(active))
        self.assertEqual(active.read_bytes(), previous)

    def test_sync_unchanged_overlay_is_noop_without_backup(self):
        active = self.seed()
        previous = active.read_bytes()
        self.prepare_mode('native')
        before = fixtures.digest_tree(self.port / 'config')
        self.assertEqual(layout.sync_config(self.port, self.state), 0)
        self.assertEqual(fixtures.digest_tree(self.port / 'config'), before)
        self.assertEqual(active.read_bytes(), previous)
        self.assertFalse((self.port / 'config/backups').exists())

    def test_sync_restores_only_flags_and_commits_other_changes_with_backup(self):
        active = self.seed()
        previous = active.read_bytes()
        self.prepare_mode('mapper')
        work = self.state / 'game/ProjectD2/ProjectDiablo.json'
        updated = json.loads(work.read_bytes())
        updated['pd2_game_settings'].update(quickcast=False, controller_sensitivity=99)
        updated['classic_game_settings']['volume'] = 88
        updated['new_setting'] = 'keep me'
        work.write_bytes(encoded(updated))
        expected = copy.deepcopy(updated)
        expected['pd2_game_settings'].update(wasd_movement=False, controller_movement=False)
        self.assertEqual(layout.sync_config(self.port, self.state), 1)
        self.assertEqual(json.loads(active.read_bytes()), expected)
        self.assertEqual((self.port / 'config/backups/ProjectDiablo.json').read_bytes(), previous)
        self.assertEqual(layout.sync_config(self.port, self.state), 0)
        self.assertEqual(fixtures.digest_tree(self.data), self.original_data)

    def test_native_then_mapper_sessions_roundtrip_only_unrelated_changes(self):
        active = self.seed()
        expected = config()
        for mode, sensitivity in (('native', 81), ('mapper', 94)):
            with self.subTest(mode=mode):
                before = active.read_bytes()
                self.prepare_mode(mode)
                self.assertEqual(active.read_bytes(), before)
                work = self.state / 'game/ProjectD2/ProjectDiablo.json'
                incoming = json.loads(work.read_bytes())
                self.assertIs(incoming['pd2_game_settings']['wasd_movement'], mode == 'mapper')
                self.assertIs(incoming['pd2_game_settings']['controller_movement'], mode == 'native')
                incoming['pd2_game_settings']['controller_sensitivity'] = sensitivity
                incoming['pd2_game_settings']['quickcast'] = mode == 'native'
                work.write_bytes(encoded(incoming))
                expected['pd2_game_settings']['controller_sensitivity'] = sensitivity
                expected['pd2_game_settings']['quickcast'] = mode == 'native'
                self.assertEqual(layout.sync_config(self.port, self.state), 1)
                self.assertEqual(json.loads(active.read_bytes()), expected)
                self.assertEqual((self.port / 'config/backups/ProjectDiablo.json').read_bytes(), before)
                self.assertEqual(fixtures.digest_tree(self.data), self.original_data)

    def test_prepare_rejects_invalid_mode_before_state_mutation(self):
        before = fixtures.digest_tree(self.port)
        for mode in ('bad', '', True, 1, [], {}):
            with self.subTest(mode=mode):
                with self.assertRaisesRegex(layout.LayoutError, '^invalid_profile$'):
                    self.prepare_mode(mode)
                self.assertEqual(fixtures.digest_tree(self.port), before)
                self.assertEqual(list(self.state.iterdir()), [])


class ControllerPackagingTests(unittest.TestCase):
    def profile(self, name):
        entries = {}
        for line in (PORT / 'defaults' / name).read_text(encoding='utf-8').splitlines():
            if line.strip() and not line.lstrip().startswith('#'):
                key, value = line.split('=', 1)
                self.assertNotIn(key.strip(), entries)
                entries[key.strip()] = value.strip()
        return entries

    def test_both_mapper_profiles_bind_l1_to_show_items_leftalt(self):
        for name in ('controls.gptk', 'controls-swap.gptk'):
            with self.subTest(profile=name):
                self.assertEqual(self.profile(name)['l1'], 'leftalt')

    def test_native_has_all_gameplay_and_hotkey_bindings_explicitly_unbound(self):
        native = self.profile('controls-native.gptk')
        mapper = self.profile('controls.gptk')
        tuning = {'deadzone_mode', 'deadzone', 'deadzone_scale', 'mouse_delay',
                  'mouse_scale', 'mouse_slow_scale'}
        gameplay = set(mapper) - tuning
        self.assertTrue(gameplay)
        self.assertEqual(set(native) - tuning, gameplay)
        for key in gameplay:
            with self.subTest(binding=key):
                self.assertEqual(native[key], '"')

    def test_launcher_env_propagates_to_namespace_and_preserved_user_session(self):
        launcher = (PORTS / 'Project Diablo 2.sh').read_text(encoding='utf-8')
        adapter = (PORT / 'scripts/weston-session.sh').read_text(encoding='utf-8')
        runner = (PORT / 'scripts/run-game.sh').read_text(encoding='utf-8')
        self.assertIn('export PD2_INPUT_MODE="${PD2_INPUT_MODE:-native}"', launcher)
        forwarded = launcher.split('unshare --mount --propagation private setsid env', 1)[1]
        self.assertIn('PD2_INPUT_MODE="$PD2_INPUT_MODE"', forwarded)
        self.assertRegex(adapter, r'runuser -u "\$PD2_USER" --preserve-environment -- python3 [^\n]*layout\.py[^\n]*--volatile-work')
        self.assertIn('runuser -u "$PD2_USER" --preserve-environment -- env PD2_AUDIO_TEST="${PD2_AUDIO_TEST:-1}" bash "$R/game-session.sh"', adapter)
        self.assertIn('input_mode="${PD2_INPUT_MODE:-mapper}"', runner)
        self.assertIn('args=(xbox360 -1 "$kill_pattern")', runner)
        self.assertIn('PD2_CONTROLLER_TEST="$PD2_CONTROLLER_TEST"', forwarded)
        self.assertIn('pd2-xinput-probe.exe', runner)
        self.assertNotIn('control.exe joy.cpl', runner)
        self.assertNotIn('controls-test.gptk', runner)

    def test_cli_propagates_selected_env_mode_and_mapper_default_to_prepare(self):
        for mode in (None, 'native', 'mapper'):
            env = {} if mode is None else {'PD2_INPUT_MODE': mode}
            with self.subTest(mode=mode), mock.patch.dict(os.environ, env, clear=True), \
                    mock.patch.object(layout, 'prepare') as prepare:
                self.assertEqual(layout.main(['--port', 'fixture-port', '--state', 'fixture-state', '--volatile-work']), 0)
                self.assertEqual(prepare.call_args.kwargs['input_mode'], mode or 'mapper')
                self.assertTrue(prepare.call_args.args[3])

    def test_builder_allows_only_named_native_entry_not_arbitrary_root_scripts(self):
        import test_prepare
        prepare = test_prepare.prepare
        self.assertEqual(str(prepare.validate_release_path('Project Diablo 2.sh')),
                         'Project Diablo 2.sh')
        for name in ('Unknown.sh', 'Project Diablo 2 - Test.sh', 'Project Diablo 2 - Native Controller.exe', 'Project Diablo 2 - Native Controller.sh', 'Project Diablo 2 - Controller Test.sh', 'Project Diablo 2 - Native 800x600.sh', 'Project Diablo 2 - Native 1024x768.sh', 'Project Diablo 2 - Audio Test.sh'):
            with self.assertRaises(prepare.PrepareError):
                prepare.validate_release_path(name)

    def test_release_includes_launchers_profiles_and_input_implementation(self):
        files = json.loads((ROOT / 'release-files.json').read_text(encoding='utf-8'))
        required = {'Project Diablo 2.sh',
                    'projectdiablo2/defaults/controls-test.gptk',
                    'projectdiablo2/scripts/controller_probe.py',
                    'projectdiablo2/scripts/xbox_mapper.py',
                    'projectdiablo2/defaults/controls.gptk',
                    'projectdiablo2/defaults/controls-swap.gptk',
                    'projectdiablo2/defaults/controls-native.gptk',
                    'projectdiablo2/scripts/layout.py',
                    'projectdiablo2/scripts/run-game.sh',
                    'projectdiablo2/scripts/weston-session.sh'}
        self.assertTrue(required <= set(files), required - set(files))
        self.assertEqual(len(files), len(set(files)))
        for name in required:
            with self.subTest(file=name):
                self.assertTrue((PORTS / name).is_file())


if __name__ == '__main__':
    unittest.main()
