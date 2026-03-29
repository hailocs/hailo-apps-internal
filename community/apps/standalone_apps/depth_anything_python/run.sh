#!/bin/bash
# Run the Depth Anything Python standalone app
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../../.." && pwd)"
export PYTHONPATH="$REPO_ROOT:$PYTHONPATH"
python "$SCRIPT_DIR/depth_anything_standalone.py" "$@"
