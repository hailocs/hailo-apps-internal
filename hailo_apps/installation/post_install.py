"""Post-installation script for Hailo Apps Infrastructure.

This script handles the post-installation tasks:
1. Load/create environment configuration (.env file)
2. Create symlink from resources root to local resources directory
3. Download resources (models, videos, images, JSON configs)
4. Compile C++ postprocess modules

Usage:
    hailo-post-install                      # Run with default settings
    hailo-post-install --group detection    # Download only detection resources
    hailo-post-install --all                # Download all models
    hailo-post-install --skip-download      # Skip resource download
    hailo-post-install --skip-compile       # Skip C++ compilation
"""

import argparse
import os
import shutil
from pathlib import Path

from hailo_apps.python.core.common.hailo_logger import get_logger
from hailo_apps.python.core.common.core import load_environment
from hailo_apps.python.core.common.defines import (
    DEFAULT_CONFIG_PATH,
    DEFAULT_DOTENV_PATH,
    DEFAULT_RESOURCES_CONFIG_PATH,
    RESOURCES_PATH_DEFAULT,
    RESOURCES_PATH_KEY,
    RESOURCES_ROOT_PATH_DEFAULT,
)
from hailo_apps.python.core.common.installation_utils import create_symlink
from hailo_apps.installation.config_utils import load_and_validate_config
from hailo_apps.installation.compile_cpp import compile_postprocess
from hailo_apps.installation.download_resources import download_resources
from hailo_apps.installation.set_env import (
    handle_dot_env,
    set_environment_vars,
)

hailo_logger = get_logger(__name__)


def setup_resources_symlink(resources_path: Path) -> None:
    """Setup the resources symlink from project to resources root.
    
    Args:
        resources_path: Target path for the symlink (in project directory)
    """
    hailo_logger.info(f"Setting up resources symlink...")
    
    if resources_path.exists():
        hailo_logger.warning(f"{resources_path} already exists — removing before symlink creation.")
        if resources_path.is_symlink():
            resources_path.unlink()
        elif resources_path.is_dir():
            shutil.rmtree(resources_path)
        else:
            resources_path.unlink()

    hailo_logger.info(f"Creating symlink: {resources_path} -> {RESOURCES_ROOT_PATH_DEFAULT}")
    create_symlink(RESOURCES_ROOT_PATH_DEFAULT, str(resources_path))


def post_install(
    config_path: str = DEFAULT_CONFIG_PATH,
    resource_config_path: str = DEFAULT_RESOURCES_CONFIG_PATH,
    dotenv_path: str = DEFAULT_DOTENV_PATH,
    group: str = None,
    all_models: bool = False,
    skip_download: bool = False,
    skip_compile: bool = False,
) -> None:
    """Post-installation setup for Hailo Apps Infrastructure.
    
    Args:
        config_path: Path to main config file
        resource_config_path: Path to resources config file
        dotenv_path: Path to .env file
        group: Specific group/app to download resources for
        all_models: Whether to download all models
        skip_download: Skip resource download
        skip_compile: Skip C++ compilation
    """
    hailo_logger.debug("Starting post_install()")
    
    # Step 1: Setup environment variables
    print("🔧 Setting up environment configuration...")
    hailo_logger.info("Setting up environment configuration...")
    
    handle_dot_env(dotenv_path)
    config = load_and_validate_config(config_path)
    set_environment_vars(config, dotenv_path)
    load_environment(dotenv_path)
    
    # Step 2: Setup resources symlink
    print("🔗 Setting up resources symlink...")
    resources_path = Path(os.getenv(RESOURCES_PATH_KEY, RESOURCES_PATH_DEFAULT))
    setup_resources_symlink(resources_path)
    
    # Step 3: Download resources (if not skipped)
    if not skip_download:
        print("⬇️  Downloading resources...")
        hailo_logger.info("Starting resource download...")
        download_resources(
            resource_config_path=resource_config_path,
            group=group,
            all_models=all_models,
        )
        hailo_logger.info(f"Resources downloaded to {resources_path}")
        print(f"✅ Resources downloaded to {resources_path}")
    else:
        print("⏭️  Skipping resource download (--skip-download)")
        hailo_logger.info("Skipping resource download")
    
    # Step 4: Compile postprocess (if not skipped)
    if not skip_compile:
        print("⚙️  Compiling C++ post-process modules...")
        hailo_logger.info("Compiling C++ post-process modules...")
        compile_postprocess()
        print("✅ C++ post-process modules compiled")
    else:
        print("⏭️  Skipping C++ compilation (--skip-compile)")
        hailo_logger.info("Skipping C++ compilation")
    
    hailo_logger.info("✅ Hailo Infra Post-installation complete.")
    print("\n✅ Hailo Infra Post-installation complete!")


def main():
    """Main entry point for the CLI."""
    hailo_logger.debug("Executing main() in post_install.py")
    
    parser = argparse.ArgumentParser(
        description="Post-installation script for Hailo Apps Infrastructure",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    hailo-post-install                      # Full post-install with default settings
    hailo-post-install --group detection    # Download only detection resources
    hailo-post-install --all                # Download all models (default + extra)
    hailo-post-install --skip-download      # Skip resource download
    hailo-post-install --skip-compile       # Skip C++ compilation
"""
    )
    parser.add_argument(
        "--config",
        type=str,
        default=DEFAULT_CONFIG_PATH,
        help="Path to config file"
    )
    parser.add_argument(
        "--resource-config",
        type=str,
        default=DEFAULT_RESOURCES_CONFIG_PATH,
        help="Path to resources config file"
    )
    parser.add_argument(
        "--dotenv",
        type=str,
        default=DEFAULT_DOTENV_PATH,
        help="Path to .env file"
    )
    parser.add_argument(
        "--group",
        type=str,
        default=None,
        help="Group/app name to download resources for (e.g., detection, pose_estimation)"
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Download all models (default + extra) for detected architecture"
    )
    parser.add_argument(
        "--skip-download",
        action="store_true",
        help="Skip resource download"
    )
    parser.add_argument(
        "--skip-compile",
        action="store_true",
        help="Skip C++ postprocess compilation"
    )
    
    args = parser.parse_args()
    hailo_logger.debug(f"Arguments parsed: {args}")
    
    post_install(
        config_path=args.config,
        resource_config_path=args.resource_config,
        dotenv_path=args.dotenv,
        group=args.group,
        all_models=args.all,
        skip_download=args.skip_download,
        skip_compile=args.skip_compile,
    )


if __name__ == "__main__":
    main()
