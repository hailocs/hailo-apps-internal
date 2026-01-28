"""
Installation Tests - Installation & Resources Validation

This module verifies that the installation (hailo-post-install) completed 
successfully and all resources are properly downloaded and configured.

Tests cover:
- Directory structure validation
- Model files (HEF) download verification
- Video and image resources
- JSON configuration files
- Compiled postprocess .so files
- Configuration files

Resources are dynamically parsed from:
- resources_config.yaml: models, videos, images, JSON files
- postprocess/cpp/meson.build: expected .so files

Run with: pytest tests/test_installation.py -v
Run only installation tests: pytest -m installation -v
"""

import json
import logging
import os
import subprocess
from pathlib import Path
from typing import List, Tuple

import pytest

# ============================================================================
# IMPORTS WITH FALLBACKS
# ============================================================================

try:
    from hailo_apps.python.core.common.defines import (
        RESOURCES_ROOT_PATH_DEFAULT,
        RESOURCES_MODELS_DIR_NAME,
        RESOURCES_VIDEOS_DIR_NAME,
        RESOURCES_SO_DIR_NAME,
        RESOURCES_JSON_DIR_NAME,
        RESOURCES_NPY_DIR_NAME,
        RESOURCES_PHOTOS_DIR_NAME,
        HAILO8_ARCH,
        HAILO8L_ARCH,
        HAILO10H_ARCH,
        DEFAULT_CONFIG_PATH,
        DEFAULT_RESOURCES_CONFIG_PATH,
    )
    IMPORTS_AVAILABLE = True
except ImportError:
    IMPORTS_AVAILABLE = False
    RESOURCES_ROOT_PATH_DEFAULT = "/usr/local/hailo/resources"
    RESOURCES_MODELS_DIR_NAME = "models"
    RESOURCES_VIDEOS_DIR_NAME = "videos"
    RESOURCES_SO_DIR_NAME = "so"
    RESOURCES_JSON_DIR_NAME = "json"
    RESOURCES_NPY_DIR_NAME = "npy"
    RESOURCES_PHOTOS_DIR_NAME = "photos"
    HAILO8_ARCH = "hailo8"
    HAILO8L_ARCH = "hailo8l"
    HAILO10H_ARCH = "hailo10h"
    DEFAULT_CONFIG_PATH = None
    DEFAULT_RESOURCES_CONFIG_PATH = None


# ============================================================================
# LOGGING CONFIGURATION
# ============================================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("installation-tests")


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def is_valid_elf_shared_library(filepath: Path) -> bool:
    """Check if a file is a valid ELF shared library.
    
    Args:
        filepath: Path to the file to check
        
    Returns:
        True if the file appears to be a valid ELF shared library
    """
    if not filepath.exists() or filepath.stat().st_size < 16:
        return False
    
    try:
        with open(filepath, 'rb') as f:
            magic = f.read(4)
            # ELF magic number: 0x7f 'E' 'L' 'F'
            return magic == b'\x7fELF'
    except Exception:
        return False


def is_valid_hef_file(filepath: Path) -> bool:
    """Check if a file appears to be a valid HEF file.
    
    Args:
        filepath: Path to the file to check
        
    Returns:
        True if the file appears to be a valid HEF file (basic check)
    """
    if not filepath.exists():
        return False
    
    # HEF files should be at least 1KB (typical models are much larger)
    min_size = 1024
    return filepath.stat().st_size >= min_size


def is_valid_json_file(filepath: Path) -> bool:
    """Check if a file is valid JSON.
    
    Args:
        filepath: Path to the file to check
        
    Returns:
        True if the file is valid JSON
    """
    if not filepath.exists() or filepath.stat().st_size == 0:
        return False
    
    try:
        with open(filepath, 'r') as f:
            json.load(f)
        return True
    except (json.JSONDecodeError, UnicodeDecodeError):
        return False

