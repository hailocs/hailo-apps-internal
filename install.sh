#!/usr/bin/env bash
#===============================================================================
# Hailo Apps Infrastructure - Installation Orchestrator
#===============================================================================
#
# This script orchestrates the complete installation of Hailo Apps Infrastructure.
# It provides a clean, hierarchical installation process with comprehensive
# logging, dry-run support, and proper error handling.
#
# INSTALLATION PHASES:
#   Phase 1: Prerequisites Check
#   Phase 2: Virtual Environment Setup
#   Phase 3: Python Package Installation
#   Phase 4: Resource Directory Setup
#   Phase 5: Environment Configuration
#   Phase 6: Post-Installation (runs as user)
#   Phase 7: Verification
#
# USAGE:
#   sudo ./install.sh [OPTIONS]
#
#===============================================================================

set -uo pipefail

#===============================================================================
# CONSTANTS & DEFAULTS
#===============================================================================

readonly SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly SCRIPT_NAME="$(basename "${BASH_SOURCE[0]}")"
readonly LOG_DIR="${SCRIPT_DIR}/logs"
readonly TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
readonly LOG_FILE="${LOG_DIR}/install_${TIMESTAMP}.log"

# Terminal colors
readonly RED='\033[0;31m'
readonly GREEN='\033[0;32m'
readonly YELLOW='\033[1;33m'
readonly BLUE='\033[0;34m'
readonly CYAN='\033[0;36m'
readonly BOLD='\033[1m'
readonly NC='\033[0m'

# Installation state tracking
declare -A PHASE_STATUS
PHASES=(
    "prerequisites"
    "venv_setup"
    "python_packages"
    "resources_setup"
    "post_install"
    "verification"
)

#===============================================================================
# CONFIGURATION - Load from config.yaml or use defaults
#===============================================================================

# Default values (will be overridden by config)
VENV_NAME="venv_hailo_apps"
DOWNLOAD_GROUP="default"
RESOURCES_ROOT="/usr/local/hailo/resources"

# Command line options
DRY_RUN=false
VERBOSE=false
NO_INSTALL=false
NO_SYSTEM_PYTHON=false
SKIP_VERIFICATION=false
PYHAILORT_PATH=""
PYTAPPAS_PATH=""
SINGLE_PHASE=""

#===============================================================================
# LOGGING FUNCTIONS
#===============================================================================

# Initialize logging
init_logging() {
    mkdir -p "${LOG_DIR}"
    exec > >(tee -a "${LOG_FILE}") 2>&1
    log_info "Installation log: ${LOG_FILE}"
}

# Log with timestamp to both console and file
log() {
    local level="$1"
    shift
    local message="$*"
    local timestamp
    timestamp="$(date '+%Y-%m-%d %H:%M:%S')"
    echo "[${timestamp}] [${level}] ${message}"
}

log_info() {
    echo -e "${GREEN}ℹ️  $*${NC}"
    log "INFO" "$*" >> "${LOG_FILE}" 2>/dev/null || true
}

log_success() {
    echo -e "${GREEN}✅ $*${NC}"
    log "SUCCESS" "$*" >> "${LOG_FILE}" 2>/dev/null || true
}

log_warning() {
    echo -e "${YELLOW}⚠️  $*${NC}"
    log "WARNING" "$*" >> "${LOG_FILE}" 2>/dev/null || true
}

log_error() {
    echo -e "${RED}❌ $*${NC}" >&2
    log "ERROR" "$*" >> "${LOG_FILE}" 2>/dev/null || true
}

log_debug() {
    if [[ "${VERBOSE}" == true ]]; then
        echo -e "${BLUE}🔍 $*${NC}"
    fi
    log "DEBUG" "$*" >> "${LOG_FILE}" 2>/dev/null || true
}

log_phase() {
    local phase_num="$1"
    local phase_name="$2"
    echo ""
    echo -e "${CYAN}${BOLD}════════════════════════════════════════════════════════════════${NC}"
    echo -e "${CYAN}${BOLD}  Phase ${phase_num}: ${phase_name}${NC}"
    echo -e "${CYAN}${BOLD}════════════════════════════════════════════════════════════════${NC}"
    echo ""
    log "PHASE" "Phase ${phase_num}: ${phase_name}" >> "${LOG_FILE}" 2>/dev/null || true
}

