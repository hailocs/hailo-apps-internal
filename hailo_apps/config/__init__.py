"""
Configuration package for Hailo applications.

This package contains YAML configuration files:
- config.yaml: Main configuration (environment, venv, resources, system packages)
- resources_config.yaml: Resource download definitions (models, videos, images, JSON)
- test_definition_config.yaml: Test configuration
"""

from pathlib import Path

# Expose config directory path for easy access
CONFIG_DIR = Path(__file__).parent

__all__ = ["CONFIG_DIR"]
