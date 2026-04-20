#!/bin/bash
# Build and install face_landmarks_postprocess shared library.
#
# Usage:
#   ./build.sh              # Build + install to /usr/local/hailo/resources/so/
#   ./build.sh --no-install # Build only (library in build/)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUILD_DIR="${SCRIPT_DIR}/build"

echo "=== Building face landmarks postprocess library ==="

if [ ! -d "${BUILD_DIR}" ]; then
    meson setup "${BUILD_DIR}" "${SCRIPT_DIR}" --prefix=/usr/local/hailo
else
    meson setup --reconfigure "${BUILD_DIR}" "${SCRIPT_DIR}" --prefix=/usr/local/hailo
fi

meson compile -C "${BUILD_DIR}"

echo ""
echo "Build complete. Libraries in: ${BUILD_DIR}/"
ls -la "${BUILD_DIR}"/lib*.so 2>/dev/null || true

if [ "${1:-}" != "--no-install" ]; then
    echo ""
    echo "Installing to /usr/local/hailo/resources/so/ ..."
    sudo meson install -C "${BUILD_DIR}"
    echo "Install complete."
else
    echo ""
    echo "Skipping install (--no-install). To install manually:"
    echo "  sudo meson install -C ${BUILD_DIR}"
fi
