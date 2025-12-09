"""Environment configuration module for Hailo installation.

This module provides OOP-based classes for managing environment variable
configuration, including auto-detection of system and Hailo device settings.

Environment Variables Set:
    - HOST_ARCH: Host system architecture (x86, rpi, arm)
    - HAILO_ARCH: Hailo device architecture (hailo8, hailo8l, hailo10h)
    - HAILORT_VERSION: Installed HailoRT version
    - TAPPAS_VERSION: Installed TAPPAS version
    - TAPPAS_VARIANT: TAPPAS variant (hailo-tappas or hailo-tappas-core)
    - TAPPAS_POSTPROC_PATH: Path to TAPPAS postprocess libraries
    - MODEL_ZOO_VERSION: Model Zoo version based on Hailo architecture
    - RESOURCES_PATH: Path to resources directory (symlink)
    - RESOURCES_ROOT_PATH: Path to resources root (/usr/local/hailo/resources)
    - VIRTUAL_ENV_NAME: Name of the virtual environment
    - HAILO_APPS_INFRA_PATH: Full path to the hailo-apps-infra repository
"""

import argparse
import os
import sys
from pathlib import Path
from typing import Dict, Optional, Union

# Try to import logger from hailo_apps, fallback to simple logger
try:
    from hailo_apps.python.core.common.hailo_logger import get_logger
except ImportError:
    import logging

    def get_logger(name):
        logger = logging.getLogger(name)
        if not logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter("%(levelname)s - %(message)s")
            handler.setFormatter(formatter)
            logger.addHandler(handler)
            logger.setLevel(logging.INFO)
        return logger

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

# Try to import defines and installation utils from hailo_apps
try:
    from hailo_apps.python.core.common.defines import (
        AUTO_DETECT,
        DEFAULT_DOTENV_PATH,
        DEFAULT_RESOURCES_SYMLINK_PATH,
        HAILO8_ARCH,
        HAILO8L_ARCH,
        HAILO10H_ARCH,
        HAILO_ARCH_DEFAULT,
        HAILO_ARCH_KEY,
        HAILORT_PACKAGE_NAME,
        HAILORT_PACKAGE_NAME_RPI,
        HAILORT_VERSION_DEFAULT,
        HAILORT_VERSION_KEY,
        HOST_ARCH_DEFAULT,
        HOST_ARCH_KEY,
        MODEL_ZOO_VERSION_DEFAULT,
        MODEL_ZOO_VERSION_KEY,
        REPO_ROOT,
        RESOURCES_PATH_KEY,
        RESOURCES_ROOT_PATH_DEFAULT,
        TAPPAS_POSTPROC_PATH_KEY,
        TAPPAS_VARIANT_DEFAULT,
        TAPPAS_VARIANT_KEY,
        TAPPAS_VERSION_DEFAULT,
        TAPPAS_VERSION_KEY,
        VALID_H8_MODEL_ZOO_VERSION,
        VALID_H10_MODEL_ZOO_VERSION,
        VIRTUAL_ENV_NAME_DEFAULT,
        VIRTUAL_ENV_NAME_KEY,
        HAILO_APPS_INFRA_PATH_KEY,
    )
    from hailo_apps.python.core.common.installation_utils import (
        auto_detect_tappas_postproc_dir,
        auto_detect_tappas_variant,
        auto_detect_tappas_version,
        detect_hailo_arch,
        detect_host_arch,
        detect_system_pkg_version,
        get_hailort_package_name,
    )
