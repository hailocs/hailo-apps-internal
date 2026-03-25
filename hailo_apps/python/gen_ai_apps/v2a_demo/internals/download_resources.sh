#!/bin/bash
# Download demo resources from freenas.
#
# Usage:
#   ./internals/download_resources.sh
#
# Source: freenas:/mnt/v02/sdk/demos/genai/v2a_resources
# Target: resources/

set -euo pipefail

FREENAS_PATH="freenas:/mnt/v02/sdk/demos/genai/v2a_resources"
LOCAL_PATH="$(cd "$(dirname "$0")/.." && pwd)/resources"

echo "Downloading resources from freenas..."
echo "  Source: $FREENAS_PATH"
echo "  Target: $LOCAL_PATH"

mkdir -p "$LOCAL_PATH"

rsync -avh --progress "$FREENAS_PATH/" "$LOCAL_PATH/"

echo ""
echo "Done. Resources downloaded to $LOCAL_PATH"
