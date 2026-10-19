#!/bin/bash
# PD2 0.1.18: experimental CPU profile; ordinary launcher is the rollback.
BASE=$(cd -- "$(dirname -- "$0")" && pwd -P) || exit 1
export PD2_PERFORMANCE=gdi
# Set to 1 to isolate renderer changes or if bigger blocks cause instability.
export PD2_BIGBLOCK="${PD2_BIGBLOCK:-2}"
export PD2_GAME_RESOLUTION="${PD2_GAME_RESOLUTION:-640x480}" PD2_FPS=0
exec bash "$BASE/Project Diablo 2.sh" "$@"
