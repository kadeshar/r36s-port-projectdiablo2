#!/bin/bash
set -euo pipefail
cd -- "$(dirname -- "$0")/.."
for file in sdcard/ports/*.sh sdcard/ports/projectdiablo2/scripts/*.sh; do bash -n "$file"; done
for name in test_gpu_runtime.py test_gles2_renderer.py test_box_variant.py test_metrics_scope.py test_safe_log.py test_prepare.py test_launcher_recovery.py test_start_menu.py; do
 python3 -B -m unittest discover -s tests -p "$name" -v
done
python3 -B -m unittest discover -s tools -p audio_metrics_tests.py -v
