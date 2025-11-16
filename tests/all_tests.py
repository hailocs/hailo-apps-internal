"""
Test Functions for All Pipeline Types

This module contains test functions for each pipeline/app type.
Each function can be called with configuration options to run tests.
"""

import logging
from typing import Dict, List, Optional, Tuple

from .test_utils import (
    build_test_args,
    get_log_file_path,
    run_pipeline_test,
)

logger = logging.getLogger(__name__)


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
    """Run detection pipeline test.
    
    Args:
        config: Test configuration
        model: Model name
        architecture: Architecture (hailo8, hailo8l, hailo10h)
        run_method: Run method (module, pythonpath, cli)
        test_suite: Test suite name
        extra_args: Additional arguments
        run_time: Optional run time override
        term_timeout: Optional termination timeout override
    
    Returns:
        Tuple of (success, log_file_path)
    """
    pipeline_config = config["pipelines"]["detection"]
    
    # Build arguments
    args = build_test_args(
        config, pipeline_config, model, architecture, test_suite, extra_args
    )
    
    # Get log file path
    log_file = get_log_file_path(
        config, "pipeline", "detection", architecture, model, run_method, test_suite
    )
    
    # Run test
    stdout, stderr, success = run_pipeline_test(
        pipeline_config, model, architecture, run_method, args, log_file,
        run_time=run_time, term_timeout=term_timeout
    )
    
    if success:
        logger.info(f"✓ Detection test passed: {model} on {architecture} using {run_method}")
    else:
        logger.error(f"✗ Detection test failed: {model} on {architecture} using {run_method}")
        logger.error(f"Error: {stderr.decode() if stderr else 'Unknown error'}")
    
    return success, log_file


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
    pipeline_config = config["pipelines"]["pose_estimation"]
    args = build_test_args(
        config, pipeline_config, model, architecture, test_suite, extra_args
    )
    log_file = get_log_file_path(
        config, "pipeline", "pose_estimation", architecture, model, run_method, test_suite
    )
    stdout, stderr, success = run_pipeline_test(
        pipeline_config, model, architecture, run_method, args, log_file,
        run_time=run_time, term_timeout=term_timeout
    )
    if success:
        logger.info(f"✓ Pose estimation test passed: {model} on {architecture}")
    else:
        logger.error(f"✗ Pose estimation test failed: {model} on {architecture}")
    return success, log_file


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
    pipeline_config = config["pipelines"]["depth"]
    args = build_test_args(
        config, pipeline_config, model, architecture, test_suite, extra_args
    )
    log_file = get_log_file_path(
        config, "pipeline", "depth", architecture, model, run_method, test_suite
    )
    stdout, stderr, success = run_pipeline_test(
        pipeline_config, model, architecture, run_method, args, log_file,
        run_time=run_time, term_timeout=term_timeout
    )
    if success:
        logger.info(f"✓ Depth test passed: {model} on {architecture}")
    else:
        logger.error(f"✗ Depth test failed: {model} on {architecture}")
    return success, log_file


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
    pipeline_config = config["pipelines"]["instance_segmentation"]
    args = build_test_args(
        config, pipeline_config, model, architecture, test_suite, extra_args
    )
    log_file = get_log_file_path(
        config, "pipeline", "instance_segmentation", architecture, model, run_method, test_suite
    )
    stdout, stderr, success = run_pipeline_test(
        pipeline_config, model, architecture, run_method, args, log_file,
        run_time=run_time, term_timeout=term_timeout
    )
    if success:
        logger.info(f"✓ Instance segmentation test passed: {model} on {architecture}")
    else:
        logger.error(f"✗ Instance segmentation test failed: {model} on {architecture}")
    return success, log_file


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
    pipeline_config = config["pipelines"]["simple_detection"]
    args = build_test_args(
        config, pipeline_config, model, architecture, test_suite, extra_args
    )
    log_file = get_log_file_path(
        config, "pipeline", "simple_detection", architecture, model, run_method, test_suite
    )
    stdout, stderr, success = run_pipeline_test(
        pipeline_config, model, architecture, run_method, args, log_file,
        run_time=run_time, term_timeout=term_timeout
    )
    if success:
        logger.info(f"✓ Simple detection test passed: {model} on {architecture}")
    else:
        logger.error(f"✗ Simple detection test failed: {model} on {architecture}")
    return success, log_file


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
    pipeline_config = config["pipelines"]["face_recognition"]
    args = build_test_args(
        config, pipeline_config, model, architecture, test_suite, extra_args
    )
    log_file = get_log_file_path(
        config, "pipeline", "face_recognition", architecture, model, run_method, test_suite
    )
    stdout, stderr, success = run_pipeline_test(
        pipeline_config, model, architecture, run_method, args, log_file,
        run_time=run_time, term_timeout=term_timeout
    )
    if success:
        logger.info(f"✓ Face recognition test passed: {model} on {architecture}")
    else:
        logger.error(f"✗ Face recognition test failed: {model} on {architecture}")
    return success, log_file


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
    pipeline_config = config["pipelines"]["multisource"]
    args = build_test_args(
        config, pipeline_config, model, architecture, test_suite, extra_args
    )
    log_file = get_log_file_path(
        config, "pipeline", "multisource", architecture, model, run_method, test_suite
    )
    stdout, stderr, success = run_pipeline_test(
        pipeline_config, model, architecture, run_method, args, log_file,
        run_time=run_time, term_timeout=term_timeout
    )
    if success:
        logger.info(f"✓ Multisource test passed: {model} on {architecture}")
    else:
        logger.error(f"✗ Multisource test failed: {model} on {architecture}")
    return success, log_file


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
    pipeline_config = config["pipelines"]["reid_multisource"]
    args = build_test_args(
        config, pipeline_config, model, architecture, test_suite, extra_args
    )
    log_file = get_log_file_path(
        config, "pipeline", "reid_multisource", architecture, model, run_method, test_suite
    )
    stdout, stderr, success = run_pipeline_test(
        pipeline_config, model, architecture, run_method, args, log_file,
        run_time=run_time, term_timeout=term_timeout
    )
    if success:
        logger.info(f"✓ REID multisource test passed: {model} on {architecture}")
    else:
        logger.error(f"✗ REID multisource test failed: {model} on {architecture}")
    return success, log_file


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
    pipeline_config = config["pipelines"]["tiling"]
    args = build_test_args(
        config, pipeline_config, model, architecture, test_suite, extra_args
    )
    log_file = get_log_file_path(
        config, "pipeline", "tiling", architecture, model, run_method, test_suite
    )
    stdout, stderr, success = run_pipeline_test(
        pipeline_config, model, architecture, run_method, args, log_file,
        run_time=run_time, term_timeout=term_timeout
    )
    if success:
        logger.info(f"✓ Tiling test passed: {model} on {architecture}")
    else:
        logger.error(f"✗ Tiling test failed: {model} on {architecture}")
    return success, log_file


# Map pipeline names to test functions
PIPELINE_TEST_FUNCTIONS = {
    "detection": run_detection_test,
    "pose_estimation": run_pose_estimation_test,
    "depth": run_depth_test,
    "instance_segmentation": run_instance_segmentation_test,
    "simple_detection": run_simple_detection_test,
    "face_recognition": run_face_recognition_test,
    "multisource": run_multisource_test,
    "reid_multisource": run_reid_multisource_test,
    "tiling": run_tiling_test,
}


def get_pipeline_test_function(pipeline_name: str):
    """Get test function for a pipeline.
    
    Args:
        pipeline_name: Name of the pipeline
    
    Returns:
        Test function or None if not found
    """
    return PIPELINE_TEST_FUNCTIONS.get(pipeline_name)

