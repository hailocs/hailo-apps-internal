#!/bin/bash
################################################################################
# Air Unit — Full Install Script
#
# Target: Raspberry Pi 5 (or RPi4) with a Hailo-8L M.2 mounted on the drone.
# Installs hailo-all, builds OpenHD + OpenHD-SysUtils + WiFi driver, sets up the
# drone-follow venv + UI, and deploys df_params.json. QOpenHD is NOT installed
# here — the air unit doesn't need it.
#
# Clones (or updates) OpenHD + OpenHD-SysUtils into the drone-follow repo root —
# no cloning into the home directory.
#
# Usage:
#   sudo ./install_air.sh [--platform <rpi|rpi5>] [--generate-key]
#
# If --platform is not given, auto-detects from /proc/device-tree/model.
# Pass --generate-key on the FIRST unit to create /usr/local/share/openhd/txrx.key;
# on the second unit, copy that key over instead (the radio link needs matching
# keys on both ends).
################################################################################

set -e

if [ "$(id -u)" -ne 0 ]; then
    echo "ERROR: Must run as root (sudo)."
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
APP_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
RUN_AS_USER="${SUDO_USER:-$USER}"

# Resolve apps-infra root without relative traversal.
ENV_FILE="/usr/local/hailo/resources/.env"
if [[ -z "${HAILO_APPS_PATH:-}" && -f "${ENV_FILE}" ]]; then
  HAILO_APPS_PATH=$(grep -iE '^HAILO_APPS_PATH=' "${ENV_FILE}" | tail -1 | cut -d= -f2- | tr -d '"')
  export HAILO_APPS_PATH
fi
if [[ -z "${HAILO_APPS_PATH:-}" || ! -d "${HAILO_APPS_PATH}" ]]; then
  echo "ERROR: HAILO_APPS_PATH not resolvable. Run hailo-apps-infra/install.sh first." >&2
  exit 1
fi
APPS_INFRA_ROOT="${HAILO_APPS_PATH}"
# Look up the user's actual primary group — don't assume username == group name.
RUN_AS_GROUP="$(id -gn "$RUN_AS_USER")"

# OpenHD repo locations — cloned alongside drone-follow (not in $HOME).
OPENHD_GIT="https://github.com/giladnah/OpenHD.git"
OPENHD_SYSUTILS_GIT="https://github.com/giladnah/OpenHD-SysUtils.git"

OPENHD_DIR="${APP_ROOT}/OpenHD"
OPENHD_SYSUTILS_DIR="${APP_ROOT}/OpenHD-SysUtils"

# Parse args
PLATFORM=""
GENERATE_KEY=false
while [[ $# -gt 0 ]]; do
    case "$1" in
        --platform) PLATFORM="$2"; shift 2 ;;
        --generate-key) GENERATE_KEY=true; shift ;;
        --help|-h)
            cat <<EOF
Usage: sudo $0 [--platform <rpi|rpi5>] [--generate-key]

  --platform       Override auto-detected platform.
  --generate-key   Generate a fresh /usr/local/share/openhd/txrx.key if one is
                   missing. WITHOUT this flag the script will not create a key
                   — air and ground must share the same key, so on the second
                   unit you should copy the key from the first instead.
EOF
            exit 0
            ;;
        *) echo "Unknown option: $1 (try --help)"; exit 1 ;;
    esac
done

# Auto-detect RPi platform
if [ -z "$PLATFORM" ]; then
    ARCH="$(uname -m)"
    if [ "$ARCH" = "aarch64" ]; then
        MODEL="$(cat /proc/device-tree/model 2>/dev/null || echo "")"
        case "$MODEL" in
            *"Raspberry Pi 5"*) PLATFORM="rpi5" ;;
            *"Raspberry Pi"*)   PLATFORM="rpi"  ;;
            *) echo "ERROR: Unknown aarch64 device: $MODEL"; exit 1 ;;
        esac
    else
        echo "ERROR: install_air.sh is for the RPi air unit (got $ARCH)."
        echo "       For an x86_64 dev machine, run ./install.sh directly."
        exit 1
    fi
fi

echo "Platform: $PLATFORM"

