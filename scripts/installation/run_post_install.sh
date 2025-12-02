#!/usr/bin/env bash
# Run post-installation tasks for Hailo Apps Infrastructure
#
# This script runs post-installation tasks:
# - Fixes resources directory permissions
# - Runs hailo-post-install which:
#   - Downloads resources and models (optional)
#   - Compiles C++ postprocess modules
#   - Creates symlinks from resources to /usr/local/hailo/resources
# - Handles post-install errors with helpful messages

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

show_help() {
    cat << EOF
Usage: sudo $0 [OPTIONS]

Run post-installation tasks for Hailo Apps Infrastructure.

⚠️  This script MUST be run with sudo.

OPTIONS:
    -n, --venv-name NAME          Virtual environment name (default: ${DEFAULT_VENV_NAME})
    --group GROUP                  Resource group to download (default: ${DEFAULT_DOWNLOAD_GROUP})
    --all                          Download all available models/resources
    --skip-download                Skip resource download
    --skip-compile                 Skip C++ compilation
    -v, --verbose                  Show detailed output
    -h, --help                     Show this help message and exit

EXAMPLES:
    sudo $0                                    # Run post-install with default settings
    sudo $0 --all                              # Download all resources
    sudo $0 --skip-compile                     # Skip C++ compilation
    sudo $0 --group detection                  # Download specific resource group

EOF
}

# Parse arguments
VERBOSE=false
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
        -v|--verbose)
            VERBOSE=true
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

# Detect user and group
detect_user_and_group

# Check if venv exists
if [[ ! -f "${VENV_PATH}/bin/activate" ]]; then
    log_error "Virtual environment not found at ${VENV_PATH}"
    log_info "Please run setup_venv.sh first"
    exit 1
fi

log_info "Running post-install script..."

# Fix resources directory permissions if needed
log_info "Checking resources directory permissions..."
if [[ -d "${PROJECT_ROOT}/resources" ]]; then
    # Check if it's a symlink and test the target directory
    if [[ -L "${PROJECT_ROOT}/resources" ]]; then
        target_dir=$(readlink "${PROJECT_ROOT}/resources")
        log_debug "Resources is a symlink pointing to: $target_dir"
        # Test if user can write to the target directory
        if ! as_original_user test -w "$target_dir" 2>/dev/null; then
            log_warning "Target directory requires sudo permissions, fixing ownership..."
            fix_ownership "$target_dir"
        fi
        # Also fix the symlink itself
        if ! as_original_user test -w "${PROJECT_ROOT}/resources" 2>/dev/null; then
            log_warning "Symlink requires sudo permissions, fixing ownership..."
            fix_ownership "${PROJECT_ROOT}/resources"
        fi
    else
        # It's a regular directory
        if ! as_original_user test -w "${PROJECT_ROOT}/resources" 2>/dev/null; then
            log_warning "Resources directory requires sudo permissions, fixing ownership..."
            fix_ownership "${PROJECT_ROOT}/resources"
        fi
    fi
fi

# Run post-install (this handles both download and compile)
if [[ "$SKIP_DOWNLOAD" == true && "$SKIP_COMPILE" == true ]]; then
    log_info "Skipping post-install (both download and compile skipped)"
else
    # Build hailo-post-install command
    POST_INSTALL_CMD="hailo-post-install"
    if [[ "$SKIP_DOWNLOAD" != true ]]; then
        if [[ "$DOWNLOAD_GROUP" == "all" ]]; then
            POST_INSTALL_CMD="${POST_INSTALL_CMD} --all"
        else
            POST_INSTALL_CMD="${POST_INSTALL_CMD} --group '${DOWNLOAD_GROUP}'"
        fi
    fi
    
    if ! as_original_user bash -c "source '${VENV_PATH}/bin/activate' && cd '${PROJECT_ROOT}' && ${POST_INSTALL_CMD}"; then
        log_error "Post-installation failed!"
        echo ""
        echo "This usually means:"
        echo "  - C++ compilation failed (check for permission issues in build directories)"
        echo "  - Resource download failed (check network connection)"
        echo "  - Environment setup failed"
        echo ""
        echo "Please check the error messages above and try again."
        echo "If you see permission errors, you may need to clean up old build directories with sudo."
        exit 1
    fi
fi

log_info "Post-installation completed successfully!"
exit 0

