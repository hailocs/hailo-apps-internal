#!/bin/bash
################################################################################
# Ground Station — Uninstall Script
#
# Removes everything install_ground_station.sh installed:
#   - /usr/local/bin/openhd, openhd_sys_utils
#   - /usr/local/share/openhd/*  (configs, df_params.json, txrx.key)
#   - rtl88x2bu / 88x2bu_ohd kernel module + blacklist
#   - regdomain configs
#   - cloned OpenHD/, OpenHD-SysUtils/, qopenHD/ under the app dir (or symlinks)
#
# Does NOT touch:
#   - HailoRT, hailo-all, the parent venv_hailo_apps, drone-follow Python install
#   - The hailo-apps-infra git tree
#
# Idempotent — safe to re-run.
#
# Usage:
#   sudo ./uninstall_ground_station.sh [--keep-clones]
#
#   --keep-clones   Leave the app-dir OpenHD/, OpenHD-SysUtils/, qopenHD/ in
#                   place (useful if you want to inspect them after uninstall).
################################################################################

set -e

if [ "$(id -u)" -ne 0 ]; then
    echo "ERROR: Must run as root (sudo)."
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
APP_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

KEEP_CLONES=false
for arg in "$@"; do
    case "$arg" in
        --keep-clones) KEEP_CLONES=true ;;
        --help|-h)
            sed -n '2,25p' "$0"
            exit 0
            ;;
        *) echo "Unknown option: $arg (try --help)"; exit 1 ;;
    esac
done

remove_path() {
    local path="$1"
    if [ -e "$path" ] || [ -L "$path" ]; then
        rm -rf "$path"
        echo "  removed: $path"
    fi
}

echo "=========================================="
echo " Step 1/4: Remove OpenHD binaries + configs"
echo "=========================================="
remove_path /usr/local/bin/openhd
remove_path /usr/local/bin/openhd_sys_utils
remove_path /usr/local/share/openhd
remove_path /etc/systemd/system/openhd.service
remove_path /etc/systemd/system/openhd-sys-utils.service
systemctl daemon-reload 2>/dev/null || true

echo ""
echo "=========================================="
echo " Step 2/4: Remove WiFi driver (rtl88x2bu / 88x2bu_ohd)"
echo "=========================================="
if lsmod | grep -q '^88x2bu_ohd'; then
    rmmod 88x2bu_ohd 2>/dev/null && echo "  88x2bu_ohd module unloaded" || echo "  WARN: failed to rmmod 88x2bu_ohd (in use?)"
fi
if command -v dkms >/dev/null 2>&1; then
    dkms remove -m rtl88x2bu -v 5.13.1 --all 2>/dev/null && echo "  dkms: removed rtl88x2bu 5.13.1" || true
fi
remove_path /usr/src/rtl88x2bu-5.13.1
find /lib/modules -name '88x2bu_ohd.ko*' -print -delete 2>/dev/null || true
remove_path /etc/modprobe.d/rtw8822bu.conf
depmod -a

echo ""
echo "=========================================="
echo " Step 3/4: Remove regdomain configs"
echo "=========================================="
remove_path /etc/default/crda
remove_path /etc/modprobe.d/cfg80211-regdomain.conf
remove_path /etc/modprobe.d/openhd-regdomain.conf

echo ""
echo "=========================================="
echo " Step 4/4: Remove cloned OpenHD/QOpenHD source trees"
echo "=========================================="
if [ "$KEEP_CLONES" = "true" ]; then
    echo "  --keep-clones: leaving clones in place"
else
    remove_path "${APP_ROOT}/OpenHD"
    remove_path "${APP_ROOT}/OpenHD-SysUtils"
    remove_path "${APP_ROOT}/qopenHD"
fi

echo ""
echo "=========================================="
echo " Ground-station uninstall complete."
echo "=========================================="
echo ""
echo "Preserved:  HailoRT, hailo-all, /usr/local/hailo/resources/,"
echo "            ${HAILO_APPS_PATH:-<hailo-apps-infra>}/venv_hailo_apps/,"
echo "            drone-follow Python install."
echo ""
echo "To reinstall, run scripts/install_ground_station.sh."
