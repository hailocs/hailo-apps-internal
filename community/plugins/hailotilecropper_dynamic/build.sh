#!/bin/bash
# Build and install the dynamic tile-cropper GStreamer element
# (hailotilecropper_dynamic) into the system GStreamer plugin directory.
#
# Usage:
#   ./build.sh              # Build + install (needs sudo for the gst plugin dir)
#   ./build.sh --no-install # Build only (library left in build/)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUILD_DIR="${SCRIPT_DIR}/build"

echo "=== Building dynamic tile cropper element (hailotilecropper_dynamic) ==="

if [ ! -d "${BUILD_DIR}" ]; then
    meson setup "${BUILD_DIR}" "${SCRIPT_DIR}"
else
    meson setup --reconfigure "${BUILD_DIR}" "${SCRIPT_DIR}"
fi

meson compile -C "${BUILD_DIR}"

echo ""
echo "Build complete. Library in: ${BUILD_DIR}/"
ls -la "${BUILD_DIR}"/lib*.so 2>/dev/null || true

if [ "${1:-}" != "--no-install" ]; then
    echo ""
    echo "Installing the GStreamer plugin (requires sudo) ..."
    sudo meson install -C "${BUILD_DIR}"
    echo "Install complete. Verify with: gst-inspect-1.0 hailotilecropper_dynamic"
else
    echo ""
    echo "Skipping install (--no-install). To install manually:"
    echo "  sudo meson install -C ${BUILD_DIR}"
fi
