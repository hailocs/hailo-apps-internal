#!/bin/bash

set -e
set -o pipefail

# Terminal colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Print error message and exit
error_exit() {
    echo -e "${RED}[ERROR] $1${NC}" >&2
    exit 1
}

# Detect if a Python package is installed via pip and return its version
detect_pip_pkg_version() {
    local pkg="$1"
    # Try various methods to get the package version
    pip3 list 2>/dev/null | grep -i "^$pkg " | awk '{print $2}' || \
    python3 -m pip list 2>/dev/null | grep -i "^$pkg " | awk '{print $2}' || \
    python3 -c "import pkg_resources; print(pkg_resources.get_distribution('$pkg').version)" 2>/dev/null || \
    echo ""
}

# Check if hailo-all pip package is installed
is_hailo_all_installed() {
    detect_pip_pkg_version "hailo-all"
}

check_kernel_module() {
    local version="-1"
    local module=""
    local module_found="false"

    # Try to find hailo_pci module first
    if lsmod | grep -q "^hailo_pci "; then
        module="hailo_pci"
        module_found="true"
    elif modinfo hailo_pci &>/dev/null; then
        module="hailo_pci"
        module_found="true"
    fi

    # If hailo_pci was not found, check for hailo1x_pci
    if [[ "$module_found" == "false" ]]; then
        if lsmod | grep -q "^hailo1x_pci "; then
            module="hailo1x_pci"
            module_found="true"
        elif modinfo hailo1x_pci &>/dev/null; then
            module="hailo1x_pci"
            module_found="true"
        fi
    fi

    # If a module was found, get its version
    if [[ "$module_found" == "true" ]]; then
        if lsmod | grep -q "^$module "; then
            if modinfo "$module" &>/dev/null; then
                version=$(modinfo "$module" | awk -F ': +' '/^version:/{print $2}')
                echo "[OK]   $module module loaded and installed, version: $version"
            else
                echo "[OK]   $module module loaded (version unknown)"
                version="unknown"
            fi
        else
            version=$(modinfo "$module" | awk -F ': +' '/^version:/{print $2}')
            echo "[OK]   $module module installed (not loaded), version: $version"
        fi
    else
        # Fallback check for the package if neither module is found
        if dpkg -l 2>/dev/null | grep -q "^ii.*hailort-pcie-driver"; then
            version=$(dpkg -l | grep "^ii.*hailort-pcie-driver" | awk '{print $3}')
            echo "[OK]   hailort-pcie-driver package installed, version: $version"
        else
            echo "[WARN] hailo_pci/hailo1x_pci module not found, version: -1"
        fi
    fi

    # Always echo the version key=value for downstream parsing
    if [[ -z "$module" ]]; then
        echo "hailo_pci_unified=$version"
    else
        echo "$module=$version"
    fi
}

# Check for hailort installation
check_hailort() {
    local hailort_version="-1"
    
    # Check system installation via apt - handle both regular and versioned packages
    if dpkg -l 2>/dev/null | grep -E "^ii.*hailort(/| )" | head -1 | grep -q .; then
        hailort_version=$(dpkg -l | grep -E "^ii.*hailort(/| )" | head -1 | awk '{print $3}')
        echo "[OK]   hailort (system) version: $hailort_version"
    # Check with hailortcli if available
    elif command -v hailortcli >/dev/null 2>&1; then
        hailort_version=$(hailortcli --version 2>/dev/null | grep -oP 'version \K[0-9\.]+' || echo "-1")
        if [[ "$hailort_version" != "-1" ]]; then
            echo "[OK]   hailort (via hailortcli) version: $hailort_version"
        else
            echo "[WARNING] hailort not installed, version: -1"
        fi
    else
        echo "[WARNING] hailort not installed, version: -1"
    fi
    
    # Return the version
    echo "hailort=$hailort_version"
}

