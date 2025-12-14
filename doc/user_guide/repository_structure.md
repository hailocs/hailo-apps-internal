# Repository Structure Guide

This document provides an overview of the directory structure for the Hailo Applications repository, explaining the purpose of each key folder and clarifying which directories are tracked by git and which are generated or managed by scripts.

```
hailo-apps-infra/
├── doc/                        # Comprehensive documentation (user & developer guides)
│   ├── user_guide/             # User-facing docs (installation, running apps, config, structure)
│   ├── developer_guide/        # Developer docs (app development, post-process, retraining)
│   └── images/                 # Documentation assets
├── hailo_apps/                 # Main AI application package (Python)
│   ├── config/                 # YAML configs used by installers and apps
│   ├── installation/           # Python-side installers and env helpers
│   ├── postprocess/            # C++ post-processing sources and builds
│   └── python/
│       ├── pipeline_apps/      # Packaged CLI apps (hailo-detect, hailo-tiling, etc.)
│       ├── standalone_apps/    # Extra/experimental apps run directly with python
│       ├── core/               # Shared logic (common utils, gstreamer, trackers, gen-ai)
│       └── gen_ai_utils/       # GenAI helper modules
├── scripts/                    # Shell installers/utilities (install, cleanup, set-env)
├── tests/                      # Pytest-based test suite
├── config/                     # Top-level configs referenced by installers
├── local_resources/            # Local demo assets (not tracked by git)
├── resources -> /usr/local/hailo/resources  # Symlink to shared models/videos store
├── venv_hailo_apps/            # Default virtual environment (created by install.sh)
├── install.sh                  # Main installation script
├── setup_env.sh                # Per-shell environment activation helper
├── pyproject.toml              # Python package configuration and console entrypoints
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