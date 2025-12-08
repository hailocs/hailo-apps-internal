"""
Installation utilities for Hailo applications.

This module provides utilities for:
- Compiling C++ post-processing code
- Downloading resources (models, videos, etc.)
- Post-installation setup
- Environment configuration
"""

from .compile_cpp import main as compile_cpp
from .config_utils import load_and_validate_config, load_config, validate_config
from .download_resources import main as download_resources
from .post_install import main as post_install
from .set_env import main as set_env

__all__ = [
    "compile_cpp",
    "download_resources",
    "load_and_validate_config",
    "load_config",
    "post_install",
    "set_env",
    "validate_config",
]

