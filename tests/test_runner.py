"""
Test Runner - Based on test_control.yaml and test_definition_config.yaml

This module:
1. Loads test_control.yaml (from tests/) and test_definition_config.yaml (from config/)
2. Integrates with resources_config.yaml for models and resources
3. Uses existing test framework functions
4. Supports run_mode (default/extra/all) and test_run_combinations
"""

import logging
import os
import yaml
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pytest

from hailo_apps.python.core.common.defines import (
    DEFAULT_DOTENV_PATH,
    HAILO8_ARCH,
    HAILO8L_ARCH,
    RESOURCES_ROOT_PATH_DEFAULT,
)
from hailo_apps.python.core.common.core import load_environment
from hailo_apps.python.core.common.installation_utils import (
    detect_hailo_arch,
    detect_host_arch,
)

from all_tests import get_pipeline_test_function
from test_utils import (
    build_hef_path,
    get_log_file_path,
    run_pipeline_test,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("test_runner")

# Configuration file paths
CONTROL_CONFIG_PATH = Path(__file__).parent / "test_control.yaml"
DEFINITION_CONFIG_PATH = Path(__file__).parent.parent / "hailo_apps" / "config" / "test_definition_config.yaml"
RESOURCES_CONFIG_PATH = Path(__file__).parent.parent / "hailo_apps" / "config" / "resources_config.yaml"


def load_env_file():
    """Load .env file from resources directory or default location."""
    # First try to load from repo's resources/.env
    repo_env_file = Path(__file__).parent.parent / "resources" / ".env"
    if repo_env_file.exists():
        logger.info(f"Loading .env file from: {repo_env_file}")
        load_environment(env_file=str(repo_env_file), required_vars=None)
    else:
        # Fall back to default location
        logger.info(f"Loading .env file from default location: {DEFAULT_DOTENV_PATH}")
        load_environment(env_file=DEFAULT_DOTENV_PATH, required_vars=None)


def detect_and_set_environment():
    """Detect host and Hailo architecture and set environment variables."""
    logger.info("=" * 80)
    logger.info("DETECTING SYSTEM ARCHITECTURE")
    logger.info("=" * 80)
    
    host_arch = detect_host_arch()
    hailo_arch = detect_hailo_arch()
    
    logger.info(f"Detected host architecture: {host_arch}")
    logger.info(f"Detected Hailo architecture: {hailo_arch or 'None (no device detected)'}")
    
    # Set in current process environment
    os.environ["HOST_ARCH"] = host_arch
    if hailo_arch:
        os.environ["HAILO_ARCH"] = hailo_arch
    
    logger.info("=" * 80)
    return host_arch, hailo_arch


def load_control_config() -> Dict:
    """Load test control configuration from test_control.yaml."""
    if not CONTROL_CONFIG_PATH.exists():
        pytest.fail(f"Test control configuration file not found: {CONTROL_CONFIG_PATH}")
    
    logger.info(f"Loading control configuration from: {CONTROL_CONFIG_PATH}")
    with open(CONTROL_CONFIG_PATH, 'r') as f:
        config = yaml.safe_load(f)
    
    if not config:
        pytest.fail("Failed to parse control configuration")
    
    logger.info("✅ Control configuration loaded")
    return config


def load_definition_config() -> Dict:
    """Load test definition configuration from test_definition_config.yaml."""
    if not DEFINITION_CONFIG_PATH.exists():
        pytest.fail(f"Test definition configuration file not found: {DEFINITION_CONFIG_PATH}")
    
    logger.info(f"Loading definition configuration from: {DEFINITION_CONFIG_PATH}")
    with open(DEFINITION_CONFIG_PATH, 'r') as f:
        config = yaml.safe_load(f)
    
    if not config:
        pytest.fail("Failed to parse definition configuration")
    
    logger.info("✅ Definition configuration loaded")
    return config


def load_resources_config() -> Dict:
    """Load resources configuration from resources_config.yaml."""
    if not RESOURCES_CONFIG_PATH.exists():
        pytest.fail(f"Resources configuration file not found: {RESOURCES_CONFIG_PATH}")
    
    logger.info(f"Loading resources configuration from: {RESOURCES_CONFIG_PATH}")
    with open(RESOURCES_CONFIG_PATH, 'r') as f:
        config = yaml.safe_load(f)
    
    if not config:
        pytest.fail("Failed to parse resources configuration")
    
    logger.info("✅ Resources configuration loaded")
    return config


def get_models_for_app_and_arch(resources_config: Dict, app_name: str, architecture: str, model_selection: str = "default") -> List[str]:
    """Get models for an app and architecture based on model_selection.
    
    Args:
        resources_config: Resources configuration
        app_name: Application name
        architecture: Architecture (hailo8, hailo8l, hailo10h)
        model_selection: Model selection (default, extra, all)
    
    Returns:
        List of model names
    """
    if app_name not in resources_config:
        logger.warning(f"App {app_name} not found in resources config")
        return []
    
    app_config = resources_config[app_name]
    models_config = app_config.get("models", {})
    
    if architecture not in models_config:
        logger.warning(f"Architecture {architecture} not found for app {app_name}")
        return []
    
    arch_models = models_config[architecture]
    models = []
    
    # Get default model if model_selection is "default" or "all"
    if model_selection in ["default", "all"]:
        if "default" in arch_models and arch_models["default"]:
            default_model = arch_models["default"]
            if isinstance(default_model, dict):
                models.append(default_model["name"])
            else:
                models.append(default_model)
    
    # Get extra models if model_selection is "extra" or "all"
    if model_selection in ["extra", "all"]:
        if "extra" in arch_models:
            for extra_model in arch_models["extra"]:
                if isinstance(extra_model, dict):
                    models.append(extra_model["name"])
                else:
                    models.append(extra_model)
    
    return models


def resolve_test_suite_flags(definition_config: Dict, suite_name: str, resources_config: Dict, app_name: str, architecture: str, model: str) -> List[str]:
    """Resolve test suite flags with placeholders replaced.
    
    Args:
        definition_config: Test definition configuration
        suite_name: Test suite name
        resources_config: Resources configuration
        app_name: Application name
        architecture: Architecture
        model: Model name
    
    Returns:
        List of resolved flags
    """
    test_suites = definition_config.get("test_suites", {})
    suite_config = test_suites.get(suite_name, {})
    flags = suite_config.get("flags", [])
    
    # Resolve placeholders
    resources_root = RESOURCES_ROOT_PATH_DEFAULT
    hef_path = build_hef_path(model, architecture, resources_root)
    
    # Get video path for app
    video_name = "example.mp4"  # default
    if app_name in resources_config:
        app_config = resources_config[app_name]
        # Try to get app-specific video from definition config resources
        # For now, use default
    
    video_path = os.path.join(resources_root, "videos", video_name)
    
    # Get labels JSON path if needed
    labels_json_path = None
    if app_name in resources_config:
        app_config = resources_config[app_name]
        json_files = app_config.get("json", [])
        if json_files:
            # Use first JSON file
            json_file = json_files[0]
            if isinstance(json_file, dict):
                json_name = json_file.get("name", "")
            else:
                json_name = json_file
            if json_name:
                labels_json_path = os.path.join(resources_root, "json", json_name)
    
    # Replace placeholders
    resolved_flags = []
    for flag in flags:
        resolved = flag.replace("${HEF_PATH}", hef_path)
        resolved = resolved.replace("${VIDEO_PATH}", video_path)
        if labels_json_path:
            resolved = resolved.replace("${LABELS_JSON_PATH}", labels_json_path)
        resolved = resolved.replace("${RESOURCES_ROOT}", resources_root)
        resolved_flags.append(resolved)
    
    return resolved_flags


def get_test_suites_for_mode(definition_config: Dict, app_name: str, test_suite_mode: str) -> List[str]:
    """Get test suites for an app based on test_suite_mode.
    
    Args:
        definition_config: Test definition configuration
        app_name: Application name
        test_suite_mode: Test suite mode (None, default, extra, all)
    
    Returns:
        List of test suite names (empty list if None)
    """
    if test_suite_mode == "None" or test_suite_mode is None:
        return []
    
    if app_name not in definition_config.get("apps", {}):
        return []
    
    app_config = definition_config["apps"][app_name]
    suites = []
    
    if test_suite_mode in ["default", "all"]:
        suites.extend(app_config.get("default_test_suites", []))
    
    if test_suite_mode in ["extra", "all"]:
        suites.extend(app_config.get("extra_test_suites", []))
    
    return suites


def generate_test_cases(
    control_config: Dict,
    definition_config: Dict,
    resources_config: Dict,
    detected_hailo_arch: Optional[str],
    host_arch: str,
    test_run_combination: Optional[str] = None,
) -> List[Dict]:
    """Generate test cases based on configuration.
    
    Args:
        control_config: Test control configuration
        definition_config: Test definition configuration
        resources_config: Resources configuration
        detected_hailo_arch: Detected Hailo architecture
        host_arch: Host architecture
        test_run_combination: Optional test run combination name
    
    Returns:
        List of test case dictionaries
    """
    test_cases = []
    
    # Get control parameters
    control_params = control_config.get("control_parameters", {})
    default_run_time = control_params.get("default_run_time", 24)
    term_timeout = control_params.get("term_timeout", 10)
    
    # Get enabled run methods
    run_methods_config = control_config.get("run_methods", {})
    enabled_run_methods = [
        name for name, config in run_methods_config.items()
        if config.get("enabled", False)
    ]
    
    # Determine which apps and modes to test
    # First check test_combinations in control_config
    test_combinations = control_config.get("test_combinations", {})
    enabled_combinations = [
        name for name, config in test_combinations.items()
        if config.get("enabled", False)
    ]
    
    if enabled_combinations:
        # Use first enabled test combination
        combination_name = enabled_combinations[0]
        logger.info(f"Using enabled test combination: {combination_name}")
        combinations = definition_config.get("test_run_combinations", {})
        if combination_name not in combinations:
            logger.warning(f"Test run combination {combination_name} not found in definition config")
            return []
        
        combo = combinations[combination_name]
        apps_to_test = combo.get("apps", [])
        test_suite_mode = combo.get("test_suite_mode", combo.get("mode", "default"))  # Support both old and new format
        model_selection = combo.get("model_selection", "default")
    elif test_run_combination:
        # Use explicitly provided test run combination
        combinations = definition_config.get("test_run_combinations", {})
        if test_run_combination not in combinations:
            logger.warning(f"Test run combination {test_run_combination} not found")
            return []
        
        combo = combinations[test_run_combination]
        apps_to_test = combo.get("apps", [])
        test_suite_mode = combo.get("test_suite_mode", combo.get("mode", "default"))  # Support both old and new format
        model_selection = combo.get("model_selection", "default")
    elif control_config.get("custom_tests", {}).get("enabled", False):
        # Use custom_tests per-app configuration
        custom_tests = control_config.get("custom_tests", {})
        apps_config = custom_tests.get("apps", {})
        apps_to_test = []
        for app_name, app_config in apps_config.items():
            test_suite_mode = app_config.get("test_suite_mode", "default")
            model_selection = app_config.get("model_selection", "default")
            if test_suite_mode and test_suite_mode != "None":
                apps_to_test.append((app_name, test_suite_mode, model_selection))
    else:
        # Default: no apps to test
        logger.warning("No test combination enabled and custom_tests disabled. No tests will run.")
        apps_to_test = []
    
    # Determine architectures to test - only run tests for detected/specified architecture
    architectures = []
    if detected_hailo_arch:
        # Only run tests for the detected architecture
        architectures = [detected_hailo_arch]
        
        # Special case: if hailo8 is detected and h8l_on_h8 special test is enabled,
        # also allow hailo8l tests (hailo8l models can run on hailo8 hardware)
        special_tests = control_config.get("special_tests", {})
        h8l_on_h8_enabled = special_tests.get("h8l_on_h8", {}).get("enabled", False)
        if detected_hailo_arch == HAILO8_ARCH and h8l_on_h8_enabled:
            logger.info("h8l_on_h8 special test enabled - adding hailo8l architecture tests")
            architectures.append(HAILO8L_ARCH)
    else:
        # If no device detected, don't run architecture-specific tests
        logger.warning("No Hailo device detected - skipping architecture-specific tests")
        architectures = []
    
    # Generate test cases
    if isinstance(apps_to_test, list) and len(apps_to_test) > 0 and isinstance(apps_to_test[0], tuple):
        # Use individual app configurations (from custom_tests)
        for app_config_tuple in apps_to_test:
            if len(app_config_tuple) == 3:
                app_name, test_suite_mode, model_selection = app_config_tuple
            else:
                # Backward compatibility
                app_name, test_suite_mode = app_config_tuple
                model_selection = "default"
            generate_cases_for_app(
                test_cases, control_config, definition_config, resources_config,
                app_name, test_suite_mode, model_selection, architectures, enabled_run_methods,
                default_run_time, term_timeout, host_arch
            )
    elif isinstance(apps_to_test, list):
        # Use combination mode for all apps (from test_run_combinations)
        for app_name in apps_to_test:
            generate_cases_for_app(
                test_cases, control_config, definition_config, resources_config,
                app_name, test_suite_mode, model_selection, architectures, enabled_run_methods,
                default_run_time, term_timeout, host_arch
            )
    
    logger.info(f"Generated {len(test_cases)} test cases")
    return test_cases


def generate_cases_for_app(
    test_cases: List[Dict],
    control_config: Dict,
    definition_config: Dict,
    resources_config: Dict,
    app_name: str,
    test_suite_mode: str,
    model_selection: str,
    architectures: List[str],
    run_methods: List[str],
    default_run_time: int,
    term_timeout: int,
    host_arch: str,
):
    """Generate test cases for a specific app.
    
    Args:
        test_cases: List to append test cases to
        control_config: Test control configuration
        definition_config: Test definition configuration
        resources_config: Resources configuration
        app_name: Application name
        test_suite_mode: Test suite mode (None, default, extra, all)
        model_selection: Model selection (default, extra, all)
        architectures: List of architectures to test
        run_methods: List of run methods to test
        default_run_time: Default run time for tests
        term_timeout: Termination timeout
        host_arch: Host architecture
    """
    if app_name not in definition_config.get("apps", {}):
        logger.warning(f"App {app_name} not found in definition config")
        return
    
    app_def = definition_config["apps"][app_name]
    
    # Get test suites for this test_suite_mode
    test_suites = get_test_suites_for_mode(definition_config, app_name, test_suite_mode)
    
    # Filter out RPI camera tests if host is not rpi
    rpi_suites = ["basic_input_rpi", "input_rpi_with_hef", "input_rpi_with_labels"]
    if host_arch != "rpi":
        test_suites = [ts for ts in test_suites if ts not in rpi_suites]
    
    for architecture in architectures:
        # Get models for this app and architecture based on model_selection
        models = get_models_for_app_and_arch(resources_config, app_name, architecture, model_selection)
        if not models:
            logger.info(f"No models for {app_name} on {architecture} with model_selection {model_selection}")
            continue
                
        for model in models:
            for run_method in run_methods:
                for test_suite in test_suites:
                    # Resolve test suite flags
                    flags = resolve_test_suite_flags(
                        definition_config, test_suite, resources_config,
                        app_name, architecture, model
                    )
                    
                    test_cases.append({
                        "app": app_name,
                        "app_config": app_def,
                        "architecture": architecture,
                        "model": model,
                        "run_method": run_method,
                        "test_suite": test_suite,
                        "flags": flags,
                        "run_time": default_run_time,
                        "term_timeout": term_timeout,
                        "test_suite_mode": test_suite_mode,
                        "model_selection": model_selection,
                    })


def get_log_file_path_new(
    control_config: Dict,
    app_name: str,
    test_suite_mode: str,
    architecture: Optional[str] = None,
    model: Optional[str] = None,
    run_method: Optional[str] = None,
    test_suite: Optional[str] = None,
) -> str:
    """Get log file path using new control config structure."""
    log_config = control_config.get("logging", {})
    subdirs = log_config.get("subdirs", {})
    per_app = subdirs.get("per_app", {})
    
    # Get app-specific log directory
    if app_name in per_app:
        app_log_dirs = per_app[app_name]
        # Map test_suite_mode to log directory (None -> default)
        log_mode = "default" if test_suite_mode == "None" else test_suite_mode
        log_dir = app_log_dirs.get(log_mode, app_log_dirs.get("default", "./logs"))
    else:
        log_dir = log_config.get("base_dir", "./logs")
    
    # Ensure directory exists
    os.makedirs(log_dir, exist_ok=True)
    
    # Build filename
    parts = [app_name]
    if architecture:
        parts.append(architecture)
    if model:
        parts.append(model)
    if run_method:
        parts.append(run_method)
    if test_suite and test_suite != "basic_show_fps":
        # Remove common prefixes for cleaner filenames
        suite_name = test_suite.replace("basic_", "").replace("input_", "").replace("pipeline_", "").replace("with_", "").replace("face_", "").replace("tiling_", "").replace("clip_", "").replace("multisource_", "")
        parts.append(suite_name)
    
    filename = "_".join(parts) + ".log"
    return os.path.join(log_dir, filename)


# Initialize at module level
logger.info("Initializing test runner...")
# Load .env file first to get any environment variables from it
load_env_file()
_host_arch, _hailo_arch = detect_and_set_environment()
_control_config = load_control_config()
_definition_config = load_definition_config()
_resources_config = load_resources_config()

# Generate test cases (can be overridden by test_run_combination parameter)
_test_cases = generate_test_cases(
    _control_config, _definition_config, _resources_config,
    _hailo_arch, _host_arch
)


@pytest.mark.parametrize(
    "test_case",
    _test_cases,
    ids=lambda tc: f"{tc['app']}_{tc['architecture']}_{tc['model']}_{tc['run_method']}_{tc['test_suite']}"
)
def test_pipeline(test_case: Dict):
    """Test a pipeline with specific configuration."""
    app_name = test_case["app"]
    app_config = test_case["app_config"]
    architecture = test_case["architecture"]
    model = test_case["model"]
    run_method = test_case["run_method"]
    test_suite = test_case["test_suite"]
    flags = test_case["flags"]
    run_time = test_case["run_time"]
    term_timeout = test_case["term_timeout"]
    test_suite_mode = test_case.get("test_suite_mode", "default")
    model_selection = test_case.get("model_selection", "default")
    
    # Get test function
    test_func = get_pipeline_test_function(app_name)
    if not test_func:
        pytest.skip(f"No test function for app: {app_name}")
    
    # Build pipeline config for compatibility with existing test functions
    pipeline_config = {
        "name": app_config.get("name", app_name),
        "module": app_config.get("module", ""),
        "script": app_config.get("script", ""),
        "cli": app_config.get("cli", ""),
    }
    
    # Create a compatible config structure
    compatible_config = {
        "pipelines": {
            app_name: pipeline_config
        },
        "test_suites": {
            test_suite: {
                "args": flags
            }
        },
        "resources": {
            "root_path": RESOURCES_ROOT_PATH_DEFAULT
        },
        "execution": {
            "default_run_time": run_time,
            "term_timeout": term_timeout,
        },
        "logging": _control_config.get("logging", {}),
    }
    
    # Get log file path
    log_file = get_log_file_path_new(
        _control_config, app_name, test_suite_mode, architecture, model, run_method, test_suite
    )
    
    # Run test using existing framework
    stdout, stderr, success = run_pipeline_test(
        pipeline_config, model, architecture, run_method, flags, log_file,
        run_time=run_time, term_timeout=term_timeout
    )
    
    # Assert success
    assert success, (
        f"App {app_name} with model {model} on {architecture} "
        f"using {run_method} with suite {test_suite} failed. "
        f"Check log: {log_file}"
    )


if __name__ == "__main__":
    # Print summary
    logger.info("=" * 80)
    logger.info("TEST RUNNER SUMMARY")
    logger.info("=" * 80)
    logger.info(f"Host architecture: {_host_arch}")
    logger.info(f"Hailo architecture: {_hailo_arch or 'None'}")
    logger.info(f"Total test cases: {len(_test_cases)}")
    logger.info("=" * 80)
    
    pytest.main(["-v", __file__])