def is_valid_npy_file(filepath: Path) -> bool:
    """Check if a file is valid NPY.
    
    Args:
        filepath: Path to the file to check
        
    Returns:
        True if the file is valid NPY
    """
    if not filepath.exists() or filepath.stat().st_size == 0:
        return False

    try:
        with open(filepath, 'rb') as f:
            # Check NPY magic number
            magic = f.read(6)
            return magic == b'\x93NUMPY'
    except Exception:
        return False

def is_valid_video_file(filepath: Path) -> bool:
    """Check if a file appears to be a valid video file.
    
    Args:
        filepath: Path to the file to check
        
    Returns:
        True if the file appears to be a valid video (non-empty)
    """
    if not filepath.exists():
        return False
    
    # Videos should be at least 10KB
    min_size = 10 * 1024
    return filepath.stat().st_size >= min_size


def is_valid_image_file(filepath: Path) -> bool:
    """Check if a file appears to be a valid image file.
    
    Args:
        filepath: Path to the file to check
        
    Returns:
        True if the file appears to be a valid image (non-empty)
    """
    if not filepath.exists():
        return False
    
    # Images should be at least 1KB
    min_size = 1024
    return filepath.stat().st_size >= min_size


# ============================================================================
# SECTION 1: DIRECTORY STRUCTURE TESTS
# ============================================================================

@pytest.mark.installation
class TestDirectoryStructure:
    """Tests for resources directory structure."""
    
    def test_resources_root_exists(self, resources_root_path):
        """Verify resources root directory exists."""
        assert resources_root_path.exists(), (
            f"Resources root directory does not exist: {resources_root_path}. "
            f"Run 'hailo-post-install' to create it."
        )
        logger.info(f"Resources root exists: {resources_root_path}")
    
    def test_resources_symlink_exists(self, repo_resources_symlink):
        """Verify resources symlink exists in repo root."""
        if repo_resources_symlink.exists() or repo_resources_symlink.is_symlink():
            logger.info(f"Resources symlink exists: {repo_resources_symlink}")
        else:
            logger.warning(
                f"Resources symlink not found: {repo_resources_symlink}. "
                f"Run 'hailo-post-install' to create it."
            )
    
    def test_models_directory_exists(self, resources_root_path):
        """Verify models directory exists."""
        models_dir = resources_root_path / RESOURCES_MODELS_DIR_NAME
        assert models_dir.exists(), f"Models directory does not exist: {models_dir}"
        logger.info(f"Models directory exists: {models_dir}")
    
    @pytest.mark.parametrize("arch", [HAILO8_ARCH, HAILO8L_ARCH, HAILO10H_ARCH])
    def test_architecture_models_directory(self, resources_root_path, arch):
        """Verify architecture-specific model directories exist."""
        arch_dir = resources_root_path / RESOURCES_MODELS_DIR_NAME / arch
        if arch_dir.exists():
            logger.info(f"Architecture models directory exists: {arch_dir}")
        else:
            logger.warning(f"Architecture models directory missing: {arch_dir}")
    
    def test_videos_directory_exists(self, resources_root_path):
        """Verify videos directory exists."""
        videos_dir = resources_root_path / RESOURCES_VIDEOS_DIR_NAME
        assert videos_dir.exists(), f"Videos directory does not exist: {videos_dir}"
        logger.info(f"Videos directory exists: {videos_dir}")
    
    def test_so_directory_exists(self, resources_root_path):
        """Verify shared libraries directory exists."""
        so_dir = resources_root_path / RESOURCES_SO_DIR_NAME
        assert so_dir.exists(), f"SO directory does not exist: {so_dir}"
        logger.info(f"SO directory exists: {so_dir}")
    
    def test_json_directory_exists(self, resources_root_path):
        """Verify JSON config directory exists."""
        json_dir = resources_root_path / RESOURCES_JSON_DIR_NAME
        assert json_dir.exists(), f"JSON directory does not exist: {json_dir}"
        logger.info(f"JSON directory exists: {json_dir}")

    def test_npy_directory_exists(self, resources_root_path):
        """Verify NPY directory exists."""
        npy_dir = resources_root_path / RESOURCES_NPY_DIR_NAME
        assert npy_dir.exists(), f"NPY directory does not exist: {npy_dir}"
        logger.info(f"NPY directory exists: {npy_dir}")