# Check for TAPPAS packages
check_tappas_packages() {
    local version="-1"
    local found=false

    # 1) Check for known Debian packages - handle versioned packages
    if dpkg -l 2>/dev/null | grep -E "^ii.*(hailo-tappas-core|hailo-tappas|tappas-core|tappas)" | head -1 | grep -q .; then
        pkg_line=$(dpkg -l 2>/dev/null | grep -E "^ii.*(hailo-tappas-core|hailo-tappas|tappas-core|tappas)" | head -1)
        pkg_name=$(echo "$pkg_line" | awk '{print $2}')
        version=$(echo "$pkg_line" | awk '{print $3}')
        echo "[OK]   $pkg_name (system) version: $version"
        found=true
    fi

    # 2) Fallback to pkg-config if no dpkg package found
    if ! $found; then
        for pc in hailo-tappas-core hailo_tappas tappas-core tappas; do
            if pkg-config --exists "$pc" 2>/dev/null; then
                if pkg-config --modversion "$pc" &>/dev/null; then
                    version=$(pkg-config --modversion "$pc")
                    echo "[OK]   pkg-config $pc version: $version"
                else
                    echo "[OK]   pkg-config $pc present, version: unknown"
                    version="unknown"
                fi
                found=true
                break
            fi
        done
    fi

    # 3) If still not found
    if ! $found; then
        echo "[MISSING] any of hailo-tappas-core / hailo-tappas / tappas-core (system), version: -1"
    fi

    # 4) Always return a key=value
    echo "tappas-core=$version"
}

# Check for Python HailoRT binding
check_hailort_py() {
    local pyhailort_version="-1"
    
    # First check if hailo-all is installed
    hailo_all_ver=$(is_hailo_all_installed)
    
    # Check pip-distribution
    if ver=$(detect_pip_pkg_version "hailort") && [[ -n "$ver" ]]; then
        pyhailort_version="$ver"
        echo "[OK]   pip 'hailort' version: $pyhailort_version"
        
        # Additional test - try to import in the current environment
        if python3 -c 'import hailo' >/dev/null 2>&1; then
            echo "[OK]   Python import 'hailo' succeeded"
        elif python3 -c 'import hailort' >/dev/null 2>&1; then
            # Try to get the version from the module itself
            module_ver=$(python3 -c 'import hailort; print(getattr(hailort, "__version__", "unknown"))' 2>/dev/null)
            if [[ "$module_ver" != "unknown" && -n "$module_ver" ]]; then
                pyhailort_version="$module_ver"
            fi
            echo "[OK]   Python import 'hailort' succeeded, version: $pyhailort_version"
        else
            echo "[WARNING] pip 'hailort' is installed but cannot be imported in current environment"
        fi
    elif [[ -n "$hailo_all_ver" ]]; then
        pyhailort_version="$hailo_all_ver"
        echo "[OK]   pip 'hailort' is part of hailo-all package: $pyhailort_version"
        
        # Check if it can be imported
        if python3 -c 'import hailo' >/dev/null 2>&1; then
            echo "[OK]   Python import 'hailo' succeeded"
        elif python3 -c 'import hailort' >/dev/null 2>&1; then
            echo "[OK]   Python import 'hailort' succeeded, version: $pyhailort_version"
        else
            echo "[WARNING] hailo-all is installed but 'hailort' module cannot be imported"
        fi
    else
        echo "[MISSING] pip 'hailort', version: -1"
        
        # One last try - maybe it's importable but not visible to pip
        if python3 -c 'import hailo' >/dev/null 2>&1; then
            echo "[OK]   Python import 'hailo' succeeded (not from pip)"
            pyhailort_version="unknown"
        elif python3 -c 'import hailort' >/dev/null 2>&1; then
            module_ver=$(python3 -c 'import hailort; print(getattr(hailort, "__version__", "unknown"))' 2>/dev/null)
            if [[ "$module_ver" != "unknown" && -n "$module_ver" ]]; then
                pyhailort_version="$module_ver"
                echo "[OK]   Python import 'hailort' succeeded (not from pip), version: $pyhailort_version"
            else
                echo "[OK]   Python import 'hailort' succeeded but version unknown"
                pyhailort_version="unknown"
            fi
        else
            echo "[MISSING] Python import 'hailort', version: -1"
        fi
    fi
    
    # Return the version
    echo "pyhailort=$pyhailort_version"
}

