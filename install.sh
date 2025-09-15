#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

DOWNLOAD_GROUP="default"
VENV_NAME="venv_hailo_apps"
PYHAILORT_PATH=""
PYTAPPAS_PATH=""
NO_INSTALL=false
ENV_FILE="${SCRIPT_DIR}/.env"


as_original_user() {
  if [[ ${EUID:-$(id -u)} -eq 0 && -n "${SUDO_USER:-}" ]]; then
    sudo -n -u "$SUDO_USER" -H -- "$@"
  else
    "$@"
  fi
}

show_help() {
    cat << EOF
Usage: $0 [OPTIONS]

Install Hailo Apps Infrastructure with virtual environment setup.

OPTIONS:
    -n, --venv-name NAME        Set virtual environment name (default: venv_hailo_apps)
    -ph, --pyhailort PATH       Path to custom PyHailoRT wheel file
    -pt, --pytappas PATH        Path to custom PyTappas wheel file
    --all                       Download all available models/resources
    -x, --no-install           Skip installation of Python packages
    -h, --help                  Show this help message and exit

EXAMPLES:
    $0                          # Basic installation with default settings
    $0 -n my_venv               # Use custom virtual environment name
    $0 --all                    # Install with all models/resources
    $0 -x                       # Skip Python package installation
    $0 -ph /path/to/pyhailort.whl -pt /path/to/pytappas.whl  # Use custom wheel files

DESCRIPTION:
    This script sets up a Python virtual environment for Hailo Apps Infrastructure.
    It checks for required Hailo components (driver, HailoRT, TAPPAS) and installs
    missing Python bindings in the virtual environment.

    The script will:
    1. Check installed Hailo components
    2. Create/recreate virtual environment
    3. Install required Python packages
    4. Download models and resources
    5. Run post-installation setup

REQUIREMENTS:
    - Hailo PCI driver must be installed
    - HailoRT must be installed  
    - TAPPAS core must be installed
    
    Use 'sudo ./scripts/hailo_installer.sh' to install missing components.

EOF
}

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
    -x | --no-install)
      NO_INSTALL=true
      echo "Skipping installation of Python packages."
      shift
      ;;
    -h|--help)
      show_help
      exit 0
      ;;
    *)
      echo "Unknown option: $1"
      echo "Use -h or --help for usage information."
      exit 1
      ;;
  esac
done

SUMMARY_LINE=$(
  sudo -u "${SUDO_USER:-$USER}" -H ./scripts/check_installed_packages.sh 2>&1 \
    | sed -n 's/^SUMMARY: //p'
)

if [[ -z "$SUMMARY_LINE" ]]; then
  echo "❌ Could not find SUMMARY line" >&2
  exit 1
fi

IFS=' ' read -r -a pairs <<< "$SUMMARY_LINE"

DRIVER_VERSION="${pairs[0]#*=}"
HAILORT_VERSION="${pairs[1]#*=}"
PYHAILORT_VERSION="${pairs[2]#*=}"
TAPPAS_CORE_VERSION="${pairs[3]#*=}"
PYTAPPAS_VERSION="${pairs[4]#*=}"

INSTALL_HAILORT=false
INSTALL_TAPPAS_CORE=false

if [[ "$DRIVER_VERSION" == "-1" ]]; then
  echo "❌ Hailo PCI driver is not installed. Please install it first."
  echo "To install the driver, run:"
  echo "    sudo ./scripts/hailo_installer.sh"
  exit 1
fi
if [[ "$HAILORT_VERSION" == "-1" ]]; then
  echo "❌ HailoRT is not installed. Please install it first."
  echo "To install the driver, run:"
  echo "    sudo ./scripts/hailo_installer.sh"
  exit 1
fi
if [[ "$TAPPAS_CORE_VERSION" == "-1" ]]; then
  echo "❌ TAPPAS is not installed. Please install it first."
  echo "To install the driver, run:"
  echo "    sudo ./scripts/hailo_installer.sh"
  exit 1
fi