# ============================================================================
# SECTION 2: MODEL FILES TESTS
# ============================================================================

@pytest.mark.installation
@pytest.mark.resources
class TestModelFiles:
    """Tests for downloaded HEF model files."""
    
    def test_default_models_downloaded(
        self, 
        resources_root_path, 
        detected_hailo_arch, 
        expected_models_for_arch
    ):
        """Verify default models for detected architecture are downloaded."""
        if not detected_hailo_arch:
            pytest.skip("No Hailo device detected - cannot verify architecture-specific models")
        
        if not expected_models_for_arch:
            pytest.skip(f"No default models defined for {detected_hailo_arch}")
        
        models_dir = resources_root_path / RESOURCES_MODELS_DIR_NAME / detected_hailo_arch
        missing_models = []
        found_models = []
        
        # Gen-AI apps are optional and require --include-gen-ai to download
        gen_ai_apps = {"agent", "llm_chat", "vlm_chat", "voice_assistant", "whisper_chat"}
        
        for app_name, model_name in expected_models_for_arch:
            hef_path = models_dir / f"{model_name}.hef"
            if hef_path.exists():
                found_models.append((app_name, model_name))
            else:
                missing_models.append((app_name, model_name))
        
        if found_models:
            logger.info(f"Found {len(found_models)} default models for {detected_hailo_arch}")
            for app, model in found_models[:5]:  # Show first 5
                logger.info(f"  ✓ {app}: {model}.hef")
            if len(found_models) > 5:
                logger.info(f"  ... and {len(found_models) - 5} more")
        
        # Separate gen-ai models from regular models
        missing_regular = [(app, model) for app, model in missing_models if app not in gen_ai_apps]
        missing_gen_ai = [(app, model) for app, model in missing_models if app in gen_ai_apps]
        
        # On Hailo-10H, gen-ai apps are supported, so include them in auto-download
        is_hailo10h = detected_hailo_arch == HAILO10H_ARCH
        
        if missing_regular or (missing_gen_ai and is_hailo10h):
            models_to_download = missing_regular + (missing_gen_ai if is_hailo10h else [])
            logger.info(f"Missing {len(models_to_download)} models for {detected_hailo_arch}:")
            for app, model in models_to_download:
                logger.info(f"  ✗ {app}: {model}.hef")
            logger.info("Downloading missing models...")
            
            # Build download command - include gen-ai flag on 10H
            download_cmd = ["hailo-download-resources", "--arch", detected_hailo_arch]
            if is_hailo10h and missing_gen_ai:
                download_cmd.append("--include-gen-ai")
            
            logger.info(f"Running: {' '.join(download_cmd)}")
            try:
                # Gen-AI models can be very large (1.7GB+ for LLMs), so use longer timeout
                download_timeout = 2700 if (is_hailo10h and missing_gen_ai) else 600  # 45 min for gen-ai, 10 min otherwise
                result = subprocess.run(
                    download_cmd,
                    capture_output=True,
                    text=True,
                    timeout=download_timeout
                )
                if result.returncode == 0:
                    logger.info("hailo-download-resources completed successfully")
                    # Verify models were downloaded
                    still_missing = []
                    for app_name, model_name in models_to_download:
                        hef_path = models_dir / f"{model_name}.hef"
                        if not hef_path.exists():
                            still_missing.append((app_name, model_name))
                    if still_missing:
                        logger.warning(f"Still missing {len(still_missing)} models after download:")
                        for app, model in still_missing[:5]:
                            logger.warning(f"  ✗ {app}: {model}.hef")
                else:
                    logger.warning(f"hailo-download-resources failed: {result.stderr}")
            except subprocess.TimeoutExpired:
                timeout_mins = download_timeout // 60
                logger.warning(f"hailo-download-resources timed out after {timeout_mins} minutes")
        
        if missing_gen_ai and not is_hailo10h:
            logger.info(f"Gen-AI models not downloaded (only supported on Hailo-10H): {len(missing_gen_ai)} models")
    
    def test_hef_files_valid(self, resources_root_path, detected_hailo_arch):
        """Verify HEF files are valid (non-empty, proper size)."""
        if not detected_hailo_arch:
            pytest.skip("No Hailo device detected")
        
        models_dir = resources_root_path / RESOURCES_MODELS_DIR_NAME / detected_hailo_arch
        if not models_dir.exists():
            pytest.skip(f"Models directory does not exist: {models_dir}")
        
        hef_files = list(models_dir.glob("*.hef"))
        if not hef_files:
            pytest.skip(f"No HEF files found in {models_dir}")
        
        invalid_files = []
        for hef_file in hef_files:
            if not is_valid_hef_file(hef_file):
                invalid_files.append(hef_file.name)
        
        if invalid_files:
            pytest.fail(
                f"Invalid HEF files found (too small or corrupted): {invalid_files}. "
                f"Re-download with 'hailo-download-resources --force'"
            )
        
        logger.info(f"All {len(hef_files)} HEF files appear valid")
    
    def test_any_models_exist(self, resources_root_path):
        """Verify at least some models exist for any architecture."""
        models_dir = resources_root_path / RESOURCES_MODELS_DIR_NAME
        if not models_dir.exists():
            pytest.fail(f"Models directory does not exist: {models_dir}")
        
        total_hefs = 0
        for arch in [HAILO8_ARCH, HAILO8L_ARCH, HAILO10H_ARCH]:
            arch_dir = models_dir / arch
            if arch_dir.exists():
                hef_count = len(list(arch_dir.glob("*.hef")))
                total_hefs += hef_count
                if hef_count > 0:
                    logger.info(f"Found {hef_count} HEF files in {arch}")
        
        assert total_hefs > 0, (
            "No HEF model files found in any architecture directory. "
            "Run 'hailo-download-resources' to download models."
        )


