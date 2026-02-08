#!/usr/bin/env python3
import os
import sys
import queue
import threading
from functools import partial
from types import SimpleNamespace
import numpy as np
from pathlib import Path

try:
    from hailo_apps.python.core.tracker.byte_tracker import BYTETracker
    from hailo_apps.python.core.common.hailo_inference import HailoInfer
    from hailo_apps.python.core.common.toolbox import (
        init_input_source,
        get_labels,
        load_json_file,
        preprocess,
        visualize,
        FrameRateTracker,
    )
    from hailo_apps.python.core.common.parser import get_standalone_parser
    from hailo_apps.python.core.common.hailo_logger import get_logger, init_logging, level_from_args
    from hailo_apps.python.standalone_apps.object_detection.object_detection_post_process import inference_result_handler
    from hailo_apps.python.core.common.core import handle_and_resolve_args
except ImportError:
    # Running as a plain script: add repo root so `import hailo_apps` works.
    repo_root = None
    for p in Path(__file__).resolve().parents:
        if (p / "hailo_apps" / "config" / "config_manager.py").exists():
            repo_root = p
            break
    if repo_root is not None:
        sys.path.insert(0, str(repo_root))

    from hailo_apps.python.core.tracker.byte_tracker import BYTETracker
    from hailo_apps.python.core.common.hailo_inference import HailoInfer
    from hailo_apps.python.core.common.core import handle_and_resolve_args
    from hailo_apps.python.core.common.toolbox import (
        init_input_source,
        get_labels,
        load_json_file,
        preprocess,
        visualize,
        FrameRateTracker,
    )
    from hailo_apps.python.core.common.parser import get_standalone_parser
    from hailo_apps.python.core.common.hailo_logger import get_logger, init_logging, level_from_args
    from hailo_apps.python.standalone_apps.object_detection.object_detection_post_process import inference_result_handler

APP_NAME = Path(__file__).stem
logger = get_logger(__name__)


def parse_args():
    """
    Parse command-line arguments for the detection application.

    Returns:
        argparse.Namespace: Parsed CLI arguments.
    """
    parser = get_standalone_parser()
    parser.description = "Run object detection with optional tracking and performance measurement."

    parser.add_argument(
        "--track",
        action="store_true",
        help=(
            "Enable object tracking for detections. "
            "When enabled, detected objects will be tracked across frames using a tracking algorithm "
            "(e.g., ByteTrack). This assigns consistent IDs to objects over time, enabling temporal analysis, "
            "trajectory visualization, and multi-frame association. Useful for video processing applications."
        ),
    )

    parser.add_argument(
        "--labels",
        "-l",
        type=str,
        default=None,
        help=(
            "Path to a text file containing class labels, one per line. "
            "Used for mapping model output indices to human-readable class names. "
            "If not specified, default labels for the model will be used (e.g., COCO labels for detection models)."
        ),
    )


    parser.add_argument(
        "--draw-trail",
        action="store_true",
        help=(
            "[Tracking only] Draw motion trails of tracked objects.\n"
            "Uses the last 30 positions from the tracker history."
        )
    )

    parser.add_argument(
        "--onnxconfig",
        type=str,
        default=None,
        help=(
            "Path to ONNX postprocessing configuration file (JSON). "
            "When specified, enables ONNX-based postprocessing instead of HailoRT NMS. "
            "The config must include: onnx_model_path, output_tensor_mapping, output_format, "
            "and postprocess_params. Optionally supports full_onnx_model_path and use_full_onnx_mode "
            "for debug mode (bypasses HEF inference entirely)."
        ),
    )

    args = parser.parse_args()
    return args


def normalized_preprocess(image: np.ndarray, model_w: int, model_h: int) -> np.ndarray:
    """
    Resize image with letterbox padding and normalize to float32 [0-1] range.
    Used for ONNX models and HEF models compiled with [0,0,0]/[1,1,1] normalization.
    
    Args:
        image (np.ndarray): Input image (uint8, 0-255).
        model_w (int): Model input width.
        model_h (int): Model input height.
    
    Returns:
        np.ndarray: Preprocessed padded image as float32 normalized 0-1.
    """
    from hailo_apps.python.core.common.toolbox import default_preprocess
    
    # First apply standard letterbox preprocessing (uint8)
    padded_image = default_preprocess(image, model_w, model_h)
    
    # Convert to float32 and normalize to 0-1
    normalized_image = padded_image.astype(np.float32) / 255.0
    
    # <DEBUG>
    DEBUG = True
    if DEBUG:
        logger.info(f"DEBUG normalized_preprocess: output shape={normalized_image.shape}, dtype={normalized_image.dtype}, min={normalized_image.min():.3f}, max={normalized_image.max():.3f}, mean={normalized_image.mean():.3f}")
    # </DEBUG>
    
    return normalized_image


