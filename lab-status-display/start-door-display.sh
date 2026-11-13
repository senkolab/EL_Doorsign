#!/usr/bin/env bash
set -euo pipefail

cd -- "$(dirname -- "$0")"
export DISPLAY="${DISPLAY:-:0}"
export XAUTHORITY="${XAUTHORITY:-$HOME/.Xauthority}"
export GDK_BACKEND=x11

# Keep this lock in the viewer for as long as its fullscreen window is open.
exec 9>.door-viewer.lock
if ! flock -n 9; then
    printf 'QuDit door display is already running.\n'
    exit 0
fi

xset s off
xset -dpms 2>/dev/null || true

printf '\n-- Door display launcher --\n' >>relay_display.log
nohup python3 -B relay_display.py >>relay_display.log 2>&1 </dev/null &
viewer_pid=$!
sleep 1
if ! kill -0 "$viewer_pid" 2>/dev/null; then
    printf 'QuDit door display could not start. See %s/relay_display.log\n' "$PWD" >&2
    exit 1
fi
printf 'QuDit door display started (PID %s).\n' "$viewer_pid"
