# Installation Scripts

This directory contains scripts used specifically for the installation flow of Hailo Apps Infrastructure. These scripts are part of the modular installation system and are called by the main `install.sh` orchestrator.

## Scripts Overview

### Core Scripts

#### `install_helpers.sh`
**Purpose**: Common utility functions for installation scripts

**Functions provided**:
- User and group detection when running with sudo
- File ownership management
- Logging functions (info, error, warning, debug)
- Directory and permission management
- YAML configuration loading

**Usage**: Sourced by other installation scripts, not meant to be run directly.

---

#### `check_prerequisites.sh`
**Purpose**: Validate system requirements before installation

**What it does**:
- Checks if running with sudo
- Detects original user and group
- Validates Hailo PCI driver installation
- Validates HailoRT installation
- Validates TAPPAS core installation
- Checks Python bindings (PyHailoRT, PyTappas)
- Outputs summary line with version information for other scripts

**Usage**:
```bash
sudo ./scripts/installation/check_prerequisites.sh [OPTIONS]
```

**Options**:
- `-v, --verbose`: Show detailed output
- `-h, --help`: Show help message

**Output**: Summary line in format: `SUMMARY: driver=<version> hailort=<version> pyhailort=<version> tappas=<version> pytappas=<version>`

---

#### `setup_venv.sh`
**Purpose**: Create and manage the Python virtual environment

**What it does**:
- Removes existing venv if requested
- Creates new virtual environment with correct options
- Handles architecture-specific settings (system site-packages)
- Cleans up build artifacts
- Validates venv creation

**Usage**:
```bash
sudo ./scripts/installation/setup_venv.sh [OPTIONS]
```

**Options**:
- `-n, --venv-name NAME`: Virtual environment name (default: venv_hailo_apps)
- `--no-system-python`: Don't use system site-packages
- `--remove-existing`: Remove existing virtualenv if it exists
- `-v, --verbose`: Show detailed output
- `-h, --help`: Show help message

---

#### `install_python_packages.sh`
**Purpose**: Install all required Python packages

**What it does**:
- Installs system packages (meson, portaudio19-dev, etc.)
- Upgrades pip, setuptools, wheel
- Installs custom PyHailoRT/PyTappas wheels if provided
- Installs Hailo Python bindings (if missing)
- Installs hailo_apps package in editable mode
- Handles installation errors with helpful messages

**Usage**:
```bash
sudo ./scripts/installation/install_python_packages.sh [OPTIONS]
```

**Options**:
- `-n, --venv-name NAME`: Virtual environment name
- `-ph, --pyhailort PATH`: Path to custom PyHailoRT wheel file
- `-pt, --pytappas PATH`: Path to custom PyTappas wheel file
- `--skip-hailo`: Skip installation of Hailo Python bindings
- `--skip-package`: Skip installation of hailo_apps package
- `--no-install`: Skip all Python package installation
- `-v, --verbose`: Show detailed output
- `-h, --help`: Show help message

---

#### `setup_resources.sh`
**Purpose**: Create and configure resource directories

**What it does**:
- Creates `/usr/local/hailo/resources/` directory structure
- Creates local `resources/` directory
- Creates `.env` file with proper permissions
- Sets correct ownership and permissions (775 for group access)
- Ensures user can write to resource directories

**Usage**:
```bash
sudo ./scripts/installation/setup_resources.sh [OPTIONS]
```

**Options**:
- `--resources-root PATH`: Resources root directory
- `--env-file PATH`: Environment file path
- `-v, --verbose`: Show detailed output
- `-h, --help`: Show help message

---

#### `setup_environment.sh`
**Purpose**: Configure environment variables

**What it does**:
- Runs `hailo-set-env` command to auto-detect and set variables
- Validates environment setup
- Handles configuration errors with helpful messages
- Ensures environment is properly configured for Hailo Apps

**Usage**:
```bash
sudo ./scripts/installation/setup_environment.sh [OPTIONS]
```

**Options**:
- `-n, --venv-name NAME`: Virtual environment name
- `-v, --verbose`: Show detailed output
- `-h, --help`: Show help message

---

#### `run_post_install.sh`
**Purpose**: Run post-installation tasks

**What it does**:
- Fixes resources directory permissions
- Runs `hailo-post-install` which:
  - Downloads resources and models (optional)
  - Compiles C++ postprocess modules
  - Creates symlinks from resources to `/usr/local/hailo/resources`
- Handles post-install errors with helpful messages

**Usage**:
```bash
sudo ./scripts/installation/run_post_install.sh [OPTIONS]
```

**Options**:
- `-n, --venv-name NAME`: Virtual environment name
- `--group GROUP`: Resource group to download
- `--all`: Download all available models/resources
- `--skip-download`: Skip resource download
- `--skip-compile`: Skip C++ compilation
- `-v, --verbose`: Show detailed output
- `-h, --help`: Show help message

---

#### `verify_installation.sh`
**Purpose**: Verify installation completed successfully

**What it does**:
- Checks virtual environment exists and is accessible
- Verifies Python packages are importable
- Checks HailoRT/TAPPAS Python bindings availability
- Validates resources directory setup
- Verifies environment file exists
- Checks C++ postprocess libraries compilation
- Supports JSON output format for automation
- Provides detailed verification report

**Usage**:
```bash
sudo ./scripts/installation/verify_installation.sh [OPTIONS]
```

**Options**:
- `-n, --venv-name NAME`: Virtual environment name
- `--json`: Output results in JSON format
- `-v, --verbose`: Show detailed output
- `-h, --help`: Show help message

---

## Installation Flow

The scripts are executed in the following order by `install.sh`:

1. **check_prerequisites.sh** - Validate system requirements
2. **setup_venv.sh** - Create virtual environment
3. **install_python_packages.sh** - Install Python packages
4. **setup_resources.sh** - Setup resource directories
5. **setup_environment.sh** - Configure environment variables
6. **run_post_install.sh** - Run post-installation tasks
7. **verify_installation.sh** - Verify installation

## Configuration

All scripts use the configuration file located at:
- `hailo_apps/config/install_config.yaml`

This YAML file contains:
- Virtual environment settings
- Resource directory paths
- System packages to install
- Resource directory structure

The configuration is automatically loaded by the `load_config()` function from `install_helpers.sh`.

## Running Individual Scripts

Each script can be run independently for debugging or specific operations:

```bash
# Check prerequisites
sudo ./scripts/installation/check_prerequisites.sh

# Setup venv only
sudo ./scripts/installation/setup_venv.sh -n my_venv

# Install Python packages only
sudo ./scripts/installation/install_python_packages.sh -n my_venv

# Verify installation
sudo ./scripts/installation/verify_installation.sh -n my_venv
```

## Dependencies

- All scripts require sudo privileges
- Scripts depend on `install_helpers.sh` for common functions
- Configuration is loaded from `hailo_apps/config/install_config.yaml`
- Some scripts depend on other scripts in the `scripts/` directory (not in `installation/`):
  - `check_installed_packages.sh` - Used by `check_prerequisites.sh`
  - `hailo_python_installation.sh` - Used by `install_python_packages.sh`

## Error Handling

All scripts include:
- Proper error messages
- Helpful troubleshooting information
- Exit codes for automation
- Fallback mechanisms where appropriate

## See Also

- Main installation script: `install.sh`
- Configuration file: `hailo_apps/config/install_config.yaml`
- Other scripts: `scripts/` (not in `installation/` subdirectory)

