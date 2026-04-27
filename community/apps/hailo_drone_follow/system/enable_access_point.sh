#!/bin/bash
set -euo pipefail

AP="HailoDrone-AP"

if nmcli -t -f NAME connection show --active 2>/dev/null | grep -q "^${AP}$"; then
    echo "Stopping AP..."
    sudo nmcli connection down "$AP"
    echo "AP stopped."
else
    echo "Starting AP..."
    sudo nmcli connection up "$AP"
    echo "AP active: SSID=HailoDrone IP=10.0.0.1 (5GHz ch36)"
fi
