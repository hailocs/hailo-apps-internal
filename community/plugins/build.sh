#!/bin/bash
# Build (and install) all community GStreamer plugins.
#
# Each plugin is a self-contained meson project under this directory; this
# wrapper just runs each one's build.sh in turn.
#
# Usage:
#   ./build.sh              # Build + install every community plugin (needs sudo)
#   ./build.sh --no-install # Build only (libraries left in each plugin's build/)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PASSTHRU="${1:-}"

PLUGINS=(
    "overlay_community"
    "hailotilecropper_dynamic"
)

for plugin in "${PLUGINS[@]}"; do
    echo ""
    echo "########################################################"
    echo "# ${plugin}"
    echo "########################################################"
    bash "${SCRIPT_DIR}/${plugin}/build.sh" "${PASSTHRU}"
done

echo ""
echo "All community plugins processed."
