"""Installation-related utilities."""

import platform
import shlex
import subprocess
import sys

from .defines import (
    ARM_NAME_I,
    ARM_POSSIBLE_NAME,
    HAILO8_ARCH,
    HAILO8_ARCH_CAPS,
    HAILO8L_ARCH,
    HAILO8L_ARCH_CAPS,
    HAILO10H_ARCH,
    HAILO10H_ARCH_CAPS,
    HAILO15H_ARCH_CAPS,
    HAILO_FW_CONTROL_CMD,
    HAILO_TAPPAS,
    HAILO_TAPPAS_CORE,
    HAILO_TAPPAS_CORE_PYTHON_NAMES,
    HAILORT_PACKAGE_NAME,
    HAILORT_PACKAGE_NAME_RPI,
    LINUX_SYSTEM_NAME_I,
    PIP_CMD,
    RPI_NAME_I,
    RPI_POSSIBLE_NAME,
    UNKNOWN_NAME_I,
    X86_NAME_I,
    X86_POSSIBLE_NAME,
)
from .hailo_logger import get_logger

hailo_logger = get_logger(__name__)


def detect_pkg_config_version(pkg_name: str) -> str:
    hailo_logger.debug(f"Detecting pkg-config version for: {pkg_name}")
    try:
        version = subprocess.check_output(
            ["pkg-config", "--modversion", pkg_name], stderr=subprocess.DEVNULL, text=True
        )
        version = version.strip()
        hailo_logger.debug(f"Found version {version} for package {pkg_name}")
        return version
    except subprocess.CalledProcessError:
        hailo_logger.warning(f"Package {pkg_name} not found in pkg-config.")
        return ""


def auto_detect_pkg_config(pkg_name: str) -> bool:
    hailo_logger.debug(f"Checking if {pkg_name} exists in pkg-config.")
    try:
        subprocess.check_output(
            ["pkg-config", "--exists", pkg_name], stderr=subprocess.DEVNULL, text=True
        )
        hailo_logger.debug(f"Package {pkg_name} exists in pkg-config.")
        return True
    except subprocess.CalledProcessError:
        hailo_logger.debug(f"Package {pkg_name} does not exist in pkg-config.")
        return False


def detect_system_pkg_version(pkg_name: str) -> str:
    hailo_logger.debug(f"Detecting system package version for: {pkg_name}")
    try:
        version = subprocess.check_output(
            ["dpkg-query", "-W", "-f=${Version}", pkg_name], stderr=subprocess.DEVNULL, text=True
        )
        version = version.strip()
        hailo_logger.debug(f"Found version {version} for system package {pkg_name}")
        return version
    except subprocess.CalledProcessError:
        hailo_logger.warning(f"System package {pkg_name} is not installed.")
        return ""


def detect_host_arch() -> str:
    hailo_logger.debug("Detecting host architecture.")
    machine_name = platform.machine().lower()
    system_name = platform.system().lower()
    hailo_logger.debug(f"Machine: {machine_name}, System: {system_name}")

    if machine_name in X86_POSSIBLE_NAME:
        hailo_logger.info("Detected host architecture: x86")
        return X86_NAME_I
    if machine_name in ARM_POSSIBLE_NAME:
        if system_name == LINUX_SYSTEM_NAME_I and platform.uname().node in RPI_POSSIBLE_NAME:
            hailo_logger.info("Detected host architecture: Raspberry Pi")
            return RPI_NAME_I
        hailo_logger.info("Detected host architecture: ARM")
        return ARM_NAME_I
    hailo_logger.warning("Unknown host architecture.")
    return UNKNOWN_NAME_I


def detect_hailo_arch() -> str | None:
    hailo_logger.debug("Detecting Hailo architecture using hailortcli.")
    try:
        args = shlex.split(HAILO_FW_CONTROL_CMD)
        res = subprocess.run(args, check=False, capture_output=True, text=True)
        if res.returncode != 0:
            hailo_logger.error(f"hailortcli failed with code {res.returncode}")
            return None
        for line in res.stdout.splitlines():
            if HAILO8L_ARCH_CAPS in line:
                hailo_logger.debug("Detected Hailo architecture: HAILO8L")
                return HAILO8L_ARCH
            if HAILO8_ARCH_CAPS in line:
                hailo_logger.debug("Detected Hailo architecture: HAILO8")
                return HAILO8_ARCH
            if HAILO10H_ARCH_CAPS in line or HAILO15H_ARCH_CAPS in line:
                hailo_logger.debug("Detected Hailo architecture: HAILO10H")
                return HAILO10H_ARCH
    except Exception as e:
        hailo_logger.exception(f"Error detecting Hailo architecture: {e}")
        return None
    hailo_logger.warning("Could not determine Hailo architecture.")
    return None


def detect_pkg_installed(pkg_name: str) -> bool:
    hailo_logger.debug(f"Checking if system package is installed: {pkg_name}")
    try:
        subprocess.check_output(["dpkg", "-s", pkg_name])
        hailo_logger.debug(f"Package {pkg_name} is installed.")
        return True
    except subprocess.CalledProcessError:
        hailo_logger.debug(f"Package {pkg_name} is not installed.")
        return False


def detect_pip_package_installed(pkg: str) -> bool:
    hailo_logger.debug(f"Checking if pip package is installed: {pkg}")
    try:
        result = subprocess.run(
            [PIP_CMD, "show", pkg],
            check=False,
            capture_output=True,
            text=True,
        )
        installed = result.returncode == 0
        hailo_logger.debug(f"Pip package {pkg} installed: {installed}")
        return installed
    except Exception as e:
        hailo_logger.exception(f"Error checking pip package {pkg}: {e}")
        return False


