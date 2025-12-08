"""
Test Functions for All Pipeline Types

This module contains a generic test runner that handles all pipeline types,
eliminating code duplication while maintaining the same interface.
"""

import logging
from typing import Dict, List, Optional, Tuple

from test_utils import (
    build_test_args,
    get_log_file_path,
    run_pipeline_test,
)

logger = logging.getLogger(__name__)


def run_pipeline_test_generic(
    config: Dict,
    pipeline_name: str,
    model: str,
    architecture: str,
    run_method: str,
    test_suite: str = "default",
    extra_args: Optional[List[str]] = None,
    run_time: Optional[int] = None,
    term_timeout: Optional[int] = None,
) -> Tuple[bool, str]:
    """
    Generic pipeline test runner.

    This function handles testing for any pipeline type, reducing code duplication.

    Args:
        config: Test configuration dictionary containing pipeline definitions
        pipeline_name: Name of the pipeline (e.g., "detection", "pose_estimation")
        model: Model name to test
        architecture: Target architecture (hailo8, hailo8l, hailo10h)
        run_method: How to run the test (module, pythonpath, cli)
        test_suite: Test suite name (default: "default")
        extra_args: Additional command-line arguments
        run_time: Optional run time override in seconds
        term_timeout: Optional termination timeout override in seconds

    Returns:
        Tuple of (success: bool, log_file_path: str)

    Raises:
        KeyError: If the pipeline_name is not found in config["pipelines"]
    """
    # Get pipeline configuration
    pipeline_config = config["pipelines"][pipeline_name]

    # Build arguments
    args = build_test_args(
        config, pipeline_config, model, architecture, test_suite, extra_args
    )

    # Get log file path
    log_file = get_log_file_path(
        config, "pipeline", pipeline_name, architecture, model, run_method, test_suite
    )

    # Run test
    stdout, stderr, success = run_pipeline_test(
        pipeline_config, model, architecture, run_method, args, log_file,
        run_time=run_time, term_timeout=term_timeout
    )

    # Format pipeline name for display (replace underscores with spaces, title case)
    display_name = pipeline_name.replace("_", " ").title()

    if success:
        logger.info(f"✓ {display_name} test passed: {model} on {architecture} using {run_method}")
    else:
        logger.error(f"✗ {display_name} test failed: {model} on {architecture} using {run_method}")
        if stderr:
            logger.error(f"Error: {stderr.decode() if isinstance(stderr, bytes) else stderr}")

    return success, log_file


# Create specialized test functions using the generic runner
# These maintain backward compatibility with existing code

def run_detection_test(
    config: Dict,
    model: str,
    architecture: str,
    run_method: str,
    test_suite: str = "default",
    extra_args: Optional[List[str]] = None,
    run_time: Optional[int] = None,
    term_timeout: Optional[int] = None,
) -> Tuple[bool, str]:
    """Run detection pipeline test."""
    return run_pipeline_test_generic(
        config, "detection", model, architecture, run_method,
        test_suite, extra_args, run_time, term_timeout
    )


def run_pose_estimation_test(
    config: Dict,
    model: str,
    architecture: str,
    run_method: str,
    test_suite: str = "default",
    extra_args: Optional[List[str]] = None,
    run_time: Optional[int] = None,
    term_timeout: Optional[int] = None,
) -> Tuple[bool, str]:
    """Run pose estimation pipeline test."""
    return run_pipeline_test_generic(
        config, "pose_estimation", model, architecture, run_method,
        test_suite, extra_args, run_time, term_timeout
    )


def run_depth_test(
    config: Dict,
    model: str,
    architecture: str,
    run_method: str,
    test_suite: str = "default",
    extra_args: Optional[List[str]] = None,
    run_time: Optional[int] = None,
    term_timeout: Optional[int] = None,
) -> Tuple[bool, str]:
    """Run depth estimation pipeline test."""
    return run_pipeline_test_generic(
        config, "depth", model, architecture, run_method,
        test_suite, extra_args, run_time, term_timeout
    )


