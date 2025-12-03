import importlib
import logging
import os
import subprocess
import sys
import yaml
from pathlib import Path

import pytest

from hailo_apps.python.core.common.defines import (
    DEFAULT_DOTENV_PATH,
    RESOURCES_ROOT_PATH_DEFAULT,
    RESOURCES_MODELS_DIR_NAME,
    RESOURCES_VIDEOS_DIR_NAME,
    RESOURCES_SO_DIR_NAME,
    RESOURCES_JSON_DIR_NAME,
    HAILO8_ARCH,
    HAILO8L_ARCH,
    HAILO10H_ARCH,
)
from hailo_apps.python.core.common.core import load_environment
from hailo_apps.python.core.common.installation_utils import (
    detect_hailo_arch,
    detect_host_arch,
    detect_pkg_installed,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("sanity-tests")

# Configuration paths
CONFIG_PATH = Path(__file__).parent / "test_config.yaml"
RESOURCES_CONFIG_PATH = Path(__file__).parent.parent / "hailo_apps" / "config" / "resources_config.yaml"


def load_sanity_config():
    """Load sanity check configuration from test_config.yaml (optional).
    
    Note: test_config.yaml is optional. If it doesn't exist, defaults will be used.
    The sanity check primarily uses resources_config.yaml for resource validation.
    """
    if not CONFIG_PATH.exists():
        logger.warning(f"Test configuration file not found: {CONFIG_PATH}, using defaults")
        return {}
    
    with open(CONFIG_PATH, 'r') as f:
        config = yaml.safe_load(f)
    
    # Get sanity_checks section from the bottom section (after END OF CONTROL SECTION)
    # We need to find it in the full config
    sanity_config = config.get("sanity_checks", {})
    return sanity_config


def load_resources_config():
    """Load resources configuration from resources_config.yaml."""
    if not RESOURCES_CONFIG_PATH.exists():
        logger.warning(f"Resources configuration file not found: {RESOURCES_CONFIG_PATH}")
        return {}
    
    with open(RESOURCES_CONFIG_PATH, 'r') as f:
        config = yaml.safe_load(f)
    
    return config


def test_check_hailo_runtime_installed():
    """Test if the Hailo runtime is installed."""
    try:
        subprocess.run(["hailortcli", "--version"], check=True, capture_output=True)
        print("Hailo runtime is installed.")
    except subprocess.CalledProcessError:
        pytest.fail("Error: Hailo runtime is not installed or not in PATH.")
    except FileNotFoundError:
        pytest.skip("Hailo runtime is not installed - skipping test on non-Hailo system.")


# TODO - Uncomment this test when the required files are changed to the current structure
# def test_check_required_files():
#     """Test if required project files and directories exist."""
#     project_root = Path(__file__).resolve().parents[1]

#     # Core files at project root
#     core_files = [
#         'LICENSE',
#         'MANIFEST.in',
#         'meson.build',
#         'pyproject.toml',
#         'README.md',
#         'requirements.txt',
#         'run_tests.sh',
#         'install.sh'
#     ]

#     # Script files
#     script_files = [
#         'scripts/compile_postprocess.sh',
#         'scripts/download_resources.sh',
#         'scripts/hailo_installation_script.sh'
#     ]

#     # Documentation files
#     doc_files = [
#         'doc/developer_guide.md',
#         'doc/development_guide.md',
#         'doc/installation_guide.md',
#         'doc/usage_of_all_pipelines.md'
#     ]

#     # C++ files
#     cpp_files = [
#         'cpp/depth_estimation.cpp',
#         'cpp/depth_estimation.hpp',
#         'cpp/hailo_nms_decode.hpp',
#         'cpp/__init__.py',
#         'cpp/mask_decoding.hpp',
#         'cpp/meson.build',
#         'cpp/remove_labels.cpp',
#         'cpp/remove_labels.hpp',
#         'cpp/yolo_hailortpp.cpp',
#         'cpp/yolo_hailortpp.hpp',
#         'cpp/yolov5seg.cpp',
#         'cpp/yolov5seg.hpp',
#         'cpp/yolov8pose_postprocess.cpp',
#         'cpp/yolov8pose_postprocess.hpp'
#     ]

#     # hailo_apps_infra modules and their internal files
#     module_files = [
#         # Common module
#         'hailo_apps_infra/common/pyproject.toml',
#         'hailo_apps_infra/common/hailo_common/get_config_values.py',
#         'hailo_apps_infra/common/hailo_common/get_usb_camera.py',
#         'hailo_apps_infra/common/hailo_common/common.py',
#         'hailo_apps_infra/common/hailo_common/__init__.py',
#         'hailo_apps_infra/common/hailo_common/test_utils.py',
#         'hailo_apps_infra/common/hailo_common/utils.py',

#         # Config module
#         'hailo_apps_infra/config/pyproject.toml',
#         'hailo_apps_infra/config/hailo_config/config.yaml',
#         'hailo_apps_infra/config/hailo_config/resources_config.yaml',

#         # GStreamer module
#         'hailo_apps_infra/gstreamer/pyproject.toml',
#         'hailo_apps_infra/gstreamer/hailo_gstreamer/gstreamer_app.py',
#         'hailo_apps_infra/gstreamer/hailo_gstreamer/gstreamer_helper_pipelines.py',
#         'hailo_apps_infra/gstreamer/hailo_gstreamer/__init__.py',

#         # Installation module
#         'hailo_apps_infra/installation/pyproject.toml',
#         'hailo_apps_infra/installation/hailo_installation/compile_cpp.py',
#         'hailo_apps_infra/installation/hailo_installation/download_resources.py',
#         'hailo_apps_infra/installation/hailo_installation/__init__.py',
#         'hailo_apps_infra/installation/hailo_installation/post_install.py',
#         'hailo_apps_infra/installation/hailo_installation/python_installation.py',
#         'hailo_apps_infra/installation/hailo_installation/set_env.py',
#         'hailo_apps_infra/installation/hailo_installation/validate_config.py',

#         # Pipelines module
#         'hailo_apps_infra/pipelines/pyproject.toml',
#         'hailo_apps_infra/pipelines/hailo_pipelines/depth_pipeline.py',
#         'hailo_apps_infra/pipelines/hailo_pipelines/detection_pipeline.py',
#         'hailo_apps_infra/pipelines/hailo_pipelines/detection_pipeline_simple.py',
#         'hailo_apps_infra/pipelines/hailo_pipelines/__init__.py',
#         'hailo_apps_infra/pipelines/hailo_pipelines/instance_segmentation_pipeline.py',
#         'hailo_apps_infra/pipelines/hailo_pipelines/pose_estimation_pipeline.py'
#     ]

#     required_paths = core_files + script_files + doc_files + cpp_files + module_files
#     missing = [path for path in required_paths if not (project_root / path).exists()]

#     if missing:
#         pytest.fail(f"The following required files or directories are missing: {', '.join(missing)}")


def test_check_resource_directory():
    """Test if the resources directory exists and has expected subdirectories."""
    # Load configurations
    sanity_config = load_sanity_config()
    resources_config = load_resources_config()
    
    # Get resources root - check environment variable first, then default
    resource_root = os.environ.get("RESOURCES_PATH", RESOURCES_ROOT_PATH_DEFAULT)
    resource_dir = Path(resource_root)
    
    # Also check local resources directory
    local_resource_dir = Path(__file__).resolve().parents[1] / "resources"
    if not resource_dir.exists() and local_resource_dir.exists():
        resource_dir = local_resource_dir
        logger.info(f"Using local resources directory: {resource_dir}")

    # Check if the resources directory exists
    if not resource_dir.exists():
        pytest.fail(f"Resources directory does not exist: {resource_dir}")

    # Check directory structure
    models_dir = resource_dir / RESOURCES_MODELS_DIR_NAME
    videos_dir = resource_dir / RESOURCES_VIDEOS_DIR_NAME
    so_dir = resource_dir / RESOURCES_SO_DIR_NAME
    json_dir = resource_dir / RESOURCES_JSON_DIR_NAME
    
    # Get expected resources from resources_config.yaml
    missing_resources = []
    found_resources = []
    
    # Check videos
    if resources_config and "videos" in resources_config:
        for video_entry in resources_config["videos"]:
            video_name = video_entry.get("name", "")
            if video_name:
                video_path = videos_dir / video_name
                if video_path.exists():
                    found_resources.append(f"videos/{video_name}")
                else:
                    missing_resources.append(f"videos/{video_name}")
    
    # Check SO files (postprocess libraries)
    if resources_config:
        # Get all apps and check for required SO files
        required_so_files = sanity_config.get("required_resources", [
            "libdepth_postprocess.so",
            "libyolo_hailortpp_postprocess.so",
            "libyolov5seg_postprocess.so",
            "libyolov8pose_postprocess.so",
        ])
        
        for so_file in required_so_files:
            so_path = so_dir / so_file
            if so_path.exists():
                found_resources.append(f"so/{so_file}")
            else:
                missing_resources.append(f"so/{so_file}")
    
    if missing_resources:
        logger.warning(f"The following resource files are missing: {', '.join(missing_resources)}")
        logger.warning(
            "This might be normal if resources haven't been downloaded yet, but will cause tests to fail."
        )
    else:
        logger.info(f"Found all required resources: {len(found_resources)} files")

    # Check for HEF files in architecture-specific subdirectories
    hef_files = []
    arch_dirs = [HAILO8_ARCH, HAILO8L_ARCH, HAILO10H_ARCH]
    
    for arch in arch_dirs:
        arch_models_dir = models_dir / arch
        if arch_models_dir.exists():
            arch_hefs = list(arch_models_dir.glob("*.hef"))
            hef_files.extend(arch_hefs)
            if arch_hefs:
                logger.info(f"Found {len(arch_hefs)} HEF files in {arch_models_dir}")
    
    if not hef_files:
        logger.warning("No HEF files found in resources/models/<arch> directories. Tests will likely fail.")
    else:
        logger.info(f"Found {len(hef_files)} HEF files total across all architectures")
        # Show sample of HEF files
        sample_hefs = [str(f.relative_to(resource_dir)) for f in hef_files[:5]]
        logger.info(f"Sample HEF files: {', '.join(sample_hefs)}")
        if len(hef_files) > 5:
            logger.info(f"... and {len(hef_files) - 5} more")

    # Check for JSON configuration files
    if json_dir.exists():
        json_files = list(json_dir.glob("*.json"))
        if not json_files:
            logger.warning("No JSON configuration files found in resources/json directory.")
        else:
            logger.info(f"Found {len(json_files)} JSON files: {', '.join(f.name for f in json_files)}")
    else:
        logger.warning(f"JSON directory does not exist: {json_dir}")


def test_python_environment():
    """Test the Python environment and required packages."""
    # Check Python version
    assert sys.version_info >= (3, 6), "Python 3.6 or higher is required."

    # Load configuration
    sanity_config = load_sanity_config()
    
    # Get packages from config or use defaults
    critical_packages = sanity_config.get("required_packages", [
        "gi",  # GStreamer bindings
        "numpy",  # Data manipulation
        "opencv-python",  # Computer vision
        "hailo",  # Hailo API
    ])

    # Additional packages that are useful but not critical
    additional_packages = sanity_config.get("optional_packages", [
        "setproctitle",
        "python-dotenv",
    ])

    # Test critical packages first
    missing_critical = []
    for package in critical_packages:
        try:
            if package == "opencv-python":
                import cv2

                print(f"opencv-python is installed. Version: {cv2.__version__}")
            else:
                importlib.import_module(package)
                print(f"{package} is installed.")
        except ImportError:
            missing_critical.append(package)

    if missing_critical:
        pytest.fail(f"Critical packages missing: {', '.join(missing_critical)}")

    # Test additional packages
    missing_additional = []
    for package in additional_packages:
        try:
            importlib.import_module(package)
            print(f"{package} is installed.")
        except ImportError:
            missing_additional.append(package)

    if missing_additional:
        print(f"Warning: Some additional packages are missing: {', '.join(missing_additional)}")


def test_gstreamer_installation():
    """Test GStreamer installation and required plugins."""
    try:
        # Test basic GStreamer installation
        result = subprocess.run(
            ["gst-inspect-1.0", "--version"],
            check=True,
            capture_output=True,
        )
        print(f"GStreamer is installed: {result.stdout.decode('utf-8').strip()}")

        # Load configuration
        sanity_config = load_sanity_config()
        
        # Get critical elements from config or use defaults
        gstreamer_config = sanity_config.get("gstreamer_elements", {})
        critical_elements = gstreamer_config.get("critical", [
            "videotestsrc",  # Basic video source
            "appsink",  # Used for custom callbacks
            "videoconvert",  # Used for format conversion
            "autovideosink",  # Display sink
        ])

        missing_elements = []
        for element in critical_elements:
            result = subprocess.run(
                ["gst-inspect-1.0", element],
                check=False,
                capture_output=True,
            )
            if result.returncode != 0:
                missing_elements.append(element)

        if missing_elements:
            pytest.fail(f"Critical GStreamer elements missing: {', '.join(missing_elements)}")

    except subprocess.CalledProcessError:
        pytest.fail("GStreamer is not properly installed or not in PATH.")
    except FileNotFoundError:
        pytest.fail("GStreamer command-line tools are not installed.")


def test_hailo_gstreamer_elements():
    """Test if Hailo GStreamer elements are installed."""
    # First check if we have a Hailo device
    hailo_arch = detect_hailo_arch()
    if hailo_arch is None:
        pytest.skip("No Hailo device detected - skipping Hailo GStreamer element check.")

    try:
        # Load configuration
        sanity_config = load_sanity_config()
        
        # Get Hailo elements from config or use defaults
        gstreamer_config = sanity_config.get("gstreamer_elements", {})
        hailo_elements = gstreamer_config.get("hailo", [
            "hailonet",  # Inference element
            "hailofilter",  # Used for post-processing
        ])

        missing_elements = []
        for element in hailo_elements:
            result = subprocess.run(
                ["gst-inspect-1.0", element],
                check=False,
                capture_output=True,
            )
            if result.returncode != 0:
                missing_elements.append(element)

        if missing_elements:
            pytest.fail(
                f"Hailo GStreamer elements missing: {', '.join(missing_elements)}. "
                f"These are required for Hailo inference pipelines."
            )
        else:
            logger.info("All Hailo GStreamer elements are installed.")

    except subprocess.CalledProcessError:
        pytest.fail("GStreamer installation issue - cannot check Hailo elements.")
    except FileNotFoundError:
        pytest.fail("GStreamer command-line tools not found - cannot check Hailo elements.")


def test_arch_specific_environment():
    """Test architecture-specific environment components."""
    # Use the utility function from hailo_rpi_common
    device_arch = detect_host_arch()
    logger.info(f"Detected device architecture: {device_arch}")

    # Arch-specific checks
    if device_arch == "rpi":
        # Raspberry Pi specific checks
        try:
            from importlib.utils import find_spec

            if find_spec("picamera2") is not None:
                logger.info("picamera2 is installed. RPi camera module can be used.")
            else:
                logger.warning(
                    "picamera2 is not installed. This is needed for using the RPi camera module."
                )
        except ImportError:
            logger.warning(
                "picamera2 is not installed. This is needed for using the RPi camera module."
            )

    elif device_arch == "arm":
        # General ARM checks (non-RPi)
        logger.info("Running on ARM architecture (non-Raspberry Pi).")

    elif device_arch == "x86":
        # x86 specific checks
        logger.info("Running on x86 architecture.")

    else:
        logger.warning(f"Unknown architecture: {device_arch}")


def test_setup_installation():
    """Test package installation from setup.py."""
    try:
        result = subprocess.run(["pip", "list"], check=False, capture_output=True, text=True)

        if "hailo-apps-infra" in result.stdout:
            logger.info("hailo-apps-infra package is installed.")
        else:
            logger.warning(
                "hailo-apps-infra package is not installed. Run 'pip install -e .' to install in development mode."
            )

    except subprocess.CalledProcessError:
        pytest.fail("Failed to check pip packages.")


def test_environment_variables():
    """Test if required environment variables are set."""
    # Load .env file first
    repo_env_file = Path(__file__).resolve().parents[1] / "resources" / ".env"
    if repo_env_file.exists():
        logger.info(f"Loading .env file from: {repo_env_file}")
        load_environment(env_file=str(repo_env_file), required_vars=None)
    else:
        logger.info(f"Loading .env file from default location: {DEFAULT_DOTENV_PATH}")
        load_environment(env_file=DEFAULT_DOTENV_PATH, required_vars=None)
    
    # Detect and set environment variables if not already set
    host_arch = detect_host_arch()
    hailo_arch = detect_hailo_arch()
    
    # Set in current process environment
    os.environ["HOST_ARCH"] = host_arch
    if hailo_arch:
        os.environ["HAILO_ARCH"] = hailo_arch
    
    # Check for key environment variables
    env_vars = {
        "HOST_ARCH": host_arch,
        "HAILO_ARCH": hailo_arch or "unknown",
    }

    # Check if environment variables are set
    for var, expected_value in env_vars.items():
        actual_value = os.environ.get(var)
        if actual_value:
            logger.info(f"Environment variable {var}={actual_value}")
            # Optional: verify if variable matches expected value
            if actual_value != expected_value and expected_value != "unknown":
                logger.warning(
                    f"Environment variable {var} has value {actual_value}, but detected value is {expected_value}"
                )
        else:
            logger.warning(f"Environment variable {var} is not set")

    # Check for TAPPAS-related environment variables
    if "TAPPAS_POST_PROC_DIR" in os.environ:
        post_proc_dir = os.environ["TAPPAS_POST_PROC_DIR"]
        logger.info(f"TAPPAS_POST_PROC_DIR={post_proc_dir}")

        # Check if directory exists
        if post_proc_dir and not os.path.exists(post_proc_dir):
            logger.warning(
                f"TAPPAS_POST_PROC_DIR points to non-existent directory: {post_proc_dir}"
            )
    # Check which TAPPAS variant is installed
    elif detect_pkg_installed("hailo-tappas"):
        logger.warning("hailo-tappas is installed but TAPPAS_POST_PROC_DIR is not set")
    elif detect_pkg_installed("hailo-tappas-core"):
        logger.warning("hailo-tappas-core is installed but TAPPAS_POST_PROC_DIR is not set")

    # Check if .env file exists
    env_file = Path(__file__).resolve().parents[1] / "resources" / ".env"
    if env_file.exists():
        logger.info(f".env file exists at {env_file}")
        # Optionally read and check the content
        try:
            with open(env_file) as f:
                env_content = f.read()
                logger.info(f".env file content: {env_content.strip()}")
        except Exception as e:
            logger.warning(f"Could not read .env file: {e}")
    else:
        logger.warning(f".env file does not exist at {env_file}")
        logger.warning("You may need to run the setup script to create it.")


if __name__ == "__main__":
    pytest.main(["-v", __file__])
