#!/bin/bash
# Runs OpenHD ground station and QOpenHD GUI on the ground station laptop

SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"

OPENHD_BIN="/usr/local/bin/openhd"
QOPENHD_BIN="$REPO_DIR/qopenHD/build/release/release/QOpenHD"
OPENHD_LOG="/tmp/openhd.log"
QOPENHD_LOG="/tmp/qopenhd.log"

if [ ! -f "$OPENHD_BIN" ]; then
    echo "Error: openhd not found at $OPENHD_BIN"
    exit 1
fi

if [ ! -f "$QOPENHD_BIN" ]; then
    echo "Error: QOpenHD not found at $QOPENHD_BIN"
    exit 1
fi

sudo -v

# Start OpenHD ground in the background
sudo "$OPENHD_BIN" --ground > "$OPENHD_LOG" 2>&1 &
OPENHD_PID=$!
sleep 2

# Start QOpenHD GUI
"$QOPENHD_BIN" > "$QOPENHD_LOG" 2>&1 &
QOPENHD_PID=$!

trap "kill $QOPENHD_PID 2>/dev/null; sudo kill $OPENHD_PID 2>/dev/null; wait" EXIT

echo "OpenHD PID: $OPENHD_PID (log: $OPENHD_LOG)"
echo "QOpenHD PID: $QOPENHD_PID (log: $QOPENHD_LOG)"
echo "Press Ctrl+C to stop both"

wait $QOPENHD_PID 2>/dev/null
