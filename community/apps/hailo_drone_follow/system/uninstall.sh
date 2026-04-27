#!/bin/bash
set -euo pipefail

echo "Removing drone networking setup..."

# Stop and disable the boot service
echo "Disabling drone-network-mode service..."
sudo systemctl stop drone-network-mode.service 2>/dev/null || true
sudo systemctl disable drone-network-mode.service 2>/dev/null || true

# Bring down AP if active
echo "Stopping AP if active..."
nmcli connection down "HailoDrone-AP" 2>/dev/null || true

# Remove NM AP profile
if nmcli connection show "HailoDrone-AP" &>/dev/null; then
    echo "Deleting HailoDrone-AP connection profile..."
    sudo nmcli connection delete "HailoDrone-AP"
else
    echo "HailoDrone-AP profile not found (already removed)."
fi

# Remove symlinks
echo "Removing symlinks..."
sudo rm -f /usr/local/bin/drone-network-mode.sh
sudo rm -f /etc/systemd/system/drone-network-mode.service
sudo rm -f /etc/udev/rules.d/71-usb-wifi.rules

sudo systemctl daemon-reload
sudo udevadm control --reload-rules

echo "Done. Reboot for udev changes to take full effect."
