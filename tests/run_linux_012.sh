#!/bin/bash
# Synthetic regressions only; no real input devices, Wine or game assets.
set -euo pipefail
cd -- "$(dirname -- "$0")/.."
for pattern in test_xbox_mapper_logic.py test_xinput_result.py test_xinput_artifact.py test_safe_log.py test_shell.py test_controller_mode.py; do
 python3 -B -m unittest discover -s tests -p "$pattern" -v
done
