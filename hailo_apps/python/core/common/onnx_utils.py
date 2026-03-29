"""
Shared ONNX utilities for Hailo apps.

Provides common functions for loading ONNX configs, resolving model paths,
initializing ONNX Runtime sessions, preprocessing, tensor mapping, and
debug-reference ONNX inference. Used by object_detection, pose_estimation, and other
apps that support ONNX-based postprocessing.
"""
import json
import os
import sys
import numpy as np
from pathlib import Path
from typing import Optional, Tuple, Dict, Any

from .defines import (
    HAILO_ARCH_KEY,
    HAILO_FILE_EXTENSION,
    RESOURCE_TYPE_ONNX,
    RESOURCES_MODELS_DIR_NAME,
    RESOURCES_ROOT_PATH_DEFAULT,
)
from .installation_utils import detect_hailo_arch

try:
    from hailo_apps.config.config_manager import get_model_info, get_supported_architectures
except ImportError:
    config_dir = Path(__file__).resolve().parents[3] / "config"
    sys.path.insert(0, str(config_dir))
    from config_manager import get_model_info, get_supported_architectures

try:
    from hailo_apps.python.core.common.hailo_logger import get_logger
except ImportError:
    from common.hailo_logger import get_logger

logger = get_logger(__name__)

ONNX_STANDALONE_APPS = {"object_detection_onnx_postproc", "pose_estimation_onnx_postproc"}


def _extract_model_name_from_hef_path(hef_path: str | Path) -> str:
    candidate_name = Path(hef_path).name
    if candidate_name.endswith(HAILO_FILE_EXTENSION):
        return candidate_name[: -len(HAILO_FILE_EXTENSION)]
    return candidate_name


def _get_standalone_app_dir(app_name: str) -> Path:
    return Path(__file__).resolve().parents[2] / "standalone_apps" / app_name


def _resolve_hef_parent_dir(hef_path_value: str | Path, arch: str | None) -> Path:
    candidate = Path(hef_path_value)
    if candidate.exists():
        return candidate.resolve().parent

    if arch:
        return (Path(RESOURCES_ROOT_PATH_DEFAULT) / RESOURCES_MODELS_DIR_NAME / arch).resolve()

    return Path.cwd()


def _infer_model_name_from_onnx_filename(path_value: str | None) -> str | None:
    if not path_value:
        return None

    stem = Path(path_value).stem
    suffixes = ("_postprocessing", "_neural_processing")
    for suffix in suffixes:
        if stem.endswith(suffix):
            return stem[: -len(suffix)]

    return None


def _resolve_debug_onnx_config_path(args: Any, app_name: str) -> str:
    explicit_config = getattr(args, "onnxconfig", None)
    if explicit_config:
        return str(Path(explicit_config))

    app_onnx_dir = _get_standalone_app_dir(app_name) / "onnx"
    model_candidates: list[str] = []

    for candidate in (
        _infer_model_name_from_onnx_filename(getattr(args, "onnx", None)),
        _infer_model_name_from_onnx_filename(getattr(args, "neural_onnx_ref", None)),
    ):
        if candidate and candidate not in model_candidates:
            model_candidates.append(candidate)

    matched_configs: list[Path] = []
    for model_name in model_candidates:
        candidate_path = app_onnx_dir / f"config_onnx_{model_name}.json"
        if candidate_path.exists():
            matched_configs.append(candidate_path)

    if not matched_configs:
        all_configs = sorted(app_onnx_dir.glob("config_onnx_*.json"))
        if len(all_configs) == 1:
            return str(all_configs[0])

        logger.error(
            "Could not auto-resolve ONNX config in debug reference mode. "
            "Provide --onnxconfig explicitly, or use ONNX filenames matching '<model>_postprocessing.onnx' / '<model>_neural_processing.onnx'."
        )
        sys.exit(1)

    if len(matched_configs) > 1:
        logger.error(
            "Ambiguous ONNX config resolution in debug reference mode. Candidates: %s. "
            "Provide --onnxconfig explicitly.",
            [str(path) for path in matched_configs],
        )
        sys.exit(1)

    return str(matched_configs[0])


def _download_onnx_artifact_if_needed(
    artifact_name: str,
    destination: Path,
    app_name: str,
    arch: str | None,
    download_resource_cb,
) -> bool:
    if destination.exists():
        return True

    if download_resource_cb(
        resource_name=artifact_name,
        resource_type=RESOURCE_TYPE_ONNX,
        app_name=app_name,
        arch=arch,
    ):
        return destination.exists()

    return False


