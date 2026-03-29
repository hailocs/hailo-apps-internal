#!/bin/bash
# Run the Line Crossing Counter pipeline app
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../../.." && pwd)"
export PYTHONPATH="$REPO_ROOT:$PYTHONPATH"
python "$SCRIPT_DIR/line_crossing_counter.py" "$@"
