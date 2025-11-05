#!/usr/bin/env bash
# Check prerequisites for Hailo Apps Infrastructure installation
#
# This script validates system requirements before installation:
# - Checks if running with sudo
# - Detects original user and group
# - Validates Hailo PCI driver installation
# - Validates HailoRT installation
# - Validates TAPPAS core installation
# - Checks Python bindings (PyHailoRT, PyTappas)
# - Outputs summary line with version information for other scripts

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

# Source helper functions
source "${SCRIPT_DIR}/install_helpers.sh"

# Initialize variables
DRIVER_VERSION=""
HAILORT_VERSION=""
PYHAILORT_VERSION=""
TAPPAS_CORE_VERSION=""
PYTAPPAS_VERSION=""
INSTALL_HAILORT=false
INSTALL_TAPPAS_CORE=false

show_help() {
    cat << EOF
Usage: sudo $0 [OPTIONS]

Check prerequisites for Hailo Apps Infrastructure installation.

⚠️  This script MUST be run with sudo.

OPTIONS:
    -v, --verbose              Show detailed output
    -h, --help                 Show this help message and exit

OUTPUT:
    This script checks for required Hailo components and outputs a summary
    in the format:
    SUMMARY: driver=<version> hailort=<version> pyhailort=<version> tappas=<version> pytappas=<version>

EXIT CODES:
    0 - All prerequisites met
    1 - Missing required components
    2 - Script error

EOF
}

# Parse arguments
VERBOSE=false
while [[ $# -gt 0 ]]; do
    case "$1" in
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

log_info "Checking prerequisites..."

    # Run check_installed_packages.sh and parse output
    SUMMARY_LINE=$(
        as_original_user bash -c "cd '${PROJECT_ROOT}' && ./scripts/check_installed_packages.sh" 2>&1 \
            | sed -n 's/^SUMMARY: //p'
    )

if [[ -z "$SUMMARY_LINE" ]]; then
    log_error "Could not find SUMMARY line from check_installed_packages.sh"
    exit 2
fi

IFS=' ' read -r -a pairs <<< "$SUMMARY_LINE"

DRIVER_VERSION="${pairs[0]#*=}"
HAILORT_VERSION="${pairs[1]#*=}"
PYHAILORT_VERSION="${pairs[2]#*=}"
TAPPAS_CORE_VERSION="${pairs[3]#*=}"
PYTAPPAS_VERSION="${pairs[4]#*=}"

# Check required components
ERRORS=0

if [[ "$DRIVER_VERSION" == "-1" ]]; then
    log_error "Hailo PCI driver is not installed. Please install it first."
    echo "To install the driver, run:"
    echo "    sudo ./scripts/hailo_installer.sh"
    ERRORS=$((ERRORS + 1))
else
    log_info "Hailo PCI driver: $DRIVER_VERSION"
fi

if [[ "$HAILORT_VERSION" == "-1" ]]; then
    log_error "HailoRT is not installed. Please install it first."
    echo "To install HailoRT, run:"
    echo "    sudo ./scripts/hailo_installer.sh"
    ERRORS=$((ERRORS + 1))
else
    log_info "HailoRT: $HAILORT_VERSION"
fi

if [[ "$TAPPAS_CORE_VERSION" == "-1" ]]; then
    log_error "TAPPAS core is not installed. Please install it first."
    echo "To install TAPPAS, run:"
    echo "    sudo ./scripts/hailo_installer.sh"
    ERRORS=$((ERRORS + 1))
else
    log_info "TAPPAS core: $TAPPAS_CORE_VERSION"
fi

# Check Python bindings (these can be installed in venv)
if [[ "$PYHAILORT_VERSION" == "-1" ]]; then
    log_warning "Python HailoRT binding is not installed."
    log_info "Will be installed in the virtualenv."
    INSTALL_HAILORT=true
else
    log_info "Python HailoRT binding: $PYHAILORT_VERSION"
fi

if [[ "$PYTAPPAS_VERSION" == "-1" ]]; then
    log_warning "Python TAPPAS binding is not installed."
    log_info "Will be installed in the virtualenv."
    INSTALL_TAPPAS_CORE=true
else
    log_info "Python TAPPAS binding: $PYTAPPAS_VERSION"
fi

# Export for use in other scripts
export DRIVER_VERSION
export HAILORT_VERSION
export PYHAILORT_VERSION
export TAPPAS_CORE_VERSION
export PYTAPPAS_VERSION
export INSTALL_HAILORT
export INSTALL_TAPPAS_CORE

# Output summary for other scripts to parse
echo "SUMMARY: driver=${DRIVER_VERSION} hailort=${HAILORT_VERSION} pyhailort=${PYHAILORT_VERSION} tappas=${TAPPAS_CORE_VERSION} pytappas=${PYTAPPAS_VERSION}"

if [[ $ERRORS -gt 0 ]]; then
    log_error "Prerequisites check failed. Please install missing components."
    exit 1
fi

log_info "All prerequisites met!"
exit 0

