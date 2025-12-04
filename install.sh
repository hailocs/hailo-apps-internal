#!/usr/bin/env bash
# Main installation orchestrator for Hailo Apps Infrastructure

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Source helper functions and load config
source "${SCRIPT_DIR}/scripts/installation/install_helpers.sh"
load_config "" "${SCRIPT_DIR}"

# Default values
DOWNLOAD_GROUP="${DEFAULT_DOWNLOAD_GROUP}"
VENV_NAME="${DEFAULT_VENV_NAME}"
PYHAILORT_PATH=""
PYTAPPAS_PATH=""
NO_INSTALL=false
NO_SYSTEM_PYTHON=false
DRY_RUN=false
VERBOSE=false
STEP=""

show_help() {
    cat << EOF
Usage: sudo $0 [OPTIONS]

Install Hailo Apps Infrastructure with virtual environment setup.

⚠️  This script MUST be run with sudo.

OPTIONS:
    -n, --venv-name NAME        Set virtual environment name (default: ${DEFAULT_VENV_NAME})
    -ph, --pyhailort PATH       Path to custom PyHailoRT wheel file
    -pt, --pytappas PATH        Path to custom PyTappas wheel file
    --all                       Download all available models/resources
    -x, --no-install           Skip installation of Python packages
    --no-system-python         Don't use system site-packages (default: use system site-packages unless on x86)
    --step STEP                 Run only specific step (check_prerequisites, setup_venv, install_python_packages, setup_resources, setup_environment, run_post_install, verify_installation)
    --dry-run                   Preview changes without executing
    -v, --verbose              Show detailed output
    -h, --help                  Show this help message and exit

EXAMPLES:
    sudo $0                          # Basic installation with default settings
    sudo $0 -n my_venv               # Use custom virtual environment name
    sudo $0 --all                    # Install with all models/resources
    sudo $0 -x                       # Skip Python package installation
    sudo $0 --no-system-python       # Don't use system site-packages
    sudo $0 --step setup_venv        # Run only venv setup step
    sudo $0 --dry-run                # Preview changes
    sudo $0 -ph /path/to/pyhailort.whl -pt /path/to/pytappas.whl  # Use custom wheel files

DESCRIPTION:
    This script orchestrates the installation of Hailo Apps Infrastructure.
    It runs the following steps in order:
    1. Check prerequisites (driver, HailoRT, TAPPAS)
    2. Setup virtual environment
    3. Install Python packages
    4. Setup resource directories
    5. Setup environment variables
    6. Run post-installation tasks
    7. Verify installation

    Each step can also be run independently using the corresponding script in scripts/.

REQUIREMENTS:
    - Must be run with sudo
    - Hailo PCI driver must be installed
    - HailoRT must be installed
    - TAPPAS core must be installed

    Use 'sudo ./scripts/hailo_installer.sh' to install missing components.

EOF
}

# Parse arguments
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
            log_info "Skipping installation of Python packages."
      shift
      ;;
    --no-system-python)
      NO_SYSTEM_PYTHON=true
      shift
      ;;
        --step)
            STEP="$2"
            shift 2
            ;;
        --dry-run)
            DRY_RUN=true
            log_info "Dry-run mode: Previewing changes without executing"
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
      echo "Use -h or --help for usage information."
      exit 1
      ;;
  esac
done

# Export verbose flag for use in other scripts
export VERBOSE

# Detect user and group
detect_user_and_group

# Function to run a step
run_step() {
    local step_name="$1"
    local script_path="$2"
    shift 2
    local args=("$@")
    
    if [[ "$DRY_RUN" == true ]]; then
        log_info "[DRY-RUN] Would run: ${script_path} ${args[*]}"
        return 0
    fi
    
    log_info "Running step: ${step_name}..."
    if "${script_path}" "${args[@]}"; then
        log_info "Step ${step_name} completed successfully"
        return 0
    else
        log_error "Step ${step_name} failed"
        return 1
    fi
}

