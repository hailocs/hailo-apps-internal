"""
Utility functions for the Photo Enhancer app.

Provides preprocessing (resize to model input) and postprocessing (clip output to uint8)
for Real-ESRGAN x2 super resolution inference on Hailo-8.
"""
import cv2
import numpy as np


def resize_infer_result_to_original(
    infer_result: np.ndarray,
    original_size: tuple[int, int],
    model_input_size: tuple[int, int]
) -> np.ndarray:
    """
    Resize and crop the super-resolution inference result to match original image size.

    The inference result may contain letterbox padding from the model input.
    This function removes that padding and resizes back to original dimensions.

    Args:
        infer_result (np.ndarray): Inference result image (H, W, C) with possible padding.
        original_size (tuple[int, int]): Original image size as (H_orig, W_orig).
        model_input_size (tuple[int, int]): Model input size as (H_model, W_model).

    Returns:
        np.ndarray: Resized and cropped image matching the original size (RGB).
    """
    orig_h, orig_w = original_size
    model_h, model_w = model_input_size

    # Calculate the scale and resized shape without padding
    scale = min(model_w / orig_w, model_h / orig_h)
    resized_h = int(orig_h * scale)
    resized_w = int(orig_w * scale)

    # Offsets due to padding
    x_offset = (model_w - resized_w) // 2
    y_offset = (model_h - resized_h) // 2

    # Crop only the region corresponding to the scaled image
    cropped = infer_result[y_offset:y_offset + resized_h, x_offset:x_offset + resized_w]

    # Resize to original image size. The inference result is already RGB, so no
    # color conversion is applied here (matches the super_resolution reference).
    result = cv2.resize(cropped, (orig_w, orig_h), interpolation=cv2.INTER_CUBIC)
    return result


def inference_result_handler(
    original_frame: np.ndarray,
    infer_result: np.ndarray,
    model_height: int,
    model_width: int,
    enhanced_only: bool = False
) -> np.ndarray:
    """
    Processes a single super-resolution inference result.

    By default, returns a side-by-side comparison of the original and enhanced image.
    If enhanced_only is True, returns only the enhanced image.

    Args:
        original_frame (np.ndarray): Original input image (H, W, 3).
        infer_result (np.ndarray): Super-resolved output image (H', W', 3).
        model_height (int): Model input height for padding removal.
        model_width (int): Model input width for padding removal.
        enhanced_only (bool): If True, return only the enhanced image.

    Returns:
        np.ndarray: Enhanced image or side-by-side comparison [original | enhanced].
    """
    # The inference result carries the model's letterbox padding, so the padding
    # is removed using the model input dimensions (model_height, model_width) the
    # handler receives — NOT the output tensor shape.
    infer_result_resized = resize_infer_result_to_original(
        infer_result=infer_result,
        original_size=original_frame.shape[:2],
        model_input_size=(model_height, model_width)
    )

    if enhanced_only:
        return infer_result_resized

    return np.hstack((original_frame, infer_result_resized))
