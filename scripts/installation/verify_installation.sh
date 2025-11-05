#!/usr/bin/env bash
# Verify installation of Hailo Apps Infrastructure
#
# This script verifies the installation completed successfully:
# - Checks virtual environment exists and is accessible
# - Verifies Python packages are importable
# - Checks HailoRT/TAPPAS Python bindings availability
# - Validates resources directory setup
# - Verifies environment file exists
# - Checks C++ postprocess libraries compilation
# - Supports JSON output format for automation
# - Provides detailed verification report

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

# Source helper functions and load config
source "${SCRIPT_DIR}/install_helpers.sh"
load_config "" "${PROJECT_ROOT}"

# Default values
VENV_NAME="${DEFAULT_VENV_NAME}"
VENV_PATH="${PROJECT_ROOT}/${VENV_NAME}"
JSON_OUTPUT=false

show_help() {
    cat << EOF
Usage: sudo $0 [OPTIONS]

Verify installation of Hailo Apps Infrastructure.

⚠️  This script MUST be run with sudo.

OPTIONS:
    -n, --venv-name NAME          Virtual environment name (default: ${DEFAULT_VENV_NAME})
    --json                         Output results in JSON format
    -v, --verbose                  Show detailed output
    -h, --help                     Show this help message and exit

EXAMPLES:
    sudo $0                                    # Verify installation with default venv
    sudo $0 -n my_venv                        # Verify installation with custom venv
    sudo $0 --json                            # Output results in JSON format

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
        --json)
            JSON_OUTPUT=true
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

log_info "Verifying installation..."

# Verification results
VERIFY_SUCCESS=true
RESULTS=()

# Check virtual environment
check_venv() {
    local result=""
    if [[ -f "${VENV_PATH}/bin/activate" ]]; then
        result="✅ Virtual environment created successfully"
        RESULTS+=("venv:pass")
    else
        result="❌ Virtual environment not found"
        RESULTS+=("venv:fail")
        VERIFY_SUCCESS=false
    fi
    if [[ "$JSON_OUTPUT" != true ]]; then
        echo "  📁 Checking virtual environment..."
        echo "    ${result}"
    fi
}

# Check Python packages
check_python_packages() {
    local result=""
    if as_original_user bash -c "source '${VENV_PATH}/bin/activate' && python3 -c 'import hailo_apps; print(\"Hailo Apps version:\", hailo_apps.__file__)'" 2>/dev/null; then
        result="✅ Hailo Apps package installed successfully"
        RESULTS+=("package:pass")
    else
        result="❌ Hailo Apps package not properly installed"
        RESULTS+=("package:fail")
        VERIFY_SUCCESS=false
    fi
    if [[ "$JSON_OUTPUT" != true ]]; then
        echo "  🐍 Checking Python packages..."
        echo "    ${result}"
    fi
}

# Check HailoRT Python bindings
check_hailort_bindings() {
    local result=""
    if as_original_user bash -c "source '${VENV_PATH}/bin/activate' && python3 -c 'import hailo; print(\"HailoRT available\")'" 2>/dev/null; then
        result="✅ HailoRT Python bindings available"
        RESULTS+=("hailort:pass")
    else
        result="⚠️  HailoRT Python bindings not available (may need system installation)"
        RESULTS+=("hailort:warning")
    fi
    if [[ "$JSON_OUTPUT" != true ]]; then
        echo "  📦 Checking HailoRT Python bindings..."
        echo "    ${result}"
    fi
}

# Check TAPPAS Python bindings
check_tappas_bindings() {
    local result=""
    if as_original_user bash -c "source '${VENV_PATH}/bin/activate' && python3 -c 'import hailo_platform; print(\"TAPPAS available\")'" 2>/dev/null; then
        result="✅ TAPPAS Python bindings available"
        RESULTS+=("tappas:pass")
    else
        result="⚠️  TAPPAS Python bindings not available (may need system installation)"
        RESULTS+=("tappas:warning")
    fi
    if [[ "$JSON_OUTPUT" != true ]]; then
        echo "  📦 Checking TAPPAS Python bindings..."
        echo "    ${result}"
    fi
}

# Check resources directory
check_resources() {
    local result=""
    if [[ -d "${PROJECT_ROOT}/resources" ]]; then
        if [[ -L "${PROJECT_ROOT}/resources" ]]; then
            result="✅ Resources symlink created successfully"
            RESULTS+=("resources:pass")
            if [[ -d "${PROJECT_ROOT}/resources/models" ]]; then
                local model_count=$(find "${PROJECT_ROOT}/resources/models" -name "*.hef" 2>/dev/null | wc -l)
                result="${result} (Found $model_count model files)"
            else
                result="${result} (Models directory not found)"
            fi
        else
            result="✅ Resources directory exists"
            RESULTS+=("resources:pass")
        fi
    else
        result="❌ Resources directory not properly set up"
        RESULTS+=("resources:fail")
        VERIFY_SUCCESS=false
    fi
    if [[ "$JSON_OUTPUT" != true ]]; then
        echo "  📁 Checking resources directory..."
        echo "    ${result}"
    fi
}

# Check environment file
check_env_file() {
    local result=""
    if [[ -f "${PROJECT_ROOT}/resources/.env" ]]; then
        result="✅ Environment file created successfully"
        RESULTS+=("env_file:pass")
    else
        result="❌ Environment file not found"
        RESULTS+=("env_file:fail")
        VERIFY_SUCCESS=false
    fi
    if [[ "$JSON_OUTPUT" != true ]]; then
        echo "  📄 Checking environment file..."
        echo "    ${result}"
    fi
}

# Check C++ postprocess compilation
check_cpp_libraries() {
    local result=""
    if [[ -d "/usr/local/hailo/resources/so" ]]; then
        local so_count=$(find /usr/local/hailo/resources/so -name "*.so" 2>/dev/null | wc -l)
        if [[ $so_count -gt 0 ]]; then
            result="✅ Found $so_count compiled C++ postprocess libraries"
            RESULTS+=("cpp_libs:pass")
        else
            result="⚠️  No compiled C++ postprocess libraries found (may affect some advanced features)"
            RESULTS+=("cpp_libs:warning")
        fi
    else
        result="⚠️  C++ library directory not found (may affect some advanced features)"
        RESULTS+=("cpp_libs:warning")
    fi
    if [[ "$JSON_OUTPUT" != true ]]; then
        echo "  🔨 Checking C++ postprocess compilation..."
        echo "    ${result}"
    fi
}

# Run all checks
check_venv
check_python_packages
check_hailort_bindings
check_tappas_bindings
check_resources
check_env_file
check_cpp_libraries

# Output JSON if requested
if [[ "$JSON_OUTPUT" == true ]]; then
    echo "{"
    echo "  \"venv_name\": \"${VENV_NAME}\","
    echo "  \"venv_path\": \"${VENV_PATH}\","
    echo "  \"success\": ${VERIFY_SUCCESS},"
    echo "  \"checks\": {"
    for result in "${RESULTS[@]}"; do
        IFS=':' read -r check status <<< "$result"
        echo "    \"${check}\": \"${status}\","
    done
    echo "  }"
    echo "}"
fi

# Final summary
if [[ "$JSON_OUTPUT" != true ]]; then
    echo ""
    if [[ "$VERIFY_SUCCESS" == true ]]; then
        log_info "Installation verification completed successfully!"
    else
        log_error "Installation verification found issues. Please review the output above."
        exit 1
    fi
fi

exit 0

