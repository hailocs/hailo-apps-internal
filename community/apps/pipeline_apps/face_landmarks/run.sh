#!/bin/bash
# Face Landmarks Detection — 468-point face mesh on Hailo
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../../.." && pwd)"

cd "$REPO_ROOT" || exit 1
source setup_env.sh 2>/dev/null

python -m community.apps.pipeline_apps.face_landmarks.face_landmarks "$@"