except ImportError:
    # Fallback: import from path
    import importlib.util

    current_file = Path(__file__).resolve()
    defines_path = current_file.parent.parent.parent / "python" / "core" / "common" / "defines.py"
    installation_utils_path = (
        current_file.parent.parent.parent / "python" / "core" / "common" / "installation_utils.py"
    )

    if defines_path.exists():
        spec = importlib.util.spec_from_file_location("defines", defines_path)
        defines_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(defines_module)
        # Import needed constants
        AUTO_DETECT = defines_module.AUTO_DETECT
        DEFAULT_DOTENV_PATH = defines_module.DEFAULT_DOTENV_PATH
        DEFAULT_RESOURCES_SYMLINK_PATH = defines_module.DEFAULT_RESOURCES_SYMLINK_PATH
        HAILO8_ARCH = defines_module.HAILO8_ARCH
        HAILO8L_ARCH = defines_module.HAILO8L_ARCH
        HAILO10H_ARCH = defines_module.HAILO10H_ARCH
        HAILO_ARCH_DEFAULT = defines_module.HAILO_ARCH_DEFAULT
        HAILO_ARCH_KEY = defines_module.HAILO_ARCH_KEY
        HAILORT_PACKAGE_NAME = defines_module.HAILORT_PACKAGE_NAME
        HAILORT_PACKAGE_NAME_RPI = defines_module.HAILORT_PACKAGE_NAME_RPI
        HAILORT_VERSION_DEFAULT = defines_module.HAILORT_VERSION_DEFAULT
        HAILORT_VERSION_KEY = defines_module.HAILORT_VERSION_KEY
        HOST_ARCH_DEFAULT = defines_module.HOST_ARCH_DEFAULT
        HOST_ARCH_KEY = defines_module.HOST_ARCH_KEY
        MODEL_ZOO_VERSION_DEFAULT = defines_module.MODEL_ZOO_VERSION_DEFAULT
        MODEL_ZOO_VERSION_KEY = defines_module.MODEL_ZOO_VERSION_KEY
        REPO_ROOT = defines_module.REPO_ROOT
        RESOURCES_PATH_KEY = defines_module.RESOURCES_PATH_KEY
        RESOURCES_ROOT_PATH_DEFAULT = defines_module.RESOURCES_ROOT_PATH_DEFAULT
        TAPPAS_POSTPROC_PATH_KEY = defines_module.TAPPAS_POSTPROC_PATH_KEY
        TAPPAS_VARIANT_DEFAULT = defines_module.TAPPAS_VARIANT_DEFAULT
        TAPPAS_VARIANT_KEY = defines_module.TAPPAS_VARIANT_KEY
        TAPPAS_VERSION_DEFAULT = defines_module.TAPPAS_VERSION_DEFAULT
        TAPPAS_VERSION_KEY = defines_module.TAPPAS_VERSION_KEY
        VALID_H8_MODEL_ZOO_VERSION = defines_module.VALID_H8_MODEL_ZOO_VERSION
        VALID_H10_MODEL_ZOO_VERSION = defines_module.VALID_H10_MODEL_ZOO_VERSION
        VIRTUAL_ENV_NAME_DEFAULT = defines_module.VIRTUAL_ENV_NAME_DEFAULT
        VIRTUAL_ENV_NAME_KEY = defines_module.VIRTUAL_ENV_NAME_KEY
        HAILO_APPS_INFRA_PATH_KEY = defines_module.HAILO_APPS_INFRA_PATH_KEY
    else:
        raise ImportError(f"Could not find defines.py at {defines_path}")

    if installation_utils_path.exists():
        spec = importlib.util.spec_from_file_location("installation_utils", installation_utils_path)
        installation_utils_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(installation_utils_module)
        auto_detect_tappas_postproc_dir = installation_utils_module.auto_detect_tappas_postproc_dir
        auto_detect_tappas_variant = installation_utils_module.auto_detect_tappas_variant
        auto_detect_tappas_version = installation_utils_module.auto_detect_tappas_version
        detect_hailo_arch = installation_utils_module.detect_hailo_arch
        detect_host_arch = installation_utils_module.detect_host_arch
        detect_system_pkg_version = installation_utils_module.detect_system_pkg_version
        get_hailort_package_name = installation_utils_module.get_hailort_package_name
    else:
        raise ImportError(f"Could not find installation_utils.py at {installation_utils_path}")

hailo_logger = get_logger(__name__)

# Additional environment variable keys
RESOURCES_ROOT_PATH_KEY = "resources_root_path"


