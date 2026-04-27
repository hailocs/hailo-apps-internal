#!/bin/bash
################################################################################
# Air Unit — Uninstall Script
#
# Removes everything install_air.sh + scripts/boot/install.sh installed:
#   - /usr/local/bin/openhd, openhd_sys_utils
#   - /usr/local/share/openhd/*  (configs, df_params.json, txrx.key)
#   - rtl88x2bu / 88x2bu_ohd kernel module + blacklist
#   - regdomain configs (/etc/default/crda, /etc/modprobe.d/*)
#   - cloned OpenHD/, OpenHD-SysUtils/ under the app dir
#   - drone-follow-boot.service + /usr/local/bin/drone-follow-boot.sh symlink
#   - ~/Desktop/drone-follow.conf
#
# Does NOT touch:
#   - HailoRT, hailo-all, the parent venv_hailo_apps, drone-follow Python install
#   - /usr/local/hailo/resources/  (hailo-apps owns this)
#   - The hailo-apps-infra git tree
#
# Idempotent — safe to re-run.
#
# Usage:
#   sudo ./uninstall_air.sh [--keep-clones]
#
#   --keep-clones   Leave the app-dir OpenHD/ and OpenHD-SysUtils/ clones in
#                   place (useful if you want to inspect them after uninstall).
################################################################################

set -e

if [ "$(id -u)" -ne 0 ]; then
    echo "ERROR: Must run as root (sudo)."
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
APP_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
RUN_AS_USER="${SUDO_USER:-$USER}"

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

# Helper — only print one removed-X line per concern, no spam if missing.
remove_path() {
    local path="$1"
    if [ -e "$path" ] || [ -L "$path" ]; then
        rm -rf "$path"
        echo "  removed: $path"
    fi
}

echo "=========================================="
echo " Step 1/5: Stop + remove boot service"
echo "=========================================="
if systemctl list-unit-files | grep -q '^drone-follow-boot.service'; then
    systemctl stop drone-follow-boot.service 2>/dev/null || true
    systemctl disable drone-follow-boot.service 2>/dev/null || true
    echo "  service stopped + disabled"
fi
remove_path /etc/systemd/system/drone-follow-boot.service
remove_path /etc/systemd/system/multi-user.target.wants/drone-follow-boot.service
remove_path /usr/local/bin/drone-follow-boot.sh
systemctl daemon-reload
remove_path "/home/${RUN_AS_USER}/Desktop/drone-follow.conf"

echo ""
echo "=========================================="
echo " Step 2/5: Remove OpenHD binaries + configs"
echo "=========================================="
remove_path /usr/local/bin/openhd
remove_path /usr/local/bin/openhd_sys_utils
remove_path /usr/local/share/openhd
# Service files installed by OpenHD's deb / build
remove_path /etc/systemd/system/openhd.service
remove_path /etc/systemd/system/openhd-sys-utils.service
systemctl daemon-reload

echo ""
echo "=========================================="
echo " Step 3/5: Remove WiFi driver (rtl88x2bu / 88x2bu_ohd)"
echo "=========================================="
if lsmod | grep -q '^88x2bu_ohd'; then
    rmmod 88x2bu_ohd 2>/dev/null && echo "  88x2bu_ohd module unloaded" || echo "  WARN: failed to rmmod 88x2bu_ohd (in use?)"
fi
# rtl88x2bu via DKMS (deb path)
if command -v dkms >/dev/null 2>&1; then
    dkms remove -m rtl88x2bu -v 5.13.1 --all 2>/dev/null && echo "  dkms: removed rtl88x2bu 5.13.1" || true
fi
remove_path /usr/src/rtl88x2bu-5.13.1
# Module .ko files installed by build_native.sh
find /lib/modules -maxdepth 4 -name '88x2bu_ohd.ko*' -print -delete 2>/dev/null || true
remove_path /etc/modprobe.d/rtw8822bu.conf
depmod -a

echo ""
echo "=========================================="
echo " Step 4/5: Remove regdomain configs"
echo "=========================================="
remove_path /etc/default/crda
remove_path /etc/modprobe.d/cfg80211-regdomain.conf
remove_path /etc/modprobe.d/openhd-regdomain.conf

echo ""
echo "=========================================="
echo " Step 5/5: Remove cloned OpenHD source trees"
echo "=========================================="
if [ "$KEEP_CLONES" = "true" ]; then
    echo "  --keep-clones: leaving ${APP_ROOT}/OpenHD and ${APP_ROOT}/OpenHD-SysUtils in place"
else
    remove_path "${APP_ROOT}/OpenHD"
    remove_path "${APP_ROOT}/OpenHD-SysUtils"
fi

echo ""
echo "=========================================="
echo " Air-unit uninstall complete."
echo "=========================================="
echo ""
echo "Preserved:  HailoRT, hailo-all, /usr/local/hailo/resources/,"
echo "            ${HAILO_APPS_PATH:-<hailo-apps-infra>}/venv_hailo_apps/,"
echo "            drone-follow Python install."
echo ""
echo "To reinstall, run scripts/install_air.sh."
