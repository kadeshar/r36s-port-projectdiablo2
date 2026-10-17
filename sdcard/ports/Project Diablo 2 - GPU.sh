#!/bin/bash
# Isolated GL2/GLES2 presentation; preserved main launcher remains rollback.
BASE=$(cd -- "$(dirname -- "$0")" && pwd -P) || exit 1
export PD2_RENDERER_VARIANT=gles2
# A35 is independently opt-in, never an implicit part of the renderer change.
export PD2_BOX_VARIANT="${PD2_BOX_VARIANT:-stock}"
export PD2_PERFORMANCE=opengl PD2_TUNING=gl-kms PD2_BIGBLOCK=1
export PD2_DIAGNOSTIC=off PD2_FPS=0 PD2_START_MENU=0 PD2_CONTROLLER_TEST=0
export PD2_AUDIO_TEST=1 PD2_AUDIO_PROBE=0
exec bash "$BASE/Project Diablo 2.sh"