# Function to check prerequisites
step_check_prerequisites() {
    local args=()
    [[ "$VERBOSE" == true ]] && args+=("-v")
    
    # Parse output to get versions (run before step to capture output)
    if [[ "$DRY_RUN" != true ]]; then
        local output
        output=$("${SCRIPT_DIR}/scripts/installation/check_prerequisites.sh" "${args[@]}" 2>&1)
        local exit_code=$?
        
        if [[ $exit_code -ne 0 ]]; then
            log_error "Prerequisites check failed"
            echo "$output"
            return 1
        fi
        
        local summary_line
        summary_line=$(echo "$output" | sed -n 's/^SUMMARY: //p')
        
        if [[ -z "$summary_line" ]]; then
            log_error "Could not find SUMMARY line from prerequisites check"
            echo "$output"
            return 1
        fi
        
        IFS=' ' read -r -a pairs <<< "$summary_line"
        # SUMMARY format: hailo_arch=... hailo_pci=... hailort=... pyhailort=... tappas-core=... tappas-python=...
        # Skip pairs[0] (hailo_arch) and start from pairs[1] (hailo_pci/driver)
        # Use default empty value to avoid unbound variable errors with set -u
        export DRIVER_VERSION="${pairs[1]:-}"
        export HAILORT_VERSION="${pairs[2]:-}"
        export PYHAILORT_VERSION="${pairs[3]:-}"
        export TAPPAS_CORE_VERSION="${pairs[4]:-}"
        export PYTAPPAS_VERSION="${pairs[5]:-}"
        # Remove key= prefix from each value
        DRIVER_VERSION="${DRIVER_VERSION#*=}"
        HAILORT_VERSION="${HAILORT_VERSION#*=}"
        PYHAILORT_VERSION="${PYHAILORT_VERSION#*=}"
        TAPPAS_CORE_VERSION="${TAPPAS_CORE_VERSION#*=}"
        PYTAPPAS_VERSION="${PYTAPPAS_VERSION#*=}"
        export DRIVER_VERSION HAILORT_VERSION PYHAILORT_VERSION TAPPAS_CORE_VERSION PYTAPPAS_VERSION
        
        # Determine if we need to install Python bindings
        export INSTALL_HAILORT=false
        export INSTALL_TAPPAS_CORE=false
        
        if [[ "$PYHAILORT_VERSION" == "-1" && "$NO_INSTALL" != true ]]; then
            export INSTALL_HAILORT=true
        fi
        if [[ "$PYTAPPAS_VERSION" == "-1" && "$NO_INSTALL" != true ]]; then
            export INSTALL_TAPPAS_CORE=true
        fi
        
        log_info "Prerequisites check completed successfully"
        log_debug "Driver: $DRIVER_VERSION, HailoRT: $HAILORT_VERSION, TAPPAS: $TAPPAS_CORE_VERSION"
    else
        log_info "[DRY-RUN] Would run: ${SCRIPT_DIR}/scripts/installation/check_prerequisites.sh ${args[*]}"
    fi
}

# Function to setup venv
step_setup_venv() {
    local args=("-n" "$VENV_NAME" "--remove-existing")
    [[ "$NO_SYSTEM_PYTHON" == true ]] && args+=("--no-system-python")
    [[ "$VERBOSE" == true ]] && args+=("-v")
    run_step "setup_venv" "${SCRIPT_DIR}/scripts/installation/setup_venv.sh" "${args[@]}"
}

# Function to install Python packages
step_install_python_packages() {
    local args=("-n" "$VENV_NAME")
    [[ -n "$PYHAILORT_PATH" ]] && args+=("-ph" "$PYHAILORT_PATH")
    [[ -n "$PYTAPPAS_PATH" ]] && args+=("-pt" "$PYTAPPAS_PATH")
    [[ "$NO_INSTALL" == true ]] && args+=("--no-install")
    [[ "$VERBOSE" == true ]] && args+=("-v")
    
    # Pass version information if available
    if [[ -n "${HAILORT_VERSION:-}" && -n "${TAPPAS_CORE_VERSION:-}" ]]; then
        export HAILORT_VERSION
        export TAPPAS_CORE_VERSION
        export INSTALL_HAILORT
        export INSTALL_TAPPAS_CORE
    fi
    
    run_step "install_python_packages" "${SCRIPT_DIR}/scripts/installation/install_python_packages.sh" "${args[@]}"
}

