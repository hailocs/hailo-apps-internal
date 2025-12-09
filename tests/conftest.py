"""
Pytest Configuration and Shared Fixtures for Hailo Apps Tests.

This module provides:
- Configuration parsing utilities
- Shared fixtures for resources, models, videos, etc.
- Test markers for categorization
"""

import os
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pytest
import yaml

# Add repo root to path for imports
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

# ============================================================================
# CONFIGURATION PATHS
# ============================================================================

CONFIG_DIR = REPO_ROOT / "hailo_apps" / "config"
RESOURCES_CONFIG_PATH = CONFIG_DIR / "resources_config.yaml"
POSTPROCESS_MESON_PATH = REPO_ROOT / "hailo_apps" / "postprocess" / "cpp" / "meson.build"

# Import defines after path setup
try:
    from hailo_apps.python.core.common.defines import (
        HAILO8_ARCH,
        HAILO8L_ARCH,
        HAILO10H_ARCH,
        RESOURCES_ROOT_PATH_DEFAULT,
        RESOURCES_MODELS_DIR_NAME,
        RESOURCES_VIDEOS_DIR_NAME,
        RESOURCES_SO_DIR_NAME,
        RESOURCES_JSON_DIR_NAME,
        RESOURCES_PHOTOS_DIR_NAME,
        DEFAULT_DOTENV_PATH,
    )
    from hailo_apps.python.core.common.installation_utils import (
        detect_hailo_arch,
        detect_host_arch,
    )
except ImportError:
    # Fallback defaults if imports fail
    HAILO8_ARCH = "hailo8"
    HAILO8L_ARCH = "hailo8l"
    HAILO10H_ARCH = "hailo10h"
    RESOURCES_ROOT_PATH_DEFAULT = "/usr/local/hailo/resources"
    RESOURCES_MODELS_DIR_NAME = "models"
    RESOURCES_VIDEOS_DIR_NAME = "videos"
    RESOURCES_SO_DIR_NAME = "so"
    RESOURCES_JSON_DIR_NAME = "json"
    RESOURCES_PHOTOS_DIR_NAME = "photos"
    DEFAULT_DOTENV_PATH = "/usr/local/hailo/resources/.env"
    detect_hailo_arch = None
    detect_host_arch = None


# ============================================================================
# PYTEST CONFIGURATION
# ============================================================================

def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line("markers", "sanity: Quick environment sanity checks")
    config.addinivalue_line("markers", "installation: Installation validation tests")
    config.addinivalue_line("markers", "resources: Resource file validation tests")
    config.addinivalue_line("markers", "requires_device: Tests requiring a Hailo device")
    config.addinivalue_line("markers", "requires_gstreamer: Tests requiring GStreamer")


# ============================================================================
# CONFIGURATION PARSING UTILITIES
# ============================================================================

def load_yaml_config(config_path: Path) -> Dict:
    """Load a YAML configuration file.
    
    Args:
        config_path: Path to the YAML file
        
    Returns:
        Parsed YAML as dictionary, or empty dict if file doesn't exist
    """
    if not config_path.exists():
        return {}
    
    with open(config_path, 'r') as f:
        return yaml.safe_load(f) or {}


def parse_resources_config() -> Dict:
    """Parse resources_config.yaml and return structured resource information.
    
    Returns:
        Dictionary with keys: 'videos', 'images', 'apps', where 'apps' contains
        per-app model and json configurations.
    """
    config = load_yaml_config(RESOURCES_CONFIG_PATH)
    if not config:
        return {'videos': [], 'images': [], 'apps': {}}
    
    result = {
        'videos': [],
        'images': [],
        'apps': {}
    }
    
    # Parse videos
    for video in config.get('videos', []):
        if isinstance(video, dict) and video.get('name'):
            result['videos'].append(video['name'])
        elif isinstance(video, str):
            result['videos'].append(video)
    
    # Parse images
    for image in config.get('images', []):
        if isinstance(image, dict) and image.get('name'):
            result['images'].append(image['name'])
        elif isinstance(image, str):
            result['images'].append(image)
    
    # Parse apps (anything that's not videos/images is an app)
    for key, value in config.items():
        if key in ('videos', 'images'):
            continue
        if not isinstance(value, dict):
            continue
        
        app_info = {
            'models': {},  # arch -> {'default': [], 'extra': []}
            'json': []
        }
        
        # Parse models per architecture
        if 'models' in value:
            for arch in [HAILO8_ARCH, HAILO8L_ARCH, HAILO10H_ARCH]:
                if arch not in value['models']:
                    continue
                
                arch_models = value['models'][arch]
                app_info['models'][arch] = {'default': [], 'extra': []}
                
                # Parse default model(s)
                if 'default' in arch_models:
                    default = arch_models['default']
                    if default is None or (isinstance(default, str) and default.lower() == 'none'):
                        pass  # No default model
                    elif isinstance(default, list):
                        for model in default:
                            model_name = _extract_model_name(model)
                            if model_name:
                                app_info['models'][arch]['default'].append(model_name)
                    else:
                        model_name = _extract_model_name(default)
                        if model_name:
                            app_info['models'][arch]['default'].append(model_name)
                
                # Parse extra models
                if 'extra' in arch_models:
                    for model in arch_models.get('extra', []):
                        model_name = _extract_model_name(model)
                        if model_name:
                            app_info['models'][arch]['extra'].append(model_name)
        
        # Parse JSON files
        for json_entry in value.get('json', []):
            if isinstance(json_entry, dict) and json_entry.get('name'):
                app_info['json'].append(json_entry['name'])
            elif isinstance(json_entry, str):
                app_info['json'].append(json_entry)
        
        result['apps'][key] = app_info
    
    return result


