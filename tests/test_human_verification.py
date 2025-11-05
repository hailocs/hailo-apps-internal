"""
Human Verification Test

This test runs each Hailo app for approximately 25 seconds (allowing for 2 video rewinds)
to enable human verification that all apps are working correctly.

Each app runs with default settings using the default video file.
"""

import logging
import os
import signal
import subprocess
import time
from pathlib import Path

import pytest

from hailo_apps.python.core.common.camera_utils import is_rpi_camera_available
from hailo_apps.python.core.common.defines import (
    RESOURCES_ROOT_PATH_DEFAULT,
    RESOURCES_VIDEOS_DIR_NAME,
    BASIC_PIPELINES_VIDEO_EXAMPLE_NAME,
)
from hailo_apps.python.core.common.installation_utils import (
    detect_hailo_arch,
    detect_host_arch,
)
from hailo_apps.python.core.common.test_utils import (
    get_pipeline_args,
    run_pipeline_cli_with_args,
    run_pipeline_module_with_args,
    run_pipeline_pythonpath_with_args,
)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("human_verification_test")

# Test configuration
HUMAN_VERIFICATION_RUN_TIME = 25  # seconds (allows for 2 video rewinds + buffer)
TERM_TIMEOUT = 5  # seconds

# Define all available apps with their configurations
APPS = [
    {
        "name": "detection",
        "script": "hailo_apps/python/pipeline_apps/detection/detection_pipeline.py",
        "description": "Object Detection App - detects objects in video frames"
    },
    {
        "name": "depth",
        "script": "hailo_apps/python/pipeline_apps/depth/depth_pipeline.py",
        "description": "Depth Estimation App - estimates depth from video frames"
    },
    {
        "name": "face_recognition",
        "script": "hailo_apps/python/pipeline_apps/face_recognition/face_recognition.py",
        "description": "Face Recognition App - detects and recognizes faces"
    },
    {
        "name": "instance_segmentation",
        "script": "hailo_apps/python/pipeline_apps/instance_segmentation/instance_segmentation_pipeline.py",
        "description": "Instance Segmentation App - segments individual object instances"
    },
    {
        "name": "pose_estimation",
        "script": "hailo_apps/python/pipeline_apps/pose_estimation/pose_estimation_pipeline.py",
        "description": "Pose Estimation App - estimates human pose keypoints"
    },
    {
        "name": "detection_simple",
        "script": "hailo_apps/python/pipeline_apps/detection_simple/detection_pipeline_simple.py",
        "description": "Simple Detection App - simplified object detection"
    },
    {
        "name": "multisource",
        "script": "hailo_apps/python/pipeline_apps/multisource/multisource_pipeline.py",
        "description": "Multisource App - processes multiple video sources"
    },
    {
        "name": "reid_multisource",
        "script": "hailo_apps/python/pipeline_apps/reid_multisource/reid_multisource_pipeline.py",
        "description": "REID Multisource App - person re-identification across multiple sources"
    },
    {
        "name": "tiling",
        "script": "hailo_apps/python/pipeline_apps/tiling/tiling_pipeline.py",
        "description": "Tiling App - processes video using tiling approach"
    },
]

# Only use script (pythonpath) method
run_methods = {
    "pythonpath": run_pipeline_pythonpath_with_args,
}


def run_app_with_video_rewind(app):
    """
    Run an app with default video selection, allowing for 2 video rewinds (25 seconds total).
    
    Args:
        app: App configuration dictionary
    
    Returns:
        tuple: (success, stdout, stderr, log_file)
    """
    app_name = app["name"]
    run_method = run_methods["pythonpath"]
    
    # Create logs directory
    log_dir = "logs/human_verification"
    os.makedirs(log_dir, exist_ok=True)
    
    # No video file specified - let the app use its default
    args = []
    
    # Create log file path
    log_file_path = os.path.join(log_dir, f"{app_name}_human_verification.log")
    
    logger.info(f"Starting {app_name} - {app['description']}")
    logger.info(f"Using default video selection")
    logger.info(f"Run time: {HUMAN_VERIFICATION_RUN_TIME} seconds (2 video rewinds)")
    
    try:
        # Run the app using script method with no arguments (default behavior)
        stdout, stderr = run_method(app["script"], args, log_file_path,
                                 run_time=HUMAN_VERIFICATION_RUN_TIME,
                                 term_timeout=TERM_TIMEOUT)
        
        # Check for errors
        err_str = stderr.decode().lower() if stderr else ""
        success = "error" not in err_str and "traceback" not in err_str
        
        if success:
            logger.info(f"✓ {app_name} completed successfully")
        else:
            logger.error(f"✗ {app_name} failed with errors")
            logger.error(f"Error output: {err_str}")
        
        return success, stdout, stderr, log_file_path
        
    except Exception as e:
        logger.error(f"Exception while running {app_name}: {e}")
        return False, b"", str(e).encode(), log_file_path


