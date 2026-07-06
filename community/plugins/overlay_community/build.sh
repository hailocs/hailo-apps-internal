#!/bin/bash
# Build and install the community overlay GStreamer element
# (hailooverlay_community) into the system GStreamer plugin directory.
#
# Prerequisite: libyaml-cpp-dev  (sudo apt install libyaml-cpp-dev)
#
# Usage:
#   ./build.sh              # Build + install (needs sudo for the gst plugin dir)
#   ./build.sh --no-install # Build only (library left in build/)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUILD_DIR="${SCRIPT_DIR}/build"

echo "=== Building community overlay element (hailooverlay_community) ==="

# yaml-cpp is a hard dependency of this element. Hint early instead of failing
# deep inside meson with a less obvious message.
if ! pkg-config --exists yaml-cpp; then
    echo "ERROR: yaml-cpp not found. Install it first:" >&2
    echo "  sudo apt install libyaml-cpp-dev" >&2
    exit 1
fi

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
    echo "Install complete. Verify with: gst-inspect-1.0 hailooverlay_community"
else
    echo ""
    echo "Skipping install (--no-install). To install manually:"
    echo "  sudo meson install -C ${BUILD_DIR}"
fi