log_dry_run() {
    echo -e "${YELLOW}[DRY-RUN]${NC} Would execute: $*"
}

#===============================================================================
# UTILITY FUNCTIONS
#===============================================================================

# Load configuration from config.yaml
load_config() {
    local config_file="${SCRIPT_DIR}/hailo_apps/config/config.yaml"
    
    if [[ ! -f "$config_file" ]]; then
        log_warning "Config file not found: $config_file"
        log_info "Using default values..."
        return 0
    fi
    
    log_debug "Loading configuration from: $config_file"
    
    # Parse YAML with Python
    eval "$(python3 << PYTHON_EOF
import yaml
import sys

try:
    with open('$config_file', 'r') as f:
        config = yaml.safe_load(f)
    
    venv_name = config.get('venv', {}).get('name', 'venv_hailo_apps')
    print(f'VENV_NAME="{venv_name}"')
    
    resources = config.get('resources', {})
    download_group = resources.get('download_group', 'default')
    resources_root = resources.get('root', '/usr/local/hailo/resources')
    
    print(f'DOWNLOAD_GROUP="{download_group}"')
    print(f'RESOURCES_ROOT="{resources_root}"')
    
except Exception as e:
    print(f'# Error loading config: {e}', file=sys.stderr)
    sys.exit(1)
PYTHON_EOF
    )" || {
        log_warning "Failed to load config, using defaults"
        return 0
    }
}

# Detect original user when running with sudo
detect_user_and_group() {
    if [[ ${EUID:-$(id -u)} -eq 0 ]]; then
        if [[ -z "${SUDO_USER:-}" ]]; then
            log_error "This script must be run with sudo, not as root directly"
            echo "Usage: sudo $0"
            exit 1
        fi
        ORIGINAL_USER="${SUDO_USER}"
        ORIGINAL_GROUP="$(id -gn "${SUDO_USER}")"
    else
        log_error "This script requires sudo privileges"
        echo "Usage: sudo $0"
        exit 1
    fi
    
    log_info "Running as user: ${ORIGINAL_USER} (group: ${ORIGINAL_GROUP})"
    export ORIGINAL_USER ORIGINAL_GROUP
}

# Execute command as the original user (not root)
as_user() {
    if [[ ${EUID:-$(id -u)} -eq 0 && -n "${SUDO_USER:-}" ]]; then
        sudo -n -u "$SUDO_USER" -H -- "$@"
    else
        "$@"
    fi
}

# Fix ownership of a path to the original user
fix_ownership() {
    local target="$1"
    if [[ -e "$target" ]]; then
        chown -R "${ORIGINAL_USER}:${ORIGINAL_GROUP}" "$target" 2>/dev/null || true
    fi
}

# Show what a command would do in dry-run mode, or execute it
run_or_dry() {
    if [[ "${DRY_RUN}" == true ]]; then
        log_dry_run "$*"
        return 0
    else
        log_debug "Executing: $*"
        "$@"
    fi
}

