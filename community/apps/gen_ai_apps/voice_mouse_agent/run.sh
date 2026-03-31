#!/bin/bash

# Voice Mouse Controller - Launch Script
# Runs the voice-controlled mouse agent on Hailo-10H

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../../.." && pwd)"

# Set PYTHONPATH to repo root
export PYTHONPATH="$REPO_ROOT:$PYTHONPATH"

# Activate virtual environment if available
if [ -f "$REPO_ROOT/setup_env.sh" ]; then
    source "$REPO_ROOT/setup_env.sh"
fi

python3 -m hailo_apps.python.gen_ai_apps.voice_mouse_agent.voice_mouse_agent "$@"