class EnvironmentFileHandler:
    """Handles .env file operations including creation, permissions, and writing."""

    def __init__(self, env_path: Optional[Path] = None):
        """Initialize with optional .env file path.

        Args:
            env_path: Path to .env file. If None, uses default path.
        """
        self.env_path = Path(env_path) if env_path else Path(DEFAULT_DOTENV_PATH)
        self._ensure_file_exists()

    def _ensure_file_exists(self) -> None:
        """Ensure the .env file and its parent directory exist."""
        hailo_logger.debug(f"Ensuring .env file exists at {self.env_path}")
        self.env_path.parent.mkdir(parents=True, exist_ok=True)

        if not self.env_path.is_file():
            hailo_logger.info(f"Creating new .env file at {self.env_path}")
            print(f"🔧 Creating .env file at {self.env_path}")
            self.env_path.touch()

        # Ensure file is writable
        os.chmod(self.env_path, 0o666)

    def _ensure_writable(self) -> None:
        """Ensure the .env file is writable, fixing permissions if needed."""
        if self.env_path.exists() and not os.access(self.env_path, os.W_OK):
            hailo_logger.warning(".env not writable — fixing permissions")
            print("⚠️ .env not writable — fixing permissions...")
            try:
                self.env_path.chmod(0o666)
            except Exception as e:
                hailo_logger.error(f"Failed to fix .env permissions: {e}")
                print(f"❌ Failed to fix .env permissions: {e}")
                sys.exit(1)

    def write_environment_variables(self, env_vars: Dict[str, Optional[str]]) -> None:
        """Write environment variables to the .env file.

        Args:
            env_vars: Dictionary of environment variable names and values.
        """
        hailo_logger.debug(f"Writing environment variables to {self.env_path}")
        self._ensure_writable()

        with open(self.env_path, "w") as f:
            f.write("# Hailo Apps Infrastructure Environment Configuration\n")
            f.write("# Auto-generated by set_env.py - Do not edit manually\n")
            f.write(f"# Generated at: {__import__('datetime').datetime.now().isoformat()}\n\n")
            
            for key, value in env_vars.items():
                if value is not None:
                    f.write(f"{key}={value}\n")

        hailo_logger.info(f"✅ Persisted environment variables to {self.env_path}")
        print(f"✅ Persisted environment variables to {self.env_path}")


class ConfigAutoDetector:
    """Handles auto-detection of configuration values from the system."""

    def __init__(self):
        """Initialize the auto-detector."""
        self.logger = get_logger(__name__)

    def detect_host_architecture(self) -> str:
        """Detect and return the host system architecture.

        Returns:
            Detected host architecture (x86, rpi, arm, or unknown).
        """
        self.logger.info("Auto-detecting host architecture...")
        return detect_host_arch()

    def detect_hailo_architecture(self) -> Optional[str]:
        """Detect and return the Hailo device architecture.

        Returns:
            Detected Hailo architecture or None if detection fails.
        """
        self.logger.info("Auto-detecting Hailo architecture...")
        try:
            return detect_hailo_arch()
        except (AssertionError, Exception) as e:
            self.logger.warning(f"Could not detect Hailo architecture: {e}")
            return None

    def detect_hailort_version(self) -> str:
        """Detect and return the installed HailoRT version.

        Returns:
            Detected HailoRT version or exits if not found.
        """
        self.logger.info("Auto-detecting HailoRT version...")
        pkg_name = get_hailort_package_name()
        version = detect_system_pkg_version(pkg_name)
        if not version:
            self.logger.error(f"HailoRT version not detected for package '{pkg_name}'. Please install HailoRT.")
            sys.exit(1)
        return version

    def detect_tappas_variant(self) -> Optional[str]:
        """Detect and return the installed TAPPAS variant.

        Returns:
            Detected TAPPAS variant or None if not found.
        """
        self.logger.info("Auto-detecting TAPPAS variant...")
        return auto_detect_tappas_variant()

    def detect_tappas_version(self, tappas_variant: str) -> Optional[str]:
        """Detect and return the TAPPAS version for a given variant.

        Args:
            tappas_variant: The TAPPAS variant to detect version for.

        Returns:
            Detected TAPPAS version or None if not found.
        """
        self.logger.info(f"Auto-detecting TAPPAS version for variant: {tappas_variant}")
        return auto_detect_tappas_version(tappas_variant)

    def detect_tappas_postproc_dir(self, tappas_variant: str) -> str:
        """Detect and return the TAPPAS post-processing directory.

        Args:
            tappas_variant: The TAPPAS variant to detect directory for.

        Returns:
            Path to TAPPAS post-processing directory.
        """
        self.logger.debug(f"Detecting TAPPAS post-processing directory for variant: {tappas_variant}")
        try:
            return auto_detect_tappas_postproc_dir(tappas_variant)
        except Exception as e:
            self.logger.warning(f"Could not detect TAPPAS postproc dir: {e}")
            return ""

    def detect_model_zoo_version(self, hailo_arch: str) -> str:
        """Detect the appropriate Model Zoo version based on Hailo architecture.

        Args:
            hailo_arch: The Hailo device architecture.

        Returns:
            Model Zoo version string.
        """
        if hailo_arch == HAILO10H_ARCH:
            version = VALID_H10_MODEL_ZOO_VERSION[0] if VALID_H10_MODEL_ZOO_VERSION else "v5.1.1"
            self.logger.info(f"Using H10 Model Zoo version: {version}")
            return version
        else:
            version = VALID_H8_MODEL_ZOO_VERSION[0] if VALID_H8_MODEL_ZOO_VERSION else "v2.17.0"
            self.logger.info(f"Using H8 Model Zoo version: {version}")
            return version