def detect_pip_package_version(pkg: str) -> str | None:
    hailo_logger.debug(f"Getting pip package version: {pkg}")
    try:
        output = run_command_with_output([PIP_CMD, "show", pkg])
        for line in output.splitlines():
            if line.startswith("Version:"):
                version = line.split(":", 1)[1].strip()
                hailo_logger.debug(f"Detected version {version} for pip package {pkg}")
                return version
    except Exception as e:
        hailo_logger.exception(f"Error getting version for pip package {pkg}: {e}")
    return None


def run_command(command, error_msg, logger=None):
    active_logger = logger or hailo_logger
    active_logger.info(f"Running: {command}")
    result = subprocess.run(command, check=False, shell=True)
    if result.returncode != 0:
        active_logger.error(f"{error_msg} (exit code {result.returncode})")
        exit(result.returncode)


def run_command_with_output(cmd: list[str]) -> str:
    hailo_logger.debug(f"Running command with output: {' '.join(cmd)}")
    result = subprocess.run(cmd, check=False, capture_output=True, text=True)
    if result.returncode != 0:
        hailo_logger.error(f"Command failed: {' '.join(cmd)}")
        raise RuntimeError(f"Command failed: {' '.join(cmd)}")
    return result.stdout


def create_symlink(src: str, dst: str) -> None:
    hailo_logger.debug(f"Creating symlink from {src} to {dst}")
    import os

    if os.path.islink(dst) or os.path.exists(dst):
        hailo_logger.debug(f"Removing existing path before symlink: {dst}")
        os.remove(dst)
    os.symlink(src, dst)


def get_hailort_package_name() -> str:
    """Get the appropriate HailoRT package name based on host architecture."""
    host_arch = detect_host_arch()
    if host_arch == RPI_NAME_I:
        hailo_logger.debug(f"Using RPI-specific HailoRT package: {HAILORT_PACKAGE_NAME_RPI}")
        return HAILORT_PACKAGE_NAME_RPI
    hailo_logger.debug(f"Using default HailoRT package: {HAILORT_PACKAGE_NAME}")
    return HAILORT_PACKAGE_NAME


def auto_detect_hailort_python_bindings() -> bool:
    hailo_logger.debug("Detecting HailoRT Python bindings.")
    pkg_name = get_hailort_package_name()
    if detect_pip_package_installed(pkg_name):
        hailo_logger.info("Detected HailoRT Python bindings installed.")
        return True
    hailo_logger.warning("HailoRT Python bindings not found.")
    return False


def auto_detect_hailort_version() -> str:
    hailo_logger.debug("Detecting installed HailoRT version.")
    pkg_name = get_hailort_package_name()
    if detect_pkg_installed(pkg_name):
        return detect_system_pkg_version(pkg_name)
    else:
        hailo_logger.warning("Could not detect HailoRT version, please install HailoRT.")
        return None


def auto_detect_tappas_variant() -> str:
    hailo_logger.debug("Detecting TAPPAS variant.")
    if detect_pkg_installed(HAILO_TAPPAS) or auto_detect_pkg_config(HAILO_TAPPAS):
        hailo_logger.info("Detected TAPPAS variant: HAILO_TAPPAS")
        return HAILO_TAPPAS
    elif (
        detect_pkg_installed(HAILO_TAPPAS_CORE)
        or auto_detect_pkg_config(HAILO_TAPPAS_CORE)
        or auto_detect_pkg_config("hailo-all")
    ):
        hailo_logger.info("Detected TAPPAS variant: HAILO_TAPPAS_CORE")
        return HAILO_TAPPAS_CORE
    else:
        hailo_logger.warning("Could not detect TAPPAS variant.")
        return None


def auto_detect_installed_tappas_python_bindings() -> bool:
    hailo_logger.debug("Detecting installed TAPPAS Python bindings.")
    if detect_pip_package_installed(HAILO_TAPPAS):
        hailo_logger.info("Detected TAPPAS Python bindings.")
        return True
    else:
        for pkg in HAILO_TAPPAS_CORE_PYTHON_NAMES:
            if detect_pip_package_installed(pkg):
                hailo_logger.info(f"Detected {pkg} Python bindings.")
                return True
    hailo_logger.warning("Could not detect TAPPAS Python bindings.")
    return False


def auto_detect_tappas_version(tappas_variant: str) -> str:
    hailo_logger.debug(f"Detecting TAPPAS version for variant: {tappas_variant}")
    if tappas_variant == HAILO_TAPPAS:
        return detect_pkg_config_version(HAILO_TAPPAS)
    elif tappas_variant == HAILO_TAPPAS_CORE:
        return detect_pkg_config_version(HAILO_TAPPAS_CORE)
    else:
        hailo_logger.warning("Could not detect TAPPAS version.")
        return None


def auto_detect_tappas_postproc_dir(tappas_variant: str) -> str:
    hailo_logger.debug(f"Detecting TAPPAS post-processing directory for variant: {tappas_variant}")
    if tappas_variant == HAILO_TAPPAS:
        workspace = run_command_with_output(
            ["pkg-config", "--variable=tappas_workspace", HAILO_TAPPAS]
        )
        return f"{workspace}/pipeline_apps/h8/gstreamer/libs/post_processes/"
    elif tappas_variant == HAILO_TAPPAS_CORE:
        return run_command_with_output(
            ["pkg-config", "--variable=tappas_postproc_lib_dir", HAILO_TAPPAS_CORE]
        )
    else:
        hailo_logger.error("Could not detect TAPPAS variant.")
        sys.exit(1)
