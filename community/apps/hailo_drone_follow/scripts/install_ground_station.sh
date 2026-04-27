#!/bin/bash
################################################################################
# Ground Station — Full Install Script
#
# Installs OpenHD + OpenHD-SysUtils + QOpenHD on an x86_64 or RPi machine.
# Clones (or updates) the three OpenHD repos into the drone-follow repo root —
# no cloning into the home directory.
#
# Usage:
#   sudo ./install_ground_station.sh [--platform <rpi|rpi5|ubuntu-x86>] \
#                                    [--generate-key]
#
# If --platform is not given, auto-detects from /proc/cpuinfo and uname.
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
REPO_DIR="$(dirname "$SCRIPT_DIR")"
RUN_AS_USER="${SUDO_USER:-$USER}"
# Look up the user's actual primary group — don't assume username == group name.
RUN_AS_GROUP="$(id -gn "$RUN_AS_USER")"

# OpenHD repo locations — cloned alongside drone-follow (not in $HOME).
OPENHD_GIT="https://github.com/giladnah/OpenHD.git"
OPENHD_SYSUTILS_GIT="https://github.com/giladnah/OpenHD-SysUtils.git"
QOPENHD_GIT="https://github.com/giladnah/QOpenHD.git"

OPENHD_DIR="$REPO_DIR/OpenHD"
OPENHD_SYSUTILS_DIR="$REPO_DIR/OpenHD-SysUtils"
QOPENHD_DIR="$REPO_DIR/qopenHD"

# Parse args
PLATFORM=""
GENERATE_KEY=false
while [[ $# -gt 0 ]]; do
    case "$1" in
        --platform) PLATFORM="$2"; shift 2 ;;
        --generate-key) GENERATE_KEY=true; shift ;;
        --help|-h)
            cat <<EOF
Usage: sudo $0 [--platform <rpi|rpi5|ubuntu-x86>] [--generate-key]

  --platform       Override auto-detected platform.
  --generate-key   Generate a fresh /usr/local/share/openhd/txrx.key if one is
                   missing. WITHOUT this flag the script will not create a key
                   — air and ground must share the same key, so on the second
                   unit you should copy the key from the first instead. See
                   the printed instructions when no key is found.
EOF
            exit 0
            ;;
        *) echo "Unknown option: $1 (try --help)"; exit 1 ;;
    esac
done

# Auto-detect platform
if [ -z "$PLATFORM" ]; then
    ARCH="$(uname -m)"
    if [ "$ARCH" = "x86_64" ]; then
        PLATFORM="ubuntu-x86"
    elif [ "$ARCH" = "aarch64" ]; then
        MODEL="$(cat /proc/device-tree/model 2>/dev/null || echo "")"
        case "$MODEL" in
            *"Raspberry Pi 5"*) PLATFORM="rpi5" ;;
            *"Raspberry Pi"*)   PLATFORM="rpi"  ;;
            *) echo "ERROR: Unknown aarch64 device: $MODEL"; exit 1 ;;
        esac
    else
        echo "ERROR: Unsupported architecture: $ARCH"
        exit 1
    fi
fi

echo "Platform: $PLATFORM"

# Pin the OpenHD branch so the build matches the protocol drone-follow expects
# (HailoFollowBridge + df_params.json sync live on feature/hailo-apps-integration).
# Override with OPENHD_BRANCH=<name> to build a different branch.
OPENHD_BRANCH="${OPENHD_BRANCH:-feature/hailo-apps-integration}"
# Pin the QOpenHD branch for the same reason — protocol fields (e.g. DF_TGT_ALT)
# live on the Hailo fork. Override with QOPENHD_BRANCH=<name>.
QOPENHD_BRANCH="${QOPENHD_BRANCH:-fix/rpi4-hw-decode}"

# Restore ownership of a path tree to RUN_AS_USER.
# build_native.sh and qmake/make run as root (this script is sudo'd) and may
# leave root-owned files in the user's clone. On a re-run, that breaks user
# git operations, so we rebalance ownership at the end.
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
    # Mark the dir as safe even if a previous run left mixed ownership — git
    # otherwise refuses to operate on a repo whose .git is owned by a different
    # uid than the caller.
    sudo -u "$RUN_AS_USER" git config --global --add safe.directory "$dir" >/dev/null 2>&1 || true
    # --untracked-files=no: ignore build artifacts (they may not all be in the
    # repo's .gitignore, and a previous run may have created them as root).
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
echo " Step 1/7: Install system prerequisites"
echo "=========================================="
apt-get install -y dkms iw git

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
clone_or_pin "$QOPENHD_DIR"         "$QOPENHD_GIT"         "$QOPENHD_BRANCH" recurse

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

echo ""
echo "=========================================="
echo " Step 6/7: Install & build QOpenHD"
echo "=========================================="
cd "$QOPENHD_DIR"
./install_build_dep.sh "$PLATFORM"

# Submodules may have been added after the initial clone — refresh just in case.
sudo -u "$RUN_AS_USER" git submodule update --init --recursive

# Compile Qt translation files (required before build)
sudo -u "$RUN_AS_USER" lrelease translations/*.ts
sudo -u "$RUN_AS_USER" cp translations/*.qm qml/

mkdir -p build/release
cd build/release
qmake ../..
make -j$(nproc)

# Restore user ownership of the OpenHD/QOpenHD trees so subsequent re-runs of
# this script — and the user's own `git pull` — work without permission errors.
chown_back "$OPENHD_DIR"
chown_back "$OPENHD_SYSUTILS_DIR"
chown_back "$QOPENHD_DIR"

echo ""
echo "=========================================="
echo " Step 7/7: Deploy config files"
echo "=========================================="
mkdir -p /usr/local/share/openhd
if [ -f "$REPO_DIR/df_params.json" ]; then
    cp "$REPO_DIR/df_params.json" /usr/local/share/openhd/df_params.json
    echo "df_params.json deployed."
else
    echo "WARNING: $REPO_DIR/df_params.json not found, skipping."
fi

normalize_wb_frequency

# txrx.key must be IDENTICAL on air and ground for the WFB radio link to work.
# Auto-generating silently is dangerous: if you install the second unit before
# copying the first unit's key, you'd end up with two mismatched keys and a
# silent link failure. So:
#   - If a key exists, keep it.
#   - If --generate-key was passed, generate a fresh one (first install).
#   - Otherwise, print clear instructions and leave it absent.
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
echo " Ground station install complete!"
echo "=========================================="
echo ""
echo "Platform:  $PLATFORM"
echo "Binaries:"
echo "  OpenHD:        /usr/local/bin/openhd"
echo "  SysUtils:      /usr/local/bin/openhd_sys_utils"
echo "  QOpenHD:       $QOPENHD_DIR/build/release/release/QOpenHD"
echo ""
echo "Run:"
echo "  scripts/start_ground.sh"
