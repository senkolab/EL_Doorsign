#!/usr/bin/env bash
set -euo pipefail

cd -- "$(dirname -- "$0")"
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
export WAYLAND_DISPLAY="${WAYLAND_DISPLAY:-wayland-0}"
export GDK_BACKEND=wayland

display_socket="$WAYLAND_DISPLAY"
if [[ "$display_socket" != /* ]]; then
    display_socket="$XDG_RUNTIME_DIR/$display_socket"
fi
if [[ ! -S "$display_socket" ]]; then
    printf 'Wait for the Pi desktop to load, then run this script again.\n' >&2
    exit 1
fi

# Serialize launches and close the lock in the dashboard process.
exec 9>"$XDG_RUNTIME_DIR/qudit-dashboard-start.lock"
flock 9
if pgrep -u "$(id -u)" -f '^python3 -B qudit_dashboard\.py( |$)' >/dev/null; then
    printf 'QuDit dashboard is already running.\n'
    exit 0
fi

printf '\n-- Dashboard launcher --\n' >>qudit_dashboard.log
if ! wlr-randr --output SPI-1 --on --custom-mode 320x480@30Hz --transform 90 --scale 1 >>qudit_dashboard.log 2>&1; then
    printf 'Could not set the touchscreen mode. See %s/qudit_dashboard.log\n' "$PWD" >&2
    exit 1
fi
wavemeter_host="${QUDIT_WAVEMETER_HOST-senkolab-laser.local}"
source_args=()
if [[ -n "$wavemeter_host" ]]; then
    source_args+=(--wavemeter "$wavemeter_host")
fi
if [[ -f .paladin-enabled ]]; then
    source_args+=(--paladin)
fi
nohup python3 -B qudit_dashboard.py "${source_args[@]}" "$@" >>qudit_dashboard.log 2>&1 </dev/null 9>&- &
dashboard_pid=$!
sleep 1
if ! kill -0 "$dashboard_pid" 2>/dev/null; then
    printf 'QuDit dashboard could not start. See %s/qudit_dashboard.log\n' "$PWD" >&2
    exit 1
fi

printf 'QuDit dashboard started (PID %s).\n' "$dashboard_pid"
