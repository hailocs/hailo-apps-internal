#!/usr/bin/env bash
# Common helper functions for installation scripts
# 
# This script provides shared utility functions used across all installation scripts:
# - User and group detection when running with sudo
# - File ownership management
# - Logging functions (info, error, warning, debug)
# - Directory and permission management
# - YAML configuration loading

set -uo pipefail

# Terminal colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Logging functions
log_info() {
    echo -e "${GREEN}ℹ️  $*${NC}"
}

log_error() {
    echo -e "${RED}❌ $*${NC}" >&2
}

log_warning() {
    echo -e "${YELLOW}⚠️  $*${NC}"
}

log_debug() {
    if [[ "${VERBOSE:-false}" == "true" ]]; then
        echo -e "${BLUE}🔍 $*${NC}"
    fi
}

# Detect if running with sudo and get original user and group
detect_user_and_group() {
    if [[ ${EUID:-$(id -u)} -eq 0 ]]; then
        if [[ -z "${SUDO_USER:-}" ]]; then
            log_error "This script must not be run as root directly. Please run with sudo as a regular user:"
            echo "   sudo $0"
            exit 1
        fi
        ORIGINAL_USER="${SUDO_USER}"
        # Get the primary group of the original user
        ORIGINAL_GROUP=$(id -gn "${SUDO_USER}")
    else
        log_error "This script requires sudo privileges. Please run with sudo:"
        echo "   sudo $0 $*"
        exit 1
    fi

    log_info "Detected user: ${ORIGINAL_USER}"
    log_info "Detected primary group: ${ORIGINAL_GROUP}"

    # Check if group name is different from username
    if [[ "${ORIGINAL_USER}" == "${ORIGINAL_GROUP}" ]]; then
        log_info "User's primary group matches username"
    else
        log_info "User's primary group is different from username: ${ORIGINAL_GROUP}"
    fi

    # Export for use in other scripts
    export ORIGINAL_USER
    export ORIGINAL_GROUP
}

# Check if running with sudo (non-fatal)
require_sudo() {
    if [[ ${EUID:-$(id -u)} -ne 0 ]]; then
        log_error "This script requires sudo privileges. Please run with sudo:"
        echo "   sudo $0 $*"
        return 1
    fi
    return 0
}

# Execute command as original user
as_original_user() {
    if [[ ${EUID:-$(id -u)} -eq 0 && -n "${SUDO_USER:-}" ]]; then
        sudo -n -u "$SUDO_USER" -H -- "$@"
    else
        "$@"
    fi
}

# Function to fix ownership of files/directories to original user and group
fix_ownership() {
    local target="$1"
    if [[ -e "$target" ]]; then
        sudo chown -R "${ORIGINAL_USER}:${ORIGINAL_GROUP}" "$target" 2>/dev/null || true
    fi
}

# Clean up build artifacts
cleanup_build_artifacts() {
    local script_dir="${1:-.}"
    log_info "Cleaning up build artifacts..."
    
    # Try cleaning as regular user first, fallback to sudo if needed
    if ! as_original_user find "${script_dir}" -name "*.egg-info" -type d -exec rm -rf {} + 2>/dev/null; then
        log_warning "Regular user cleanup failed, fixing ownership..."
        fix_ownership "${script_dir}"
        as_original_user find "${script_dir}" -name "*.egg-info" -type d -exec rm -rf {} + 2>/dev/null || true
    fi

    if ! as_original_user rm -rf "${script_dir}/build" "${script_dir}/dist" 2>/dev/null; then
        log_warning "Regular user cleanup failed, fixing ownership..."
        fix_ownership "${script_dir}"
        as_original_user rm -rf "${script_dir}/build" "${script_dir}/dist" 2>/dev/null || true
    fi
    
    log_info "Build artifacts cleaned"
}

# Get script directory
get_script_dir() {
    local script_path="${BASH_SOURCE[0]}"
    if [[ -L "$script_path" ]]; then
        script_path=$(readlink -f "$script_path")
    fi
    echo "$(cd "$(dirname "$script_path")/.." && pwd)"
}

# Check if file/directory exists and is writable by original user
check_writable() {
    local target="$1"
    if [[ -e "$target" ]]; then
        if ! as_original_user test -w "$target" 2>/dev/null; then
            log_warning "Target requires sudo permissions, fixing ownership..."
            fix_ownership "$target"
        fi
        return 0
    fi
    return 1
}

