#!/bin/bash
set -e
cd -- "$(dirname -- "$0")/.."
python3 -B -m unittest discover -s tests -v
python3 -B - <<'PY'
import importlib.util,tarfile
spec=importlib.util.spec_from_file_location('layout','sdcard/ports/projectdiablo2/scripts/layout.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
with tarfile.open('sdcard/ports/projectdiablo2/runtime/wine-8.0-x86.tar.xz','r:xz') as t:
 v=m.validate_tar(t);print('Pinned Wine archive validated:',len(v),'members')
PY
