# Repository Structure Guide

This document provides an overview of the directory structure for the Hailo Applications repository, explaining the purpose of each key folder and clarifying which directories are tracked by git and which are generated or managed by scripts.

```
hailo-apps-internal/
├── doc/                        # Comprehensive documentation (user & developer guides)
│   ├── user_guide/             # User-facing documentation (this file, installation, etc.)
│   ├── developer_guide/        # Developer-focused documentation
│   └── images/                 # Images for documentation
├── hailo_apps/                 # Main AI application package (Python)
│   └── python/       # Contains 'apps/' (AI apps) and 'core/' (shared logic)
│       ├── apps/               # Individual AI application folders (detection, pose, etc.)
│       └── core/               # Shared logic, utilities, and GStreamer integration
│           ├── common/         # Foundational utilities (installation, configuration, helpers)
│           ├── gstreamer/      # Reusable GStreamer components and pipelines
│           ├── cpp_postprocess/# C++ post-processing modules for AI outputs
│           └── installation/   # Installation and environment setup utilities
├── scripts/                    # Installation and utility shell scripts
├── tests/                      # Pytest-based test suite
├── config/                     # Configuration files (YAML, etc.)
├── local_resources/            # Local assets, images, and configuration (not tracked by git)
├── hailo_temp_resources/       # Temporary installation packages (not tracked by git)
├── resources                   # Symlink to shared models/videos (see below)
├── venv_hailo_apps/            # Python virtual environment (not tracked by git)
├── hailo_apps.egg-info/        # Python package metadata (generated, not tracked)
├── install.sh                  # Main installation script
├── pyproject.toml              # Python package configuration
```

## Key Directories

### `doc/`
Contains all project documentation, including user guides, developer guides, and architectural overviews.

### `hailo_apps/`
Main Python package for AI applications. Contains:
- **`python/`**:
  - `apps/`: Individual AI application folders (e.g., detection, face_recognition, etc.)
  - `core/`: Shared logic, utilities, and GStreamer integration for apps.
    - `common/`: Foundational utilities (installation, configuration, helpers).
    - `gstreamer/`: Reusable GStreamer components and pipelines.
    - `cpp_postprocess/`: C++ post-processing modules for AI outputs.
    - `installation/`: Installation and environment setup utilities.

### `resources/`
After running the installation script, you will see a `resources` directory in the root of the project. This is a **symbolic link** (symlink) to a system-wide directory, `/usr/local/hailo/resources`.

- **What it is**: A shortcut to a central location for large files needed by the applications (models, videos, assets).
- **Why a symlink**: Avoids duplication of large files across projects. All Hailo applications can share a single pool of models and videos, saving disk space and simplifying resource management.
- **How it's created**: The post install script creates this symlink if it doesn't exist.

### `venv_hailo_apps/`
Python virtual environment for local development. Not tracked by git.

### `scripts/`
Shell scripts for installation, environment setup, and utilities. The main `install.sh` orchestrates many of these scripts.

---

For more details on each application or component, see the respective README files in their directories.