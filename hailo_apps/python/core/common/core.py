"""Core helpers: arch detection, parser, buffer utils, model resolution."""

import argparse
import os
import queue
import sys
from pathlib import Path

from dotenv import load_dotenv

from .defines import (
    DEFAULT_DOTENV_PATH,
    DEFAULT_LOCAL_RESOURCES_PATH,
    DEPTH_MODEL_NAME,
    DEPTH_PIPELINE,
    DETECTION_MODEL_NAME_H8,
    DETECTION_MODEL_NAME_H8L,
    DETECTION_PIPELINE,
    DIC_CONFIG_VARIANTS,
    FACE_DETECTION_MODEL_NAME_H8,
    FACE_DETECTION_MODEL_NAME_H8L,
    FACE_DETECTION_PIPELINE,
    FACE_RECOGNITION_MODEL_NAME_H8,
    FACE_RECOGNITION_MODEL_NAME_H8L,
    FACE_RECOGNITION_PIPELINE,
    HAILO8_ARCH,
    HAILO8L_ARCH,
    HAILO10H_ARCH,
    HAILO_ARCH_KEY,
    HAILO_FILE_EXTENSION,
    INSTANCE_SEGMENTATION_MODEL_NAME_H8,
    INSTANCE_SEGMENTATION_MODEL_NAME_H8L,
    INSTANCE_SEGMENTATION_PIPELINE,
    POSE_ESTIMATION_MODEL_NAME_H8,
    POSE_ESTIMATION_MODEL_NAME_H8L,
    POSE_ESTIMATION_PIPELINE,
    RESOURCES_JSON_DIR_NAME,
    RESOURCES_MODELS_DIR_NAME,
    # for get_resource_path
    RESOURCES_PHOTOS_DIR_NAME,
    RESOURCES_ROOT_PATH_DEFAULT,
    RESOURCES_SO_DIR_NAME,
    RESOURCES_VIDEOS_DIR_NAME,
    SIMPLE_DETECTION_MODEL_NAME,
    SIMPLE_DETECTION_PIPELINE,
    CLIP_PIPELINE,
    CLIP_MODEL_NAME,
    CLIP_DETECTION_PIPELINE,
    CLIP_DETECTION_MODEL_NAME
)
from .hailo_logger import add_logging_cli_args, get_logger
from .installation_utils import detect_hailo_arch

hailo_logger = get_logger(__name__)


def load_environment(env_file=DEFAULT_DOTENV_PATH, required_vars=None) -> bool:
    hailo_logger.debug(f"Loading environment from: {env_file}")
    if env_file is None:
        env_file = DEFAULT_DOTENV_PATH
    load_dotenv(dotenv_path=env_file)

    env_path = Path(env_file)
    if not os.path.exists(env_path):
        hailo_logger.warning(f".env file not found: {env_file}")
        return False
    if not os.access(env_path, os.R_OK):
        hailo_logger.warning(f".env file not readable: {env_file}")
        return False
    if not os.access(env_path, os.W_OK):
        hailo_logger.warning(f".env file not writable: {env_file}")
        return False
    if not os.access(env_path, os.F_OK):
        hailo_logger.warning(f".env file not found (F_OK): {env_file}")
        return False

    if required_vars is None:
        required_vars = DIC_CONFIG_VARIANTS
    missing = []
    for var in required_vars:
        value = os.getenv(var)
        if not value:
            missing.append(var)

    if missing:
        hailo_logger.warning(f"Missing environment variables: {missing}")
        return False
    hailo_logger.info("All required environment variables loaded successfully.")
    return True


