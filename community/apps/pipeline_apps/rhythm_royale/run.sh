#!/bin/bash
# Rhythm Royale — run wrapper
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../../.." && pwd)"

export PYTHONPATH="$REPO_ROOT:$PYTHONPATH"

python3 -m community.apps.pipeline_apps.rhythm_royale.rhythm_royale "$@"