# Pin the OpenHD branch so the build matches the protocol drone-follow expects
# (HailoFollowBridge + df_params.json sync live on feature/hailo-apps-integration).
# Override with OPENHD_BRANCH=<name> to build a different branch.
OPENHD_BRANCH="${OPENHD_BRANCH:-feature/hailo-apps-integration}"

# Restore ownership of a path tree to RUN_AS_USER. The build steps run as root
# (this script is sudo'd) and may leave root-owned files in user-owned clones;
# rebalance ownership at the end so re-runs and the user's `git pull` work.
chown_back() {
    local dir="$1"
    [ -e "$dir" ] || return 0
    chown -R "$RUN_AS_USER:$RUN_AS_GROUP" "$dir"
}

# Idempotently write $2 to $1 if the file is missing or has different content.
write_config_if_needed() {
    local path="$1" content="$2"
    if [ -f "$path" ] && [ "$(cat "$path" 2>/dev/null)" = "$content" ]; then
        echo "  $path: already up to date"
        return
    fi
    mkdir -p "$(dirname "$path")"
    printf '%s\n' "$content" > "$path"
    echo "  $path: written"
}

# Persistent regulatory-domain fix that unlocks 5 GHz on the RTL8812BU monitor
# card. Without these, the card defaults to country 00 (world) which disables
# 5 GHz channels OpenHD wants. See memory: reference_openhd_wifi_regdomain.md.
deploy_regdomain_config() {
    write_config_if_needed /etc/default/crda                       "REGDOMAIN=US"
    write_config_if_needed /etc/modprobe.d/cfg80211-regdomain.conf "options cfg80211 ieee80211_regdom=US"
    write_config_if_needed /etc/modprobe.d/openhd-regdomain.conf   "options 88x2bu_ohd rtw_country_code=US"
}

# build_native.sh installs 88x2bu_ohd.ko into /lib/modules/$(uname -r) but
# doesn't run depmod or modprobe. Without this OpenHD reports "no wifibroadcast
# card found" until the user reboots or replugs.
load_openhd_driver() {
    depmod -a
    if lsmod | grep -q '^88x2bu_ohd'; then
        echo "  88x2bu_ohd already loaded"
        return
    fi
    if modprobe 88x2bu_ohd; then
        echo "  88x2bu_ohd loaded"
    else
        echo "  WARNING: failed to load 88x2bu_ohd. Replug the USB adapter or reboot."
    fi
}

# Channel 36 (5180 MHz, UNII-1) is the only 5 GHz channel allowed in every
# regulatory domain (including country 00) and is non-DFS — so air and ground
# can always agree out of the box without per-region tuning. Override via
# WB_DEFAULT_FREQUENCY=<MHz> in the environment.
WB_DEFAULT_FREQUENCY="${WB_DEFAULT_FREQUENCY:-5180}"
normalize_wb_frequency() {
    local f=/usr/local/share/openhd/interface/wifibroadcast_settings.json
    if [ -f "$f" ]; then
        if grep -q '"wb_frequency"' "$f"; then
            sed -i 's/"wb_frequency": *[0-9]\+/"wb_frequency": '"$WB_DEFAULT_FREQUENCY"'/' "$f"
            echo "  $f: wb_frequency=$WB_DEFAULT_FREQUENCY"
        else
            echo "  WARNING: $f exists but has no wb_frequency key"
        fi
    else
        # Fresh install — pre-seed so OpenHD's first run uses our channel.
        # Other defaults will be filled in by OpenHD on startup.
        mkdir -p "$(dirname "$f")"
        printf '{\n    "wb_frequency": %s\n}\n' "$WB_DEFAULT_FREQUENCY" > "$f"
        echo "  $f: pre-seeded wb_frequency=$WB_DEFAULT_FREQUENCY"
    fi
}

