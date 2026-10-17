#!/bin/bash
# Synthetic tests only: no real Wine, controller, uinput or game data.
set -euo pipefail
cd -- "$(dirname -- "$0")/.."
for pattern in test_xbox_mapper_logic.py test_safe_log.py test_shell.py test_layout.py test_resolution_patch.py test_controller_mode.py test_controller_probe.py test_winebus_config.py test_xinput_artifact.py test_xinput_result.py; do
 python3 -B -m unittest discover -s tests -p "$pattern" -v
done
if command -v cc >/dev/null; then
 binary=$(mktemp /tmp/pd2-input-abi.XXXXXXXX)
 [[ "$binary" == /tmp/pd2-input-abi.* && -f "$binary" && ! -L "$binary" ]]
 trap '[[ "$binary" == /tmp/pd2-input-abi.* && -f "$binary" && ! -L "$binary" ]] && rm -f -- "$binary"' EXIT
 cc -std=c11 -Wall -Wextra -Werror tests/check_input_abi.c -o "$binary"
 "$binary"
else
 printf '%s\n' 'Optional C UAPI compile check skipped: cc unavailable.'
fi