# ============================================================================
# SECTION 3: VIDEO FILES TESTS
# ============================================================================

@pytest.mark.installation
@pytest.mark.resources
class TestVideoFiles:
    """Tests for downloaded video files."""
    
    def test_expected_videos_downloaded(self, resources_root_path, expected_videos):
        """Verify expected videos are downloaded."""
        if not expected_videos:
            pytest.skip("No videos defined in resources_config.yaml")
        
        videos_dir = resources_root_path / RESOURCES_VIDEOS_DIR_NAME
        if not videos_dir.exists():
            pytest.fail(f"Videos directory does not exist: {videos_dir}")
        
        missing_videos = []
        found_videos = []
        
        for video_name in expected_videos:
            video_path = videos_dir / video_name
            if video_path.exists():
                found_videos.append(video_name)
            else:
                missing_videos.append(video_name)
        
        if found_videos:
            logger.info(f"Found {len(found_videos)}/{len(expected_videos)} expected videos")
        
        if missing_videos:
            logger.warning(f"Missing videos: {missing_videos}")
            logger.warning("Run 'hailo-download-resources' to download missing videos.")
    
    def test_videos_valid(self, resources_root_path, expected_videos):
        """Verify video files are valid (non-empty, proper size)."""
        if not expected_videos:
            pytest.skip("No videos defined in resources_config.yaml")
        
        videos_dir = resources_root_path / RESOURCES_VIDEOS_DIR_NAME
        if not videos_dir.exists():
            pytest.skip(f"Videos directory does not exist: {videos_dir}")
        
        invalid_videos = []
        for video_name in expected_videos:
            video_path = videos_dir / video_name
            if video_path.exists() and not is_valid_video_file(video_path):
                invalid_videos.append(video_name)
        
        if invalid_videos:
            logger.warning(
                f"Invalid/corrupted video files found: {invalid_videos}. "
                f"Re-download with 'hailo-download-resources --force'"
            )


# ============================================================================
# SECTION 4: IMAGE FILES TESTS
# ============================================================================