def get_base_parser():
    """
    Creates the base argument parser with core flags shared by all Hailo applications.

    This parser defines the standard interface for common functionality across
    all applications, ensuring consistent flag naming and behavior.

    Returns:
        argparse.ArgumentParser: Base parser with core flags
    """
    hailo_logger.debug("Creating base argparse parser.")
    parser = argparse.ArgumentParser(
        description="Hailo Application Base Parser",
        add_help=False  # Allow parent parsers to control help display
    )

    # Logging configuration group
    log_group = parser.add_argument_group('logging options', 'Configure logging behavior')
    add_logging_cli_args(log_group)

    # Core input/output flags
    parser.add_argument(
        "--input", "-i",
        type=str,
        default=None,
        help=(
            "Input source for processing. Can be a file path (image or video), "
            "camera index (integer), folder path containing images, or RTSP URL. "
            "For USB cameras, use 'usb' to auto-detect or '/dev/video<X>' for a specific device. "
            "For Raspberry Pi camera, use 'rpi'. If not specified, defaults to application-specific source."
        )
    )

    parser.add_argument(
        "--hef-path", "-n",
        type=str,
        default=None,
        help=(
            "Path or name of Hailo Executable Format (HEF) model file. "
            "Can be: (1) full path to .hef file, (2) model name (will search in resources), "
            "or (3) model name from available models (will auto-download if not found). "
            "If not specified, uses the default model for this application."
        )
    )

    parser.add_argument(
        "--list-models",
        action="store_true",
        help=(
            "List all available models for this application and exit. "
            "Shows default and extra models that can be used with --hef-path."
        )
    )

    parser.add_argument(
        "--batch-size", "-b",
        type=int,
        default=1,
        help=(
            "Number of frames or images to process in parallel during inference. "
            "Higher batch sizes can improve throughput but require more memory. "
            "Default is 1 (sequential processing)."
        )
    )

    parser.add_argument(
        "--labels", "-l",
        type=str,
        default=None,
        help=(
            "Path to a text file containing class labels, one per line. "
            "Used for mapping model output indices to human-readable class names. "
            "If not specified, default labels for the model will be used (e.g., COCO labels for detection models)."
        )
    )

    parser.add_argument(
        "--width", "-W",
        type=int,
        default=None,
        help=(
            "Custom output width in pixels for video or image output. "
            "If specified, the output will be resized to this width while maintaining aspect ratio. "
            "If not specified, uses the input resolution or model default."
        )
    )

    parser.add_argument(
        "--height", "-H",
        type=int,
        default=None,
        help=(
            "Custom output height in pixels for video or image output. "
            "If specified, the output will be resized to this height while maintaining aspect ratio. "
            "If not specified, uses the input resolution or model default."
        )
    )

    parser.add_argument(
        "--arch", "-a",
        type=str,
        default=None,
        choices=["hailo8", "hailo8l", "hailo10h"],
        help=(
            "Target Hailo architecture for model execution. "
            "Options: 'hailo8' (Hailo-8 processor), 'hailo8l' (Hailo-8L processor), "
            "'hailo10h' (Hailo-10H processor). "
            "If not specified, the architecture will be auto-detected from the connected device."
        )
    )

    parser.add_argument(
        "--show-fps",
        action="store_true",
        help=(
            "Enable FPS (frames per second) counter display. "
            "When enabled, the application will display real-time performance metrics "
            "showing the current processing rate. Useful for performance monitoring and optimization."
        )
    )

    parser.add_argument(
        "--save-output", "-s",
        action="store_true",
        help=(
            "Enable output file saving. When enabled, processed images or videos will be saved to disk. "
            "The output location is determined by the --output-dir flag (for standalone apps) "
            "or application-specific defaults. Without this flag, output is only displayed (if applicable)."
        )
    )

    parser.add_argument(
        "--frame-rate", "-f",
        type=int,
        default=30,
        help=(
            "Target frame rate for video processing in frames per second. "
            "Controls the playback speed and processing rate for video sources. "
            "Default is 30 FPS. Lower values reduce processing load, higher values increase throughput."
        )
    )

    return parser


