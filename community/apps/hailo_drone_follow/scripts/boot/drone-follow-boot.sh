#!/bin/bash
# Boot wrapper: checks desktop config file, then launches start_air.sh
set -euo pipefail

LOG_TAG="drone-follow-boot"
DRONE_USER="hailo"
CONFIG_FILE="/home/${DRONE_USER}/Desktop/drone-follow.conf"
REPO_DIR="/home/${DRONE_USER}/hailo-drone-follow"
START_SCRIPT="${REPO_DIR}/scripts/start_air.sh"

log() { logger -t "$LOG_TAG" "$*"; echo "$(date '+%Y-%m-%d %H:%M:%S') $*"; }

# Read config
if [ ! -f "$CONFIG_FILE" ]; then
    log "Config file not found: $CONFIG_FILE — skipping."
    exit 0
fi

ENABLED=$(grep -oP '^ENABLED=\K.*' "$CONFIG_FILE" 2>/dev/null || echo "false")
ENABLED=$(echo "$ENABLED" | tr '[:upper:]' '[:lower:]' | xargs)

if [ "$ENABLED" != "true" ]; then
    log "Drone-follow is DISABLED in $CONFIG_FILE — skipping."
    exit 0
fi

log "Drone-follow is ENABLED — starting."

if [ ! -x "$START_SCRIPT" ]; then
    log "ERROR: start script not found or not executable: $START_SCRIPT"
    exit 1
fi

# Run start_air.sh as the drone user
exec sudo -u "$DRONE_USER" \
    DISPLAY=:0 \
    XDG_RUNTIME_DIR="/run/user/$(id -u "$DRONE_USER")" \
    "$START_SCRIPT"
