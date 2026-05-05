#!/bin/bash
# Install the drone-follow boot service.
# Idempotent — safe to re-run.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
DRONE_USER="hailo"
CONFIG_FILE="/home/${DRONE_USER}/Desktop/drone-follow.conf"
OPENHD_BIN="/usr/local/bin/openhd"
SUDOERS_FILE="/etc/sudoers.d/drone-follow-openhd"

echo "=== Installing drone-follow boot service ==="

# Install new service
sudo ln -sf "${SCRIPT_DIR}/drone-follow-boot.sh" /usr/local/bin/drone-follow-boot.sh
sudo chmod +x /usr/local/bin/drone-follow-boot.sh
sudo ln -sf "${SCRIPT_DIR}/drone-follow-boot.service" /etc/systemd/system/drone-follow-boot.service
sudo systemctl daemon-reload
sudo systemctl enable drone-follow-boot.service

# start_air.sh launches OpenHD with `sudo openhd --air`. Under the boot
# service there is no tty, so an interactive password prompt fails and OpenHD
# never starts (drone-follow runs but the radio link is dead). Allow the
# drone user to run that exact binary without a password.
sudo tee "$SUDOERS_FILE" >/dev/null <<EOF
${DRONE_USER} ALL=(root) NOPASSWD: ${OPENHD_BIN}
EOF
sudo chmod 0440 "$SUDOERS_FILE"
if ! sudo visudo -c -f "$SUDOERS_FILE" >/dev/null; then
    echo "ERROR: sudoers drop-in failed validation; removing." >&2
    sudo rm -f "$SUDOERS_FILE"
    exit 1
fi

# Create desktop config if it doesn't exist. ENABLED=false by default so the
# next boot does NOT silently auto-launch drone-follow + OpenHD; the user
# opts in by editing this file. Re-running install.sh is idempotent and
# does not overwrite an existing user choice.
if [ ! -f "$CONFIG_FILE" ]; then
    cat > "$CONFIG_FILE" <<'CONF'
# Drone Follow Boot Configuration
# Set ENABLED=true to auto-start at boot, ENABLED=false to disable.
# The systemd unit reads this file on every boot — no reload needed.
ENABLED=false

# Camera mode passed through to start_air.sh. Optional — omit to use the
# script's default (stream / Mode A). Must match how install_air.sh was run
# (primary_camera_type + /boot/openhd/hailo.txt).
#   stream  Mode A — drone-follow owns the camera, --openhd RTP.
#   shm     Mode B — OpenHD owns the camera, drone-follow reads SHM.
#MODE=stream
CONF
    chown "${DRONE_USER}:${DRONE_USER}" "$CONFIG_FILE"
    echo "Created config: $CONFIG_FILE (ENABLED=false — opt in by editing)"
else
    echo "Config already exists: $CONFIG_FILE"
fi

echo "=== Done. Service enabled. Edit $CONFIG_FILE to toggle ENABLED=true. ==="