# Check for TAPPAS Python binding
check_tappas_core_py() {
    local tappas_python_version="-1"
    
    # First check if hailo-all is installed
    hailo_all_ver=$(is_hailo_all_installed)
    
    # Check pip-distribution with multiple possible package names
    found_version=""
    found_pkg=""
    for pkg in "hailo-tappas-core-python-binding" "tappas-core-python-binding" "hailo-tappas-python-binding" "tappas"; do
        if ver=$(detect_pip_pkg_version "$pkg") && [[ -n "$ver" ]]; then
            tappas_python_version="$ver"
            found_version="$ver"
            found_pkg="$pkg"
            echo "[OK]   pip '$pkg' version: $tappas_python_version"
            break
        fi
    done
    
    if [[ -z "$found_version" ]]; then
        if [[ -n "$hailo_all_ver" ]]; then
            tappas_python_version="$hailo_all_ver"
            echo "[OK]   TAPPAS Python binding is part of hailo-all package: $tappas_python_version"
        else
            echo "[MISSING] TAPPAS Python binding pip package, version: -1"
        fi
    fi
    
    # Check if the module can be imported
    if python3 -c 'import hailo_platform' >/dev/null 2>&1; then
        # Try to get version from the module
        module_ver=$(python3 -c 'import hailo_platform; print(getattr(hailo_platform, "__version__", "unknown"))' 2>/dev/null)
        if [[ "$module_ver" != "unknown" && -n "$module_ver" ]]; then
            tappas_python_version="$module_ver"
        fi
        echo "[OK]   Python import 'hailo_platform' succeeded, version: $tappas_python_version"
    else
        if [[ -n "$hailo_all_ver" || -n "$found_version" ]]; then
            echo "[WARNING] TAPPAS Python package is installed but 'hailo_platform' module cannot be imported"
            # Don't reset version to -1 if package is installed
        else
            echo "[MISSING] Python import 'hailo_platform', version: -1"
            tappas_python_version="-1"
        fi
    fi
    
    # Return the version
    echo "tappas-python=$tappas_python_version"
}

# Main function to perform all checks
to_check() {
    echo "=== Hailo Package Detection ==="
    echo ""
    
    # Display all check results for verbose output
    kernel_output=$(check_kernel_module)
    hailort_output=$(check_hailort)
    tappas_output=$(check_tappas_packages) 
    pyhailort_output=$(check_hailort_py)
    tappas_py_output=$(check_tappas_core_py)
    
    # Display all outputs (filtering out the key=value lines)
    echo "Kernel Module Check:"
    echo "$kernel_output" | grep -v "^hailo_pci="
    echo ""
    
    echo "HailoRT Check:"
    echo "$hailort_output" | grep -v "^hailort="
    echo ""
    
    echo "TAPPAS Core Check:"
    echo "$tappas_output" | grep -v "^tappas-core="
    echo ""
    
    echo "Python HailoRT Check:"
    echo "$pyhailort_output" | grep -v "^pyhailort="
    echo ""
    
    echo "Python TAPPAS Check:"
    echo "$tappas_py_output" | grep -v "^tappas-python="
    echo ""
    
    # Extract versions from the last line of each output
    local kernel_version=$(echo "$kernel_output" | grep "^hailo_pci=" | cut -d'=' -f2)
    local hailort_version=$(echo "$hailort_output" | grep "^hailort=" | cut -d'=' -f2)
    local tappas_version=$(echo "$tappas_output" | grep "^tappas-core=" | cut -d'=' -f2)
    local pyhailort_version=$(echo "$pyhailort_output" | grep "^pyhailort=" | cut -d'=' -f2)
    local tappas_py_version=$(echo "$tappas_py_output" | grep "^tappas-python=" | cut -d'=' -f2)
    
    # Print summary
    echo "================================"
    echo "SUMMARY: hailo_pci=$kernel_version hailort=$hailort_version pyhailort=$pyhailort_version tappas-core=$tappas_version tappas-python=$tappas_py_version"
}

# Execute the main function
to_check