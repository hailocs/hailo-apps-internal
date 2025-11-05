#!/usr/bin/env bash
# Setup resource directories for Hailo Apps Infrastructure
#
# This script creates and configures resource directories:
# - Creates /usr/local/hailo/resources/ directory structure
# - Creates local resources/ directory
# - Creates .env file with proper permissions
# - Sets correct ownership and permissions (775 for group access)
# - Ensures user can write to resource directories

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

# Source helper functions and load config
source "${SCRIPT_DIR}/install_helpers.sh"
load_config "" "${PROJECT_ROOT}"

# Default values
RESOURCES_ROOT="${DEFAULT_RESOURCES_ROOT}"
ENV_FILE="${DEFAULT_ENV_FILE}"

show_help() {
    cat << EOF
Usage: sudo $0 [OPTIONS]

Setup resource directories for Hailo Apps Infrastructure.

⚠️  This script MUST be run with sudo.

OPTIONS:
    --resources-root PATH         Resources root directory (default: ${DEFAULT_RESOURCES_ROOT})
    --env-file PATH                Environment file path (default: ${DEFAULT_ENV_FILE})
    -v, --verbose                  Show detailed output
    -h, --help                     Show this help message and exit

EXAMPLES:
    sudo $0                                    # Create resources with default paths
    sudo $0 --resources-root /custom/path      # Use custom resources root

EOF
}

# Parse arguments
VERBOSE=false
while [[ $# -gt 0 ]]; do
    case "$1" in
        --resources-root)
            RESOURCES_ROOT="$2"
            shift 2
            ;;
        --env-file)
            ENV_FILE="$2"
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

log_info "Creating Hailo resources directories..."

# Create the main resources root directory
ensure_directory "${RESOURCES_ROOT}"

# Create the directory structure
for dir in "${RESOURCE_DIRS[@]}"; do
    ensure_directory "${RESOURCES_ROOT}/${dir}"
done

log_info "Hailo resources directories created successfully"
log_info "Owner: ${ORIGINAL_USER}:${ORIGINAL_GROUP}"
log_info "Location: ${RESOURCES_ROOT}"

# Ensure local resources directory exists
if [[ ! -d "${PROJECT_ROOT}/resources" ]]; then
    log_info "Creating local resources directory..."
    as_original_user mkdir -p "${PROJECT_ROOT}/resources"
fi

# Remove existing .env file if it exists
if [[ -f "${ENV_FILE}" ]]; then
    log_info "Removing existing .env file at ${ENV_FILE}"
    if ! as_original_user rm -f "${ENV_FILE}" 2>/dev/null; then
        log_warning "Regular user removal failed, fixing ownership..."
        fix_ownership "${ENV_FILE}"
        as_original_user rm -f "${ENV_FILE}"
    fi
fi

# Create .env file with proper ownership and permissions
log_info "Creating .env file at ${ENV_FILE}"
as_original_user touch "${ENV_FILE}"
as_original_user chmod 644 "${ENV_FILE}"

log_info "Resources setup completed successfully!"

# Export for use in other scripts
export RESOURCES_ROOT
export ENV_FILE

exit 0