# Function to setup resources
step_setup_resources() {
    local args=()
    [[ "$VERBOSE" == true ]] && args+=("-v")
    run_step "setup_resources" "${SCRIPT_DIR}/scripts/installation/setup_resources.sh" "${args[@]}"
}

# Function to setup environment
step_setup_environment() {
    local args=("-n" "$VENV_NAME")
    [[ "$VERBOSE" == true ]] && args+=("-v")
    run_step "setup_environment" "${SCRIPT_DIR}/scripts/installation/setup_environment.sh" "${args[@]}"
}

# Function to run post-install
step_run_post_install() {
    local args=("-n" "$VENV_NAME" "--group" "$DOWNLOAD_GROUP")
    [[ "$VERBOSE" == true ]] && args+=("-v")
    run_step "run_post_install" "${SCRIPT_DIR}/scripts/installation/run_post_install.sh" "${args[@]}"
}

# Function to verify installation
step_verify_installation() {
    local args=("-n" "$VENV_NAME")
    [[ "$VERBOSE" == true ]] && args+=("-v")
    run_step "verify_installation" "${SCRIPT_DIR}/scripts/installation/verify_installation.sh" "${args[@]}"
}

# Main installation flow
main() {
    log_info "Starting Hailo Apps Infrastructure installation..."
    log_info "Virtual environment: ${VENV_NAME}"
    log_info "Download group: ${DOWNLOAD_GROUP}"
    
    # If --step is specified, run only that step
    if [[ -n "$STEP" ]]; then
        case "$STEP" in
            check_prerequisites)
                step_check_prerequisites
                ;;
            setup_venv)
                step_setup_venv
                ;;
            install_python_packages)
                step_install_python_packages
                ;;
            setup_resources)
                step_setup_resources
                ;;
            setup_environment)
                step_setup_environment
                ;;
            run_post_install)
                step_run_post_install
                ;;
            verify_installation)
                step_verify_installation
                ;;
            *)
                log_error "Unknown step: $STEP"
                echo "Available steps: check_prerequisites, setup_venv, install_python_packages, setup_resources, setup_environment, run_post_install, verify_installation"
                exit 1
                ;;
        esac
        exit $?
    fi
    
    # Run all steps in order
    if ! step_check_prerequisites; then
        log_error "Prerequisites check failed. Please install missing components."
        exit 1
    fi
    
    if ! step_setup_venv; then
        log_error "Virtual environment setup failed."
        exit 1
    fi
    
    if ! step_install_python_packages; then
        log_error "Python package installation failed."
        exit 1
    fi
    
    if ! step_setup_resources; then
        log_error "Resource setup failed."
        exit 1
    fi
    
    if ! step_setup_environment; then
        log_error "Environment setup failed."
        exit 1
    fi
    
    if ! step_run_post_install; then
        log_error "Post-installation failed."
        exit 1
    fi
    
    if ! step_verify_installation; then
        log_warning "Installation verification found issues. Please review the output."
    fi
    
    # Final ownership fix for all project files
    if [[ "$DRY_RUN" != true ]]; then
        log_info "Ensuring all project files have correct ownership..."
        fix_ownership "${SCRIPT_DIR}"
        log_info "Project files ownership fixed to ${ORIGINAL_USER}:${ORIGINAL_GROUP}"
    fi
    
    log_info ""
    log_info "Installation process completed!"
    log_info "Virtual environment: ${VENV_NAME}"
    log_info "Location: ${SCRIPT_DIR}/${VENV_NAME}"
    log_info "User: ${ORIGINAL_USER}"
    log_info "Group: ${ORIGINAL_GROUP}"
    log_info ""
    log_info "All done! Your package is now in '${VENV_NAME}'."
    log_info "Run 'source setup_env.sh' to setup the environment"
}

# Run main function
main
