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





def download_file(url: str, dest_path: Path):
    hailo_logger.debug(f"Preparing to download file: {url} → {dest_path}")
    if dest_path.exists():
        hailo_logger.info(f"{dest_path.name} already exists, skipping.")
        return
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    urllib.request.urlretrieve(url, dest_path)
    hailo_logger.info(f"Downloaded to {dest_path}")


def download_resources(
    group: str | None = None, resource_config_path: str | None = None, arch: str | None = None
):
    hailo_logger.debug(
        f"Starting download_resources with group={group}, config={resource_config_path}, arch={arch}"
    )
    cfg_path = Path(resource_config_path or DEFAULT_RESOURCES_CONFIG_PATH)
    if not cfg_path.is_file():
        hailo_logger.warning(f"Config file not found at {cfg_path}, creating default.")
        cfg_path = create_config_at_path()

    config = load_config(cfg_path)
    hailo_logger.debug(f"Loaded resource configuration from {cfg_path}")

    hailo_arch = arch or detect_hailo_arch()
    if not hailo_arch:
        hailo_logger.warning("Hailo architecture could not be detected. Defaulting to hailo8")
        hailo_arch = HAILO8_ARCH
    hailo_logger.info(f"Using Hailo architecture: {hailo_arch}")

    download_arch = hailo_arch
    if hailo_arch == HAILO10H_ARCH:
        download_arch = "hailo15h"
    model_zoo_version = os.getenv(MODEL_ZOO_VERSION_KEY, MODEL_ZOO_VERSION_DEFAULT)
    if hailo_arch == HAILO10H_ARCH and model_zoo_version not in VALID_H10_MODEL_ZOO_VERSION:
        model_zoo_version = "v5.1.0"
    if (hailo_arch == HAILO8_ARCH or hailo_arch == HAILO8L_ARCH) and model_zoo_version not in VALID_H8_MODEL_ZOO_VERSION:
        model_zoo_version = "v2.17.0"
    hailo_logger.info(f"Using Model Zoo version: {model_zoo_version}")

    groups = [RESOURCES_GROUP_DEFAULT]
    if group != RESOURCES_GROUP_DEFAULT and group in RESOURCES_GROUPS_MAP:
        groups.append(group)
        if group == RESOURCES_GROUP_ALL:
            groups.append(RESOURCES_GROUP_RETRAIN)

    if hailo_arch == HAILO8_ARCH:
        groups.append(RESOURCES_GROUP_HAILO8)
    elif hailo_arch == HAILO8L_ARCH:
        groups.append(RESOURCES_GROUP_HAILO8L)
    elif hailo_arch == HAILO10H_ARCH:
        groups.append(RESOURCES_GROUP_HAILO10H)

    seen = set()
    items = []
    for grp in groups:
        # Handle both "hailo10" and "hailo10h" config keys for backward compatibility
        config_key = grp
        if grp == RESOURCES_GROUP_HAILO10H:
            # Try "hailo10h" first, fallback to "hailo10"
            if "hailo10h" not in config and "hailo10" in config:
                config_key = "hailo10"
        
        for entry in config.get(config_key, []):
            key = entry if isinstance(entry, str) else next(iter(entry.keys()))
            if key not in seen:
                seen.add(key)
                items.append(entry)

    resource_root = Path(RESOURCES_ROOT_PATH_DEFAULT)
    base_url = MODEL_ZOO_URL

    for entry in items:
        if isinstance(entry, str):
            if entry.startswith(("http://", "https://")):
                url = entry
                ext = Path(url).suffix.lower()
                if ext == HAILO_FILE_EXTENSION:
                    name = Path(url).stem
                    dest = (
                        resource_root
                        / RESOURCES_MODELS_DIR_NAME
                        / hailo_arch
                        / f"{name}{HAILO_FILE_EXTENSION}"
                    )
                else:
                    filename = Path(url).name
                    if ext == JSON_FILE_EXTENSION:
                        dest = resource_root / RESOURCES_JSON_DIR_NAME / filename
                    else:
                        dest = resource_root / RESOURCES_VIDEOS_DIR_NAME / filename
            else:
                name = entry
                url = f"{base_url}/{model_zoo_version}/{download_arch}/{name}{HAILO_FILE_EXTENSION}"
                dest = (
                    resource_root
                    / RESOURCES_MODELS_DIR_NAME
                    / hailo_arch
                    / f"{name}{HAILO_FILE_EXTENSION}"
                )
        else:
            name, url = next(iter(entry.items()))
            ext = Path(url).suffix.lower()
            if ext == HAILO_FILE_EXTENSION:
                dest = (
                    resource_root
                    / RESOURCES_MODELS_DIR_NAME
                    / hailo_arch
                    / f"{name}{HAILO_FILE_EXTENSION}"
                )
            else:
                dest = resource_root / RESOURCES_VIDEOS_DIR_NAME / f"{name}{ext}"

        hailo_logger.info(f"Downloading {url}")
        download_file(url, dest)


def main():
    parser = argparse.ArgumentParser(description="Install and download Hailo resources")
    parser.add_argument("--all", action="store_true", help="Download all resources")
    parser.add_argument(
        "--group", type=str, default=RESOURCES_GROUP_DEFAULT, help="Resource group to download"
    )
    parser.add_argument(
        "--config", type=str, default=DEFAULT_RESOURCES_CONFIG_PATH, help="Path to config file"
    )
    parser.add_argument("--arch", type=str, default=None, help="Hailo architecture override")
    args = parser.parse_args()

    if args.all:
        args.group = RESOURCES_GROUP_ALL

    load_environment()
    download_resources(group=args.group, resource_config_path=args.config, arch=args.arch)
    hailo_logger.info("All resources downloaded successfully.")


if __name__ == "__main__":
    main()