class EnvironmentConfigurator:
    """Main orchestrator for environment configuration.

    Combines config loading, auto-detection, and environment variable setting.
    """

    def __init__(self, env_path: Optional[Path] = None):
        """Initialize the configurator.

        Args:
            env_path: Optional path to .env file. If None, uses default.
        """
        self.env_handler = EnvironmentFileHandler(env_path)
        self.auto_detector = ConfigAutoDetector()
        self.logger = get_logger(__name__)

    def _extract_config_values(self, config: Dict) -> Dict[str, Optional[str]]:
        """Extract configuration values with defaults.

        Args:
            config: Configuration dictionary from config file.

        Returns:
            Dictionary of configuration values.
        """
        # Handle nested config structure (resources.path, venv.name)
        resources_config = config.get('resources', {})
        venv_config = config.get('venv', {})
        
        return {
            HOST_ARCH_KEY: config.get(HOST_ARCH_KEY, HOST_ARCH_DEFAULT),
            HAILO_ARCH_KEY: config.get(HAILO_ARCH_KEY, HAILO_ARCH_DEFAULT),
            RESOURCES_PATH_KEY: resources_config.get('path', DEFAULT_RESOURCES_SYMLINK_PATH),
            MODEL_ZOO_VERSION_KEY: config.get(MODEL_ZOO_VERSION_KEY, MODEL_ZOO_VERSION_DEFAULT),
            HAILORT_VERSION_KEY: config.get(HAILORT_VERSION_KEY, HAILORT_VERSION_DEFAULT),
            TAPPAS_VERSION_KEY: config.get(TAPPAS_VERSION_KEY, TAPPAS_VERSION_DEFAULT),
            VIRTUAL_ENV_NAME_KEY: venv_config.get('name', VIRTUAL_ENV_NAME_DEFAULT),
            TAPPAS_VARIANT_KEY: config.get(TAPPAS_VARIANT_KEY, TAPPAS_VARIANT_DEFAULT),
        }

    def _perform_auto_detections(self, config_values: Dict[str, Optional[str]]) -> Dict[str, Optional[str]]:
        """Perform auto-detection for values set to 'auto'.

        Args:
            config_values: Dictionary of configuration values.

        Returns:
            Updated dictionary with detected values.
        """
        self.logger.debug("Performing auto-detections for 'auto' values")

        # Auto-detect host architecture
        if config_values.get(HOST_ARCH_KEY) == AUTO_DETECT:
            config_values[HOST_ARCH_KEY] = self.auto_detector.detect_host_architecture()

        # Auto-detect Hailo architecture
        if config_values.get(HAILO_ARCH_KEY) == AUTO_DETECT:
            detected = self.auto_detector.detect_hailo_architecture()
            config_values[HAILO_ARCH_KEY] = detected if detected else HAILO_ARCH_DEFAULT

        # Auto-detect HailoRT version
        if config_values.get(HAILORT_VERSION_KEY) == AUTO_DETECT:
            config_values[HAILORT_VERSION_KEY] = self.auto_detector.detect_hailort_version()

        # Auto-detect TAPPAS variant and version
        tappas_variant = config_values.get(TAPPAS_VARIANT_KEY)
        if tappas_variant == AUTO_DETECT:
            tappas_variant = self.auto_detector.detect_tappas_variant()
            config_values[TAPPAS_VARIANT_KEY] = tappas_variant

        # Auto-detect TAPPAS version
        if config_values.get(TAPPAS_VERSION_KEY) == AUTO_DETECT and tappas_variant:
            config_values[TAPPAS_VERSION_KEY] = self.auto_detector.detect_tappas_version(tappas_variant)

        # Always detect TAPPAS post-processing directory
        if tappas_variant:
            tappas_postproc_dir = self.auto_detector.detect_tappas_postproc_dir(tappas_variant)
            if tappas_postproc_dir:
                config_values[TAPPAS_POSTPROC_PATH_KEY] = tappas_postproc_dir.strip()
                print(f"Using Tappas post-processing directory: {tappas_postproc_dir.strip()}")
            else:
                self.logger.warning("Tappas post-processing directory not found.")

        # Auto-detect Model Zoo version based on Hailo architecture
        hailo_arch = config_values.get(HAILO_ARCH_KEY)
        if config_values.get(MODEL_ZOO_VERSION_KEY) == AUTO_DETECT or config_values.get(MODEL_ZOO_VERSION_KEY) == MODEL_ZOO_VERSION_DEFAULT:
            # Update model zoo version based on detected architecture
            if hailo_arch:
                config_values[MODEL_ZOO_VERSION_KEY] = self.auto_detector.detect_model_zoo_version(hailo_arch)

        return config_values

    def _add_additional_variables(self, config_values: Dict[str, Optional[str]]) -> Dict[str, Optional[str]]:
        """Add additional computed environment variables.

        Args:
            config_values: Dictionary of configuration values.

        Returns:
            Updated dictionary with additional variables.
        """
        # Add HAILO_APPS_INFRA_PATH - the repo root
        try:
            config_values[HAILO_APPS_INFRA_PATH_KEY] = str(REPO_ROOT)
        except NameError:
            # Fallback: compute from this file's location
            current_file = Path(__file__).resolve()
            repo_root = current_file.parent.parent.parent
            config_values[HAILO_APPS_INFRA_PATH_KEY] = str(repo_root)

        # Add RESOURCES_ROOT_PATH (the actual root, not the symlink)
        config_values[RESOURCES_ROOT_PATH_KEY] = RESOURCES_ROOT_PATH_DEFAULT

        return config_values

    def configure_environment(self, config: Dict, update_os_env: bool = True) -> None:
        """Configure environment variables from config and auto-detection.

        Args:
            config: Configuration dictionary from config file.
            update_os_env: If True, update os.environ with the values.
        """
        self.logger.debug(f"Configuring environment from config: {config}")

        # Extract config values with defaults
        env_vars = self._extract_config_values(config)

        # Perform auto-detections
        env_vars = self._perform_auto_detections(env_vars)

        # Add additional computed variables
        env_vars = self._add_additional_variables(env_vars)

        self.logger.debug(f"Final environment variables: {env_vars}")

        # Update os.environ if requested
        if update_os_env:
            os.environ.update({k: v for k, v in env_vars.items() if v is not None})

        # Write to .env file
        self.env_handler.write_environment_variables(env_vars)

        # Print summary
        print("\n📋 Environment Configuration Summary:")
        print("─" * 50)
        for key, value in env_vars.items():
            if value is not None:
                print(f"  {key}: {value}")
        print("─" * 50)


