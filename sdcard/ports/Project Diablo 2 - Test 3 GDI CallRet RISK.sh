#!/bin/bash
# RISK: CALLRET optimization can break self-modifying code. Use disposable saves.
BASE=$(cd -- "$(dirname -- "$0")" && pwd -P) || exit 1
export PD2_TUNING=callret PD2_PERFORMANCE=gdi PD2_BIGBLOCK=1
export PD2_START_MENU=0 PD2_GAME_RESOLUTION=800x600 PD2_FPS="${PD2_FPS:-1}"
exec bash "$BASE/Project Diablo 2.sh" "$@"