def run_instance_segmentation_test(
    config: Dict,
    model: str,
    architecture: str,
    run_method: str,
    test_suite: str = "default",
    extra_args: Optional[List[str]] = None,
    run_time: Optional[int] = None,
    term_timeout: Optional[int] = None,
) -> Tuple[bool, str]:
    """Run instance segmentation pipeline test."""
    return run_pipeline_test_generic(
        config, "instance_segmentation", model, architecture, run_method,
        test_suite, extra_args, run_time, term_timeout
    )


def run_simple_detection_test(
    config: Dict,
    model: str,
    architecture: str,
    run_method: str,
    test_suite: str = "default",
    extra_args: Optional[List[str]] = None,
    run_time: Optional[int] = None,
    term_timeout: Optional[int] = None,
) -> Tuple[bool, str]:
    """Run simple detection pipeline test."""
    return run_pipeline_test_generic(
        config, "simple_detection", model, architecture, run_method,
        test_suite, extra_args, run_time, term_timeout
    )


def run_face_recognition_test(
    config: Dict,
    model: str,
    architecture: str,
    run_method: str,
    test_suite: str = "default",
    extra_args: Optional[List[str]] = None,
    run_time: Optional[int] = None,
    term_timeout: Optional[int] = None,
) -> Tuple[bool, str]:
    """Run face recognition pipeline test."""
    return run_pipeline_test_generic(
        config, "face_recognition", model, architecture, run_method,
        test_suite, extra_args, run_time, term_timeout
    )


def run_multisource_test(
    config: Dict,
    model: str,
    architecture: str,
    run_method: str,
    test_suite: str = "default",
    extra_args: Optional[List[str]] = None,
    run_time: Optional[int] = None,
    term_timeout: Optional[int] = None,
) -> Tuple[bool, str]:
    """Run multisource pipeline test."""
    return run_pipeline_test_generic(
        config, "multisource", model, architecture, run_method,
        test_suite, extra_args, run_time, term_timeout
    )


def run_reid_multisource_test(
    config: Dict,
    model: str,
    architecture: str,
    run_method: str,
    test_suite: str = "default",
    extra_args: Optional[List[str]] = None,
    run_time: Optional[int] = None,
    term_timeout: Optional[int] = None,
) -> Tuple[bool, str]:
    """Run REID multisource pipeline test."""
    return run_pipeline_test_generic(
        config, "reid_multisource", model, architecture, run_method,
        test_suite, extra_args, run_time, term_timeout
    )


def run_tiling_test(
    config: Dict,
    model: str,
    architecture: str,
    run_method: str,
    test_suite: str = "default",
    extra_args: Optional[List[str]] = None,
    run_time: Optional[int] = None,
    term_timeout: Optional[int] = None,
) -> Tuple[bool, str]:
    """Run tiling pipeline test."""
    return run_pipeline_test_generic(
        config, "tiling", model, architecture, run_method,
        test_suite, extra_args, run_time, term_timeout
    )


def run_paddle_ocr_test(
    config: Dict,
    model: str,
    architecture: str,
    run_method: str,
    test_suite: str = "default",
    extra_args: Optional[List[str]] = None,
    run_time: Optional[int] = None,
    term_timeout: Optional[int] = None,
) -> Tuple[bool, str]:
    """Run paddle OCR pipeline test."""
    return run_pipeline_test_generic(
        config, "paddle_ocr", model, architecture, run_method,
        test_suite, extra_args, run_time, term_timeout
    )


# Map pipeline names to test functions for backward compatibility
PIPELINE_TEST_FUNCTIONS: Dict[str, callable] = {
    "detection": run_detection_test,
    "pose_estimation": run_pose_estimation_test,
    "depth": run_depth_test,
    "instance_segmentation": run_instance_segmentation_test,
    "simple_detection": run_simple_detection_test,
    "face_recognition": run_face_recognition_test,
    "multisource": run_multisource_test,
    "reid_multisource": run_reid_multisource_test,
    "tiling": run_tiling_test,
    "paddle_ocr": run_paddle_ocr_test,
}


def get_pipeline_test_function(pipeline_name: str):
    """
    Get test function for a pipeline.

    For new code, consider using run_pipeline_test_generic() directly
    instead of looking up specific functions.

    Args:
        pipeline_name: Name of the pipeline

    Returns:
        Test function or None if not found
    """
    return PIPELINE_TEST_FUNCTIONS.get(pipeline_name)
