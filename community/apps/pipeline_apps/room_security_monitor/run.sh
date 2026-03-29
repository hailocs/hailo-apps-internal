#!/bin/bash
# Run the Room Security Monitor pipeline app
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../../.." && pwd)"
export PYTHONPATH="$REPO_ROOT:$PYTHONPATH"
python "$SCRIPT_DIR/room_security_monitor.py" "$@"
