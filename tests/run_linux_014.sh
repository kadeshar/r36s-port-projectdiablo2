#!/bin/bash
# Synthetic input/audio/FPS/render regressions only; no real Wine or devices.
set -euo pipefail
cd -- "$(dirname -- "$0")/.."
for pattern in test_xbox_mapper_logic.py test_xinput_result.py test_xinput_artifact.py test_safe_log.py test_shell.py test_controller_mode.py test_audio_config.py test_audio_result.py test_audio_native.py test_audio_syscalls.py test_audio_compat.py test_fps_counter.py test_resolution_patch.py; do
 python3 -B -m unittest discover -s tests -p "$pattern" -v
done
