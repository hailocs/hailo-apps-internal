#!/bin/bash
# Build the depth_anything_postprocess shared library.
#
# The library is built into postprocess/build.release/ and is NOT installed
# system-wide — depth_anything_pipeline.py loads it by absolute path from there
# (see POSTPROCESS_SO). This matches meson.build (install: false).
#
# Usage:
#   ./build.sh        # Build libdepth_anything_postprocess.so into build.release/
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUILD_DIR="${SCRIPT_DIR}/build.release"

echo "=== Building depth_anything postprocess library ==="

if [ ! -d "${BUILD_DIR}" ]; then
    meson setup "${BUILD_DIR}" "${SCRIPT_DIR}"
else
    meson setup --reconfigure "${BUILD_DIR}" "${SCRIPT_DIR}"
fi

meson compile -C "${BUILD_DIR}"

echo ""
echo "Build complete. Library in: ${BUILD_DIR}/"
ls -la "${BUILD_DIR}"/lib*.so 2>/dev/null || true