def run_inference_pipeline(net, input_src, batch_size, labels, output_dir,  
          save_output=False, camera_resolution="sd", output_resolution=None,
          enable_tracking=False, show_fps=False, frame_rate=None, draw_trail=False, onnxconfig=None) -> None:
    """
    Initialize queues, HailoAsyncInference instance, and run the inference.
    """
    labels = get_labels(labels)
    config_data = load_json_file("config.json")
    
    # Load ONNX config and initialize sessions if specified
    onnx_config = None
    onnx_session = None
    full_onnx_session = None
    full_onnx_intermediate_session = None
    use_full_onnx = False
    
    if onnxconfig:
        import json
        import onnxruntime as ort
        
        # Load ONNX config with permissive path resolution
        onnx_config_path = Path(onnxconfig)
        if not onnx_config_path.is_absolute():
            # Try relative to current directory first
            if not onnx_config_path.exists():
                # Try relative to object_detection directory
                onnx_config_path = Path(__file__).parent / onnxconfig
        
        if not onnx_config_path.exists():
            raise FileNotFoundError(f"ONNX config file not found: {onnxconfig}")
        
        with open(onnx_config_path, 'r') as f:
            onnx_config = json.load(f)
        
        logger.info(f"Loaded ONNX config from: {onnx_config_path}")
        
        # Helper function for permissive ONNX model path resolution
        def resolve_onnx_path(model_path_str):
            model_path = Path(model_path_str)
            if model_path.is_absolute() and model_path.exists():
                return str(model_path)
            # Try relative to config file directory
            config_dir_path = onnx_config_path.parent / model_path
            if config_dir_path.exists():
                return str(config_dir_path)
            # Try relative to current directory
            if model_path.exists():
                return str(model_path)
            raise FileNotFoundError(f"ONNX model file not found: {model_path_str}")
        
        # Check for full ONNX mode (debug mode)
        use_full_onnx = onnx_config.get("use_full_onnx_mode", False)
        
        if use_full_onnx:
            # Load intermediate ONNX model (outputs HEF-like tensors) for Full-ONNX mode
            intermediate_model_path = onnx_config.get("full_onnx_intermediate_model_path")
            if not intermediate_model_path:
                raise ValueError("use_full_onnx_mode is True but full_onnx_intermediate_model_path not specified in config")
            intermediate_model_path = resolve_onnx_path(intermediate_model_path)
            full_onnx_intermediate_session = ort.InferenceSession(intermediate_model_path)
            logger.info(f"Loaded full ONNX intermediate model: {intermediate_model_path}")
            
            # Also load postprocessing model to apply to intermediates
            onnx_model_path = onnx_config.get("onnx_model_path")
            if not onnx_model_path:
                raise ValueError("onnx_model_path not specified in ONNX config")
            onnx_model_path = resolve_onnx_path(onnx_model_path)
            onnx_session = ort.InferenceSession(onnx_model_path)
            logger.info(f"Loaded ONNX postprocessing model: {onnx_model_path}")
            
            # Optionally load full model for reference
            full_model_path = onnx_config.get("full_onnx_model_path")
            if full_model_path:
                full_model_path = resolve_onnx_path(full_model_path)
                full_onnx_session = ort.InferenceSession(full_model_path)
                logger.info(f"Loaded full ONNX model (reference): {full_model_path}")
        else:
            # Load postprocessing ONNX model (used with HEF outputs)
            onnx_model_path = onnx_config.get("onnx_model_path")
            if not onnx_model_path:
                raise ValueError("onnx_model_path not specified in ONNX config")
            onnx_model_path = resolve_onnx_path(onnx_model_path)
            onnx_session = ort.InferenceSession(onnx_model_path)
            logger.info(f"Loaded ONNX postprocessing model: {onnx_model_path}")

    # Initialize input source from string: "camera", video file, or image folder.
    cap, images = init_input_source(input_src, batch_size, camera_resolution)
    tracker = None
    fps_tracker = None
    if show_fps:
        fps_tracker = FrameRateTracker()

    if enable_tracking:
        # load tracker config from config_data
        tracker_config = config_data.get("visualization_params", {}).get("tracker", {})
        tracker = BYTETracker(SimpleNamespace(**tracker_config))

    input_queue = queue.Queue()
    output_queue = queue.Queue()

    post_process_callback_fn = partial(
        inference_result_handler, labels=labels,
        config_data=config_data, tracker=tracker, draw_trail=draw_trail,
        onnx_config=onnx_config, onnx_session=onnx_session
    )

    # Skip HEF initialization in full ONNX mode
    if use_full_onnx:
        # Use full ONNX intermediate model input shape
        full_onnx_input = full_onnx_intermediate_session.get_inputs()[0]
        # Assume NCHW or NHWC format - extract H, W
        input_shape = full_onnx_input.shape
        if len(input_shape) == 4:
            # NCHW: [batch, channels, height, width] or NHWC: [batch, height, width, channels]
            if input_shape[1] in [1, 3]:  # NCHW
                height, width = input_shape[2], input_shape[3]
            else:  # NHWC
                height, width = input_shape[1], input_shape[2]
        else:
            raise ValueError(f"Unexpected full ONNX input shape: {input_shape}")
        hailo_inference = None
        logger.info(f"Full ONNX mode enabled - using intermediate outputs + ONNX postprocessing (input size: {height}x{width})")
    else:
        # When using ONNX postprocessing, request FLOAT32 inputs and outputs
        # Model was compiled with normalization [0,0,0]/[1,1,1] so expects float32 0-1 range
        # Otherwise, use default (UINT8 for HailoRT-NMS models)
        if onnx_session is not None:
            input_type = "FLOAT32"
            output_type = "FLOAT32"
            logger.info(f"HEF configured for FLOAT32 inputs (0-1 normalized) and outputs (dequantized)")
        else:
            input_type = None
            output_type = None
        
        hailo_inference = HailoInfer(net, batch_size, input_type=input_type, output_type=output_type)
        height, width, _ = hailo_inference.get_input_shape()

    preprocess_thread = threading.Thread(
        target=preprocess, args=(images, cap, frame_rate, batch_size, input_queue, width, height),
        kwargs={'preprocess_fn': normalized_preprocess if (onnx_session is not None or use_full_onnx) else None}
    )
    postprocess_thread = threading.Thread(
        target=visualize, 
        args=(output_queue, cap, save_output, output_dir,
               post_process_callback_fn, fps_tracker, output_resolution, frame_rate)
    )
    
    if use_full_onnx:
        # Use full ONNX inference (intermediate model + postprocessing)
        infer_thread = threading.Thread(
            target=infer_full_onnx, args=(full_onnx_intermediate_session, onnx_session, onnx_config, input_queue, output_queue)
        )
    else:
        infer_thread = threading.Thread(
            target=infer, args=(hailo_inference, input_queue, output_queue)
        )

    preprocess_thread.start()
    postprocess_thread.start()
    infer_thread.start()

    if show_fps:
        fps_tracker.start()

    preprocess_thread.join()
    infer_thread.join()
    output_queue.put(None)  # Signal process thread to exit
    postprocess_thread.join()

    if show_fps:
        logger.info(fps_tracker.frame_rate_summary())

    logger.success("Inference was successful!")
    if save_output or input_src.lower() not in ("usb", "rpi"):
        logger.info(f"Results have been saved in {output_dir}")



