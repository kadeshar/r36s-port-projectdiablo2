#!/bin/bash
set -euo pipefail
cd -- "$(dirname -- "$0")/.."
for script in sdcard/ports/*.sh sdcard/ports/projectdiablo2/scripts/*.sh; do bash -n "$script"; done
python3 -B -m unittest discover -s tests -p test_tuning_profiles.py -v
python3 -B -m unittest discover -s tests -p test_metrics_performance.py -v
python3 -B -m unittest discover -s tests -p test_graphics_probe.py -v
PYTHONPATH=tests python3 -B -m unittest \
 test_shell.ShellTests.test_numbered_tuning_reaches_wine_after_audio_refresh \
 test_shell.ShellTests.test_performance_profiles_export_dynarec_to_all_wine_calls \
 test_shell.ShellTests.test_performance_launchers_export_defaults_and_preserve_bigblock_override \
 test_shell.ShellTests.test_performance_off_or_unset_keeps_normal_wine_environment \
 test_shell.ShellTests.test_performance_invalid_options_never_start_wine -v