# Clone-or-pin a repo at $1 from $2 onto branch $3, with optional --recurse-submodules.
clone_or_pin() {
    local dir="$1" url="$2" branch="$3" recurse="${4:-}"
    if [ ! -d "$dir/.git" ]; then
        echo "Cloning $url into $dir (branch: $branch)..."
        local extra=()
        [ "$recurse" = "recurse" ] && extra+=(--recurse-submodules)
        sudo -u "$RUN_AS_USER" git clone "${extra[@]}" -b "$branch" "$url" "$dir"
        return
    fi
    echo "Updating existing repo $dir on branch $branch..."
    sudo -u "$RUN_AS_USER" git config --global --add safe.directory "$dir" >/dev/null 2>&1 || true
    if [ -n "$(cd "$dir" && sudo -u "$RUN_AS_USER" git status --porcelain --untracked-files=no)" ]; then
        echo "ERROR: $dir has uncommitted changes to tracked files."
        echo "       Commit or stash them, then re-run this script."
        exit 1
    fi
    (
        cd "$dir"
        sudo -u "$RUN_AS_USER" git fetch origin --tags
        sudo -u "$RUN_AS_USER" git checkout "$branch"
        sudo -u "$RUN_AS_USER" git pull --ff-only origin "$branch"
    )
}

echo ""
echo "=========================================="
echo " Step 1/7: Install Hailo + system prerequisites"
echo "=========================================="
apt-get update
apt-get install -y dkms iw git hailo-all

# Verify the Hailo device is reachable. Fresh hailo-all installs sometimes
# need a reboot before the driver loads, so don't fail hard — warn and continue.
if hailortcli fw-control identify >/dev/null 2>&1; then
    echo "Hailo device detected."
else
    echo "WARNING: hailortcli fw-control identify failed."
    echo "         A reboot may be required after a fresh 'hailo-all' install."
    echo "         If the build/install completes but drone-follow can't see the"
    echo "         Hailo device, reboot and re-run scripts/start_air.sh."
fi