def infer(hailo_inference, input_queue, output_queue):
    """
    Main inference loop that pulls data from the input queue, runs asynchronous
    inference, and pushes results to the output queue.

    Each item in the input queue is expected to be a tuple:
        (input_batch, preprocessed_batch)
        - input_batch: Original frames (used for visualization or tracking)
        - preprocessed_batch: Model-ready frames (e.g., resized, normalized)

    Args:
        hailo_inference (HailoInfer): The inference engine to run model predictions.
        input_queue (queue.Queue): Provides (input_batch, preprocessed_batch) tuples.
        output_queue (queue.Queue): Collects (input_frame, result) tuples for visualization.

    Returns:
        None
    """
    while True:
        next_batch = input_queue.get()
        if not next_batch:
            break  # Stop signal received

        input_batch, preprocessed_batch = next_batch

        # Prepare the callback for handling the inference result
        inference_callback_fn = partial(
            inference_callback,
            input_batch=input_batch,
            output_queue=output_queue
        )

        # Run async inference
        hailo_inference.run(preprocessed_batch, inference_callback_fn)

    # Release resources and context
    hailo_inference.close()


def infer_full_onnx(intermediate_session, postprocess_session, onnx_config, input_queue, output_queue):
    """
    Full ONNX inference loop that runs intermediate model + ONNX postprocessing.
    This matches the HEF+ONNX flow but using ONNX for both stages.
    
    Args:
        intermediate_session: ONNXRuntime session for model that outputs HEF-like intermediates.
        postprocess_session: ONNXRuntime session for ONNX postprocessing.
        onnx_config: ONNX configuration with tensor mapping.
        input_queue (queue.Queue): Provides (input_batch, preprocessed_batch) tuples.
        output_queue (queue.Queue): Collects (input_frame, result) tuples for visualization.

    Returns:
        None
    """
    # <DEBUG>
    DEBUG = True
    if DEBUG:
        logger.info(">>> infer_full_onnx() starting (intermediate + postprocess)")
    # </DEBUG>
    
    # Build reverse mapping: ONNX tensor name -> HEF tensor name
    tensor_mapping = onnx_config.get("output_tensor_mapping", {})
    onnx_to_hef = {onnx_name: hef_name for hef_name, (onnx_name, _) in tensor_mapping.items()}
    
    while True:
        next_batch = input_queue.get()
        if not next_batch:
            break  # Stop signal received

        input_batch, preprocessed_batch = next_batch

        # Process each frame in the batch
        for i, preprocessed_frame in enumerate(preprocessed_batch):
            # Prepare input for ONNX (may need to transpose/reshape depending on model)
            # Assuming model expects NCHW format [1, 3, H, W] with float32 values 0-1
            if preprocessed_frame.ndim == 3:  # HWC format
                onnx_input = np.transpose(preprocessed_frame, (2, 0, 1))  # CHW
                onnx_input = np.expand_dims(onnx_input, axis=0)  # NCHW
            else:
                onnx_input = np.expand_dims(preprocessed_frame, axis=0)
            
            # <DEBUG>
            if DEBUG:
                logger.info(f"DEBUG infer_full_onnx: onnx_input shape={onnx_input.shape}, dtype={onnx_input.dtype}, min={onnx_input.min():.3f}, max={onnx_input.max():.3f}, mean={onnx_input.mean():.3f}")
            # </DEBUG>
            
            # Convert to float32 and normalize to 0-1 if needed
            if onnx_input.dtype == np.uint8:
                onnx_input = onnx_input.astype(np.float32) / 255.0
            
            # Run intermediate ONNX model (get HEF-like outputs)
            intermediate_input_name = intermediate_session.get_inputs()[0].name
            intermediate_output_names = [out.name for out in intermediate_session.get_outputs()]
            intermediate_results = intermediate_session.run(intermediate_output_names, {intermediate_input_name: onnx_input})
            
            # <DEBUG>
            if DEBUG:
                logger.info(f"DEBUG infer_full_onnx: Intermediate outputs (HEF-like tensors):")
                for name, tensor in zip(intermediate_output_names[:2], intermediate_results[:2]):
                    logger.info(f"  {name}: shape={tensor.shape}, dtype={tensor.dtype}, min={tensor.min():.3f}, max={tensor.max():.3f}, mean={tensor.mean():.3f}")
            # </DEBUG>
            
            # Apply sigmoid to classifier tensors (80 channels) to match HEF behavior
            # HEF applies sigmoid to conv61, conv77, conv91 (the box regression layers)
            # but we need sigmoid on the CLASSIFIER layers (80 channels, not 4 channels)
            # to match the expected postprocessing input
            for idx, (onnx_name, tensor) in enumerate(zip(intermediate_output_names, intermediate_results)):
                # Check if this is a classifier tensor (80 channels in dim 1)
                if tensor.shape[1] == 80:
                    intermediate_results[idx] = 1.0 / (1.0 + np.exp(-tensor))  # sigmoid
                    if DEBUG:
                        logger.info(f"  Applied sigmoid to {onnx_name} (classifier, 80 channels): min={intermediate_results[idx].min():.3f}, max={intermediate_results[idx].max():.3f}")
            
            # Map ONNX tensor names to HEF tensor names for compatibility with extract_detections_onnx
            result = {}
            for onnx_name, tensor in zip(intermediate_output_names, intermediate_results):
                hef_name = onnx_to_hef.get(onnx_name)
                if hef_name:
                    result[hef_name] = tensor
                else:
                    logger.warning(f"ONNX intermediate output '{onnx_name}' not found in tensor mapping")
            
            output_queue.put((input_batch[i], result))


