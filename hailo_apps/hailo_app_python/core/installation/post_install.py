import argparse
import grp
import os
import pwd
import shutil
import subprocess
from pathlib import Path

from hailo_apps.hailo_app_python.core.common.hailo_logger import get_logger

hailo_logger = get_logger(__name__)


from hailo_apps.hailo_app_python.core.common.config_utils import load_and_validate_config
from hailo_apps.hailo_app_python.core.common.core import load_environment
from hailo_apps.hailo_app_python.core.common.defines import (
    DEFAULT_CONFIG_PATH,
    DEFAULT_DOTENV_PATH,
    RESOURCES_DIRS_MAP,
    RESOURCES_GROUP_DEFAULT,
    RESOURCES_PATH_DEFAULT,
    RESOURCES_PATH_KEY,
    RESOURCES_ROOT_PATH_DEFAULT,
)
from hailo_apps.hailo_app_python.core.common.installation_utils import create_symlink
from hailo_apps.hailo_app_python.core.installation.compile_cpp import compile_postprocess
from hailo_apps.hailo_app_python.core.installation.download_resources import download_resources
from hailo_apps.hailo_app_python.core.installation.set_env import (
    handle_dot_env,
    set_environment_vars,
)


def setup_resource_dirs():
    """Create resource directories for Hailo applications.
    Also sets ownership and permissions.
    """
    hailo_logger.debug("Entering setup_resource_dirs()")

    # Determine installation user
    sudo_user = os.environ.get("SUDO_USER")
    install_user = sudo_user or pwd.getpwuid(os.getuid()).pw_name
    hailo_logger.debug(f"Detected installation user: {install_user}")

    # Get group name
    pw = pwd.getpwnam(install_user)
    grpname = grp.getgrgid(pw.pw_gid).gr_name
    hailo_logger.debug(f"Detected group: {grpname}")

    # Create subdirectories
    for sub in RESOURCES_DIRS_MAP:
        target = sub
        hailo_logger.debug(f"Creating directory: {target}")
        subprocess.run(["sudo", "mkdir", "-p", str(target)], check=True)

    # Set permissions
    hailo_logger.debug(f"Setting ownership to {install_user}:{grpname}")
    subprocess.run(
        ["sudo", "chown", "-R", f"{install_user}:{grpname}", str(RESOURCES_ROOT_PATH_DEFAULT)],
        check=True,
    )
    hailo_logger.debug("Setting directory permissions to 755")
    subprocess.run(["sudo", "chmod", "-R", "755", str(RESOURCES_ROOT_PATH_DEFAULT)], check=True)

    hailo_logger.info("✅ Resource directories created successfully.")
    print("✅ Resource directories created successfully.")


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

    handle_dot_env()  # Load .env if exists
    config = load_and_validate_config(args.config)
    hailo_logger.debug(f"Loaded configuration: {config}")

    set_environment_vars(config, args.dotenv)
    load_environment()

    setup_resource_dirs()

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
