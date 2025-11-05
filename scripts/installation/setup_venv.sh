#!/usr/bin/env bash
# Setup virtual environment for Hailo Apps Infrastructure
#
# This script creates and manages the Python virtual environment:
# - Removes existing venv if requested
# - Creates new virtual environment with correct options
# - Handles architecture-specific settings (system site-packages)
# - Cleans up build artifacts
# - Validates venv creation

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

# Source helper functions and load config
source "${SCRIPT_DIR}/install_helpers.sh"
load_config "" "${PROJECT_ROOT}"

# Default values
VENV_NAME="${DEFAULT_VENV_NAME}"
NO_SYSTEM_PYTHON=false
REMOVE_EXISTING=false

show_help() {
    cat << EOF
Usage: sudo $0 [OPTIONS]

Setup virtual environment for Hailo Apps Infrastructure.

⚠️  This script MUST be run with sudo.

OPTIONS:
    -n, --venv-name NAME          Set virtual environment name (default: ${DEFAULT_VENV_NAME})
    --no-system-python             Don't use system site-packages
    --remove-existing              Remove existing virtualenv if it exists
    -v, --verbose                  Show detailed output
    -h, --help                     Show this help message and exit

EXAMPLES:
    sudo $0                                    # Create venv with default name
    sudo $0 -n my_venv                        # Create venv with custom name
    sudo $0 --no-system-python                # Create venv without system packages
    sudo $0 --remove-existing                 # Remove existing venv first

EOF
}

# Parse arguments
VERBOSE=false
while [[ $# -gt 0 ]]; do
    case "$1" in
        -n|--venv-name)
            VENV_NAME="$2"
            shift 2
            ;;
        --no-system-python)
            NO_SYSTEM_PYTHON=true
            shift
            ;;
        --remove-existing)
            REMOVE_EXISTING=true
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

VENV_PATH="${PROJECT_ROOT}/${VENV_NAME}"

# Detect architecture
ARCH=$(uname -m)
IS_X86=false
if [[ "$ARCH" == "x86_64" || "$ARCH" == "i386" || "$ARCH" == "i686" ]]; then
    IS_X86=true
fi

# Determine whether to use system site-packages
USE_SYSTEM_SITE_PACKAGES=true
if [[ "$NO_SYSTEM_PYTHON" == true ]]; then
    USE_SYSTEM_SITE_PACKAGES=false
    log_info "Using --no-system-python flag: virtualenv will not use system site-packages"
else
    log_info "Using system site-packages for virtualenv"
fi

# Remove existing venv if requested or if it exists and REMOVE_EXISTING is true
if [[ -d "${VENV_PATH}" ]]; then
    if [[ "$REMOVE_EXISTING" == true ]]; then
        log_info "Removing existing virtualenv at ${VENV_PATH}"
        # Try removing as regular user first, fallback to sudo if needed
        if ! as_original_user rm -rf "${VENV_PATH}" 2>/dev/null; then
            log_warning "Regular user removal failed, fixing ownership..."
            fix_ownership "${VENV_PATH}"
            as_original_user rm -rf "${VENV_PATH}"
        fi
    else
        log_warning "Virtual environment already exists at ${VENV_PATH}"
        log_info "Use --remove-existing to recreate it"
        exit 0
    fi
fi

# Clean up build artifacts
cleanup_build_artifacts "${PROJECT_ROOT}"

# Create virtual environment with or without system site-packages
if [[ "$USE_SYSTEM_SITE_PACKAGES" == true ]]; then
    log_info "Creating virtualenv '${VENV_NAME}' (with system site-packages)..."
    as_original_user python3 -m venv --system-site-packages "${VENV_PATH}"
else
    log_info "Creating virtualenv '${VENV_NAME}' (without system site-packages)..."
    as_original_user python3 -m venv "${VENV_PATH}"
fi

if [[ ! -f "${VENV_PATH}/bin/activate" ]]; then
    log_error "Could not find activate at ${VENV_PATH}/bin/activate"
    exit 1
fi

log_info "Virtual environment created successfully at ${VENV_PATH}"

# Export for use in other scripts
export VENV_NAME
export VENV_PATH

exit 0

