#!/bin/bash

# Vampire Mirror — run wrapper
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../../../.." && pwd)"

export PYTHONPATH="$REPO_ROOT:$PYTHONPATH"

# Build + install the app's hailovampire_overlay GStreamer element if it isn't
# discoverable yet (it lives with this app, not in the shared postprocess).
if ! gst-inspect-1.0 hailovampire_overlay >/dev/null 2>&1; then
    echo "hailovampire_overlay element not found — building it..."
    bash "$SCRIPT_DIR/postprocess/build.sh"
fi

python3 -m community.apps.pipeline_apps.vampire_mirror.vampire_mirror "$@"
