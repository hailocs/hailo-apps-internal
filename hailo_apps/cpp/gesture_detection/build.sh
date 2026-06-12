#!/bin/bash
# Build the standalone gesture detection app.
# Usage: ./build.sh [clean]

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUILD_DIR="${SCRIPT_DIR}/build"

if [ "$1" = "clean" ]; then
    echo "Cleaning build directory..."
    rm -rf "${BUILD_DIR}"
fi

mkdir -p "${BUILD_DIR}"
cd "${BUILD_DIR}"

cmake "${SCRIPT_DIR}" -DCMAKE_BUILD_TYPE=Release
make -j$(nproc)

echo ""
echo "Build successful!"
echo "Binary: ${BUILD_DIR}/gesture_detection"
echo ""
echo "Usage:"
echo "  ${BUILD_DIR}/gesture_detection --palm-model <palm.hef> --hand-model <hand.hef>"
echo "  ${BUILD_DIR}/gesture_detection --input video.mp4"
echo "  ${BUILD_DIR}/gesture_detection --input photo.jpg"