# Show help
show_help() {
    cat << EOF
${BOLD}Hailo Apps Infrastructure Installer${NC}

${BOLD}USAGE:${NC}
    sudo $SCRIPT_NAME [OPTIONS]

${BOLD}OPTIONS:${NC}
    -n, --venv-name NAME        Virtual environment name (default: ${VENV_NAME})
    -ph, --pyhailort PATH       Path to custom PyHailoRT wheel file
    -pt, --pytappas PATH        Path to custom PyTappas wheel file
    --all                       Download all available models/resources
    -x, --no-install            Skip Python package installation
    --no-system-python          Don't use system site-packages in venv
    --skip-verification         Skip final verification phase
    --phase PHASE               Run only a specific phase (see PHASES below)
    --dry-run                   Show what would be done without executing
    -v, --verbose               Enable verbose/debug output
    -h, --help                  Show this help message

${BOLD}PHASES:${NC}
    prerequisites      Check system prerequisites (driver, HailoRT, TAPPAS)
    venv_setup         Create/setup virtual environment
    python_packages    Install Python packages
    resources_setup    Create resource directories
    post_install       Setup environment, download resources, compile postprocess
    verification       Verify the installation

${BOLD}EXAMPLES:${NC}
    sudo $SCRIPT_NAME                     # Full installation
    sudo $SCRIPT_NAME --dry-run           # Preview what would be done
    sudo $SCRIPT_NAME --dry-run -v        # Detailed dry-run preview
    sudo $SCRIPT_NAME --phase prerequisites   # Run only prerequisites check
    sudo $SCRIPT_NAME --all               # Install with all models
    sudo $SCRIPT_NAME -x                  # Skip Python package installation

${BOLD}LOG FILES:${NC}
    Installation logs are saved to: ${LOG_DIR}/

EOF
}

#===============================================================================
# INSTALLATION PHASES
#===============================================================================

# Phase 1: Check Prerequisites
phase_prerequisites() {
    log_phase "1" "Prerequisites Check"
    
    local script="${SCRIPT_DIR}/scripts/installation/check_prerequisites.sh"
    
    if [[ ! -f "$script" ]]; then
        log_error "Prerequisites script not found: $script"
        return 1
    fi
    
    local args=()
    [[ "${VERBOSE}" == true ]] && args+=("-v")
    
    if [[ "${DRY_RUN}" == true ]]; then
        log_dry_run "$script ${args[*]}"
        log_info "Would check: Hailo driver, HailoRT, TAPPAS installations"
        return 0
    fi
    
    log_info "Checking system prerequisites..."
    
    local output
    output=$("$script" "${args[@]}" 2>&1)
    local exit_code=$?
    
    if [[ $exit_code -ne 0 ]]; then
        log_error "Prerequisites check failed"
        echo "$output"
        return 1
    fi
    
    # Parse SUMMARY line for version info
    local summary_line
    summary_line=$(echo "$output" | sed -n 's/^SUMMARY: //p')
    
    if [[ -n "$summary_line" ]]; then
        IFS=' ' read -r -a pairs <<< "$summary_line"
        
        # Extract versions (format: key=value)
        for pair in "${pairs[@]}"; do
            local key="${pair%%=*}"
            local value="${pair#*=}"
            case "$key" in
                hailo_arch) export DETECTED_HAILO_ARCH="$value" ;;
                hailort) export HAILORT_VERSION="$value" ;;
                pyhailort) export PYHAILORT_VERSION="$value" ;;
                tappas-core) export TAPPAS_CORE_VERSION="$value" ;;
                tappas-python) export PYTAPPAS_VERSION="$value" ;;
            esac
        done
        
        log_info "Detected versions:"
        log_info "  Hailo Architecture: ${DETECTED_HAILO_ARCH:-unknown}"
        log_info "  HailoRT: ${HAILORT_VERSION:-unknown}"
        log_info "  TAPPAS Core: ${TAPPAS_CORE_VERSION:-unknown}"
    fi
    
    # Determine if Python bindings need installation
    export INSTALL_HAILORT=false
    export INSTALL_TAPPAS_CORE=false
    
    if [[ "${PYHAILORT_VERSION:-}" == "-1" && "${NO_INSTALL}" != true ]]; then
        export INSTALL_HAILORT=true
        log_info "PyHailoRT will be installed"
    fi
    
    if [[ "${PYTAPPAS_VERSION:-}" == "-1" && "${NO_INSTALL}" != true ]]; then
        export INSTALL_TAPPAS_CORE=true
        log_info "PyTappas will be installed"
    fi
    
    log_success "Prerequisites check passed"
    return 0
}

