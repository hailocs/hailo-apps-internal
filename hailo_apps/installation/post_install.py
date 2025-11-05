import argparse
import os
import shutil
from pathlib import Path

from hailo_apps.python.core.common.hailo_logger import get_logger

hailo_logger = get_logger(__name__)


from hailo_apps.python.core.common.core import load_environment
from hailo_apps.python.core.common.defines import (
    DEFAULT_CONFIG_PATH,
    DEFAULT_DOTENV_PATH,
    RESOURCES_GROUP_DEFAULT,
    RESOURCES_PATH_DEFAULT,
    RESOURCES_PATH_KEY,
    RESOURCES_ROOT_PATH_DEFAULT,
)
from hailo_apps.python.core.common.installation_utils import create_symlink
from hailo_apps.installation.compile_cpp import compile_postprocess
from hailo_apps.installation.download_resources import download_resources
from hailo_apps.installation.set_env import (
    handle_dot_env,
    set_environment_vars,
)


def post_install():
    """Post-installation setup for Hailo Apps Infra."""
    hailo_logger.debug("Starting post_install()")
    parser = argparse.ArgumentParser(description="Post-installation script for Hailo Apps Infra")
    parser.add_argument(
        "--config", type=str, default=DEFAULT_CONFIG_PATH, help="Path to config file"
    )
    parser.add_argument(
        "--group", type=str, default=RESOURCES_GROUP_DEFAULT, help="Resource group to download"
    )
    parser.add_argument("--dotenv", type=str, default=DEFAULT_DOTENV_PATH, help="Path to .env file")
    args = parser.parse_args()

    hailo_logger.debug(f"Arguments parsed: {args}")

    # Set environment variables (will use existing .env if set_env was already run)
    handle_dot_env(args.dotenv)
    # Try to import from local installation folder first, then fallback to path
    try:
        from .config_utils import load_and_validate_config
    except ImportError:
        # Fallback: import from path
        import importlib.util
        current_file = Path(__file__).resolve()
        config_utils_path = current_file.parent / "config_utils.py"
        if config_utils_path.exists():
            spec = importlib.util.spec_from_file_location("config_utils", config_utils_path)
            config_utils_module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(config_utils_module)
            load_and_validate_config = config_utils_module.load_and_validate_config
        else:
            raise ImportError(f"Could not find config_utils.py at {config_utils_path}")
    config = load_and_validate_config(args.config)
    set_environment_vars(config, args.dotenv)
    load_environment(args.dotenv)

    # Prepare resources symlink
    resources_path = Path(os.getenv(RESOURCES_PATH_KEY, RESOURCES_PATH_DEFAULT))
    if resources_path.exists():
        hailo_logger.warning(f"{resources_path} already exists — removing before symlink creation.")
        if resources_path.is_symlink():
            resources_path.unlink()
        elif resources_path.is_dir():
            shutil.rmtree(resources_path)
        else:
            resources_path.unlink()

    hailo_logger.info(f"Creating symlink from {RESOURCES_ROOT_PATH_DEFAULT} to {resources_path}")
    create_symlink(RESOURCES_ROOT_PATH_DEFAULT, resources_path)

    print("⬇️ Downloading resources...")
    hailo_logger.info("Starting resource download...")
    download_resources(group=args.group)
    hailo_logger.info(f"Resources downloaded to {resources_path}")
    print(f"Resources downloaded to {resources_path}")

    print("⚙️ Compiling post-process...")
    hailo_logger.info("Compiling C++ post-process module...")
    compile_postprocess()

    hailo_logger.info("✅ Hailo Infra Post-installation complete.")
    print("✅ Hailo Infra Post-installation complete.")


def main():
    hailo_logger.debug("Executing main() in post_install.py")
    post_install()


if __name__ == "__main__":
    main()