def handle_dot_env(env_path: Optional[Union[Path, str]] = None) -> Path:
    """Legacy function for backward compatibility.
    
    Creates and ensures .env file exists and is writable.

    Args:
        env_path: Optional path to .env file. If None, uses default path.

    Returns:
        Path to the .env file.
    """
    handler = EnvironmentFileHandler(env_path)
    return handler.env_path


def set_environment_vars(config: Dict, env_path: Optional[Path] = None) -> None:
    """Legacy function for backward compatibility.

    Args:
        config: Configuration dictionary from config file.
        env_path: Optional path to .env file.
    """
    configurator = EnvironmentConfigurator(env_path)
    configurator.configure_environment(config, update_os_env=True)


def main():
    """Main entry point for the CLI."""
    parser = argparse.ArgumentParser(
        description="Set environment variables for Hailo installation.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Environment Variables Set:
  HOST_ARCH             Host system architecture (x86, rpi, arm)
  HAILO_ARCH            Hailo device architecture (hailo8, hailo8l, hailo10h)
  HAILORT_VERSION       Installed HailoRT version
  TAPPAS_VERSION        Installed TAPPAS version
  TAPPAS_VARIANT        TAPPAS variant (hailo-tappas or hailo-tappas-core)
  TAPPAS_POSTPROC_PATH  Path to TAPPAS postprocess libraries
  MODEL_ZOO_VERSION     Model Zoo version (auto-selected based on architecture)
  RESOURCES_PATH        Path to resources symlink
  RESOURCES_ROOT_PATH   Path to resources root (/usr/local/hailo/resources)
  HAILO_APPS_INFRA_PATH Full path to the repository
  VIRTUAL_ENV_NAME      Name of the virtual environment
"""
    )
    parser.add_argument(
        "--config", type=str, default=None, help="Path to the config file (optional)"
    )
    parser.add_argument(
        "--env-path", type=str, default=DEFAULT_DOTENV_PATH, help="Path to the .env file"
    )

    args = parser.parse_args()
    hailo_logger.debug(f"CLI arguments: {args}")

    # Load and validate config
    config = load_and_validate_config(args.config)

    # Configure environment
    configurator = EnvironmentConfigurator(env_path=Path(args.env_path))
    configurator.configure_environment(config)


if __name__ == "__main__":
    main()