def inference_callback(
    completion_info,
    bindings_list: list,
    input_batch: list,
    output_queue: queue.Queue
) -> None:
    """
    infernce callback to handle inference results and push them to a queue.

    Args:
        completion_info: Hailo inference completion info.
        bindings_list (list): Output bindings for each inference.
        input_batch (list): Original input frames.
        output_queue (queue.Queue): Queue to push output results to.
    """
    if completion_info.exception:
        logger.error(f'Inference error: {completion_info.exception}')
    else:
        for i, bindings in enumerate(bindings_list):
            if len(bindings._output_names) == 1:
                result = bindings.output().get_buffer()
            else:
                result = {
                    name: np.expand_dims(
                        bindings.output(name).get_buffer(), axis=0
                    )
                    for name in bindings._output_names
                }
            output_queue.put((input_batch[i], result))


def main() -> None:
    """
    Main function to run the script.
    """
    args = parse_args()
    init_logging(level=level_from_args(args))
    handle_and_resolve_args(args, APP_NAME)
    run_inference_pipeline(
        args.hef_path,
        args.input,
        args.batch_size,
        args.labels,
        args.output_dir,
        args.save_output,
        args.camera_resolution,
        args.output_resolution,
        args.track,
        args.show_fps,
        args.frame_rate,
        args.draw_trail,
        args.onnxconfig
    )


if __name__ == "__main__":
    main()
