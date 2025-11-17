"""
Test Utilities for Pipeline Execution

This module provides utilities for creating and running pipeline tests
based on configuration.
"""

import logging
import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from hailo_apps.python.core.common.defines import RESOURCES_ROOT_PATH_DEFAULT
from hailo_apps.python.core.common.test_utils import (
    get_pipeline_args,
    run_pipeline_cli_with_args,
    run_pipeline_module_with_args,
    run_pipeline_pythonpath_with_args,
)

logger = logging.getLogger(__name__)

# Map run method names to functions
RUN_METHOD_FUNCTIONS = {
    "module": run_pipeline_module_with_args,
    "pythonpath": run_pipeline_pythonpath_with_args,
    "cli": run_pipeline_cli_with_args,
}


def build_hef_path(model: str, architecture: str, resources_root: Optional[str] = None) -> str:
    """Build full path to HEF file.
    
    Args:
        model: Model name (without .hef extension)
        architecture: Architecture (hailo8, hailo8l, hailo10h)
        resources_root: Resources root path (defaults to RESOURCES_ROOT_PATH_DEFAULT)
    
    Returns:
        Full path to HEF file
    """
    if resources_root is None:
        resources_root = RESOURCES_ROOT_PATH_DEFAULT
    
    hef_file = f"{model}.hef"
    return os.path.join(resources_root, "models", architecture, hef_file)


def build_test_args(
    config: Dict,
    pipeline_config: Dict,
    model: str,
    architecture: str,
    test_suite: str = "default",
    extra_args: Optional[List[str]] = None,
) -> List[str]:
    """Build command-line arguments for a test.
    
    Args:
        config: Full test configuration
        pipeline_config: Pipeline-specific configuration
        model: Model name
        architecture: Architecture name
        test_suite: Test suite name (default: "default")
        extra_args: Additional arguments to append
    
    Returns:
        List of command-line arguments
    """
    args = []
    
    # Add HEF path
    hef_path = build_hef_path(model, architecture)
    args.extend(["--hef-path", hef_path])
    
    # Add test suite arguments
    test_suites = config.get("test_suites", {})
    suite_config = test_suites.get(test_suite, {})
    suite_args = suite_config.get("args", [])
    
    # Replace placeholders in suite args
    resources_root = config.get("resources", {}).get("root_path", RESOURCES_ROOT_PATH_DEFAULT)
    suite_args = [
        arg.replace("${HEF_PATH}", hef_path)
        .replace("${RESOURCES_ROOT}", resources_root)
        for arg in suite_args
    ]
    
    args.extend(suite_args)
    
    # Add extra arguments if provided
    if extra_args:
        args.extend(extra_args)
    
    return args


def run_pipeline_test(
    pipeline_config: Dict,
    model: str,
    architecture: str,
    run_method: str,
    args: List[str],
    log_file: str,
    run_time: Optional[int] = None,
    term_timeout: Optional[int] = None,
) -> Tuple[bytes, bytes, bool]:
    """Run a pipeline test and return results.
    
    Args:
        pipeline_config: Pipeline configuration
        model: Model name
        architecture: Architecture name
        run_method: Run method ("module", "pythonpath", or "cli")
        args: Command-line arguments
        log_file: Path to log file
        run_time: Optional run time override
        term_timeout: Optional termination timeout override
    
    Returns:
        Tuple of (stdout, stderr, success)
    """
    run_func = RUN_METHOD_FUNCTIONS.get(run_method)
    if not run_func:
        logger.error(f"Unknown run method: {run_method}")
        return b"", b"Unknown run method".encode(), False
    
    try:
        kwargs = {}
        if run_time is not None:
            kwargs["run_time"] = run_time
        if term_timeout is not None:
            kwargs["term_timeout"] = term_timeout
        
        if run_method == "module":
            stdout, stderr = run_func(pipeline_config["module"], args, log_file, **kwargs)
        elif run_method == "pythonpath":
            stdout, stderr = run_func(pipeline_config["script"], args, log_file, **kwargs)
        elif run_method == "cli":
            stdout, stderr = run_func(pipeline_config["cli"], args, log_file, **kwargs)
        else:
            return b"", b"Invalid run method".encode(), False
        
        # Check for errors
        err_str = stderr.decode().lower() if stderr else ""
        success = "error" not in err_str and "traceback" not in err_str
        
        return stdout, stderr, success
        
    except Exception as e:
        logger.error(f"Exception running pipeline test: {e}")
        return b"", str(e).encode(), False


