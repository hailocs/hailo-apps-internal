"""
Shared ONNX utilities for Hailo apps.

Provides common functions for loading ONNX configs, resolving model paths,
initializing ONNX Runtime sessions, preprocessing, tensor mapping, and
full-ONNX inference. Used by object_detection, pose_estimation, and other
apps that support ONNX-based postprocessing.
"""
import json
import numpy as np
from pathlib import Path
from typing import Optional, Tuple, Dict, Any

try:
    from hailo_apps.python.core.common.hailo_logger import get_logger
except ImportError:
    from common.hailo_logger import get_logger

logger = get_logger(__name__)


def load_onnx_config(onnxconfig: str, caller_file: Optional[str] = None) -> Tuple[dict, Path]:
    """
    Load and return an ONNX postprocessing configuration JSON file.

    Resolves the path relative to the current directory, or relative to the
    caller's directory if not found.

    Args:
        onnxconfig: Path string to the ONNX config JSON file.
        caller_file: __file__ of the calling module (used for relative path resolution).

    Returns:
        Tuple of (config dict, resolved config Path).

    Raises:
        FileNotFoundError: If the config file cannot be found.
    """
    config_path = Path(onnxconfig)
    if not config_path.is_absolute():
        if not config_path.exists() and caller_file:
            config_path = Path(caller_file).parent / onnxconfig
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
    use_full_onnx: bool = False,
) -> Dict[str, Any]:
    """
    Initialize ONNX Runtime sessions based on config and mode.

    Args:
        onnx_config: Parsed ONNX config dict.
        config_path: Resolved path to the config JSON (for relative model resolution).
        use_full_onnx: If True, load intermediate + postproc models for full-ONNX mode.

    Returns:
        Dict with keys:
            'onnx_session': postprocessing session (always present when ONNX is used)
            'full_onnx_intermediate_session': intermediate model session (full-ONNX only)
            'full_onnx_session': full model session (optional reference, full-ONNX only)
            'use_full_onnx': bool
    """
    import onnxruntime as ort

    result: Dict[str, Any] = {
        "onnx_session": None,
        "full_onnx_intermediate_session": None,
        "full_onnx_session": None,
        "use_full_onnx": use_full_onnx,
    }

    if use_full_onnx:
        # Intermediate model (outputs HEF-like tensors)
        intermediate_path = onnx_config.get("hef_like_proc_onnx_path")
        if not intermediate_path:
            raise ValueError(
                "full-onnx mode requires hef_like_proc_onnx_path in config"
            )
        intermediate_path = resolve_onnx_path(intermediate_path, config_path)
        result["full_onnx_intermediate_session"] = ort.InferenceSession(intermediate_path)
        logger.info(f"Loaded HEF-like intermediate ONNX model: {intermediate_path}")

        # Postprocessing model
        postproc_path = onnx_config.get("postproc_onnx_path")
        if not postproc_path:
            raise ValueError("postproc_onnx_path not specified in ONNX config")
        postproc_path = resolve_onnx_path(postproc_path, config_path)
        result["onnx_session"] = ort.InferenceSession(postproc_path)
        logger.info(f"Loaded ONNX postprocessing model: {postproc_path}")

        # Optional full model for reference
        full_path = onnx_config.get("full_onnx_path")
        if full_path:
            full_path = resolve_onnx_path(full_path, config_path)
            result["full_onnx_session"] = ort.InferenceSession(full_path)
            logger.info(f"Loaded full ONNX model (reference): {full_path}")
    else:
        # Postprocessing only (used with HEF outputs)
        postproc_path = onnx_config.get("postproc_onnx_path")
        if not postproc_path:
            raise ValueError("postproc_onnx_path not specified in ONNX config")
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


def infer_full_onnx(
    intermediate_session,
    postprocess_session,
    onnx_config: dict,
    input_queue,
    output_queue,
) -> None:
    """
    Full-ONNX inference loop: runs intermediate model then ONNX postprocessing.

    Replaces the HEF inference thread in full-ONNX debug mode. Each frame is
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
