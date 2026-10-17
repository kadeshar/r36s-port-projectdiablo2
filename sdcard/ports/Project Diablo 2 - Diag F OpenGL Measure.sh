#!/bin/bash
# Actual game + lightweight presentation capture; still experimental GL output.
BASE=$(cd -- "$(dirname -- "$0")" && pwd -P) || exit 1
export PD2_DIAGNOSTIC=present PD2_TUNING=gl-kms PD2_PERFORMANCE=opengl PD2_BIGBLOCK=1
export PD2_START_MENU=0 PD2_GAME_RESOLUTION=800x600 PD2_FPS=0
exec bash "$BASE/Project Diablo 2.sh" "$@"
