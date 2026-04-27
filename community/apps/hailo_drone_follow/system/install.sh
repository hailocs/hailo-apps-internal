#!/bin/bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "Setting up dual-mode networking (Home/Field AP)..."

# Create NM AP connection profile (idempotent)
if ! nmcli connection show "HailoDrone-AP" &>/dev/null; then
    echo "Creating HailoDrone-AP connection profile..."
    sudo nmcli connection add type wifi ifname wlan1 con-name "HailoDrone-AP" \
        autoconnect no ssid "HailoDrone" mode ap \
        wifi.band a wifi.channel 36 \
        wifi-sec.key-mgmt wpa-psk wifi-sec.psk "hailodrone" \
        ipv4.method shared ipv4.addresses 10.0.0.1/24 ipv6.method disabled
else
    echo "HailoDrone-AP connection profile already exists."
fi

# Symlink scripts and services
echo "Creating symlinks..."
sudo ln -sf "$SCRIPT_DIR/71-usb-wifi.rules" /etc/udev/rules.d/71-usb-wifi.rules
sudo ln -sf "$SCRIPT_DIR/drone-network-mode.sh" /usr/local/bin/drone-network-mode.sh
sudo ln -sf "$SCRIPT_DIR/drone-network-mode.service" /etc/systemd/system/drone-network-mode.service

# Enable system service, disable user auto-start
echo "Enabling drone-network-mode system service..."
sudo systemctl daemon-reload
sudo systemctl enable drone-network-mode.service

echo "Disabling user-level drone-follow auto-start..."
systemctl --user daemon-reload
systemctl --user disable drone-follow.service 2>/dev/null || true

echo "Done. Reboot to test."