@pytest.mark.parametrize("app", APPS, ids=[app["name"] for app in APPS])
def test_app_human_verification(app):
    """
    Test each app using script method for human verification.
    Runs for 25 seconds to allow 2 video rewinds.
    """
    success, stdout, stderr, log_file = run_app_with_video_rewind(app)
    
    # Log results for human verification
    logger.info(f"Human Verification Results for {app['name']}:")
    logger.info(f"Success: {success}")
    logger.info(f"Log file: {log_file}")
    
    if stdout:
        logger.info(f"Output preview: {stdout.decode()[:500]}...")
    
    # Basic assertion - app should not crash with errors
    err_str = stderr.decode().lower() if stderr else ""
    assert "error" not in err_str, (
        f"{app['name']} reported errors during human verification: {err_str}"
    )
    assert "traceback" not in err_str, (
        f"{app['name']} had traceback during human verification: {err_str}"
    )


def test_all_apps_human_verification_summary():
    """
    Run all apps and provide a summary for human verification.
    This test gives an overview of all apps running successfully.
    """
    logger.info("=" * 80)
    logger.info("HUMAN VERIFICATION TEST - ALL APPS SUMMARY")
    logger.info("=" * 80)
    logger.info(f"Testing {len(APPS)} apps for {HUMAN_VERIFICATION_RUN_TIME} seconds each")
    logger.info("Each app will use its default video selection, allowing for 2 video rewinds")
    logger.info("=" * 80)
    
    results = {}
    total_tests = 0
    total_passed = 0
    
    for app in APPS:
        app_name = app["name"]
        logger.info(f"\nTesting {app_name}: {app['description']}")
        
        # Test with script method
        success, stdout, stderr, log_file = run_app_with_video_rewind(app)
        
        results[app_name] = {
            "success": success,
            "description": app["description"],
            "log_file": log_file,
            "stdout": stdout.decode() if stdout else "",
            "stderr": stderr.decode() if stderr else "",
        }
        
        total_tests += 1
        if success:
            total_passed += 1
            logger.info(f"✓ {app_name}: PASSED")
        else:
            logger.error(f"✗ {app_name}: FAILED")
    
    # Generate summary report
    logger.info("\n" + "=" * 80)
    logger.info("HUMAN VERIFICATION SUMMARY")
    logger.info("=" * 80)
    logger.info(f"Total apps tested: {total_tests}")
    logger.info(f"Successfully passed: {total_passed}")
    logger.info(f"Failed: {total_tests - total_passed}")
    logger.info("=" * 80)
    
    # Detailed results
    for app_name, result in results.items():
        status = "PASS" if result["success"] else "FAIL"
        logger.info(f"{status:4} | {app_name:20} | {result['description']}")
        if not result["success"]:
            logger.error(f"      Error: {result['stderr'][:200]}...")
    
    logger.info("=" * 80)
    logger.info("HUMAN VERIFICATION INSTRUCTIONS:")
    logger.info("1. Check the log files in logs/human_verification/ for detailed output")
    logger.info("2. Verify that each app processed video frames correctly")
    logger.info("3. Look for detection/processing output in the logs")
    logger.info("4. Ensure no critical errors occurred during execution")
    logger.info("=" * 80)
    
    # Assert overall success
    if total_passed < total_tests:
        failed_apps = [name for name, result in results.items() if not result["success"]]
        pytest.fail(
            f"Human verification failed. {total_passed}/{total_tests} apps passed. "
            f"Failed apps: {failed_apps}"
        )


if __name__ == "__main__":
    # You can run specific tests like this:
    # pytest test_human_verification.py::test_all_apps_human_verification_summary -v -s
    # pytest test_human_verification.py::test_app_human_verification -v -s
    pytest.main(["-v", "-s", __file__])
