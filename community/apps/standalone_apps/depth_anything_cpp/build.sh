#!/bin/bash
# Build script for the Depth Anything C++ standalone app.
# Compiles for the host architecture by default.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../../.." && pwd)"
HAILO_APPS_CONFIG="$REPO_ROOT/hailo-apps/hailo_apps/config"

echo "-I- Building depth_anything for $(uname -m)"
mkdir -p build/$(uname -m)
cmake -H. -Bbuild/$(uname -m)
cmake --build build/$(uname -m)

# Create a symlink to the hailo-apps config directory so the executable
# can find get_hef.sh / get_input.sh (toolbox.cpp walks up from the
# executable location looking for a 'config/' directory).
if [[ -d "$HAILO_APPS_CONFIG" ]]; then
    ln -sfn "$HAILO_APPS_CONFIG" "$SCRIPT_DIR/build/$(uname -m)/config"
    echo "-I- Linked config -> $HAILO_APPS_CONFIG"
else
    echo "-W- Could not find hailo-apps config at $HAILO_APPS_CONFIG"
fi

if [[ -f "hailort.log" ]]; then
    rm hailort.log
fi

echo "-I- Build complete: build/$(uname -m)/depth_anything"
