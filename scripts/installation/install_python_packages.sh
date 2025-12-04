#!/usr/bin/env bash
# Install Python packages for Hailo Apps Infrastructure
#
# This script installs all required Python packages:
# - Installs system packages (meson, portaudio19-dev, etc.)
# - Upgrades pip, setuptools, wheel
# - Installs custom PyHailoRT/PyTappas wheels if provided
# - Installs Hailo Python bindings (if missing)
# - Installs hailo_apps package in editable mode
# - Handles installation errors with helpful messages

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

# Source helper functions and load config
source "${SCRIPT_DIR}/install_helpers.sh"
load_config "" "${PROJECT_ROOT}"

# Default values
VENV_NAME="${DEFAULT_VENV_NAME}"
VENV_PATH="${PROJECT_ROOT}/${VENV_NAME}"
PYHAILORT_PATH=""
PYTAPPAS_PATH=""
NO_INSTALL=false
SKIP_HAILO_BINDINGS=false
SKIP_PACKAGE=false

show_help() {
    cat << EOF
Usage: sudo $0 [OPTIONS]

Install Python packages for Hailo Apps Infrastructure.

⚠️  This script MUST be run with sudo.

OPTIONS:
    -n, --venv-name NAME          Virtual environment name (default: ${DEFAULT_VENV_NAME})
    -ph, --pyhailort PATH          Path to custom PyHailoRT wheel file
    -pt, --pytappas PATH           Path to custom PyTappas wheel file
    --skip-hailo                   Skip installation of Hailo Python bindings
    --skip-package                 Skip installation of hailo_apps package
    --no-install                   Skip all Python package installation
    -v, --verbose                  Show detailed output
    -h, --help                     Show this help message and exit

EXAMPLES:
    sudo $0                                    # Install all packages
    sudo $0 -ph /path/to/pyhailort.whl        # Use custom PyHailoRT wheel
    sudo $0 --skip-hailo                      # Skip Hailo bindings
    sudo $0 --skip-package                    # Skip hailo_apps package

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
        -ph|--pyhailort)
            PYHAILORT_PATH="$2"
            shift 2
            ;;
        -pt|--pytappas)
            PYTAPPAS_PATH="$2"
            shift 2
            ;;
        --skip-hailo)
            SKIP_HAILO_BINDINGS=true
            shift
            ;;
        --skip-package)
            SKIP_PACKAGE=true
            shift
            ;;
        --no-install)
            NO_INSTALL=true
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

log_info "Virtual environment: ${VENV_NAME}"
log_info "Location: ${VENV_PATH}"

if [[ "$NO_INSTALL" == true ]]; then
    log_info "Skipping installation of Python packages."
    exit 0
fi

# Install system packages
log_info "Installing system packages..."
sudo apt-get install -y "${REQUIRED_SYSTEM_PACKAGES[@]}"

# Activate venv and upgrade pip
log_info "Upgrading pip, setuptools, and wheel..."
as_original_user bash -c "source '${VENV_PATH}/bin/activate' && python3 -m pip install --upgrade pip setuptools wheel"

# Install custom wheels if provided
if [[ -n "$PYHAILORT_PATH" ]]; then
    log_info "Using custom HailoRT Python binding path: $PYHAILORT_PATH"
    if [[ ! -f "$PYHAILORT_PATH" ]]; then
        log_error "HailoRT Python binding not found at $PYHAILORT_PATH"
        exit 1
    fi
    as_original_user bash -c "source '${VENV_PATH}/bin/activate' && pip install '$PYHAILORT_PATH'"
    SKIP_HAILO_BINDINGS=true
fi

if [[ -n "$PYTAPPAS_PATH" ]]; then
    log_info "Using custom TAPPAS Python binding path: $PYTAPPAS_PATH"
    if [[ ! -f "$PYTAPPAS_PATH" ]]; then
        log_error "TAPPAS Python binding not found at $PYTAPPAS_PATH"
        exit 1
    fi
    as_original_user bash -c "source '${VENV_PATH}/bin/activate' && pip install '$PYTAPPAS_PATH'"
    SKIP_HAILO_BINDINGS=true