# Phase 2: Setup Virtual Environment
phase_venv_setup() {
    log_phase "2" "Virtual Environment Setup"
    
    local script="${SCRIPT_DIR}/scripts/installation/setup_venv.sh"
    local venv_path="${SCRIPT_DIR}/${VENV_NAME}"
    
    if [[ ! -f "$script" ]]; then
        log_error "Venv setup script not found: $script"
        return 1
    fi
    
    local args=("-n" "$VENV_NAME" "--remove-existing")
    [[ "${NO_SYSTEM_PYTHON}" == true ]] && args+=("--no-system-python")
    [[ "${VERBOSE}" == true ]] && args+=("-v")
    
    if [[ "${DRY_RUN}" == true ]]; then
        log_dry_run "$script ${args[*]}"
        log_info "Would create virtual environment at: $venv_path"
        [[ "${NO_SYSTEM_PYTHON}" == true ]] && log_info "  - Without system site-packages"
        [[ "${NO_SYSTEM_PYTHON}" != true ]] && log_info "  - With system site-packages"
        return 0
    fi
    
    log_info "Creating virtual environment: $venv_path"
    
    if ! "$script" "${args[@]}"; then
        log_error "Failed to create virtual environment"
        return 1
    fi
    
    log_success "Virtual environment created"
    return 0
}

# Phase 3: Install Python Packages
phase_python_packages() {
    log_phase "3" "Python Package Installation"
    
    local script="${SCRIPT_DIR}/scripts/installation/install_python_packages.sh"
    
    if [[ ! -f "$script" ]]; then
        log_error "Python packages script not found: $script"
        return 1
    fi
    
    local args=("-n" "$VENV_NAME")
    [[ -n "$PYHAILORT_PATH" ]] && args+=("-ph" "$PYHAILORT_PATH")
    [[ -n "$PYTAPPAS_PATH" ]] && args+=("-pt" "$PYTAPPAS_PATH")
    [[ "${NO_INSTALL}" == true ]] && args+=("--no-install")
    [[ "${VERBOSE}" == true ]] && args+=("-v")
    
    if [[ "${DRY_RUN}" == true ]]; then
        log_dry_run "$script ${args[*]}"
        log_info "Would install Python packages:"
        log_info "  - hailo_apps (this package)"
        [[ "${INSTALL_HAILORT:-false}" == true ]] && log_info "  - PyHailoRT bindings"
        [[ "${INSTALL_TAPPAS_CORE:-false}" == true ]] && log_info "  - PyTappas bindings"
        [[ "${NO_INSTALL}" == true ]] && log_info "  (SKIPPED - --no-install flag set)"
        return 0
    fi
    
    if [[ "${NO_INSTALL}" == true ]]; then
        log_info "Skipping Python package installation (--no-install)"
        return 0
    fi
    
    log_info "Installing Python packages..."
    
    # Export version info for the script
    export HAILORT_VERSION TAPPAS_CORE_VERSION INSTALL_HAILORT INSTALL_TAPPAS_CORE
    
    if ! "$script" "${args[@]}"; then
        log_error "Failed to install Python packages"
        return 1
    fi
    
    log_success "Python packages installed"
    return 0
}

# Phase 4: Setup Resource Directories
phase_resources_setup() {
    log_phase "4" "Resource Directory Setup"
    
    local script="${SCRIPT_DIR}/scripts/installation/setup_resources.sh"
    
    if [[ ! -f "$script" ]]; then
        log_error "Resources setup script not found: $script"
        return 1
    fi
    
    local args=()
    [[ "${VERBOSE}" == true ]] && args+=("-v")
    
    if [[ "${DRY_RUN}" == true ]]; then
        log_dry_run "$script ${args[*]}"
        log_info "Would create resource directories at: $RESOURCES_ROOT"
        log_info "  - models/hailo8, models/hailo8l, models/hailo10h"
        log_info "  - videos, images, json, so, packages"
        return 0
    fi
    
    log_info "Creating resource directories..."
    
    if ! "$script" "${args[@]}"; then
        log_error "Failed to setup resource directories"
        return 1
    fi
    
    log_success "Resource directories created"
    return 0
}

