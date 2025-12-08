"""
Configuration package for Hailo applications.

This package contains YAML configuration files:
- config.yaml: Main application configuration
- install_config.yaml: Installation configuration
- resources_config.yaml: Resource download definitions
- test_definition_config.yaml: Test configuration
"""

from pathlib import Path

# Expose config directory path for easy access
CONFIG_DIR = Path(__file__).parent

__all__ = ["CONFIG_DIR"]
