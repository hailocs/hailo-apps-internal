#!/bin/bash
set -euo pipefail

LOG_TAG="drone-network-mode"
AP_CONNECTION="HailoDrone-AP"
DRONE_USER="hailo"
DRONE_SERVICE="drone-follow.service"
SETTLE_TIMEOUT=30
CHECK_INTERVAL=5

log() { logger -t "$LOG_TAG" "$*"; echo "$(date '+%Y-%m-%d %H:%M:%S') $*"; }

is_wifi_connected() {
    local con
    con=$(nmcli -t -f NAME,DEVICE connection show --active 2>/dev/null \
          | grep ':wlan0$' | cut -d: -f1)
    [ -n "$con" ] && [ "$con" != "$AP_CONNECTION" ]
}

log "Waiting up to ${SETTLE_TIMEOUT}s for known WiFi..."
elapsed=0
while [ $elapsed -lt $SETTLE_TIMEOUT ]; do
    if is_wifi_connected; then
        log "HOME MODE — connected to known WiFi. Drone app will NOT start."
        exit 0
    fi
    sleep $CHECK_INTERVAL
    elapsed=$((elapsed + CHECK_INTERVAL))
    log "No WiFi yet (${elapsed}s/${SETTLE_TIMEOUT}s)"
done

log "FIELD MODE — no known WiFi. Starting AP on wlan1 + drone-follow."
nmcli connection up "$AP_CONNECTION"
log "AP active on wlan1: SSID=HailoDrone IP=10.0.0.1 (5GHz ch36)"

sudo -u "$DRONE_USER" XDG_RUNTIME_DIR="/run/user/$(id -u $DRONE_USER)" \
    systemctl --user start "$DRONE_SERVICE"
log "drone-follow started."