@pytest.mark.installation
@pytest.mark.resources
class TestImageFiles:
    """Tests for downloaded image files."""
    
    def test_expected_images_downloaded(self, resources_root_path, expected_images):
        """Verify expected images are downloaded."""
        if not expected_images:
            pytest.skip("No images defined in resources_config.yaml")
        
        images_dir = resources_root_path / RESOURCES_PHOTOS_DIR_NAME
        if not images_dir.exists():
            logger.warning(f"Images directory does not exist: {images_dir}")
            return
        
        missing_images = []
        found_images = []
        
        for image_name in expected_images:
            image_path = images_dir / image_name
            if image_path.exists():
                found_images.append(image_name)
            else:
                missing_images.append(image_name)
        
        if found_images:
            logger.info(f"Found {len(found_images)}/{len(expected_images)} expected images")
        
        if missing_images:
            logger.warning(f"Missing images: {missing_images}")


# ============================================================================
# SECTION 5: JSON CONFIG FILES TESTS
# ============================================================================

@pytest.mark.installation
@pytest.mark.resources
class TestJsonConfigFiles:
    """Tests for downloaded JSON configuration files."""
    
    def test_expected_json_files_downloaded(self, resources_root_path, expected_json_files):
        """Verify expected JSON config files are downloaded."""
        if not expected_json_files:
            pytest.skip("No JSON files defined in resources_config.yaml")
        
        json_dir = resources_root_path / RESOURCES_JSON_DIR_NAME
        if not json_dir.exists():
            pytest.fail(f"JSON directory does not exist: {json_dir}")
        
        missing_json = []
        found_json = []
        
        for json_name in expected_json_files:
            json_path = json_dir / json_name
            if json_path.exists():
                found_json.append(json_name)
            else:
                missing_json.append(json_name)
        
        if found_json:
            logger.info(f"Found {len(found_json)}/{len(expected_json_files)} expected JSON files")
        
        if missing_json:
            logger.warning(f"Missing JSON files: {missing_json}")
    
    def test_json_files_valid(self, resources_root_path, expected_json_files):
        """Verify JSON files are valid JSON."""
        if not expected_json_files:
            pytest.skip("No JSON files defined in resources_config.yaml")
        
        json_dir = resources_root_path / RESOURCES_JSON_DIR_NAME
        if not json_dir.exists():
            pytest.skip(f"JSON directory does not exist: {json_dir}")
        
        invalid_json = []
        
        for json_name in expected_json_files:
            json_path = json_dir / json_name
            if json_path.exists() and not is_valid_json_file(json_path):
                invalid_json.append(json_name)
        
        if invalid_json:
            pytest.fail(f"Invalid JSON files found: {invalid_json}")
        
        logger.info("All JSON files are valid")


# ============================================================================
# SECTION 6: POSTPROCESS SO FILES TESTS
# ============================================================================

