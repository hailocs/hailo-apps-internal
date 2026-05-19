#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

APPS=(
    classification
    depth_estimation_mono
    depth_estimation_stereo
    instance_segmentation
    object_detection
    onnxrt_hailo_pipeline
    oriented_object_detection
    pose_estimation
    semantic_segmentation
    zero_shot_classification
)

FAILED=()

for APP in "${APPS[@]}"; do
    echo ""
    echo "=========================================="
    echo " Building: $APP"
    echo "=========================================="
    if bash "$SCRIPT_DIR/$APP/build.sh"; then
        echo "-I- $APP: OK"
    else
        echo "-E- $APP: FAILED"
        FAILED+=("$APP")
    fi
done

echo ""
echo "=========================================="
if [[ ${#FAILED[@]} -eq 0 ]]; then
    echo " All apps built successfully"
else
    echo " Failed: ${FAILED[*]}"
    exit 1
fi
echo "=========================================="
