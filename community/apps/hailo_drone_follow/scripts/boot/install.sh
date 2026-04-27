#!/bin/bash
# Install the drone-follow boot service.
# Idempotent — safe to re-run.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
DRONE_USER="hailo"
CONFIG_FILE="/home/${DRONE_USER}/Desktop/drone-follow.conf"

echo "=== Installing drone-follow boot service ==="

# Install new service
sudo ln -sf "${SCRIPT_DIR}/drone-follow-boot.sh" /usr/local/bin/drone-follow-boot.sh
sudo chmod +x /usr/local/bin/drone-follow-boot.sh
sudo ln -sf "${SCRIPT_DIR}/drone-follow-boot.service" /etc/systemd/system/drone-follow-boot.service
sudo systemctl daemon-reload
sudo systemctl enable drone-follow-boot.service

# Create desktop config if it doesn't exist
if [ ! -f "$CONFIG_FILE" ]; then
    cat > "$CONFIG_FILE" <<'CONF'
# Drone Follow Boot Configuration
# Set ENABLED=true to auto-start at boot, ENABLED=false to disable.
ENABLED=true
CONF
    chown "${DRONE_USER}:${DRONE_USER}" "$CONFIG_FILE"
    echo "Created config: $CONFIG_FILE"
else
    echo "Config already exists: $CONFIG_FILE"
fi

echo "=== Done. Service enabled. Edit $CONFIG_FILE to toggle. ==="