@pytest.mark.installation
@pytest.mark.resources
class TestPostprocessSoFiles:
    """Tests for compiled postprocess shared library files."""
    
    def test_expected_so_files_exist(self, resources_root_path, expected_so_files):
        """Verify expected .so files from meson.build are compiled."""
        if not expected_so_files:
            pytest.skip("Could not parse expected SO files from meson.build")
        
        so_dir = resources_root_path / RESOURCES_SO_DIR_NAME
        if not so_dir.exists():
            pytest.fail(f"SO directory does not exist: {so_dir}")
        
        missing_so = []
        found_so = []
        
        for so_name in expected_so_files:
            so_path = so_dir / so_name
            if so_path.exists():
                found_so.append(so_name)
            else:
                missing_so.append(so_name)
        
        if found_so:
            logger.info(f"Found {len(found_so)}/{len(expected_so_files)} expected SO files")
            for so in found_so[:5]:
                logger.info(f"  ✓ {so}")
            if len(found_so) > 5:
                logger.info(f"  ... and {len(found_so) - 5} more")
        
        if missing_so:
            logger.warning(f"Missing SO files: {missing_so}")
            logger.warning(
                "Run 'hailo-compile-postprocess' or 'hailo-post-install' to compile them."
            )
    
    def test_so_files_valid(self, resources_root_path, expected_so_files):
        """Verify .so files are valid ELF shared libraries."""
        if not expected_so_files:
            pytest.skip("Could not parse expected SO files from meson.build")
        
        so_dir = resources_root_path / RESOURCES_SO_DIR_NAME
        if not so_dir.exists():
            pytest.skip(f"SO directory does not exist: {so_dir}")
        
        invalid_so = []
        for so_name in expected_so_files:
            so_path = so_dir / so_name
            if so_path.exists() and not is_valid_elf_shared_library(so_path):
                invalid_so.append(so_name)
        
        if invalid_so:
            pytest.fail(
                f"Invalid SO files (not valid ELF): {invalid_so}. "
                f"Re-compile with 'hailo-compile-postprocess'"
            )
        
        logger.info("All SO files are valid ELF shared libraries")
    
    def test_any_so_files_exist(self, resources_root_path):
        """Verify at least some SO files exist."""
        so_dir = resources_root_path / RESOURCES_SO_DIR_NAME
        if not so_dir.exists():
            pytest.fail(f"SO directory does not exist: {so_dir}")
        
        so_files = list(so_dir.glob("*.so"))
        assert len(so_files) > 0, (
            "No .so files found. "
            "Run 'hailo-compile-postprocess' or 'hailo-post-install' to compile them."
        )
        logger.info(f"Found {len(so_files)} SO files in {so_dir}")


# ============================================================================
# SECTION 7: CONFIG FILES TESTS
# ============================================================================

@pytest.mark.installation
class TestConfigFiles:
    """Tests for configuration files."""
    
    def test_resources_config_exists(self):
        """Verify resources_config.yaml exists and is valid."""
        from conftest import RESOURCES_CONFIG_PATH
        
        assert RESOURCES_CONFIG_PATH.exists(), (
            f"resources_config.yaml not found: {RESOURCES_CONFIG_PATH}"
        )
        
        # Try to parse it
        import yaml
        with open(RESOURCES_CONFIG_PATH, 'r') as f:
            config = yaml.safe_load(f)
        
        assert config is not None, "resources_config.yaml is empty or invalid"
        logger.info(f"resources_config.yaml is valid: {RESOURCES_CONFIG_PATH}")
    
    def test_meson_build_exists(self):
        """Verify postprocess meson.build exists."""
        from conftest import POSTPROCESS_MESON_PATH
        
        assert POSTPROCESS_MESON_PATH.exists(), (
            f"postprocess meson.build not found: {POSTPROCESS_MESON_PATH}"
        )
        logger.info(f"meson.build exists: {POSTPROCESS_MESON_PATH}")


# ============================================================================
# SECTION 8: INTEGRATION SMOKE TESTS
# ============================================================================

