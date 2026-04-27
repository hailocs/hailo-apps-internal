#!/bin/bash
# Runs OpenHD air and drone-follow side by side on the drone (RPi)

SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
OPENHD_BIN="/usr/local/bin/openhd"

if [ ! -f "$OPENHD_BIN" ]; then
    echo "Error: openhd not found at $OPENHD_BIN"
    exit 1
fi

# Start OpenHD air in the background
sudo "$OPENHD_BIN" --air &
OPENHD_PID=$!
sleep 3

# Set up drone-follow environment and run
cd "$REPO_DIR"
source "$REPO_DIR/setup_env.sh"
export DISPLAY=:0

# Auto-load saved controller tuning if present (see PARAMETERS.md).
# The file is gitignored and created via the web UI / QOpenHD "Save Config"
# button or `drone-follow --save-config $REPO_DIR/df_config.json`.
CONFIG_FILE="$REPO_DIR/df_config.json"
CONFIG_ARG=()
if [ -f "$CONFIG_FILE" ]; then
    CONFIG_ARG=(--config "$CONFIG_FILE")
    echo "Loading controller config: $CONFIG_FILE"
else
    echo "No df_config.json found at $CONFIG_FILE — using ControllerConfig defaults"
fi

drone-follow --input rpi --openhd-stream "${CONFIG_ARG[@]}" --connection tcpout://127.0.0.1:5760 --tiles-x 2 --tiles-y 2 &
FOLLOW_PID=$!

trap "kill $FOLLOW_PID 2>/dev/null; sudo kill $OPENHD_PID 2>/dev/null; wait" EXIT

echo "OpenHD PID: $OPENHD_PID"
echo "drone-follow PID: $FOLLOW_PID"
echo "Press Ctrl+C to stop both"

wait