def _extract_model_name(model_entry) -> Optional[str]:
    """Extract model name from a model entry (dict or string)."""
    if model_entry is None:
        return None
    if isinstance(model_entry, str):
        if model_entry.lower() == 'none':
            return None
        return model_entry
    if isinstance(model_entry, dict):
        name = model_entry.get('name')
        if name and (not isinstance(name, str) or name.lower() != 'none'):
            return name
    return None


def parse_meson_shared_libraries() -> List[str]:
    """Parse meson.build to extract shared library names.
    
    Returns:
        List of shared library filenames (e.g., ['libyolo_hailortpp_postprocess.so', ...])
    """
    if not POSTPROCESS_MESON_PATH.exists():
        return []
    
    with open(POSTPROCESS_MESON_PATH, 'r') as f:
        content = f.read()
    
    # Match shared_library('name', ...) pattern
    # The pattern captures the library name in the first argument
    pattern = r"shared_library\s*\(\s*['\"]([^'\"]+)['\"]"
    matches = re.findall(pattern, content)
    
    # Convert to .so filename format: libNAME.so
    return [f"lib{name}.so" for name in matches]


def get_all_expected_models(arch: str) -> List[Tuple[str, str]]:
    """Get all expected default models for an architecture.
    
    Args:
        arch: Hailo architecture (hailo8, hailo8l, hailo10h)
        
    Returns:
        List of tuples: (app_name, model_name)
    """
    resources = parse_resources_config()
    models = []
    
    for app_name, app_info in resources['apps'].items():
        if arch in app_info['models']:
            for model_name in app_info['models'][arch].get('default', []):
                models.append((app_name, model_name))
    
    return models


def get_all_expected_json_files() -> List[Tuple[str, str]]:
    """Get all expected JSON files from all apps.
    
    Returns:
        List of tuples: (app_name, json_filename)
    """
    resources = parse_resources_config()
    json_files = []
    
    for app_name, app_info in resources['apps'].items():
        for json_name in app_info.get('json', []):
            json_files.append((app_name, json_name))
    
    return json_files


# ============================================================================
# PYTEST FIXTURES
# ============================================================================

@pytest.fixture(scope="session")
def resources_config() -> Dict:
    """Fixture providing parsed resources configuration."""
    return parse_resources_config()


@pytest.fixture(scope="session")
def expected_videos(resources_config) -> List[str]:
    """Fixture providing list of expected video filenames."""
    return resources_config.get('videos', [])


@pytest.fixture(scope="session")
def expected_images(resources_config) -> List[str]:
    """Fixture providing list of expected image filenames."""
    return resources_config.get('images', [])


@pytest.fixture(scope="session")
def expected_so_files() -> List[str]:
    """Fixture providing list of expected .so filenames from meson.build."""
    return parse_meson_shared_libraries()


@pytest.fixture(scope="session")
def detected_hailo_arch() -> Optional[str]:
    """Fixture providing detected Hailo architecture (or None)."""
    if detect_hailo_arch is None:
        return None
    try:
        return detect_hailo_arch()
    except Exception:
        return None


@pytest.fixture(scope="session")
def detected_host_arch() -> str:
    """Fixture providing detected host architecture."""
    if detect_host_arch is None:
        return "unknown"
    try:
        return detect_host_arch()
    except Exception:
        return "unknown"


@pytest.fixture(scope="session")
def resources_root_path() -> Path:
    """Fixture providing the resources root path."""
    return Path(RESOURCES_ROOT_PATH_DEFAULT)


@pytest.fixture(scope="session")
def repo_resources_symlink() -> Path:
    """Fixture providing the repo resources symlink path."""
    return REPO_ROOT / "resources"


@pytest.fixture(scope="session")
def dotenv_path() -> Path:
    """Fixture providing the .env file path."""
    return Path(DEFAULT_DOTENV_PATH)


@pytest.fixture(scope="session")
def expected_models_for_arch(detected_hailo_arch, resources_config) -> List[Tuple[str, str]]:
    """Fixture providing expected models for the detected architecture.
    
    Returns list of (app_name, model_name) tuples.
    """
    if not detected_hailo_arch:
        return []
    
    models = []
    for app_name, app_info in resources_config['apps'].items():
        if detected_hailo_arch in app_info['models']:
            for model_name in app_info['models'][detected_hailo_arch].get('default', []):
                models.append((app_name, model_name))
    
    return models


@pytest.fixture(scope="session")
def expected_json_files(resources_config) -> List[Tuple[str, str]]:
    """Fixture providing expected JSON files from all apps.
    
    Returns list of (app_name, json_filename) tuples.
    """
    json_files = []
    for app_name, app_info in resources_config['apps'].items():
        for json_name in app_info.get('json', []):
            json_files.append((app_name, json_name))
    return json_files

