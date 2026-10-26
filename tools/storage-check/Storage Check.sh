#!/bin/bash
# Standalone storage inventory; never launches a game or production launcher.
umask 077
BASE=$(cd -- "$(dirname -- "$0")" && pwd -P) || exit 1
if ! command -v python3 >/dev/null 2>&1; then
 printf '%s\n' 'Storage Check requires Python 3.' >&2
 exit 1
fi
exec python3 -B "$BASE/storage-check/storage_check.py" "$BASE" "$@"
