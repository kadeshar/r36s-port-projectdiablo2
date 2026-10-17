#!/bin/bash
# Native ARMHF SDL GLES2: red/green/blue, no game launch.
BASE=$(cd -- "$(dirname -- "$0")" && pwd -P) || exit 1
export PD2_DIAGNOSTIC=sdl PD2_TUNING=gl-kms PD2_PERFORMANCE=opengl PD2_BIGBLOCK=1
export PD2_START_MENU=0 PD2_GAME_RESOLUTION=800x600 PD2_FPS=0
exec bash "$BASE/Project Diablo 2.sh" "$@"
