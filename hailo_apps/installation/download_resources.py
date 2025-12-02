#!/usr/bin/env python3
import argparse
import os
import urllib.request
from pathlib import Path

import yaml

from hailo_apps.python.core.common.hailo_logger import get_logger

hailo_logger = get_logger(__name__)

# Try to import from local installation folder first, then fallback to path
try:
    from .config_utils import load_config
except ImportError:
    # Fallback: import from path
    import importlib.util
    from pathlib import Path
    current_file = Path(__file__).resolve()
    config_utils_path = current_file.parent / "config_utils.py"
    if config_utils_path.exists():
        spec = importlib.util.spec_from_file_location("config_utils", config_utils_path)
        config_utils_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(config_utils_module)
        load_config = config_utils_module.load_config
    else:
        raise ImportError(f"Could not find config_utils.py at {config_utils_path}")
from hailo_apps.python.core.common.core import load_environment
from hailo_apps.python.core.common.defines import *
from hailo_apps.python.core.common.installation_utils import detect_hailo_arch





def _show_progress(block_num: int, block_size: int, total_size: int):
    """Callback function to show download progress."""
    downloaded = block_num * block_size
    if total_size > 0:
        percent = min(100, (downloaded * 100) // total_size)
        # Show progress bar
        bar_length = 40
        filled = int(bar_length * downloaded // total_size)
        bar = '=' * filled + '-' * (bar_length - filled)
        size_mb = total_size / (1024 * 1024)
        downloaded_mb = downloaded / (1024 * 1024)
        print(f"\r[{bar}] {percent}% ({downloaded_mb:.2f}/{size_mb:.2f} MB)", end='', flush=True)
    else:
        # Unknown size - show downloaded amount
        downloaded_mb = downloaded / (1024 * 1024)
        if downloaded_mb < 0.01:
            downloaded_kb = downloaded / 1024
            print(f"\rDownloading... {downloaded_kb:.2f} KB", end='', flush=True)
        else:
            print(f"\rDownloading... {downloaded_mb:.2f} MB", end='', flush=True)


def download_file(url: str, dest_path: Path, show_progress: bool = True):
    """Download a file from URL to destination path with progress indicator."""
    hailo_logger.debug(f"Preparing to download file: {url} → {dest_path}")
    if dest_path.exists():
        hailo_logger.info(f"{dest_path.name} already exists, skipping.")
        return
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        if show_progress:
            urllib.request.urlretrieve(url, dest_path, _show_progress)
            print()  # New line after progress bar
        else:
            urllib.request.urlretrieve(url, dest_path)
        hailo_logger.info(f"Downloaded to {dest_path}")
    except Exception as e:
        hailo_logger.error(f"Failed to download {url}: {e}")
        raise


def map_arch_to_config_key(hailo_arch: str) -> str:
    """Map Hailo architecture to config key (H8 or H10)."""
    if hailo_arch in (HAILO8_ARCH, HAILO8L_ARCH):
        return "H8"
    elif hailo_arch == HAILO10H_ARCH:
        return "H10"
    else:
        hailo_logger.warning(f"Unknown architecture {hailo_arch}, defaulting to H8")
        return "H8"


def map_arch_to_s3_path(hailo_arch: str, model_name: str = None) -> str:
    """Map Hailo architecture to S3 path architecture.
    
    Args:
        hailo_arch: Hailo architecture (hailo8, hailo8l, hailo10h)
        model_name: Optional model name (not used, kept for backward compatibility)
    
    Returns:
        S3 path architecture (h8, h8l, h10)
    """
    if hailo_arch == HAILO8_ARCH:
        return "h8"
    elif hailo_arch == HAILO8L_ARCH:
        return "h8l"
    elif hailo_arch == HAILO10H_ARCH:
        return "h10"
    else:
        hailo_logger.warning(f"Unknown architecture {hailo_arch}, defaulting to h8")
        assert False, f"Unknown architecture {hailo_arch}"


def download_model_from_config(model_entry: dict, hailo_arch: str, resource_root: Path, model_zoo_version: str, download_arch: str):
    """Download a model from config entry (either Model Zoo or S3 URL)."""
    base_url = MODEL_ZOO_URL
    
    # Handle None
    if model_entry is None:
        hailo_logger.debug(f"Skipping None model entry for {hailo_arch}")
        return
    
    source = model_entry.get("source", "mz")
    name = model_entry.get("name")
    
    if not name:
        hailo_logger.warning(f"Model entry missing name: {model_entry}")
        return
    
    # Build destination path
    dest = (
        resource_root
        / RESOURCES_MODELS_DIR_NAME
        / hailo_arch
        / f"{name}{HAILO_FILE_EXTENSION}"
    )
    
    # Determine URL based on source
    if source == "s3":
        # S3 model - build URL dynamically if not provided
        if "url" in model_entry:
            # Explicit URL provided (backward compatibility)
            url = model_entry["url"]
            hailo_logger.info(f"Downloading model from S3 (explicit URL): {url} → {dest}")
        else:
            # Build URL dynamically based on architecture and model name
            s3_arch = map_arch_to_s3_path(hailo_arch, name)
            url = f"{S3_RESOURCES_BASE_URL}/hefs/{s3_arch}/{name}{HAILO_FILE_EXTENSION}"
            hailo_logger.info(f"Downloading model from S3 (built URL): {url} → {dest}")
        download_file(url, dest)
    elif source == "gen-ai-mz":
        # Gen-AI Model Zoo model - downloaded directly from server (explicit URL required)
        if "url" not in model_entry:
            hailo_logger.error(f"Gen-AI model '{name}' requires explicit URL")
            return
        url = model_entry["url"]
        hailo_logger.info(f"Downloading gen-ai model from server: {url} → {dest}")
        download_file(url, dest)
    elif source == "mz" or "url" not in model_entry:
        # Model Zoo model
        url = f"{base_url}/{model_zoo_version}/{download_arch}/{name}{HAILO_FILE_EXTENSION}"
        hailo_logger.info(f"Downloading model from Model Zoo: {url} → {dest}")
        download_file(url, dest)
    else:
        hailo_logger.warning(f"Invalid model entry: {model_entry}")


def download_group_resources(
    group_name: str, resource_config_path: str | None = None, arch: str | None = None
):
    """Download resources for a specific group (app) based on the new resource config structure."""
    hailo_logger.debug(
        f"Starting download_group_resources for group={group_name}, config={resource_config_path}, arch={arch}"
    )
    cfg_path = Path(resource_config_path or DEFAULT_RESOURCES_CONFIG_PATH)
    if not cfg_path.is_file():
        hailo_logger.error(f"Config file not found at {cfg_path}")
        return

    config = load_config(cfg_path)
    hailo_logger.debug(f"Loaded resource configuration from {cfg_path}")

    # Detect or use provided architecture
    hailo_arch = arch or detect_hailo_arch()
    if not hailo_arch:
        hailo_logger.warning("Hailo architecture could not be detected. Defaulting to hailo8")
        hailo_arch = HAILO8_ARCH
    hailo_logger.info(f"Using Hailo architecture: {hailo_arch}")

    # Check if group (app) exists in config
    if group_name not in config:
        hailo_logger.error(f"Group '{group_name}' not found in resources config")
        hailo_logger.info(f"Available groups/apps: {', '.join([k for k in config.keys() if isinstance(config.get(k), dict)])}")
        return

    group_config = config[group_name]
    if not isinstance(group_config, dict):
        hailo_logger.error(f"Group '{group_name}' config is not a dictionary")
        return

    # Check if this is the new structure (has 'models', 'videos', 'images', 'json' keys)
    is_new_structure = any(key in group_config for key in ['models', 'videos', 'images', 'json'])
    
    if is_new_structure:
        # New structure: organized by group/app with models/videos/images/json
        resource_root = Path(RESOURCES_ROOT_PATH_DEFAULT)
        
        # Setup Model Zoo version
        download_arch = hailo_arch
        if hailo_arch == HAILO10H_ARCH:
            download_arch = "hailo15h"
        model_zoo_version = os.getenv(MODEL_ZOO_VERSION_KEY, MODEL_ZOO_VERSION_DEFAULT)
        if hailo_arch == HAILO10H_ARCH and model_zoo_version not in VALID_H10_MODEL_ZOO_VERSION:
            model_zoo_version = "v5.1.0"
        if (hailo_arch == HAILO8_ARCH or hailo_arch == HAILO8L_ARCH) and model_zoo_version not in VALID_H8_MODEL_ZOO_VERSION:
            model_zoo_version = "v2.17.0"
        hailo_logger.info(f"Using Model Zoo version: {model_zoo_version}")
        
        # Download models
        if "models" in group_config:
            models_config = group_config["models"]
            if hailo_arch in models_config:
                arch_models = models_config[hailo_arch]
                
                # Download default model (can be a single dict or None)
                if "default" in arch_models:
                    default_model = arch_models["default"]
                    if default_model is None:
                        hailo_logger.debug(f"No default model for {group_name}/{hailo_arch}")
                    elif isinstance(default_model, dict):
                        # Skip gen-ai-mz models
                        source = default_model.get("source", "mz")
                        if source != "gen-ai-mz":
                            download_model_from_config(default_model, hailo_arch, resource_root, model_zoo_version, download_arch)
                    elif isinstance(default_model, str):
                        # Backward compatibility: string model name (assumed to be mz)
                        url = f"{MODEL_ZOO_URL}/{model_zoo_version}/{download_arch}/{default_model}{HAILO_FILE_EXTENSION}"
                        dest = (
                            resource_root
                            / RESOURCES_MODELS_DIR_NAME
                            / hailo_arch
                            / f"{default_model}{HAILO_FILE_EXTENSION}"
                        )
                        hailo_logger.info(f"Downloading model: {url} → {dest}")
                        download_file(url, dest)
                    elif isinstance(default_model, list):
                        # Backward compatibility: list of models
                        for model_entry in default_model:
                            if isinstance(model_entry, dict):
                                source = model_entry.get("source", "mz")
                                if source != "gen-ai-mz":
                                    download_model_from_config(model_entry, hailo_arch, resource_root, model_zoo_version, download_arch)
                            elif isinstance(model_entry, str):
                                url = f"{MODEL_ZOO_URL}/{model_zoo_version}/{download_arch}/{model_entry}{HAILO_FILE_EXTENSION}"
                                dest = (
                                    resource_root
                                    / RESOURCES_MODELS_DIR_NAME
                                    / hailo_arch
                                    / f"{model_entry}{HAILO_FILE_EXTENSION}"
                                )
                                hailo_logger.info(f"Downloading model: {url} → {dest}")
                                download_file(url, dest)
                
                # Download extra models
                if "extra" in arch_models:
                    for model_entry in arch_models["extra"]:
                        if isinstance(model_entry, dict):
                            source = model_entry.get("source", "mz")
                            if source != "gen-ai-mz":
                                download_model_from_config(model_entry, hailo_arch, resource_root, model_zoo_version, download_arch)
                        elif isinstance(model_entry, str):
                            # Backward compatibility: string model name (assumed to be mz)
                            url = f"{MODEL_ZOO_URL}/{model_zoo_version}/{download_arch}/{model_entry}{HAILO_FILE_EXTENSION}"
                            dest = (
                                resource_root
                                / RESOURCES_MODELS_DIR_NAME
                                / hailo_arch
                                / f"{model_entry}{HAILO_FILE_EXTENSION}"
                            )
                            hailo_logger.info(f"Downloading model: {url} → {dest}")
                            download_file(url, dest)
        
        # Download videos from top-level config (shared across all apps)
        if "videos" in config:
            for video_entry in config["videos"]:
                if isinstance(video_entry, dict):
                    video_name = video_entry.get("name")
                    video_url = video_entry.get("url")
                    if video_url:
                        dest = resource_root / RESOURCES_VIDEOS_DIR_NAME / video_name
                        hailo_logger.info(f"Downloading video: {video_url} → {dest}")
                        download_file(video_url, dest)
                elif isinstance(video_entry, str) and video_entry.startswith(("http://", "https://")):
                    # Backward compatibility: direct URL
                    filename = Path(video_entry).name
                    dest = resource_root / RESOURCES_VIDEOS_DIR_NAME / filename
                    hailo_logger.info(f"Downloading video: {video_entry} → {dest}")
                    download_file(video_entry, dest)
        
        # Download images from top-level config (shared across all apps)
        if "images" in config:
            for image_entry in config["images"]:
                if isinstance(image_entry, dict):
                    image_name = image_entry.get("name")
                    image_url = image_entry.get("url")
                    if image_url:
                        dest = resource_root / "images" / image_name
                        hailo_logger.info(f"Downloading image: {image_url} → {dest}")
                        download_file(image_url, dest)
                elif isinstance(image_entry, str) and image_entry.startswith(("http://", "https://")):
                    # Backward compatibility: direct URL
                    filename = Path(image_entry).name
                    dest = resource_root / "images" / filename
                    hailo_logger.info(f"Downloading image: {image_entry} → {dest}")
                    download_file(image_entry, dest)
        
        # Download JSON files
        if "json" in group_config:
            for json_entry in group_config["json"]:
                if isinstance(json_entry, dict):
                    json_name = json_entry.get("name")
                    source = json_entry.get("source", None)
                    json_url = json_entry.get("url")
                    
                    if not json_name:
                        hailo_logger.warning(f"JSON entry missing name: {json_entry}")
                        continue
                    
                    dest = resource_root / RESOURCES_JSON_DIR_NAME / json_name
                    
                    # Build URL based on source
                    if source == "s3":
                        # S3 JSON - build URL dynamically if not provided
                        if json_url:
                            # Explicit URL provided (backward compatibility)
                            hailo_logger.info(f"Downloading JSON from S3 (explicit URL): {json_url} → {dest}")
                        else:
                            # Build URL dynamically
                            json_url = f"{S3_RESOURCES_BASE_URL}/configs/{json_name}"
                            hailo_logger.info(f"Downloading JSON from S3 (built URL): {json_url} → {dest}")
                        download_file(json_url, dest)
                    elif json_url:
                        # Non-S3 JSON with explicit URL
                        hailo_logger.info(f"Downloading JSON: {json_url} → {dest}")
                        download_file(json_url, dest)
                    else:
                        hailo_logger.warning(f"JSON entry '{json_name}' missing URL and source is not 's3': {json_entry}")
                elif isinstance(json_entry, str) and json_entry.startswith(("http://", "https://")):
                    # Backward compatibility: direct URL
                    filename = Path(json_entry).name
                    dest = resource_root / RESOURCES_JSON_DIR_NAME / filename
                    hailo_logger.info(f"Downloading JSON: {json_entry} → {dest}")
                    download_file(json_entry, dest)
    else:
        # Old structure: backward compatibility
        # Map architecture to config key (H8 or H10)
        config_key = map_arch_to_config_key(hailo_arch)
        hailo_logger.info(f"Using config key: {config_key} (old structure)")

        # Get resources for the specified architecture
        if config_key not in group_config:
            hailo_logger.warning(f"Group '{group_name}' does not have resources for {config_key}")
            hailo_logger.info(f"Available architectures for '{group_name}': {', '.join(group_config.keys())}")
            return

        resources = group_config[config_key]
        if not isinstance(resources, list):
            hailo_logger.error(f"Resources for '{group_name}/{config_key}' is not a list")
            return

        hailo_logger.info(f"Found {len(resources)} resources for {group_name}/{config_key}")

        resource_root = Path(RESOURCES_ROOT_PATH_DEFAULT)

        for url in resources:
            if not isinstance(url, str) or not url.startswith(("http://", "https://")):
                hailo_logger.warning(f"Skipping invalid resource entry: {url}")
                continue

            # Determine destination based on file type and URL structure
            url_path = Path(url)
            ext = url_path.suffix.lower()
            filename = url_path.name

            # Handle special paths (e.g., whisper decoder assets, images)
            if "decoder_assets" in url or ("npy" in url.lower() and "whisper" in url.lower()):
                # Preserve directory structure for decoder assets
                # Extract path after decoder_assets/ or npy files/whisper/decoder_assets/
                if "decoder_assets" in url:
                    # Extract the path after decoder_assets/
                    parts = url.split("/decoder_assets/")
                    if len(parts) > 1:
                        relative_path = parts[1]
                        dest = resource_root / "decoder_assets" / relative_path
                    else:
                        dest = resource_root / "decoder_assets" / filename
                elif "npy%20files" in url or "npy files" in url:
                    # Handle URL-encoded space in "npy files"
                    if "decoder_assets" in url:
                        # Extract path after decoder_assets/
                        parts = url.split("decoder_assets/")
                        if len(parts) > 1:
                            relative_path = parts[1]
                            dest = resource_root / "decoder_assets" / relative_path
                        else:
                            dest = resource_root / "decoder_assets" / filename
                    else:
                        dest = resource_root / "decoder_assets" / filename
                else:
                    dest = resource_root / "decoder_assets" / filename
            elif ext == HAILO_FILE_EXTENSION:
                # HEF files go to models directory
                name = url_path.stem
                dest = (
                    resource_root
                    / RESOURCES_MODELS_DIR_NAME
                    / hailo_arch
                    / f"{name}{HAILO_FILE_EXTENSION}"
                )
            elif ext == JSON_FILE_EXTENSION:
                # JSON files go to json directory
                dest = resource_root / RESOURCES_JSON_DIR_NAME / filename
            elif ext in [".jpg", ".jpeg", ".png", ".gif", ".bmp"]:
                # Image files go to images directory (create if needed)
                dest = resource_root / "images" / filename
            elif ext in [".mp4", ".avi", ".mov", ".mkv"]:
                # Video files go to videos directory
                dest = resource_root / RESOURCES_VIDEOS_DIR_NAME / filename
            else:
                # Default: save to resources root with original filename
                dest = resource_root / filename

            hailo_logger.info(f"Downloading {url} → {dest}")
            download_file(url, dest)


def download_all_images_and_videos(config: dict, resource_root: Path):
    """Download all images and videos from config (always executed)."""
    hailo_logger.info("Downloading all images and videos...")
    
    # Download videos from top-level config (shared across all apps)
    if "videos" in config:
        for video_entry in config["videos"]:
            if isinstance(video_entry, dict):
                video_name = video_entry.get("name")
                video_url = video_entry.get("url")
                if video_url:
                    dest = resource_root / RESOURCES_VIDEOS_DIR_NAME / video_name
                    hailo_logger.info(f"Downloading video: {video_url} → {dest}")
                    download_file(video_url, dest)
            elif isinstance(video_entry, str) and video_entry.startswith(("http://", "https://")):
                # Backward compatibility: direct URL
                filename = Path(video_entry).name
                dest = resource_root / RESOURCES_VIDEOS_DIR_NAME / filename
                hailo_logger.info(f"Downloading video: {video_entry} → {dest}")
                download_file(video_entry, dest)
    
    # Download images from top-level config (shared across all apps)
    if "images" in config:
        for image_entry in config["images"]:
            if isinstance(image_entry, dict):
                image_name = image_entry.get("name")
                image_url = image_entry.get("url")
                if image_url:
                    dest = resource_root / "images" / image_name
                    hailo_logger.info(f"Downloading image: {image_url} → {dest}")
                    download_file(image_url, dest)
            elif isinstance(image_entry, str) and image_entry.startswith(("http://", "https://")):
                # Backward compatibility: direct URL
                filename = Path(image_entry).name
                dest = resource_root / "images" / filename
                hailo_logger.info(f"Downloading image: {image_entry} → {dest}")
                download_file(image_entry, dest)


def download_all_json_files(config: dict, resource_root: Path):
    """Download all JSON files from all apps in config (always executed)."""
    hailo_logger.info("Downloading all JSON configuration files...")
    
    # Iterate through all apps in config
    for app_name, app_config in config.items():
        # Skip non-app entries (videos, images, etc.)
        if not isinstance(app_config, dict) or "json" not in app_config:
            continue
        
        # Download JSON files for this app
        for json_entry in app_config["json"]:
            if isinstance(json_entry, dict):
                json_name = json_entry.get("name")
                source = json_entry.get("source", None)
                json_url = json_entry.get("url")
                
                if not json_name:
                    hailo_logger.warning(f"JSON entry missing name: {json_entry}")
                    continue
                
                dest = resource_root / RESOURCES_JSON_DIR_NAME / json_name
                
                # Build URL based on source
                if source == "s3":
                    # S3 JSON - build URL dynamically if not provided
                    if json_url:
                        # Explicit URL provided (backward compatibility)
                        hailo_logger.info(f"Downloading JSON from S3 (explicit URL): {json_url} → {dest}")
                    else:
                        # Build URL dynamically
                        json_url = f"{S3_RESOURCES_BASE_URL}/configs/{json_name}"
                        hailo_logger.info(f"Downloading JSON from S3 (built URL): {json_url} → {dest}")
                    download_file(json_url, dest)
                elif json_url:
                    # Non-S3 JSON with explicit URL
                    hailo_logger.info(f"Downloading JSON: {json_url} → {dest}")
                    download_file(json_url, dest)
                else:
                    hailo_logger.warning(f"JSON entry '{json_name}' missing URL and source is not 's3': {json_entry}")
            elif isinstance(json_entry, str) and json_entry.startswith(("http://", "https://")):
                # Backward compatibility: direct URL
                filename = Path(json_entry).name
                dest = resource_root / RESOURCES_JSON_DIR_NAME / filename
                hailo_logger.info(f"Downloading JSON: {json_entry} → {dest}")
                download_file(json_entry, dest)


def download_all_default_models_for_arch(
    config: dict, hailo_arch: str, resource_root: Path, model_zoo_version: str, download_arch: str, include_extra: bool = False
):
    """Download all default models (and optionally extra) for a given architecture, excluding gen-ai-mz models."""
    hailo_logger.info(f"Downloading {'all' if include_extra else 'default'} models for {hailo_arch} (excluding gen-ai-mz)...")
    
    # Iterate through all apps in config
    for app_name, app_config in config.items():
        # Skip non-app entries (videos, images, etc.)
        if not isinstance(app_config, dict) or "models" not in app_config:
            continue
        
        models_config = app_config["models"]
        if hailo_arch not in models_config:
            continue
        
        arch_models = models_config[hailo_arch]
        
        # Download default model
        if "default" in arch_models:
            default_model = arch_models["default"]
            if default_model is not None:
                # Skip gen-ai-mz models
                if isinstance(default_model, dict):
                    source = default_model.get("source", "mz")
                    if source != "gen-ai-mz":
                        download_model_from_config(default_model, hailo_arch, resource_root, model_zoo_version, download_arch)
                elif isinstance(default_model, str):
                    # Backward compatibility: string model name (assumed to be mz)
                    url = f"{MODEL_ZOO_URL}/{model_zoo_version}/{download_arch}/{default_model}{HAILO_FILE_EXTENSION}"
                    dest = (
                        resource_root
                        / RESOURCES_MODELS_DIR_NAME
                        / hailo_arch
                        / f"{default_model}{HAILO_FILE_EXTENSION}"
                    )
                    hailo_logger.info(f"Downloading model: {url} → {dest}")
                    download_file(url, dest)
                elif isinstance(default_model, list):
                    # Backward compatibility: list of models
                    for model_entry in default_model:
                        if isinstance(model_entry, dict):
                            source = model_entry.get("source", "mz")
                            if source != "gen-ai-mz":
                                download_model_from_config(model_entry, hailo_arch, resource_root, model_zoo_version, download_arch)
                        elif isinstance(model_entry, str):
                            url = f"{MODEL_ZOO_URL}/{model_zoo_version}/{download_arch}/{model_entry}{HAILO_FILE_EXTENSION}"
                            dest = (
                                resource_root
                                / RESOURCES_MODELS_DIR_NAME
                                / hailo_arch
                                / f"{model_entry}{HAILO_FILE_EXTENSION}"
                            )
                            hailo_logger.info(f"Downloading model: {url} → {dest}")
                            download_file(url, dest)
        
        # Download extra models if requested
        if include_extra and "extra" in arch_models:
            for model_entry in arch_models["extra"]:
                if isinstance(model_entry, dict):
                    source = model_entry.get("source", "mz")
                    if source != "gen-ai-mz":
                        download_model_from_config(model_entry, hailo_arch, resource_root, model_zoo_version, download_arch)
                elif isinstance(model_entry, str):
                    # Backward compatibility: string model name (assumed to be mz)
                    url = f"{MODEL_ZOO_URL}/{model_zoo_version}/{download_arch}/{model_entry}{HAILO_FILE_EXTENSION}"
                    dest = (
                        resource_root
                        / RESOURCES_MODELS_DIR_NAME
                        / hailo_arch
                        / f"{model_entry}{HAILO_FILE_EXTENSION}"
                    )
                    hailo_logger.info(f"Downloading model: {url} → {dest}")
                    download_file(url, dest)


def download_specific_model(
    config: dict, model_name: str, hailo_arch: str, resource_root: Path, model_zoo_version: str, download_arch: str
):
    """Download a specific model by name for a given architecture."""
    hailo_logger.info(f"Searching for model '{model_name}' for architecture {hailo_arch}...")
    
    found = False
    for app_name, app_config in config.items():
        if not isinstance(app_config, dict) or "models" not in app_config:
            continue
        
        models_config = app_config["models"]
        if hailo_arch not in models_config:
            continue
        
        arch_models = models_config[hailo_arch]
        
        # Check default model
        if "default" in arch_models:
            default_model = arch_models["default"]
            if default_model is not None:
                if isinstance(default_model, dict):
                    if default_model.get("name") == model_name:
                        download_model_from_config(default_model, hailo_arch, resource_root, model_zoo_version, download_arch)
                        found = True
                        break
                elif isinstance(default_model, str) and default_model == model_name:
                    url = f"{MODEL_ZOO_URL}/{model_zoo_version}/{download_arch}/{model_name}{HAILO_FILE_EXTENSION}"
                    dest = (
                        resource_root
                        / RESOURCES_MODELS_DIR_NAME
                        / hailo_arch
                        / f"{model_name}{HAILO_FILE_EXTENSION}"
                    )
                    hailo_logger.info(f"Downloading model: {url} → {dest}")
                    download_file(url, dest)
                    found = True
                    break
        
        # Check extra models
        if "extra" in arch_models:
            for model_entry in arch_models["extra"]:
                if isinstance(model_entry, dict):
                    if model_entry.get("name") == model_name:
                        download_model_from_config(model_entry, hailo_arch, resource_root, model_zoo_version, download_arch)
                        found = True
                        break
                elif isinstance(model_entry, str) and model_entry == model_name:
                    url = f"{MODEL_ZOO_URL}/{model_zoo_version}/{download_arch}/{model_name}{HAILO_FILE_EXTENSION}"
                    dest = (
                        resource_root
                        / RESOURCES_MODELS_DIR_NAME
                        / hailo_arch
                        / f"{model_name}{HAILO_FILE_EXTENSION}"
                    )
                    hailo_logger.info(f"Downloading model: {url} → {dest}")
                    download_file(url, dest)
                    found = True
                    break
        
        if found:
            break
    
    if not found:
        hailo_logger.warning(f"Model '{model_name}' not found for architecture {hailo_arch}")


def list_models_for_arch(
    resource_config_path: str | None = None,
    arch: str | None = None,
    include_extra: bool = True
):
    """List all available models for a given architecture.
    
    Args:
        resource_config_path: Path to resources config file
        arch: Hailo architecture override (hailo8, hailo8l, hailo10h)
        include_extra: If True, include extra models in the list
    """
    cfg_path = Path(resource_config_path or DEFAULT_RESOURCES_CONFIG_PATH)
    if not cfg_path.is_file():
        hailo_logger.error(f"Config file not found at {cfg_path}")
        return

    config = load_config(cfg_path)
    
    # Detect or use provided architecture
    hailo_arch = arch or detect_hailo_arch()
    if not hailo_arch:
        hailo_logger.warning("Hailo architecture could not be detected. Defaulting to hailo8")
        hailo_arch = HAILO8_ARCH
    
    print(f"\nAvailable models for architecture: {hailo_arch}\n")
    print("=" * 80)
    
    default_models = []
    extra_models = []
    
    # Iterate through all apps in config
    for app_name, app_config in config.items():
        # Skip non-app entries (videos, images, etc.)
        if not isinstance(app_config, dict) or "models" not in app_config:
            continue
        
        models_config = app_config["models"]
        if hailo_arch not in models_config:
            continue
        
        arch_models = models_config[hailo_arch]
        
        # Get default model
        if "default" in arch_models:
            default_model = arch_models["default"]
            if default_model is not None:
                if isinstance(default_model, dict):
                    source = default_model.get("source", "mz")
                    name = default_model.get("name")
                    if name and source != "gen-ai-mz":
                        default_models.append((app_name, name, source))
                elif isinstance(default_model, str):
                    default_models.append((app_name, default_model, "mz"))
        
        # Get extra models
        if include_extra and "extra" in arch_models:
            for model_entry in arch_models["extra"]:
                if isinstance(model_entry, dict):
                    source = model_entry.get("source", "mz")
                    name = model_entry.get("name")
                    if name and source != "gen-ai-mz":
                        extra_models.append((app_name, name, source))
                elif isinstance(model_entry, str):
                    extra_models.append((app_name, model_entry, "mz"))
    
    # Print default models
    if default_models:
        print("\n📦 Default Models:")
        print("-" * 80)
        for app_name, model_name, source in sorted(default_models):
            print(f"  • {model_name:30s} [{source:8s}] (app: {app_name})")
    else:
        print("\n📦 Default Models: None")
    
    # Print extra models
    if include_extra and extra_models:
        print("\n📚 Extra Models:")
        print("-" * 80)
        for app_name, model_name, source in sorted(extra_models):
            print(f"  • {model_name:30s} [{source:8s}] (app: {app_name})")
    elif include_extra:
        print("\n📚 Extra Models: None")
    
    print("\n" + "=" * 80)
    print(f"\nTotal: {len(default_models)} default model(s)" + (f", {len(extra_models)} extra model(s)" if include_extra else ""))


def download_resources(
    resource_config_path: str | None = None, 
    arch: str | None = None, 
    group: str | None = None,
    all_models: bool = False,
    model: str | None = None
):
    """Download resources based on the new workflow.
    
    Args:
        resource_config_path: Path to resources config file
        arch: Hailo architecture override (hailo8, hailo8l, hailo10h)
        group: Specific group/app name to download resources for
        all_models: If True, download all models (default + extra), otherwise only default
        model: Specific model name to download
    """
    # If group is specified, use group-specific download
    if group:
        download_group_resources(group, resource_config_path, arch)
        return

    hailo_logger.debug(
        f"Starting download_resources with config={resource_config_path}, arch={arch}, all_models={all_models}, model={model}"
    )
    cfg_path = Path(resource_config_path or DEFAULT_RESOURCES_CONFIG_PATH)
    if not cfg_path.is_file():
        hailo_logger.error(f"Config file not found at {cfg_path}")
        return

    config = load_config(cfg_path)
    hailo_logger.debug(f"Loaded resource configuration from {cfg_path}")

    # Detect or use provided architecture
    hailo_arch = arch or detect_hailo_arch()
    if not hailo_arch:
        hailo_logger.warning("Hailo architecture could not be detected. Defaulting to hailo8")
        hailo_arch = HAILO8_ARCH
    hailo_logger.info(f"Using Hailo architecture: {hailo_arch}")

    # Setup Model Zoo version
    download_arch = hailo_arch
    if hailo_arch == HAILO10H_ARCH:
        download_arch = "hailo15h"
    model_zoo_version = os.getenv(MODEL_ZOO_VERSION_KEY, MODEL_ZOO_VERSION_DEFAULT)
    if hailo_arch == HAILO10H_ARCH and model_zoo_version not in VALID_H10_MODEL_ZOO_VERSION:
        model_zoo_version = "v5.1.0"
    if (hailo_arch == HAILO8_ARCH or hailo_arch == HAILO8L_ARCH) and model_zoo_version not in VALID_H8_MODEL_ZOO_VERSION:
        model_zoo_version = "v2.17.0"
    hailo_logger.info(f"Using Model Zoo version: {model_zoo_version}")

    resource_root = Path(RESOURCES_ROOT_PATH_DEFAULT)

    # Always download all images, videos, and JSON files
    download_all_images_and_videos(config, resource_root)
    download_all_json_files(config, resource_root)

    # Download models based on flags
    if model:
        # Download specific model
        download_specific_model(config, model, hailo_arch, resource_root, model_zoo_version, download_arch)
    else:
        # Download default models (or all if --all flag is set)
        download_all_default_models_for_arch(
            config, hailo_arch, resource_root, model_zoo_version, download_arch, include_extra=all_models
        )


def main():
    parser = argparse.ArgumentParser(description="Install and download Hailo resources")
    parser.add_argument("--all", action="store_true", help="Download all models (default + extra) for detected architecture (excluding gen-ai-mz)")
    parser.add_argument(
        "--config", type=str, default=DEFAULT_RESOURCES_CONFIG_PATH, help="Path to config file"
    )
    parser.add_argument("--arch", type=str, default=None, help="Hailo architecture override (hailo8, hailo8l, hailo10h)")
    parser.add_argument("--group", type=str, default=None, help="Group/app name to download resources for (e.g., detection, instance_segmentation, face_recognition)")
    parser.add_argument("--model", type=str, default=None, help="Specific model name to download for the detected/selected architecture")
    parser.add_argument("--list-models", action="store_true", help="List all available models for the detected/selected architecture")
    args = parser.parse_args()

    load_environment()
    
    # If --list-models flag is set, just list models and exit
    if args.list_models:
        list_models_for_arch(resource_config_path=args.config, arch=args.arch, include_extra=True)
        return
    
    download_resources(
        resource_config_path=args.config, 
        arch=args.arch, 
        group=args.group,
        all_models=args.all,
        model=args.model
    )
    hailo_logger.info("All resources downloaded successfully.")


if __name__ == "__main__":
    main()
