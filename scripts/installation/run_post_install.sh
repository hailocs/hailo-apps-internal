#!/usr/bin/env bash
#===============================================================================
# Run Post-Installation Tasks for Hailo Apps Infrastructure
#===============================================================================
#
# This script runs post-installation tasks as the original user (not root).
# It delegates to the Python-based hailo-post-install command.
#
# Tasks performed by hailo-post-install:
#   1. Setup environment configuration (.env file)
#   2. Create symlink from resources to /usr/local/hailo/resources
#   3. Download resources (models, videos, images, JSON configs)
#   4. Compile C++ postprocess modules
#
#===============================================================================

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

# Source helper functions and load config
source "${SCRIPT_DIR}/install_helpers.sh"
load_config "" "${PROJECT_ROOT}"

# Default values
VENV_NAME="${DEFAULT_VENV_NAME}"
VENV_PATH="${PROJECT_ROOT}/${VENV_NAME}"
DOWNLOAD_GROUP="${DEFAULT_DOWNLOAD_GROUP}"
SKIP_DOWNLOAD=false
SKIP_COMPILE=false
VERBOSE=false

show_help() {
    cat << EOF
Usage: sudo $0 [OPTIONS]

Run post-installation tasks for Hailo Apps Infrastructure.

This script runs hailo-post-install as the original user (not root) to:
  - Setup environment configuration
  - Create resources symlink
  - Download resources (optional)
  - Compile C++ postprocess modules (optional)

⚠️  This script MUST be run with sudo (for ownership fixes).

OPTIONS:
    -n, --venv-name NAME          Virtual environment name (default: ${DEFAULT_VENV_NAME})
    --group GROUP                  Resource group to download (default: ${DEFAULT_DOWNLOAD_GROUP})
    --all                          Download all available models/resources
    --skip-download                Skip resource download
    --skip-compile                 Skip C++ compilation
    -h, --help                     Show this help message and exit

EXAMPLES:
    sudo $0                        # Run post-install with default settings
    sudo $0 --all                  # Download all resources
    sudo $0 --skip-compile         # Skip C++ compilation
    sudo $0 --group detection      # Download specific resource group

EOF
}

# Parse arguments
while [[ $# -gt 0 ]]; do
    case "$1" in
        -n|--venv-name)
            VENV_NAME="$2"
            VENV_PATH="${PROJECT_ROOT}/${VENV_NAME}"
            shift 2
            ;;
        --group)
            DOWNLOAD_GROUP="$2"
            shift 2
            ;;
        --all)
            DOWNLOAD_GROUP="all"
            shift
            ;;
        --skip-download)
            SKIP_DOWNLOAD=true
            shift
            ;;
        --skip-compile)
            SKIP_COMPILE=true
            shift
            ;;
        -h|--help)
            show_help
            exit 0
            ;;
        *)
            log_error "Unknown option: $1"
            show_help
            exit 1
            ;;
    esac
done

# Detect user and group (requires sudo)
detect_user_and_group

# Check if venv exists
if [[ ! -f "${VENV_PATH}/bin/activate" ]]; then
    log_error "Virtual environment not found at ${VENV_PATH}"
    log_info "Please run setup_venv.sh first"
    exit 1
fi

log_info "Running post-install as user: ${ORIGINAL_USER}"
log_debug "Virtual environment: ${VENV_PATH}"
log_debug "Download group: ${DOWNLOAD_GROUP}"

# Fix project directory ownership before running
log_info "Fixing project directory ownership..."
fix_ownership "${PROJECT_ROOT}"

# Fix resources root ownership
if [[ -d "${DEFAULT_RESOURCES_ROOT}" ]]; then
    log_info "Fixing resources directory ownership..."
    fix_ownership "${DEFAULT_RESOURCES_ROOT}"
fi

# Build the hailo-post-install command
POST_INSTALL_CMD="hailo-post-install"

# Add download options
if [[ "$SKIP_DOWNLOAD" == true ]]; then
    POST_INSTALL_CMD="${POST_INSTALL_CMD} --skip-download"
elif [[ "$DOWNLOAD_GROUP" == "all" ]]; then
    POST_INSTALL_CMD="${POST_INSTALL_CMD} --all"
elif [[ -n "$DOWNLOAD_GROUP" && "$DOWNLOAD_GROUP" != "default" ]]; then
    POST_INSTALL_CMD="${POST_INSTALL_CMD} --group '${DOWNLOAD_GROUP}'"
fi

# Add compile options
if [[ "$SKIP_COMPILE" == true ]]; then
    POST_INSTALL_CMD="${POST_INSTALL_CMD} --skip-compile"
fi

log_debug "Running command: ${POST_INSTALL_CMD}"

# Run hailo-post-install as the original user
log_info "Executing hailo-post-install..."
echo ""

if ! as_original_user bash -c "source '${VENV_PATH}/bin/activate' && cd '${PROJECT_ROOT}' && ${POST_INSTALL_CMD}"; then
    log_error "Post-installation failed!"
    echo ""
    echo "Troubleshooting tips:"
    echo "  1. Check if the virtual environment is properly set up:"
    echo "     source ${VENV_PATH}/bin/activate && pip list | grep hailo"
    echo ""
    echo "  2. If you see permission errors, try fixing ownership:"
    echo "     sudo chown -R ${ORIGINAL_USER}:${ORIGINAL_GROUP} ${PROJECT_ROOT}"
    echo ""
    echo "  3. If C++ compilation fails, check if meson/ninja are installed:"
    echo "     which meson ninja"
    echo ""
    echo "  4. If resource download fails, check your network connection"
    echo ""
    exit 1
fi

echo ""
log_info "Post-installation completed successfully!"

# Final ownership fix
log_info "Final ownership fix..."
fix_ownership "${PROJECT_ROOT}"
if [[ -d "${DEFAULT_RESOURCES_ROOT}" ]]; then
    fix_ownership "${DEFAULT_RESOURCES_ROOT}"
fi

exit 0
