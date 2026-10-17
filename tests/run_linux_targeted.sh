#!/bin/bash
set -e
cd -- "$(dirname -- "$0")/.."
python3 -B -m unittest discover -s tests -p test_shell.py -v
python3 -B -m unittest discover -s tests -p test_fetch_metrics.py -v
python3 -B -m unittest discover -s tests -p test_runtime_fix.py -v
python3 -B -m unittest discover -s tests -p test_graphics_probe.py -v
python3 -B -m unittest discover -s tests -p test_x11_probe.py -v
python3 -B -m unittest discover -s tests -p test_x11_auth.py -v
bash tests/check_namespace_isolation.sh
