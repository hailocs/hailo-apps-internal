#!/bin/bash
# Runs OpenHD air and drone-follow side by side on the drone (RPi).
#
# Two camera modes (see CLAUDE.md "OpenHD Camera Modes"):
#   stream (default) — Mode A: drone-follow owns the CSI camera, encodes the
#                      overlay and pushes RTP to OpenHD via --openhd-stream.
#   shm              — Mode B: OpenHD owns the camera and tees raw NV12 to
#                      /tmp/openhd_raw_video; drone-follow reads from SHM and
#                      runs AI only (no encoding, no overlay in WFB stream).
#
# The companion install_air.sh writes the matching primary_camera_type and
# /boot/openhd/hailo.txt flag — pass the same --mode to both.

MODE="stream"
while [[ $# -gt 0 ]]; do
    case "$1" in
        --mode)
            MODE="$2"; shift 2
            ;;
        -h|--help)
            cat <<EOF
Usage: $0 [--mode <stream|shm>]

  --mode stream  (default) Mode A: drone-follow owns the camera, encodes overlay,
                 pushes RTP to OpenHD on UDP 5500 (--openhd-stream).
  --mode shm     Mode B: OpenHD owns the camera; drone-follow reads raw frames
                 from /tmp/openhd_raw_video and does AI only.

The mode must match how the air unit was configured by install_air.sh
(primary_camera_type + /boot/openhd/hailo.txt).
EOF
            exit 0
            ;;
        *) echo "Unknown option: $1 (try --help)"; exit 1 ;;
    esac
done

case "$MODE" in
    stream|shm) ;;
    *) echo "ERROR: --mode must be 'stream' or 'shm' (got: $MODE)"; exit 1 ;;
esac

SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
APP_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
OPENHD_BIN="/usr/local/bin/openhd"

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

if [ ! -f "$OPENHD_BIN" ]; then
    echo "Error: openhd not found at $OPENHD_BIN"
    exit 1
fi

# Start OpenHD air in the background
sudo "$OPENHD_BIN" --air &
OPENHD_PID=$!
sleep 3

# Set up drone-follow environment and run
cd "${APPS_INFRA_ROOT}"
source "${APPS_INFRA_ROOT}/setup_env.sh"
export DISPLAY=:0

# Auto-load saved controller tuning if present (see PARAMETERS.md).
# The file is gitignored and created via the web UI / QOpenHD "Save Config"
# button or `drone-follow --save-config ${APP_ROOT}/df_config.json`.
CONFIG_FILE="${APP_ROOT}/df_config.json"
CONFIG_ARG=()
if [ -f "$CONFIG_FILE" ]; then
    CONFIG_ARG=(--config "$CONFIG_FILE")
    echo "Loading controller config: $CONFIG_FILE"
else
    echo "No df_config.json found at $CONFIG_FILE — using ControllerConfig defaults"
fi

case "$MODE" in
    stream) MODE_ARGS=(--input rpi --openhd-stream) ;;
    shm)    MODE_ARGS=(--input shm:///tmp/openhd_raw_video --no-display) ;;
esac

drone-follow "${MODE_ARGS[@]}" "${CONFIG_ARG[@]}" --connection tcpout://127.0.0.1:5760 --tiles-x 2 --tiles-y 2 &
FOLLOW_PID=$!

trap "kill $FOLLOW_PID 2>/dev/null; sudo kill $OPENHD_PID 2>/dev/null; wait" EXIT

echo "OpenHD PID: $OPENHD_PID"
echo "drone-follow PID: $FOLLOW_PID"
echo "Press Ctrl+C to stop both"

wait