def get_pipeline_parser():
    """
    Creates an argument parser for GStreamer pipeline applications.

    This parser extends the base parser with pipeline-specific flags for
    GStreamer-based applications that process video streams in real-time.

    Returns:
        argparse.ArgumentParser: Parser with base and pipeline-specific flags
    """
    hailo_logger.debug("Creating pipeline argparse parser.")
    base_parser = get_base_parser()
    parser = argparse.ArgumentParser(
        description="Hailo GStreamer Pipeline Application",
        parents=[base_parser],
        add_help=True  # Enable --help flag to show all available options
    )

    parser.add_argument(
        "--use-frame",
        action="store_true",
        help=(
            "Enable frame access in callback functions. "
            "When enabled, the callback function receives access to the raw frame data, "
            "allowing for custom processing, analysis, or visualization within the pipeline. "
            "Useful for applications that need to perform additional operations on individual frames."
        )
    )

    parser.add_argument(
        "--disable-sync",
        action="store_true",
        help=(
            "Disable display sink synchronization. "
            "When enabled, the pipeline will process frames as fast as possible without waiting "
            "for display synchronization. This is particularly useful when processing from file sources "
            "where you want maximum throughput rather than real-time playback speed."
        )
    )

    parser.add_argument(
        "--disable-callback",
        action="store_true",
        help=(
            "Skip user callback execution. "
            "When enabled, the pipeline will run without invoking custom callback functions, "
            "processing frames through the standard pipeline only. Useful for performance testing "
            "or when you want to run the pipeline without custom post-processing logic."
        )
    )

    parser.add_argument(
        "--dump-dot",
        action="store_true",
        help=(
            "Export pipeline graph to DOT file. "
            "When enabled, the GStreamer pipeline structure will be saved as a Graphviz DOT file "
            "(typically named 'pipeline.dot'). This file can be visualized using tools like 'dot' "
            "to understand the pipeline topology and debug pipeline configuration issues."
        )
    )

    parser.add_argument(
        "--enable-watchdog",
        action="store_true",
        help=(
            "Enable pipeline watchdog. "
            "When enabled, the pipeline will be monitored for stalled frame processing. "
            "If no frames are processed for the configured timeout, the pipeline will be automatically "
            "rebuilt. Note: This requires the application callback to be enabled (i.e., not disabled via --disable-callback)."
        )
    )

    return parser


def get_standalone_parser():
    """
    Creates an argument parser for standalone processing applications.

    This parser extends the base parser with standalone-specific flags for
    applications that process files or batches without GStreamer pipelines.

    Returns:
        argparse.ArgumentParser: Parser with base and standalone-specific flags
    """
    hailo_logger.debug("Creating standalone argparse parser.")
    base_parser = get_base_parser()
    parser = argparse.ArgumentParser(
        description="Hailo Standalone Processing Application",
        parents=[base_parser],
        add_help=True  # Enable --help flag to show all available options
    )

    parser.add_argument(
        "--track",
        action="store_true",
        help=(
            "Enable object tracking for detections. "
            "When enabled, detected objects will be tracked across frames using a tracking algorithm "
            "(e.g., ByteTrack). This assigns consistent IDs to objects over time, enabling temporal analysis, "
            "trajectory visualization, and multi-frame association. Useful for video processing applications."
        )
    )

    parser.add_argument(
        "--resolution", "-r",
        type=str,
        choices=["sd", "hd", "fhd"],
        default="sd",
        help=(
            "Predefined resolution for camera input sources. "
            "Options: 'sd' (640x480, Standard Definition), 'hd' (1280x720, High Definition), "
            "'fhd' (1920x1080, Full High Definition). "
            "Default is 'sd'. This flag is only applicable when using camera input sources."
        )
    )

    parser.add_argument(
        "--output-dir", "-o",
        type=str,
        default=None,
        help=(
            "Directory where output files will be saved. "
            "When --save-output is enabled, processed images, videos, or result files will be "
            "written to this directory. If not specified, outputs are saved to a default location "
            "or the current working directory. The directory will be created if it does not exist."
        )
    )

    return parser


def get_default_parser():
    """
    Legacy function for backward compatibility.

    Returns the pipeline parser as the default to maintain compatibility
    with existing code that uses get_default_parser().

    Returns:
        argparse.ArgumentParser: Pipeline parser (for backward compatibility)

    .. deprecated::
        Use :func:`get_pipeline_parser` or :func:`get_standalone_parser` instead.
    """
    import warnings
    warnings.warn(
        "get_default_parser() is deprecated. Use get_pipeline_parser() or get_standalone_parser() instead.",
        DeprecationWarning,
        stacklevel=2
    )
    return get_pipeline_parser()