# Ensure directory exists with correct permissions
ensure_directory() {
    local dir="$1"
    local owner="${ORIGINAL_USER}:${ORIGINAL_GROUP}"
    
    if [[ ! -d "$dir" ]]; then
        log_info "Creating directory: $dir"
        sudo mkdir -p "$dir"
        sudo chown -R "$owner" "$dir"
        sudo chmod -R 775 "$dir"
    else
        # Ensure correct ownership
        check_writable "$dir"
    fi
}

# Load YAML configuration file
# Usage: load_config [config_file_path]
# Sets variables: DEFAULT_VENV_NAME, DEFAULT_DOWNLOAD_GROUP, DEFAULT_RESOURCES_ROOT, 
#                 DEFAULT_ENV_FILE, REQUIRED_SYSTEM_PACKAGES (array), RESOURCE_DIRS (array)
load_config() {
    local config_file="${1:-}"
    local project_root="${2:-}"
    
    # Default config file path (in hailo_apps/config/)
    if [[ -z "$config_file" ]]; then
        if [[ -n "$project_root" ]]; then
            config_file="${project_root}/hailo_apps/config/install_config.yaml"
        else
            # Try to find project root
            local script_path="${BASH_SOURCE[0]}"
            if [[ -L "$script_path" ]]; then
                script_path=$(readlink -f "$script_path")
            fi
            project_root="$(cd "$(dirname "$script_path")/../.." && pwd)"
            config_file="${project_root}/hailo_apps/config/install_config.yaml"
        fi
    fi
    
    if [[ ! -f "$config_file" ]]; then
        log_error "Configuration file not found: $config_file"
        return 1
    fi
    
    log_debug "Loading configuration from: $config_file"
    
    # Use Python to parse YAML and export variables
    # This is more reliable than trying to parse YAML in bash
    eval "$(python3 << PYTHON_EOF
import yaml
import sys
import os

config_file = '$config_file'
if not config_file or not os.path.exists(config_file):
    sys.exit(1)

try:
    with open(config_file, 'r') as f:
        config = yaml.safe_load(f)
    
    # Export venv config
    venv_name = config.get('venv', {}).get('name', 'venv_hailo_apps')
    print(f'export DEFAULT_VENV_NAME="{venv_name}"')
    
    # Export resources config
    resources = config.get('resources', {})
    download_group = resources.get('download_group', 'default')
    resources_root = resources.get('root', '/usr/local/hailo/resources')
    env_file = resources.get('env_file', f'{resources_root}/.env')
    
    print(f'export DEFAULT_DOWNLOAD_GROUP="{download_group}"')
    print(f'export DEFAULT_RESOURCES_ROOT="{resources_root}"')
    print(f'export DEFAULT_ENV_FILE="{env_file}"')
    
    # Export system packages as array
    system_packages = config.get('system_packages', [])
    if system_packages:
        packages_str = ' '.join(f'"{pkg}"' for pkg in system_packages)
        print(f'export REQUIRED_SYSTEM_PACKAGES=({packages_str})')
    else:
        print('export REQUIRED_SYSTEM_PACKAGES=()')
    
    # Export resource directories as array
    resource_dirs = config.get('resource_dirs', [])
    if resource_dirs:
        dirs_str = ' '.join(f'"{d}"' for d in resource_dirs)
        print(f'export RESOURCE_DIRS=({dirs_str})')
    else:
        print('export RESOURCE_DIRS=()')
        
except Exception as e:
    print(f'# Error loading config: {e}', file=sys.stderr)
    sys.exit(1)
PYTHON_EOF
    )" || {
        log_error "Failed to load configuration from $config_file"
        log_info "Falling back to default values..."
        # Fallback to default values if YAML parsing fails
        export DEFAULT_VENV_NAME="venv_hailo_apps"
        export DEFAULT_DOWNLOAD_GROUP="default"
        export DEFAULT_RESOURCES_ROOT="/usr/local/hailo/resources"
        export DEFAULT_ENV_FILE="${DEFAULT_RESOURCES_ROOT}/.env"
        export REQUIRED_SYSTEM_PACKAGES=("meson" "portaudio19-dev" "python3-gi" "python3-gi-cairo")
        export RESOURCE_DIRS=("models/hailo8" "models/hailo8l" "models/hailo10h" "videos" "so" "photos" "json" "packages" "face_recon/train" "face_recon/samples")
        return 1
    }
    
    log_debug "Configuration loaded successfully"
    return 0
}

