#!/bin/bash
# Remove the drone-follow boot service.
set -euo pipefail

echo "=== Uninstalling drone-follow boot service ==="

sudo systemctl stop drone-follow-boot.service 2>/dev/null || true
sudo systemctl disable drone-follow-boot.service 2>/dev/null || true
sudo rm -f /etc/systemd/system/drone-follow-boot.service
sudo rm -f /usr/local/bin/drone-follow-boot.sh
sudo systemctl daemon-reload

echo "=== Done. Desktop config file left in place. ==="