def resolve_onnx_postproc_for_standalone(args: Any, app_name: str, download_resource_cb) -> None:
    if app_name not in ONNX_STANDALONE_APPS:
        return

    debug_no_hef_mode = bool(getattr(args, "neural_onnx_ref", None)) and not getattr(args, "hef_path", None)
    if debug_no_hef_mode:
        # lightweight debug mode - no need for HEF (can test scaffold while compiling)
        if not getattr(args, "onnx", None):
            logger.error(
                "When using --neural-onnx-ref, --onnx must be provided explicitly."
            )
            sys.exit(1)
        args.onnxconfig = _resolve_debug_onnx_config_path(args, app_name)
        args.onnx = str(Path(args.onnx))
        return

    model_name = _extract_model_name_from_hef_path(args.hef_path)
    arch = os.getenv(HAILO_ARCH_KEY) or detect_hailo_arch()

    model_info = None
    if arch:
        model_info = get_model_info(app_name, arch, model_name, app_type="standalone")

    if model_info is None:
        for candidate_arch in get_supported_architectures(app_name):
            model_info = get_model_info(app_name, candidate_arch, model_name, app_type="standalone")
            if model_info is not None:
                break

    onnx_postproc_name = model_info.onnx_postproc_name if model_info is not None else None
    if not onnx_postproc_name:
        logger.error(
            "Model '%s' for app '%s' does not define required ONNX metadata 'onnx_postproc_name' in resources_config.yaml",
            model_name,
            app_name,
        )
        sys.exit(1)

    app_dir = _get_standalone_app_dir(app_name)
    config_path = app_dir / "onnx" / f"config_onnx_{model_name}.json"
    if not config_path.exists():
        logger.error(
            "ONNX postprocessing is enabled for model '%s', but config file was not found at: %s\n"
            "Expected naming convention: config_onnx_<model_name>.json in the app's onnx/ directory.",
            model_name,
            config_path,
        )
        sys.exit(1)
    args.onnxconfig = str(config_path)

    hef_parent_dir = _resolve_hef_parent_dir(args.hef_path, arch)

    user_onnx_override = getattr(args, "onnx", None)
    if user_onnx_override:
        args.onnx = str(Path(user_onnx_override))

    postprocessing_path = Path(getattr(args, "onnx", "")) if getattr(args, "onnx", None) else (hef_parent_dir / onnx_postproc_name)
    if not _download_onnx_artifact_if_needed(
        artifact_name=onnx_postproc_name,
        destination=postprocessing_path,
        app_name=app_name,
        arch=arch,
        download_resource_cb=download_resource_cb,
    ):
        logger.error(
            "Missing ONNX postprocessing artifact: %s\n"
            "Either place the file at this path, provide --onnx <path>, or ensure '%s' can be downloaded for app '%s'.",
            postprocessing_path,
            onnx_postproc_name,
            app_name,
        )
        sys.exit(1)
    args.onnx = str(postprocessing_path)


def load_onnx_config(onnxconfig: str, caller_file: Optional[str] = None) -> Tuple[dict, Path]:
    """
    Load and return an ONNX postprocessing configuration JSON file.

    Resolves the path in this order:
    1) As provided (absolute or relative to current working directory)
    2) Relative to the caller's directory
    3) Relative to the caller's ``onnx/`` subdirectory

    Args:
        onnxconfig: Path string to the ONNX config JSON file.
        caller_file: __file__ of the calling module (used for relative path resolution).

    Returns:
        Tuple of (config dict, resolved config Path).

    Raises:
        FileNotFoundError: If the config file cannot be found.
    """
    config_path = Path(onnxconfig)
    if not config_path.is_absolute() and not config_path.exists() and caller_file:
        caller_dir = Path(caller_file).parent
        caller_relative = caller_dir / onnxconfig
        caller_onnx_relative = caller_dir / "onnx" / onnxconfig

        if caller_relative.exists():
            config_path = caller_relative
        elif caller_onnx_relative.exists():
            config_path = caller_onnx_relative

    if not config_path.exists():
        raise FileNotFoundError(f"ONNX config file not found: {onnxconfig}")

    with open(config_path, "r") as f:
        config = json.load(f)

    logger.info(f"Loaded ONNX config from: {config_path}")
    return config, config_path