if [[ "$PYHAILORT_VERSION" == "-1" ]]; then
  echo "❌ Python HailoRT binding is not installed."
  echo "Will be installed in the virtualenv."
  INSTALL_HAILORT=true
fi
if [[ "$PYTAPPAS_VERSION" == "-1" ]]; then
  echo "❌ Python TAPPAS binding is not installed."
  echo "Will be installed in the virtualenv."
  INSTALL_TAPPAS_CORE=true
fi

if [[ "$NO_INSTALL" = true ]]; then
  echo "Skipping installation of Python packages."
  INSTALL_HAILORT=false
  INSTALL_TAPPAS_CORE=false
fi

VENV_PATH="${SCRIPT_DIR}/${VENV_NAME}"

if [[ -d "${VENV_PATH}" ]]; then
  echo "🗑️  Removing existing virtualenv at ${VENV_PATH}"
  rm -rf "${VENV_PATH}"
fi

echo "🧹 Cleaning up build artifacts..."
find . -name "*.egg-info" -type d -exec rm -rf {} + 2>/dev/null || true
rm -rf build/ dist/ 2>/dev/null || true
echo "✅ Build artifacts cleaned"

# Remove existing .env file if it exists
if [[ -f "${ENV_FILE}" ]]; then
  echo "🗑️  Removing existing .env file at ${ENV_FILE}"
  as_original_user rm -f "${ENV_FILE}"
fi

# Create .env file with proper ownership and permissions
as_original_user touch "${ENV_FILE}"
as_original_user chmod 644 "${ENV_FILE}"
echo "✅ Created .env file at ${ENV_FILE}"

sudo apt-get install -y meson
sudo apt install python3-gi python3-gi-cairo

echo "🌱 Creating virtualenv '${VENV_NAME}' (with system site-packages)…"
python3 -m venv --system-site-packages "${VENV_PATH}"

if [[ ! -f "${VENV_PATH}/bin/activate" ]]; then
  echo "❌ Could not find activate at ${VENV_PATH}/bin/activate"
  exit 1
fi

echo "🔌 Activating venv: ${VENV_NAME}"
source "${VENV_PATH}/bin/activate"

if [[ -n "$PYHAILORT_PATH" ]]; then
  echo "Using custom HailoRT Python binding path: $PYHAILORT_PATH"
  if [[ ! -f "$PYHAILORT_PATH" ]]; then
    echo "❌ HailoRT Python binding not found at $PYHAILORT_PATH"
    exit 1
  fi
  pip install "$PYHAILORT_PATH"
  INSTALL_HAILORT=false
fi
if [[ -n "$PYTAPPAS_PATH" ]]; then
  echo "Using custom TAPPAS Python binding path: $PYTAPPAS_PATH"
  if [[ ! -f "$PYTAPPAS_PATH" ]]; then
    echo "❌ TAPPAS Python binding not found at $PYTAPPAS_PATH"
    exit 1
  fi
  pip install "$PYTAPPAS_PATH"
  INSTALL_TAPPAS_CORE=false
fi

echo "📦 Installing Python Hailo packages…"
FLAGS=""
if [[ "$INSTALL_TAPPAS_CORE" = true ]]; then
  echo "Installing TAPPAS core Python binding"
  FLAGS="--tappas-core-version=${TAPPAS_CORE_VERSION}"
fi
if [[ "$INSTALL_HAILORT" = true ]]; then
  echo "Installing HailoRT Python binding"
  FLAGS="${FLAGS} --hailort-version=${HAILORT_VERSION}"
fi

if [[ -z "$FLAGS" ]]; then
  echo "No Hailo Python packages to install."
else
  echo "Installing Hailo Python packages with flags: ${FLAGS}"
  ./scripts/hailo_python_installation.sh ${FLAGS}
fi

python3 -m pip install --upgrade pip setuptools wheel

echo "📦 Installing package (editable + post-install)…"
pip install -e .

echo "🔧 Running post-install script…"

hailo-post-install --group "$DOWNLOAD_GROUP"

echo "✅ All done! Your package is now in '${VENV_NAME}'."
echo "source setup_env.sh to setup the environment"