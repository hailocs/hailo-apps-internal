#!/bin/bash
# Start PX4 SITL + Gazebo Garden with the x500_vision drone (includes camera).
#
# Usage: sim/start_sim.sh [--bridge] [--remote IP] [--world NAME]
#
# Options:
#   --bridge        Also start the video bridge (Gazebo camera -> UDP 5600)
#   --remote IP     Run simulation for a remote drone-follow machine.
#                   Starts the video bridge targeting the remote IP and a
#                   MAVLink UDP relay so the remote machine receives both
#                   video and MAVLink.  Implies --bridge.
#   --world NAME    Load a custom world from sim/worlds/ (e.g. 2_person_world)
#                   Defaults to PX4's built-in default world.
#
# Environment variables:
#   HEADLESS=1      Run Gazebo without GUI (useful for CI / remote machines)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
PX4_DIR="$SCRIPT_DIR/PX4-Autopilot"
SDF_WORLDS="$SCRIPT_DIR/worlds"
BRIDGE_SCRIPT="$SCRIPT_DIR/bridge/video_bridge.py"
RELAY_SCRIPT="$SCRIPT_DIR/mavlink_relay.py"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0m'

list_worlds() {
    for f in "$SDF_WORLDS"/*.sdf; do
        [ -f "$f" ] && echo "  $(basename "$f" .sdf)"
    done
}

# Parse flags
START_BRIDGE=false
REMOTE_IP=""
WORLD=""
while [[ $# -gt 0 ]]; do
    case $1 in
        --bridge) START_BRIDGE=true; shift ;;
        --remote)
            if [ -z "$2" ] || [[ "$2" == --* ]]; then
                echo -e "${RED}Error: --remote requires an IP address${NC}"
                echo "Usage: $0 --remote <IP> [--world NAME]"
                exit 1
            fi
            REMOTE_IP="$2"; START_BRIDGE=true; shift 2 ;;
        --world)
            if [ -z "$2" ] || [[ "$2" == --* ]]; then
                echo -e "${RED}Error: --world requires a world name${NC}"
                echo "Available worlds:"
                list_worlds
                exit 1
            fi
            WORLD="$2"; shift 2 ;;
        *)
            echo -e "${RED}Unknown argument: $1${NC}"
            echo "Usage: $0 [--bridge] [--remote IP] [--world NAME]"
            exit 1 ;;
    esac
done

# Preflight checks
if [ ! -d "$PX4_DIR/build/px4_sitl_default" ]; then
    echo -e "${RED}Error: PX4 SITL not built. Run sim/setup_sim.sh first.${NC}"
    exit 1
fi

# Set GZ_SIM_RESOURCE_PATH so Gazebo can find custom models (e.g. "Walking actor")
export GZ_SIM_RESOURCE_PATH="${SDF_WORLDS}:${GZ_SIM_RESOURCE_PATH:-}"

# Install custom world into PX4's worlds directory (symlink)
# PX4's gz_env.sh hardcodes PX4_GZ_WORLDS to its own worlds dir,
# so we symlink our SDF files there instead of overriding the env var.
PX4_WORLDS_DIR="$PX4_DIR/Tools/simulation/gz/worlds"
if [ -n "$WORLD" ]; then
    WORLD_FILE="$SDF_WORLDS/${WORLD}.sdf"
    if [ ! -f "$WORLD_FILE" ]; then
        echo -e "${RED}Error: World not found: $WORLD_FILE${NC}"
        echo "Available worlds:"
        list_worlds
        exit 1
    fi
    ln -sf "$WORLD_FILE" "$PX4_WORLDS_DIR/${WORLD}.sdf"
    export PX4_GZ_WORLD="$WORLD"
fi

echo -e "${GREEN}Starting PX4 SITL + Gazebo (x500_vision with camera)...${NC}"
echo "  PX4:        $PX4_DIR"
echo "  SDF models: $SDF_WORLDS"
if [ -n "$WORLD" ]; then
    echo "  World:      $WORLD"
else
    echo "  World:      default"
fi
echo "  MAVLink:    udp://localhost:14540"

if [ -n "$REMOTE_IP" ]; then
    BRIDGE_HOST="$REMOTE_IP"
    echo "  Remote:     $REMOTE_IP"
    echo "  Bridge:     video_bridge.py -> udp://${REMOTE_IP}:5600"
    echo "  Relay:      mavlink_relay.py -> ${REMOTE_IP}:14540"
elif $START_BRIDGE; then
    BRIDGE_HOST="127.0.0.1"
    echo "  Bridge:     video_bridge.py -> udp://127.0.0.1:5600"
else
    echo "  Camera:     use --bridge or run sim/bridge/video_bridge.py separately"
fi
echo ""

# Print remote machine instructions
if [ -n "$REMOTE_IP" ]; then
    echo -e "${GREEN}On the remote machine ($REMOTE_IP), run:${NC}"
    echo "  source setup_env.sh"
    echo "  drone-follow --input udp://0.0.0.0:5600 --takeoff-landing --ui"
    echo ""
fi

# Collect background PIDs for cleanup
BG_PIDS=()

cleanup() {
    for pid in "${BG_PIDS[@]}"; do
        kill "$pid" 2>/dev/null || true
        wait "$pid" 2>/dev/null || true
    done
}
trap cleanup EXIT

# Start MAVLink relay if remote
if [ -n "$REMOTE_IP" ]; then
    echo -e "${GREEN}Starting MAVLink relay...${NC}"
    python3 "$RELAY_SCRIPT" "$REMOTE_IP" &
    BG_PIDS+=($!)
fi

# Start video bridge if requested
if $START_BRIDGE; then
    echo -e "${GREEN}Starting video bridge...${NC}"
    PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python python3 "$BRIDGE_SCRIPT" --host "$BRIDGE_HOST" &
    BG_PIDS+=($!)
fi

cd "$PX4_DIR"
make px4_sitl gz_x500_vision