# Pipeline reads JSON configs from here — make sure they're world-readable.
if compgen -G "/usr/local/hailo/resources/json/*.json" >/dev/null; then
    chmod 644 /usr/local/hailo/resources/json/*.json
fi

# hailo-all ships /usr/local/hailo/resources/ as root:root, but hailo-apps
# downloads HEFs and writes its .env into that tree at runtime as the user.
# Hand the directory to RUN_AS_USER so on-demand model downloads don't EACCES.
chown_back /usr/local/hailo/resources

echo ""
echo "=========================================="
echo " Step 2/7: Configure WiFi regulatory domain"
echo "=========================================="
deploy_regdomain_config

echo ""
echo "=========================================="
echo " Step 3/7: Clone / update OpenHD repos"
echo "=========================================="
clone_or_pin "$OPENHD_DIR"          "$OPENHD_GIT"          "$OPENHD_BRANCH"  recurse
clone_or_pin "$OPENHD_SYSUTILS_DIR" "$OPENHD_SYSUTILS_GIT" "main"

echo ""
echo "=========================================="
echo " Step 4/7: Install OpenHD dependencies"
echo "=========================================="
cd "$OPENHD_DIR"
./install_build_dep.sh "$PLATFORM"

echo ""
echo "=========================================="
echo " Step 5/7: Build OpenHD + SysUtils + WiFi driver"
echo "=========================================="
./build_native.sh all
load_openhd_driver

chown_back "$OPENHD_DIR"
chown_back "$OPENHD_SYSUTILS_DIR"

echo ""
echo "=========================================="
echo " Step 6/7: Verify drone-follow is installed"
echo "=========================================="
# install_air.sh runs AFTER the parent hailo-apps-infra installer
# (creates venv_hailo_apps + writes /usr/local/hailo/resources/.env) and
# AFTER the per-app install.sh (installs drone-follow into that venv,
# downloads ReID HEFs, builds the UI). Verify both have happened; we
# don't re-run them here. Run the per-app install.sh manually first if
# this assertion fails.
if [ ! -x "${APPS_INFRA_ROOT}/venv_hailo_apps/bin/drone-follow" ]; then
    echo "ERROR: ${APPS_INFRA_ROOT}/venv_hailo_apps/bin/drone-follow missing." >&2
    echo "       Run ${APPS_INFRA_ROOT}/install.sh, then ${APP_ROOT}/install.sh, then re-run this script." >&2
    exit 1
fi

# Targeted chown for files our prior steps (apt, OpenHD build) may have
# left root-owned. We deliberately don't chown the whole APP_ROOT —
# git-tracked files were already user-owned and we don't want to touch
# unrelated files the user has staged.
chown_back "${APP_ROOT}/drone_follow/ui/node_modules"
chown_back "${APP_ROOT}/drone_follow/ui/build"
for egg in "${APP_ROOT}"/*.egg-info; do
    [ -e "$egg" ] && chown_back "$egg"
done
# hailo-post-install (run by the parent installer) drops files into
# /usr/local/hailo/resources/. Belt-and-braces: ensure the tree is user-
# owned so subsequent runtime model downloads don't EACCES.
chown_back /usr/local/hailo/resources

echo ""
echo "=========================================="
echo " Step 7/7: Deploy config files"
echo "=========================================="
mkdir -p /usr/local/share/openhd
if [ -f "${APP_ROOT}/df_params.json" ]; then
    cp "${APP_ROOT}/df_params.json" /usr/local/share/openhd/df_params.json
    echo "df_params.json deployed."
else
    echo "WARNING: ${APP_ROOT}/df_params.json not found, skipping."
fi

normalize_wb_frequency

# Force OpenHD into Mode A (X_CAM_TYPE_HAILO_AI = 5). With the default
# (31 = IMX219) OpenHD acquires the CSI camera itself at startup, which
# starves drone-follow's Picamera2 with "Device or resource busy". In Mode A
# drone-follow owns the camera and pushes RTP to OpenHD via --openhd-stream
# (the layout scripts/start_air.sh uses). Idempotent: only writes if the
# value differs. See CLAUDE.md "OpenHD Camera Modes" for context.
CAM_CONFIG="/usr/local/share/openhd/video/air_camera_generic.json"
if [ -f "$CAM_CONFIG" ]; then
    python3 - "$CAM_CONFIG" <<'PY'
import json, pathlib, sys
path = pathlib.Path(sys.argv[1])
data = json.loads(path.read_text())
if data.get("primary_camera_type") != 5:
    data["primary_camera_type"] = 5
    path.write_text(json.dumps(data, indent=4) + "\n")
    print(f"Set primary_camera_type=5 (Mode A / HAILO_AI) in {path}")
else:
    print(f"primary_camera_type already 5 in {path}")
PY
else
    echo "WARNING: $CAM_CONFIG not found — set camera type 5 manually after the first OpenHD start."
fi

# txrx.key must be IDENTICAL on air and ground for the WFB radio link to work.
# See install_ground_station.sh for the full reasoning behind --generate-key.
KEY_PATH="/usr/local/share/openhd/txrx.key"
if [ -f "$KEY_PATH" ]; then
    echo "txrx.key already present at $KEY_PATH — keeping existing key."
elif [ "$GENERATE_KEY" = "true" ]; then
    echo "Generating fresh txrx.key at $KEY_PATH (first-install mode)."
    echo "IMPORTANT: Copy this key to the OTHER unit before flying:"
    echo "    sudo scp $KEY_PATH <other-unit>:$KEY_PATH"
    dd if=/dev/urandom of="$KEY_PATH" bs=32 count=1 2>/dev/null
    chmod 644 "$KEY_PATH"
else
    cat <<EOF

WARNING: $KEY_PATH is missing.
         The radio link requires the SAME txrx.key on both air and ground.
         Choose one of:

           (a) Copy the existing key from the other unit:
                 sudo scp <other-unit>:$KEY_PATH /tmp/txrx.key
                 sudo install -m 644 /tmp/txrx.key $KEY_PATH

           (b) If this is the FIRST unit being installed (no key exists
               anywhere yet), re-run this script with --generate-key to
               create one, then scp it to the other unit afterwards.

         Skipping key step.
EOF
fi

echo ""
echo "=========================================="
echo " Air unit install complete!"
echo "=========================================="
echo ""
echo "Platform:  $PLATFORM"
echo "Binaries:"
echo "  OpenHD:        /usr/local/bin/openhd"
echo "  SysUtils:      /usr/local/bin/openhd_sys_utils"
echo "  drone-follow:  ${APP_ROOT}/venv/bin/drone-follow"
echo ""
echo "Run:"
echo "  ${APP_ROOT}/scripts/start_air.sh"
echo ""
echo "Optional — auto-start at boot:"
echo "  sudo ${APP_ROOT}/scripts/boot/install.sh"
