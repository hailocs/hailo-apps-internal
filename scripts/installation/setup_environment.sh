#!/usr/bin/env bash
# Setup environment variables for Hailo Apps Infrastructure
#
# This script configures environment variables:
# - Runs hailo-set-env command to auto-detect and set variables
# - Validates environment setup
# - Handles configuration errors with helpful messages
# - Ensures environment is properly configured for Hailo Apps

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

# Source helper functions and load config
source "${SCRIPT_DIR}/install_helpers.sh"
load_config "" "${PROJECT_ROOT}"

# Default values
VENV_NAME="${DEFAULT_VENV_NAME}"
VENV_PATH="${PROJECT_ROOT}/${VENV_NAME}"

show_help() {
    cat << EOF
Usage: sudo $0 [OPTIONS]

Setup environment variables for Hailo Apps Infrastructure.

⚠️  This script MUST be run with sudo.

OPTIONS:
    -n, --venv-name NAME          Virtual environment name (default: ${DEFAULT_VENV_NAME})
    -v, --verbose                  Show detailed output
    -h, --help                     Show this help message and exit

EXAMPLES:
    sudo $0                                    # Setup environment with default venv
    sudo $0 -n my_venv                        # Setup environment with custom venv

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

log_info "Setting environment variables..."

if ! as_original_user bash -c "source '${VENV_PATH}/bin/activate' && hailo-set-env"; then
    log_error "Environment variable setup failed!"
    echo ""
    echo "This usually means:"
    echo "  - Configuration file not found"
    echo "  - Auto-detection failed"
    echo ""
    echo "Please check the error messages above and try again."
    exit 1
fi

log_info "Environment variables set successfully!"
exit 0

