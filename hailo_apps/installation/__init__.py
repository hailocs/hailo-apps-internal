"""
Installation utilities for Hailo applications.

This module provides utilities for:
- Compiling C++ post-processing code
- Downloading resources (models, videos, etc.)
- Post-installation setup
- Environment configuration
"""

from .compile_cpp import main as compile_cpp
from .download_resources import main as download_resources
from .post_install import main as post_install
from .set_env import main as set_env

# Re-export config_manager functions for convenience
from hailo_apps.config.config_manager import (
    get_main_config,
    get_resources_config,
    get_available_apps,
    get_model_names,
    get_default_model_name,
    is_gen_ai_app,
)

__all__ = [
    "compile_cpp",
    "download_resources",
    "get_available_apps",
    "get_main_config",
    "get_resources_config",
    "get_model_names",
    "get_default_model_name",
    "is_gen_ai_app",
    "post_install",
    "set_env",
]
