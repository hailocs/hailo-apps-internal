#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
export DISPLAY=:0

# Wait for serial device to appear (USB enumeration can be slow on boot)
SERIAL_DEV="/dev/ttyACM0"
SERIAL_TIMEOUT=30
elapsed=0
while [ ! -e "$SERIAL_DEV" ] && [ $elapsed -lt $SERIAL_TIMEOUT ]; do
    echo "Waiting for $SERIAL_DEV... (${elapsed}s/${SERIAL_TIMEOUT}s)"
    sleep 2
    elapsed=$((elapsed + 2))
done
if [ ! -e "$SERIAL_DEV" ]; then
    echo "WARNING: $SERIAL_DEV not found after ${SERIAL_TIMEOUT}s, proceeding anyway"
fi

# Log to timestamped file and terminal
LOG_DIR="$(pwd)/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/flight_$(date '+%Y-%m-%d_%H-%M-%S').log"
echo "Logging to $LOG_FILE"

source setup_env.sh
drone-follow --input rpi --tiles-x 1 --tiles-y 1 --ui --record --serial 2>&1 | tee "$LOG_FILE"