def get_model_name(pipeline_name: str, arch: str) -> str:
    hailo_logger.debug(f"Getting model name for pipeline={pipeline_name}, arch={arch}")
    is_h8 = arch in (HAILO8_ARCH, HAILO10H_ARCH)
    pipeline_map = {
        DEPTH_PIPELINE: DEPTH_MODEL_NAME,
        CLIP_PIPELINE: CLIP_MODEL_NAME,
        CLIP_DETECTION_PIPELINE: CLIP_DETECTION_MODEL_NAME,
        SIMPLE_DETECTION_PIPELINE: SIMPLE_DETECTION_MODEL_NAME,
        DETECTION_PIPELINE: DETECTION_MODEL_NAME_H8 if is_h8 else DETECTION_MODEL_NAME_H8L,
        INSTANCE_SEGMENTATION_PIPELINE: INSTANCE_SEGMENTATION_MODEL_NAME_H8
        if is_h8
        else INSTANCE_SEGMENTATION_MODEL_NAME_H8L,
        POSE_ESTIMATION_PIPELINE: POSE_ESTIMATION_MODEL_NAME_H8
        if is_h8
        else POSE_ESTIMATION_MODEL_NAME_H8L,
        FACE_DETECTION_PIPELINE: FACE_DETECTION_MODEL_NAME_H8
        if is_h8
        else FACE_DETECTION_MODEL_NAME_H8L,
        FACE_RECOGNITION_PIPELINE: FACE_RECOGNITION_MODEL_NAME_H8
        if is_h8
        else FACE_RECOGNITION_MODEL_NAME_H8L
    }
    name = pipeline_map[pipeline_name]
    hailo_logger.debug(f"Resolved model name: {name}")
    return name


def get_resource_path(
    pipeline_name: str, resource_type: str, arch: str | None = None, model: str | None = None
) -> Path | None:
    hailo_logger.debug(
        f"Getting resource path for pipeline={pipeline_name}, resource_type={resource_type}, model={model}"
    )
    root = Path(RESOURCES_ROOT_PATH_DEFAULT)
    # Auto-detect arch if not provided and needed for RESOURCES_MODELS_DIR_NAME
    if arch is None and resource_type == RESOURCES_MODELS_DIR_NAME:
        arch = os.getenv(HAILO_ARCH_KEY) or detect_hailo_arch()
        hailo_logger.debug(f"Auto-detected arch: {arch}")
    if not arch and resource_type == RESOURCES_MODELS_DIR_NAME:
        hailo_logger.error("Could not detect Hailo architecture.")
        assert False, "Could not detect Hailo architecture."


    if resource_type == RESOURCES_SO_DIR_NAME and model:
        return root / RESOURCES_SO_DIR_NAME / model
    if resource_type == RESOURCES_VIDEOS_DIR_NAME and model:
        return root / RESOURCES_VIDEOS_DIR_NAME / model
    if resource_type == RESOURCES_PHOTOS_DIR_NAME and model:
        return root / RESOURCES_PHOTOS_DIR_NAME / model
    if resource_type == RESOURCES_JSON_DIR_NAME and model:
        return root / RESOURCES_JSON_DIR_NAME / model
    if resource_type == DEFAULT_LOCAL_RESOURCES_PATH and model:
        return root / DEFAULT_LOCAL_RESOURCES_PATH / model

    if resource_type == RESOURCES_MODELS_DIR_NAME:
        if model:
            model_path = root / RESOURCES_MODELS_DIR_NAME / arch / model
            if "." in model:
                return model_path.with_name(model_path.name + HAILO_FILE_EXTENSION)
            return model_path.with_suffix(HAILO_FILE_EXTENSION)
        if pipeline_name:
            name = get_model_name(pipeline_name, arch)
            name_path = root / RESOURCES_MODELS_DIR_NAME / arch / name
            if "." in name:
                return name_path.with_name(name_path.name + HAILO_FILE_EXTENSION)
            return name_path.with_suffix(HAILO_FILE_EXTENSION)
    return None