# Phase 5: Post-Installation (runs as user!)
phase_post_install() {
    log_phase "5" "Post-Installation"
    
    local venv_path="${SCRIPT_DIR}/${VENV_NAME}"
    local venv_activate="${venv_path}/bin/activate"
    
    if [[ ! -f "$venv_activate" ]]; then
        log_error "Virtual environment not found at: $venv_path"
        return 1
    fi
    
    # Build post-install command
    local post_install_args=""
    if [[ "$DOWNLOAD_GROUP" == "all" ]]; then
        post_install_args="--all"
    else
        post_install_args="--group '${DOWNLOAD_GROUP}'"
    fi
    
    if [[ "${DRY_RUN}" == true ]]; then
        log_dry_run "as_user: source $venv_activate && hailo-post-install $post_install_args"
        log_info "Would run as user ${ORIGINAL_USER}:"
        log_info "  - Configure environment variables (.env)"
        log_info "  - Create symlink: resources -> ${RESOURCES_ROOT}"
        log_info "  - Download resources (group: $DOWNLOAD_GROUP)"
        log_info "  - Compile C++ postprocess modules"
        return 0
    fi
    
    log_info "Running post-installation as user: ${ORIGINAL_USER}"
    log_info "Download group: $DOWNLOAD_GROUP"
    
    # Fix ownership of project directory before running as user
    fix_ownership "${SCRIPT_DIR}"
    
    # Fix ownership of resources directory
    fix_ownership "${RESOURCES_ROOT}"
    
    # Run post-install as the original user (NOT as root)
    if ! as_user bash -c "source '${venv_activate}' && cd '${SCRIPT_DIR}' && hailo-post-install ${post_install_args}"; then
        log_error "Post-installation failed"
        echo ""
        log_info "Common causes:"
        log_info "  - Network issues (resource download failed)"
        log_info "  - Permission issues (try: sudo chown -R $ORIGINAL_USER:$ORIGINAL_GROUP ${SCRIPT_DIR})"
        log_info "  - C++ compilation failed (check meson/ninja installation)"
        return 1
    fi
    
    log_success "Post-installation completed"
    return 0
}

# Phase 6: Verification
phase_verification() {
    log_phase "6" "Installation Verification"
    
    if [[ "${SKIP_VERIFICATION}" == true ]]; then
        log_info "Skipping verification (--skip-verification)"
        return 0
    fi
    
    local script="${SCRIPT_DIR}/scripts/installation/verify_installation.sh"
    
    if [[ ! -f "$script" ]]; then
        log_warning "Verification script not found: $script"
        return 0
    fi
    
    local args=("-n" "$VENV_NAME")
    [[ "${VERBOSE}" == true ]] && args+=("-v")
    
    if [[ "${DRY_RUN}" == true ]]; then
        log_dry_run "$script ${args[*]}"
        log_info "Would verify:"
        log_info "  - Virtual environment activation"
        log_info "  - Python package imports"
        log_info "  - Resource availability"
        log_info "  - Postprocess compilation"
        return 0
    fi
    
    log_info "Verifying installation..."
    
    if ! "$script" "${args[@]}"; then
        log_warning "Verification found some issues (see above)"
        return 1
    fi
    
    log_success "Installation verified"
    return 0
}

#===============================================================================
# MAIN ORCHESTRATION
#===============================================================================

parse_arguments() {
    while [[ $# -gt 0 ]]; do
        case "$1" in
            -n|--venv-name)
                VENV_NAME="$2"
                shift 2
                ;;
            -ph|--pyhailort)
                PYHAILORT_PATH="$2"
                shift 2
                ;;
            -pt|--pytappas)
                PYTAPPAS_PATH="$2"
                shift 2
                ;;
            --all)
                DOWNLOAD_GROUP="all"
                shift
                ;;
            -x|--no-install)
                NO_INSTALL=true
                shift
                ;;
            --no-system-python)
                NO_SYSTEM_PYTHON=true
                shift
                ;;
            --skip-verification)
                SKIP_VERIFICATION=true
                shift
                ;;
            --phase)
                SINGLE_PHASE="$2"
                shift 2
                ;;
            --dry-run)
                DRY_RUN=true
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
                echo "Use --help for usage information"
                exit 1
                ;;
        esac
    done
}