def get_log_file_path(
    config: Dict,
    test_type: str,
    pipeline_name: str,
    architecture: Optional[str] = None,
    model: Optional[str] = None,
    run_method: Optional[str] = None,
    test_suite: Optional[str] = None,
) -> str:
    """Get log file path for a test.
    
    Args:
        config: Test configuration
        test_type: Type of test (e.g., "pipeline", "h8l_on_h8", "human_verification")
        pipeline_name: Pipeline name
        architecture: Optional architecture name
        model: Optional model name
        run_method: Optional run method name
        test_suite: Optional test suite name
    
    Returns:
        Full path to log file
    """
    log_config = config.get("logging", {})
    base_dir = log_config.get("base_dir", "logs")
    subdirs = log_config.get("subdirectories", {})
    
    # Get appropriate subdirectory
    if test_type in subdirs:
        log_dir = subdirs[test_type]
    else:
        log_dir = base_dir
    
    # Ensure directory exists
    os.makedirs(log_dir, exist_ok=True)
    
    # Build filename
    parts = [pipeline_name]
    if architecture:
        parts.append(architecture)
    if model:
        parts.append(model)
    if run_method:
        parts.append(run_method)
    if test_suite and test_suite != "default":
        parts.append(test_suite)
    
    filename = "_".join(parts) + ".log"
    return os.path.join(log_dir, filename)


def validate_test_config(config: Dict) -> Tuple[bool, List[str]]:
    """Validate test configuration.
    
    Args:
        config: Test configuration dictionary
    
    Returns:
        Tuple of (is_valid, list_of_errors)
    """
    errors = []
    
    # Check required sections
    required_sections = ["execution", "logging", "pipelines", "run_methods"]
    for section in required_sections:
        if section not in config:
            errors.append(f"Missing required section: {section}")
    
    # Check execution settings
    if "execution" in config:
        exec_config = config["execution"]
        if "default_run_time" not in exec_config:
            errors.append("Missing execution.default_run_time")
        if "term_timeout" not in exec_config:
            errors.append("Missing execution.term_timeout")
    
    # Check pipelines
    if "pipelines" in config:
        for pipeline_name, pipeline_config in config["pipelines"].items():
            required_keys = ["name", "module", "script", "cli", "models"]
            for key in required_keys:
                if key not in pipeline_config:
                    errors.append(f"Pipeline {pipeline_name} missing required key: {key}")
    
    # Check run methods
    if "run_methods" in config:
        for rm in config["run_methods"]:
            if "name" not in rm:
                errors.append("Run method missing 'name' field")
            if rm["name"] not in RUN_METHOD_FUNCTIONS:
                errors.append(f"Unknown run method: {rm['name']}")
    
    return len(errors) == 0, errors


def get_enabled_pipelines(config: Dict) -> Dict[str, Dict]:
    """Get all enabled pipelines from configuration.
    
    Args:
        config: Test configuration
    
    Returns:
        Dictionary of enabled pipeline configurations
    """
    pipelines = config.get("pipelines", {})
    return {
        name: pipeline
        for name, pipeline in pipelines.items()
        if pipeline.get("enabled", True)
    }


def get_enabled_run_methods(config: Dict) -> List[str]:
    """Get all enabled run methods from configuration.
    
    Args:
        config: Test configuration
    
    Returns:
        List of enabled run method names
    """
    run_methods = config.get("run_methods", [])
    return [
        rm["name"]
        for rm in run_methods
        if rm.get("enabled", True)
    ]


def get_models_for_architecture(pipeline_config: Dict, architecture: str) -> List[str]:
    """Get models for a specific architecture from pipeline configuration.
    
    Models can be specified in two ways:
    1. "default" key - models available for all architectures
    2. Architecture-specific key (e.g., "hailo8", "hailo8l", "hailo10h") - models specific to that architecture
    
    The function combines default models with architecture-specific models.
    
    Args:
        pipeline_config: Pipeline configuration
        architecture: Architecture name
    
    Returns:
        List of model names for the architecture (default + architecture-specific)
    """
    models_config = pipeline_config.get("models", {})
    models = []
    
    # Add default models (available for all architectures)
    if "default" in models_config:
        models.extend(models_config["default"])
    
    # Add architecture-specific models
    if architecture in models_config:
        models.extend(models_config[architecture])
    
    return models


def expand_test_suite_args(config: Dict, suite_name: str, **replacements) -> List[str]:
    """Expand test suite arguments with replacements.
    
    Args:
        config: Test configuration
        suite_name: Test suite name
        **replacements: Key-value pairs for placeholder replacement
    
    Returns:
        List of expanded arguments
    """
    test_suites = config.get("test_suites", {})
    suite_config = test_suites.get(suite_name, {})
    args = suite_config.get("args", [])
    
    # Apply replacements
    for key, value in replacements.items():
        placeholder = f"${{{key}}}"
        args = [arg.replace(placeholder, str(value)) for arg in args]
    
    return args