def resolve_onnx_path(model_path_str: str, config_path: Path) -> str:
    """
    Resolve an ONNX model path, trying absolute, relative-to-config, then CWD.

    Args:
        model_path_str: Model path string from the config.
        config_path: Path to the config file (used as base for relative paths).

    Returns:
        Resolved absolute path as a string.

    Raises:
        FileNotFoundError: If the model file cannot be found.
    """
    model_path = Path(model_path_str)
    if model_path.is_absolute() and model_path.exists():
        return str(model_path)
    config_dir_path = config_path.parent / model_path
    if config_dir_path.exists():
        return str(config_dir_path)
    if model_path.exists():
        return str(model_path)
    raise FileNotFoundError(f"ONNX model file not found: {model_path_str}")


def init_onnx_sessions(
    onnx_config: dict,
    config_path: Path,
    use_debug_ref_onnx: bool = False,
    postproc_onnx_path: Optional[str] = None,
    neural_onnx_ref_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Initialize ONNX Runtime sessions based on config and mode.

    Args:
        onnx_config: Parsed ONNX config dict.
        config_path: Resolved path to the config JSON (for relative model resolution).
        use_debug_ref_onnx: If True, load debug reference intermediate + postproc ONNX models.
        postproc_onnx_path: Explicit postprocessing ONNX path.
        neural_onnx_ref_path: Explicit debug reference ONNX path that mimics HEF outputs.

    Returns:
        Dict with keys:
            'onnx_session': postprocessing session (always present when ONNX is used)
            'debug_ref_onnx_intermediate_session': intermediate model session (debug-reference only)
            'use_debug_ref_onnx': bool
    """
    import onnxruntime as ort

    result: Dict[str, Any] = {
        "onnx_session": None,
        "debug_ref_onnx_intermediate_session": None,
        "use_debug_ref_onnx": use_debug_ref_onnx,
    }

    if use_debug_ref_onnx:
        # Debug reference model (outputs HEF-like tensors)
        intermediate_path = neural_onnx_ref_path
        if not intermediate_path:
            raise ValueError(
                "debug ONNX reference mode requires --neural-onnx-ref <path>"
            )
        intermediate_path = resolve_onnx_path(intermediate_path, config_path)
        result["debug_ref_onnx_intermediate_session"] = ort.InferenceSession(intermediate_path)
        logger.info(f"Loaded debug neural ONNX reference model: {intermediate_path}")

        # Postprocessing model
        postproc_path = postproc_onnx_path
        if not postproc_path:
            raise ValueError("postprocessing ONNX path is required")
        postproc_path = resolve_onnx_path(postproc_path, config_path)
        result["onnx_session"] = ort.InferenceSession(postproc_path)
        logger.info(f"Loaded ONNX postprocessing model: {postproc_path}")
    else:
        # Postprocessing only (used with HEF outputs)
        postproc_path = postproc_onnx_path
        if not postproc_path:
            raise ValueError("postprocessing ONNX path is required")
        postproc_path = resolve_onnx_path(postproc_path, config_path)
        result["onnx_session"] = ort.InferenceSession(postproc_path)
        logger.info(f"Loaded ONNX postprocessing model: {postproc_path}")

    return result


def normalized_preprocess(image: np.ndarray, model_w: int, model_h: int) -> np.ndarray:
    """
    Resize image with letterbox padding and normalize to float32 [0-1] range.
    Used for ONNX models and HEF models compiled with [0,0,0]/[1,1,1] normalization.

    Args:
        image: Input image (uint8, 0-255).
        model_w: Model input width.
        model_h: Model input height.

    Returns:
        Preprocessed padded image as float32 normalized 0-1.
    """
    from hailo_apps.python.core.common.toolbox import default_preprocess

    padded_image = default_preprocess(image, model_w, model_h)
    return padded_image.astype(np.float32) / 255.0


def map_hef_outputs_to_onnx_inputs(
    hailo_outputs: dict,
    tensor_mapping: dict,
) -> dict:
    """
    Map HEF inference output tensors to ONNX postprocessing input tensors.

    Handles NHWC -> NCHW transposition when needed, validates shapes, and
    checks that tensors are FLOAT32.

    Args:
        hailo_outputs: Dict of HEF output tensors ``{hef_name: ndarray}``.
        tensor_mapping: ``{hef_name: [onnx_name, [C, H, W]]}`` from config.

    Returns:
        Dict of ``{onnx_input_name: ndarray}`` ready for ``onnx_session.run()``.

    Raises:
        ValueError: On missing tensors, shape mismatches, or wrong dtype.
    """
    onnx_inputs: dict = {}
    for hef_name, (onnx_name, expected_shape) in tensor_mapping.items():
        if hef_name not in hailo_outputs:
            raise ValueError(
                f"Expected HEF output '{hef_name}' not found. "
                f"Available: {list(hailo_outputs.keys())}"
            )

        tensor = hailo_outputs[hef_name]
        actual = list(tensor.shape)

        needs_transpose = False
        if len(actual) == 4 and len(expected_shape) == 3:
            no_batch = actual[1:]
            if no_batch != expected_shape:
                if [actual[3], actual[1], actual[2]] == expected_shape:
                    needs_transpose = True
                else:
                    raise ValueError(
                        f"Shape mismatch for '{hef_name}': expected {expected_shape}, "
                        f"got {no_batch} (full: {tensor.shape})"
                    )

        if tensor.dtype == np.uint8:
            raise ValueError(
                f"HEF output '{hef_name}' is UINT8. ONNX postprocessing requires FLOAT32. "
                "Ensure HailoInfer is initialized with output_type='FLOAT32'."
            )

        if needs_transpose:
            tensor = np.transpose(tensor, (0, 3, 1, 2))  # NHWC -> NCHW

        onnx_inputs[onnx_name] = tensor

    return onnx_inputs


def infer_debug_ref_onnx(
    intermediate_session,
    postprocess_session,
    onnx_config: dict,
    input_queue,
    output_queue,
) -> None:
    """
    Debug-reference ONNX inference loop: runs intermediate model then ONNX postprocessing.

    Replaces the HEF inference thread in debug-reference mode. Each frame is
    processed through the intermediate ONNX model (producing HEF-like tensors),
    optional sigmoid is applied, then tensors are renamed to HEF names so the
    downstream postprocessing sees the same dict format as HEF mode.

    Args:
        intermediate_session: ONNXRuntime session for the neural-processing model.
        postprocess_session: ONNXRuntime session for ONNX postprocessing.
        onnx_config: ONNX configuration dict (with tensor mapping).
        input_queue: Queue providing ``(input_batch, preprocessed_batch)`` tuples.
        output_queue: Queue collecting ``(input_frame, result_dict)`` tuples.
    """
    tensor_mapping = onnx_config.get("output_tensor_mapping", {})
    onnx_to_hef = {onnx_name: hef_name for hef_name, (onnx_name, _) in tensor_mapping.items()}
    tensors_to_sigmoid = onnx_config.get("intermediate_tensors_to_add_sigmoid", [])

    try:
        while True:
            next_batch = input_queue.get()
            if not next_batch:
                break

            input_batch, preprocessed_batch = next_batch

            for i, preprocessed_frame in enumerate(preprocessed_batch):
                # Prepare NCHW float32 input
                if preprocessed_frame.ndim == 3:  # HWC
                    onnx_input = np.transpose(preprocessed_frame, (2, 0, 1))  # CHW
                    onnx_input = np.expand_dims(onnx_input, axis=0)  # NCHW
                else:
                    onnx_input = np.expand_dims(preprocessed_frame, axis=0)

                if onnx_input.dtype == np.uint8:
                    onnx_input = onnx_input.astype(np.float32) / 255.0

                # Run intermediate model
                input_name = intermediate_session.get_inputs()[0].name
                output_names = [o.name for o in intermediate_session.get_outputs()]
                intermediates = intermediate_session.run(output_names, {input_name: onnx_input})

                # Optional sigmoid on specified tensors
                if tensors_to_sigmoid:
                    for idx, name in enumerate(output_names):
                        if name in tensors_to_sigmoid:
                            intermediates[idx] = 1.0 / (1.0 + np.exp(-intermediates[idx]))

                # Map ONNX tensor names -> HEF tensor names
                result: dict = {}
                for onnx_name, tensor in zip(output_names, intermediates):
                    hef_name = onnx_to_hef.get(onnx_name)
                    if hef_name:
                        result[hef_name] = tensor
                    else:
                        logger.warning(
                            f"ONNX intermediate output '{onnx_name}' not in tensor mapping"
                        )

                output_queue.put((input_batch[i], result))
    finally:
        output_queue.put(None)
