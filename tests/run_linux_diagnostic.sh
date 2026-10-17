#!/bin/bash
set -euo pipefail
cd -- "$(dirname -- "$0")/.."
for file in sdcard/ports/*.sh sdcard/ports/projectdiablo2/scripts/*.sh; do bash -n "$file"; done
python3 -B -m unittest discover -s tests -p test_diagnostic_pipeline.py -v
python3 -B -m unittest discover -s tests -p test_present_renderer.py -v
python3 -B -m unittest discover -s tests -p test_tuning_profiles.py -v
python3 -B -m unittest discover -s tests -p test_graphics_layers.py -v
python3 -B -m unittest discover -s tests -p 'test*metrics*.py' -v
python3 -B -m unittest discover -s tests -p test_shell.py -v
python3 -B -m unittest discover -s tests -p test_safe_log.py -v
python3 -B -m unittest discover -s tests -p test_prepare.py -v
python3 -B -m unittest discover -s tests -p test_layout.py -v
