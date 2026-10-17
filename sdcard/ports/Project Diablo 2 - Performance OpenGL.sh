#!/bin/bash
# PD2 0.1.18: experimental full Weston/Crusty/OpenGL profile, not INI alone.
BASE=$(cd -- "$(dirname -- "$0")" && pwd -P) || exit 1
export PD2_PERFORMANCE=opengl
# Set to 1 to isolate renderer changes or if bigger blocks cause instability.
export PD2_BIGBLOCK="${PD2_BIGBLOCK:-2}"
# Headless/noop Weston cannot display the core-X11 launcher menu.
# Selecting this Ports entry is the explicit request to start the game.
export PD2_START_MENU=0
# No menu in this profile: set PD2_FPS=1 here (or in the environment) to measure.
export PD2_GAME_RESOLUTION=800x600 PD2_FPS="${PD2_FPS:-0}"
exec bash "$BASE/Project Diablo 2.sh" "$@"