class FIFODropQueue(queue.Queue):
    def put(self, item, block=False, timeout=None):
        if self.full():
            hailo_logger.debug("Queue full, dropping oldest item.")
            self.get_nowait()
        super().put(item, block, timeout)


# =============================================================================
# Model Resolution and Listing
# =============================================================================

def list_models_for_app(app_name: str, arch: str | None = None) -> None:
    """
    List all available models for an application and exit.
    
    Args:
        app_name: The app name from resources config (e.g., 'detection', 'vlm_chat')
        arch: Hailo architecture. If None, auto-detects.
    """
    try:
        from hailo_apps.installation.config_utils import (
            get_default_models_for_app_and_arch,
            get_extra_models_for_app_and_arch,
            get_supported_architectures_for_app,
            is_gen_ai_app,
        )
    except ImportError:
        print("Error: Could not import config_utils. Run 'pip install -e .' first.")
        sys.exit(1)
    
    # Detect architecture if not provided
    if arch is None:
        arch = os.getenv(HAILO_ARCH_KEY) or detect_hailo_arch()
        if not arch:
            arch = HAILO8_ARCH
    
    print(f"\n{'=' * 60}")
    print(f"Available models for: {app_name} ({arch})")
    print(f"{'=' * 60}")
    
    # Check if architecture is supported
    supported_archs = get_supported_architectures_for_app(app_name)
    if arch not in supported_archs:
        if is_gen_ai_app(app_name):
            print(f"\n⚠️  This is a Gen-AI app, only available on: {', '.join(supported_archs)}")
        else:
            print(f"\n⚠️  Architecture '{arch}' not supported. Available: {', '.join(supported_archs)}")
        print()
        sys.exit(0)
    
    # Get models
    default_models = get_default_models_for_app_and_arch(app_name, arch)
    extra_models = get_extra_models_for_app_and_arch(app_name, arch)
    
    if default_models:
        print("\n📦 Default Models:")
        for model in default_models:
            print(f"   • {model}")
    else:
        print("\n📦 Default Models: None")
    
    if extra_models:
        print("\n📚 Extra Models:")
        for model in extra_models:
            print(f"   • {model}")
    
    print(f"\n{'=' * 60}")
    print(f"Total: {len(default_models)} default, {len(extra_models)} extra")
    print("\nUsage: --hef-path <model_name>")
    print("       Model will be auto-downloaded if not found locally.")
    print()
    sys.exit(0)


