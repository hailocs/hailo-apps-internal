#!/bin/bash
# Build and run the Depth Anything C++ standalone app
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Build if needed
if [ ! -f build/depth_anything ]; then
    echo "Building..."
    bash build.sh
fi

./build/depth_anything "$@"
