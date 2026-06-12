#!/bin/bash

# Vampire Mirror — run wrapper
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../../../.." && pwd)"

export PYTHONPATH="$REPO_ROOT:$PYTHONPATH"

python3 -m hailo_apps.python.pipeline_apps.vampire_mirror.vampire_mirror "$@"