def resolve_hef_path(
    hef_path: str | None,
    app_name: str,
    arch: str
) -> Path | None:
    """
    Smart HEF path resolution with auto-download capability.
    
    Resolution order:
    1. If hef_path is None, use default model for the app
    2. If hef_path is a full path that exists, use it
    3. If hef_path is in the resources folder, use it
    4. If hef_path is a known model name, download it
    
    Args:
        hef_path: User-provided path or model name (can be None)
        app_name: App name from resources config (e.g., 'detection') - use pipeline constants like DETECTION_PIPELINE
        arch: Hailo architecture
    
    Returns:
        Resolved Path to the HEF file, or None if not found
    """
    try:
        from hailo_apps.installation.config_utils import (
            get_all_models_for_app_and_arch,
            get_default_model_for_app_and_arch,
        )
    except ImportError:
        hailo_logger.warning("Could not import config_utils, using legacy resolution")
        # Fallback to legacy resolution
        if hef_path is None:
            return get_resource_path(app_name, RESOURCES_MODELS_DIR_NAME, arch)
        return Path(hef_path) if hef_path else None
    
    resources_root = Path(RESOURCES_ROOT_PATH_DEFAULT)
    models_dir = resources_root / RESOURCES_MODELS_DIR_NAME / arch
    
    # Get available models for this app/arch
    available_models = get_all_models_for_app_and_arch(app_name, arch)
    default_model = get_default_model_for_app_and_arch(app_name, arch)
    is_using_default = False
    
    # Case 1: No hef_path provided - use default model
    if hef_path is None:
        if default_model:
            hef_path = default_model
            is_using_default = True
            hailo_logger.info(f"Using default model: {default_model}")
        else:
            # Fallback to legacy pipeline-based model
            legacy_path = get_resource_path(app_name, RESOURCES_MODELS_DIR_NAME, arch)
            if legacy_path and legacy_path.exists():
                return legacy_path
            hailo_logger.error(f"No default model found for {app_name}/{arch}")
            return None
    
    # Normalize model name (remove .hef if present)
    model_name = hef_path
    if model_name.endswith(HAILO_FILE_EXTENSION):
        model_name = model_name[:-len(HAILO_FILE_EXTENSION)]
    
    # Case 2: Check if it's a full path that exists
    hef_full_path = Path(hef_path)
    if hef_full_path.is_absolute() and hef_full_path.exists():
        hailo_logger.info(f"Using HEF from absolute path: {hef_full_path}")
        return hef_full_path
    
    # Also check with .hef extension
    if not hef_path.endswith(HAILO_FILE_EXTENSION):
        hef_full_path = Path(hef_path + HAILO_FILE_EXTENSION)
        if hef_full_path.exists():
            hailo_logger.info(f"Using HEF from path: {hef_full_path}")
            return hef_full_path
    
    # Case 3: Check in resources folder
    resource_path = models_dir / f"{model_name}{HAILO_FILE_EXTENSION}"
    if resource_path.exists():
        hailo_logger.info(f"Found HEF in resources: {resource_path}")
        return resource_path
    
    # Case 4: Model not found locally - check if it's in the available models list
    if model_name in available_models:
        # Show warning before downloading
        if is_using_default:
            print(f"\n⚠️  WARNING: Default model '{model_name}' is not downloaded.")
            print(f"   Downloading model for {app_name}/{arch}...")
            print(f"   This may take a while depending on your internet connection.\n")
        else:
            print(f"\n⚠️  WARNING: Model '{model_name}' is not downloaded.")
            print(f"   Downloading model for {app_name}/{arch}...")
            print(f"   This may take a while depending on your internet connection.\n")
        
        if _download_model(model_name, arch):
            if resource_path.exists():
                hailo_logger.info(f"Model downloaded successfully: {resource_path}")
                return resource_path
            else:
                hailo_logger.error(f"Download succeeded but file not found: {resource_path}")
                return None
        else:
            hailo_logger.error(f"Failed to download model: {model_name}")
            return None
    
    # Model not in available list - don't auto-download unknown models
    hailo_logger.error(
        f"Model '{model_name}' not found and not in available models list. "
        f"Available models for {app_name}/{arch}: {', '.join(available_models) if available_models else 'None'}"
    )
    return None


def _download_model(model_name: str, arch: str) -> bool:
    """
    Download a specific model using the download_resources module.
    
    Args:
        model_name: Name of the model to download
        arch: Hailo architecture
    
    Returns:
        True if download succeeded, False otherwise
    """
    try:
        from hailo_apps.installation.download_resources import download_resources
        
        print(f"Downloading model: {model_name} for {arch}...")
        download_resources(
            arch=arch,
            model=model_name,
            dry_run=False,
            force=False,
            parallel=False  # Sequential for single model
        )
        return True
    except Exception as e:
        hailo_logger.error(f"Failed to download model: {e}")
        return False


def handle_list_models_flag(args, app_name: str) -> None:
    """
    Handle the --list-models flag if present.
    
    Args:
        args: Parsed arguments (or parser to parse)
        app_name: App name from resources config
    """
    # Parse args if it's a parser
    if hasattr(args, 'parse_known_args'):
        options, _ = args.parse_known_args()
    else:
        options = args
    
    # Check if --list-models flag is set
    if getattr(options, 'list_models', False):
        arch = getattr(options, 'arch', None)
        list_models_for_app(app_name, arch)
