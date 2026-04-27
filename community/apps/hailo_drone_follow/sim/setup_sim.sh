#!/bin/bash
# Setup script for PX4 SITL simulation
# Initialises the PX4-Autopilot git submodule (v1.14.0) and builds the SITL firmware.
#
# Usage: sim/setup_sim.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
PX4_DIR="$SCRIPT_DIR/PX4-Autopilot"
PX4_VERSION="v1.14.0"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo "========================================="
echo "  PX4 SITL Simulation Setup"
echo "========================================="
echo ""

# Step 1: Clone and setup PX4-Autopilot at the pinned version
echo -e "${GREEN}[1/3] Setting up PX4-Autopilot ($PX4_VERSION)...${NC}"
PX4_URL="https://github.com/PX4/PX4-Autopilot.git"

if [ ! -d "$PX4_DIR/.git" ]; then
    echo -e "  Cloning PX4-Autopilot into $PX4_DIR..."
    git clone "$PX4_URL" "$PX4_DIR"
fi

cd "$PX4_DIR"
git fetch --tags origin

# Ensure we're on the pinned version
CURRENT=$(git describe --tags 2>/dev/null || echo "unknown")
if [ "$CURRENT" != "$PX4_VERSION" ]; then
    echo -e "${YELLOW}  Checking out $PX4_VERSION (currently on $CURRENT)...${NC}"
    git checkout -f "$PX4_VERSION"
fi

# Init PX4's own recursive submodules
echo -e "  Initialising PX4 internal submodules (this may take a few minutes)..."
git submodule update --init --recursive

echo -e "  PX4-Autopilot at: $PX4_DIR"
echo -e "  Version: $(git describe --tags 2>/dev/null || echo 'unknown')"

# Step 2: Apply patches
echo ""
echo -e "${GREEN}[2/3] Applying patches...${NC}"

# Helper: apply a patch if not already applied
apply_patch() {
    local patch_file="$1"
    local description="$2"
    if [ ! -f "$patch_file" ]; then
        echo -e "${RED}  Error: Patch file not found at $patch_file${NC}"
        exit 1
    fi
    if git apply --check "$patch_file" 2>/dev/null; then
        git apply "$patch_file"
        echo -e "  Applied: $description"
    else
        echo -e "${YELLOW}  Already applied or conflicts — skipping: $description${NC}"
    fi
}

# Gazebo Harmonic (gz-transport13) compatibility for PX4 v1.14 (expects gz-transport12)
apply_patch "$SCRIPT_DIR/patches/gz_transport13_compat.patch" "gz-transport13 compatibility"

# Camera sensor on x500_vision model
apply_patch "$SCRIPT_DIR/patches/x500_vision_camera.patch" "x500_vision camera sensor"

# Step 3: Build PX4 SITL
echo ""
echo -e "${GREEN}[3/3] Building PX4 SITL firmware (this may take 10-20 minutes on first build)...${NC}"
# PX4 v1.14 does not compile cleanly with GCC 12+/13+:
#   - False-positive -Warray-bounds in the matrix template lib → downgrade to warning
#   - Missing <cstdint> includes (GCC 13 no longer transitively provides uint8_t) → force-include
# These flags are only read by CMake at initial configure, so if the build dir
# already exists from before these flags were added, delete it first (or run
# `rm -rf build/px4_sitl_default` manually).
export CXXFLAGS="${CXXFLAGS:+$CXXFLAGS }-Wno-error=array-bounds -include cstdint"
make px4_sitl_default

echo ""
echo -e "${GREEN}Setup complete!${NC}"
echo ""
echo "Next steps (local):"
echo "  1. Start the simulator:  sim/start_sim.sh --bridge --world 2_person_world"
echo "  2. In another terminal:  source setup_env.sh"
echo "     drone-follow --input udp://0.0.0.0:5600 --takeoff-landing --ui"
echo ""
echo "Next steps (remote — drone-follow on another machine):"
echo "  1. On this machine:      sim/start_sim.sh --remote <DRONE_APP_IP> --world 2_person_world"
echo "  2. On the remote machine: source setup_env.sh"
echo "     drone-follow --input udp://0.0.0.0:5600 --takeoff-landing --ui"