fi

# Install Hailo Python bindings if needed
if [[ "$SKIP_HAILO_BINDINGS" != true ]]; then
    # Get versions from prerequisites check (should be set by main install.sh or check_prerequisites.sh)
    if [[ -z "${HAILORT_VERSION:-}" || -z "${TAPPAS_CORE_VERSION:-}" ]]; then
        log_warning "HAILORT_VERSION and TAPPAS_CORE_VERSION not set"
        log_info "Running prerequisites check to get versions..."
        # Run prerequisites check to get versions
        local prereq_output
        prereq_output=$(bash -c "cd '${PROJECT_ROOT}' && ./scripts/installation/check_prerequisites.sh" 2>&1)
        local summary_line
        summary_line=$(echo "$prereq_output" | sed -n 's/^SUMMARY: //p')
        
        if [[ -n "$summary_line" ]]; then
            IFS=' ' read -r -a pairs <<< "$summary_line"
            # SUMMARY format: hailo_arch=... hailo_pci=... hailort=... pyhailort=... tappas-core=... tappas-python=...
            # Skip pairs[0] (hailo_arch) and start from pairs[1] (hailo_pci/driver)
            # Use default empty value to avoid unbound variable errors with set -u
            local hailort_val="${pairs[2]:-}"
            local tappas_val="${pairs[4]:-}"
            local pyhailort_val="${pairs[3]:-}"
            local pytappas_val="${pairs[5]:-}"
            # Remove key= prefix from each value
            HAILORT_VERSION="${hailort_val#*=}"
            TAPPAS_CORE_VERSION="${tappas_val#*=}"
            INSTALL_HAILORT=false
            INSTALL_TAPPAS_CORE=false
            
            if [[ "${pyhailort_val#*=}" == "-1" ]]; then
                INSTALL_HAILORT=true
            fi
            if [[ "${pytappas_val#*=}" == "-1" ]]; then
                INSTALL_TAPPAS_CORE=true
            fi
        else
            log_error "Could not get version information from prerequisites check"
            exit 1
        fi
    fi

    log_info "Installing Python Hailo packages..."
    FLAGS=''
    if [[ "${INSTALL_TAPPAS_CORE:-false}" == true ]]; then
        log_info "Installing TAPPAS core Python binding"
        FLAGS="--tappas-core-version=${TAPPAS_CORE_VERSION}"
    fi
    if [[ "${INSTALL_HAILORT:-false}" == true ]]; then
        log_info "Installing HailoRT Python binding"
        FLAGS="${FLAGS} --hailort-version=${HAILORT_VERSION}"
    fi

    if [[ -n "$FLAGS" ]]; then
        log_info "Installing Hailo Python packages with flags: ${FLAGS}"
        as_original_user bash -c "source '${VENV_PATH}/bin/activate' && cd '${PROJECT_ROOT}' && ./scripts/hailo_python_installation.sh ${FLAGS}"
    else
        log_info "No Hailo Python packages to install."
    fi
fi

# Install hailo_apps package
if [[ "$SKIP_PACKAGE" != true ]]; then
    log_info "Installing package (editable + post-install)..."
    if ! as_original_user bash -c "source '${VENV_PATH}/bin/activate' && cd '${PROJECT_ROOT}' && pip install -e ."; then
        log_error "Package installation failed!"
        echo ""
        echo "This usually means:"
        echo "  - Missing system dependencies (e.g., portaudio19-dev for PyAudio)"
        echo "  - Build dependencies not available"
        echo "  - Network issues"
        echo ""
        echo "Please check the error messages above and try again."
        echo "If you see missing header files (e.g., portaudio.h), install the corresponding -dev package."
        exit 1
    fi
    log_info "Package installed successfully"
else
    log_info "Skipping hailo_apps package installation"
fi

log_info "Python packages installation completed!"
exit 0