# Run a single phase with status tracking
run_phase() {
    local phase_name="$1"
    local phase_func="phase_${phase_name}"
    
    if ! declare -f "$phase_func" > /dev/null; then
        log_error "Unknown phase: $phase_name"
        echo "Available phases: ${PHASES[*]}"
        return 1
    fi
    
    PHASE_STATUS["$phase_name"]="running"
    
    if "$phase_func"; then
        PHASE_STATUS["$phase_name"]="success"
        return 0
    else
        PHASE_STATUS["$phase_name"]="failed"
        return 1
    fi
}

# Print final summary
print_summary() {
    echo ""
    echo -e "${BOLD}════════════════════════════════════════════════════════════════${NC}"
    echo -e "${BOLD}  Installation Summary${NC}"
    echo -e "${BOLD}════════════════════════════════════════════════════════════════${NC}"
    echo ""
    
    local all_success=true
    
    for phase in "${PHASES[@]}"; do
        local status="${PHASE_STATUS[$phase]:-skipped}"
        local icon
        case "$status" in
            success) icon="✅" ;;
            failed) icon="❌"; all_success=false ;;
            skipped) icon="⏭️ " ;;
            *) icon="❓" ;;
        esac
        printf "  %s %-20s %s\n" "$icon" "$phase" "[$status]"
    done
    
    echo ""
    
    if [[ "${DRY_RUN}" == true ]]; then
        echo -e "${YELLOW}This was a DRY RUN - no changes were made${NC}"
        echo ""
    fi
    
    if [[ "$all_success" == true ]]; then
        echo -e "${GREEN}${BOLD}Installation completed successfully!${NC}"
        echo ""
        echo "Virtual environment: ${SCRIPT_DIR}/${VENV_NAME}"
        echo "To activate: source ${SCRIPT_DIR}/setup_env.sh"
        echo ""
    else
        echo -e "${RED}${BOLD}Installation completed with errors${NC}"
        echo "Check the log file: ${LOG_FILE}"
        echo ""
    fi
    
    echo "Log file: ${LOG_FILE}"
}

main() {
    # Parse command line arguments first (before any output)
    parse_arguments "$@"
    
    # Initialize logging
    init_logging
    
    # Show banner
    echo ""
    echo -e "${CYAN}${BOLD}╔══════════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${CYAN}${BOLD}║       Hailo Apps Infrastructure Installer                        ║${NC}"
    echo -e "${CYAN}${BOLD}╚══════════════════════════════════════════════════════════════════╝${NC}"
    echo ""
    
    if [[ "${DRY_RUN}" == true ]]; then
        echo -e "${YELLOW}${BOLD}🔍 DRY-RUN MODE - No changes will be made${NC}"
        echo ""
    fi
    
    # Detect user/group
    detect_user_and_group
    
    # Load configuration
    load_config
    
    log_info "Configuration:"
    log_info "  Virtual Environment: ${VENV_NAME}"
    log_info "  Download Group: ${DOWNLOAD_GROUP}"
    log_info "  Resources Root: ${RESOURCES_ROOT}"
    log_info "  Verbose: ${VERBOSE}"
    log_info "  Dry Run: ${DRY_RUN}"
    echo ""
    
    # Run single phase or all phases
    if [[ -n "${SINGLE_PHASE}" ]]; then
        log_info "Running single phase: ${SINGLE_PHASE}"
        if ! run_phase "${SINGLE_PHASE}"; then
            log_error "Phase ${SINGLE_PHASE} failed"
            exit 1
        fi
        exit 0
    fi
    
    # Run all phases in order
    local failed=false
    
    for phase in "${PHASES[@]}"; do
        if ! run_phase "$phase"; then
            failed=true
            log_error "Phase $phase failed - stopping installation"
            break
        fi
    done
    
    # Final ownership fix (if not dry-run)
    if [[ "${DRY_RUN}" != true && "$failed" != true ]]; then
        log_info "Fixing final ownership..."
        fix_ownership "${SCRIPT_DIR}"
    fi
    
    # Print summary
    print_summary
    
    if [[ "$failed" == true ]]; then
        exit 1
    fi
    
    exit 0
}

# Run main
main "$@"