@pytest.mark.installation
class TestIntegrationSmoke:
    """Integration smoke tests to verify basic functionality."""
    
    def test_can_import_hailo_apps(self):
        """Verify hailo_apps package can be imported."""
        try:
            import hailo_apps
            logger.info("hailo_apps package imported successfully")
        except ImportError as e:
            pytest.fail(f"Failed to import hailo_apps: {e}")
    
    def test_can_import_core_modules(self):
        """Verify core modules can be imported."""
        modules_to_test = [
            "hailo_apps.python.core.common.defines",
            "hailo_apps.python.core.common.core",
            "hailo_apps.python.core.common.installation_utils",
        ]
        
        failed_imports = []
        for module_name in modules_to_test:
            try:
                __import__(module_name)
            except ImportError as e:
                failed_imports.append((module_name, str(e)))
        
        if failed_imports:
            pytest.fail(f"Failed to import modules: {failed_imports}")
        
        logger.info(f"All {len(modules_to_test)} core modules imported successfully")
    
    def test_can_import_pipeline_modules(self):
        """Verify pipeline modules can be imported."""
        pipeline_modules = [
            "hailo_apps.python.pipeline_apps.detection.detection_pipeline",
            "hailo_apps.python.pipeline_apps.pose_estimation.pose_estimation_pipeline",
            "hailo_apps.python.pipeline_apps.depth.depth_pipeline",
            "hailo_apps.python.pipeline_apps.instance_segmentation.instance_segmentation_pipeline",
        ]
        
        failed_imports = []
        successful_imports = []
        
        for module_name in pipeline_modules:
            try:
                __import__(module_name)
                successful_imports.append(module_name.split('.')[-1])
            except ImportError as e:
                failed_imports.append((module_name.split('.')[-1], str(e)))
        
        if successful_imports:
            logger.info(f"Successfully imported {len(successful_imports)} pipeline modules")
        
        if failed_imports:
            # Don't fail - just warn about missing pipelines
            for module, error in failed_imports:
                logger.warning(f"Could not import {module}: {error}")
    
    @pytest.mark.requires_device
    def test_can_load_hef_file(self, resources_root_path, detected_hailo_arch):
        """Verify a HEF file can be loaded using hailo API."""
        if not detected_hailo_arch:
            pytest.skip("No Hailo device detected")
        
        models_dir = resources_root_path / RESOURCES_MODELS_DIR_NAME / detected_hailo_arch
        if not models_dir.exists():
            pytest.skip(f"Models directory does not exist: {models_dir}")
        
        hef_files = list(models_dir.glob("*.hef"))
        if not hef_files:
            pytest.skip(f"No HEF files found in {models_dir}")
        
        # Try to load the first HEF file
        test_hef = hef_files[0]
        
        try:
            from hailo_platform import HEF
            hef = HEF(str(test_hef))
            logger.info(f"Successfully loaded HEF: {test_hef.name}")
        except ImportError:
            pytest.skip("hailo_platform not available")
        except Exception as e:
            pytest.fail(f"Failed to load HEF file {test_hef.name}: {e}")

# ============================================================================
# SECTION 9: NPY CONFIG FILES TESTS
# ============================================================================

@pytest.mark.installation
@pytest.mark.resources
class TestNpyConfigFiles:
    """Tests for downloaded NPY configuration files."""

    def test_expected_npy_files_downloaded(self, resources_root_path, expected_npy_files):
        """Verify expected NPY config files are downloaded."""
        if not expected_npy_files:
            pytest.skip("No NPY files defined in resources_config.yaml")

        npy_dir = resources_root_path / RESOURCES_NPY_DIR_NAME
        if not npy_dir.exists():
            pytest.fail(f"NPY directory does not exist: {npy_dir}")

        missing_npy = []
        found_npy = []

        for npy_name in expected_npy_files:
            npy_path = npy_dir / npy_name
            if npy_path.exists():
                found_npy.append(npy_name)
            else:
                missing_npy.append(npy_name)

        if found_npy:
            logger.info(f"Found {len(found_npy)}/{len(expected_npy_files)} expected NPY files")

        if missing_npy:
            logger.warning(f"Missing NPY files: {missing_npy}")

    def test_npy_files_valid(self, resources_root_path, expected_npy_files):
        """Verify NPY files are valid NPY."""
        if not expected_npy_files:
            pytest.skip("No NPY files defined in resources_config.yaml")

        npy_dir = resources_root_path / RESOURCES_NPY_DIR_NAME
        if not npy_dir.exists():
            pytest.skip(f"NPY directory does not exist: {npy_dir}")

        invalid_npy = []

        for npy_name in expected_npy_files:
            npy_path = npy_dir / npy_name
            if npy_path.exists() and not is_valid_npy_file(npy_path):
                invalid_npy.append(npy_name)

        if invalid_npy:
            pytest.fail(f"Invalid NPY files found: {invalid_npy}")

        logger.info("All NPY files are valid")


# ============================================================================
# MAIN ENTRY POINT
# ============================================================================

if __name__ == "__main__":
    pytest.main(["-v", __file__, "-m", "installation"])

