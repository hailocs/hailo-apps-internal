"""
Test Runner - Parses configuration and orchestrates test execution

This module:
1. Detects host and Hailo architecture at startup
2. Sets environment variables if not in .env
3. Parses test configuration
4. Orchestrates test execution based on configuration
"""

import logging
import os
import yaml
from pathlib import Path
from typing import Dict, List, Optional

import pytest

from hailo_apps.python.core.common.defines import (
    DEFAULT_DOTENV_PATH,
    HAILO8_ARCH,
    RESOURCES_ROOT_PATH_DEFAULT,
)
from hailo_apps.python.core.common.installation_utils import (
    detect_hailo_arch,
    detect_host_arch,
)

from .all_tests import get_pipeline_test_function
from .test_utils import (
    get_enabled_pipelines,
    get_enabled_run_methods,
    get_models_for_architecture,
    validate_test_config,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("test_runner")

# Configuration file path
CONFIG_PATH = Path(__file__).parent / "test_config.yaml"


def detect_and_set_environment():
    """Detect host and Hailo architecture and set environment variables.
    
    Checks .env file and sets variables if not present.
    """
    logger.info("=" * 80)
    logger.info("DETECTING SYSTEM ARCHITECTURE")
    logger.info("=" * 80)
    
    # Detect architectures
    host_arch = detect_host_arch()
    hailo_arch = detect_hailo_arch()
    
    logger.info(f"Detected host architecture: {host_arch}")
    logger.info(f"Detected Hailo architecture: {hailo_arch or 'None (no device detected)'}")
    
    # Check .env file
    env_file = Path(DEFAULT_DOTENV_PATH)
    env_vars = {}
    
    if env_file.exists():
        logger.info(f"Reading .env file: {env_file}")
        with open(env_file, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    env_vars[key.strip()] = value.strip()
    else:
        logger.info(f".env file not found at {env_file}, will create if needed")
    
    # Set environment variables if not present
    updates = {}
    
    if "HOST_ARCH" not in env_vars or not env_vars.get("HOST_ARCH"):
        updates["HOST_ARCH"] = host_arch
        logger.info(f"Setting HOST_ARCH={host_arch}")
    
    if "HAILO_ARCH" not in env_vars or not env_vars.get("HAILO_ARCH"):
        if hailo_arch:
            updates["HAILO_ARCH"] = hailo_arch
            logger.info(f"Setting HAILO_ARCH={hailo_arch}")
        else:
            logger.warning("HAILO_ARCH not detected and not in .env file")
    
    # Write updates to .env if needed
    if updates:
        logger.info(f"Writing environment variables to {env_file}")
        env_file.parent.mkdir(parents=True, exist_ok=True)
        
        # Read existing content
        existing_lines = []
        if env_file.exists():
            with open(env_file, 'r') as f:
                existing_lines = f.readlines()
        
        # Update or add variables
        updated_lines = []
        updated_keys = set()
        
        for line in existing_lines:
            line_stripped = line.strip()
            if line_stripped and not line_stripped.startswith('#') and '=' in line_stripped:
                key = line_stripped.split('=', 1)[0].strip()
                if key in updates:
                    updated_lines.append(f"{key}={updates[key]}\n")
                    updated_keys.add(key)
                else:
                    updated_lines.append(line)
            else:
                updated_lines.append(line)
        
        # Add new variables
        for key, value in updates.items():
            if key not in updated_keys:
                updated_lines.append(f"{key}={value}\n")
        
        # Write back
        with open(env_file, 'w') as f:
            f.writelines(updated_lines)
        
        logger.info(f"✅ Environment variables written to {env_file}")
    
    # Set in current process environment
    os.environ["HOST_ARCH"] = host_arch
    if hailo_arch:
        os.environ["HAILO_ARCH"] = hailo_arch
    
    logger.info("=" * 80)
    return host_arch, hailo_arch


def load_config() -> Dict:
    """Load test configuration from YAML file.
    
    Reads both sections:
    1. Top section (control/decisions) - what to run
    2. Bottom section (all configurations) - available options
    Then merges them based on enabled flags.
    """
    if not CONFIG_PATH.exists():
        pytest.fail(f"Test configuration file not found: {CONFIG_PATH}")
    
    logger.info(f"Loading configuration from: {CONFIG_PATH}")
    
    # Read entire file
    with open(CONFIG_PATH, 'r') as f:
        full_content = f.read()
    
    # Split into control section and configurations section
    control_lines = []
    config_lines = []
    in_control_section = True
    
    for line in full_content.split('\n'):
        if "END OF CONTROL SECTION" in line:
            in_control_section = False
            continue
        if in_control_section:
            control_lines.append(line)
        else:
            config_lines.append(line)
    
    # Parse both sections
    control_text = '\n'.join(control_lines)
    config_text = '\n'.join(config_lines)
    
    control_config = yaml.safe_load(control_text)
    all_configs = yaml.safe_load(config_text)
    
    if not control_config:
        pytest.fail("Failed to parse control section")
    if not all_configs:
        pytest.fail("Failed to parse configurations section")
    
    # Merge: Use control section decisions to enable configurations from bottom section
    merged_config = {}
    
    # Copy execution and logging from control
    merged_config["execution"] = control_config.get("execution", {})
    merged_config["logging"] = control_config.get("logging", {})
    
    # Get enabled pipelines from control section
    enabled_pipelines_dict = control_config.get("enabled_pipelines", {})
    
    # Filter pipelines from bottom section based on enabled flags
    all_pipelines = all_configs.get("pipelines", {})
    merged_config["pipelines"] = {
        name: pipeline
        for name, pipeline in all_pipelines.items()
        if enabled_pipelines_dict.get(name, True)
    }
    
    # Get enabled run methods from control section
    enabled_run_methods_dict = control_config.get("enabled_run_methods", {})
    
    # Filter run methods from bottom section
    all_run_methods = all_configs.get("run_methods", {})
    merged_config["run_methods"] = [
        {"name": name, "enabled": enabled_run_methods_dict.get(name, True), **method_config}
        for name, method_config in all_run_methods.items()
    ]
    
    # Copy test suites from bottom section (all available)
    merged_config["test_suites"] = all_configs.get("test_suites", {})
    
    # Copy test selection and profiles from control section
    merged_config["test_selection"] = control_config.get("test_selection", {})
    merged_config["test_profiles"] = control_config.get("test_profiles", {})
    
    # Copy special test configurations from bottom section
    merged_config["hailo8l_on_hailo8_tests"] = all_configs.get("hailo8l_on_hailo8_tests", {})
    merged_config["retraining"] = all_configs.get("retraining", {})
    merged_config["sanity_checks"] = all_configs.get("sanity_checks", {})
    merged_config["human_verification"] = all_configs.get("human_verification", {})
    merged_config["resources"] = all_configs.get("resources", {})
    
    # Add enabled flags for special tests from control section
    special_tests = control_config.get("special_tests", {})
    if "hailo8l_on_hailo8_tests" in merged_config:
        merged_config["hailo8l_on_hailo8_tests"]["enabled"] = special_tests.get("hailo8l_on_hailo8", True)
    if "retraining" in merged_config:
        merged_config["retraining"]["enabled"] = special_tests.get("retraining", True)
    if "sanity_checks" in merged_config:
        merged_config["sanity_checks"]["enabled"] = special_tests.get("sanity_checks", True)
    if "human_verification" in merged_config:
        merged_config["human_verification"]["enabled"] = special_tests.get("human_verification", True)
    
    # Validate merged configuration
    is_valid, errors = validate_test_config(merged_config)
    if not is_valid:
        error_msg = "Configuration validation failed:\n" + "\n".join(f"  - {e}" for e in errors)
        pytest.fail(error_msg)
    
    logger.info("✅ Configuration loaded and merged (control + available configs)")
    return merged_config


def resolve_test_selection(config: Dict, detected_hailo_arch: Optional[str]) -> Dict:
    """Resolve what tests to run based on profiles and test_selection."""
    test_selection = config.get("test_selection", {})
    test_profiles = config.get("test_profiles", {})
    
    # Find enabled profiles
    enabled_profiles = [
        name for name, profile in test_profiles.items()
        if profile.get("enabled", False)
    ]
    
    # Start with test_selection defaults
    selected_pipelines = test_selection.get("pipelines", "all")
    selected_architectures = test_selection.get("architectures", "all")
    selected_run_methods = test_selection.get("run_methods", "all")
    selected_test_suites = test_selection.get("test_suites", ["default"])
    
    # Override based on enabled profiles
    for profile_name in enabled_profiles:
        profile = test_profiles[profile_name]
        logger.info(f"Active profile: {profile_name} - {profile.get('description', '')}")
        
        if "pipelines" in profile:
            selected_pipelines = profile["pipelines"]
        if "architectures" in profile:
            selected_architectures = profile["architectures"]
    
    # Resolve "all" to actual lists
    if selected_pipelines == "all":
        enabled_pipelines = get_enabled_pipelines(config)
        selected_pipelines = list(enabled_pipelines.keys())
    
    if selected_architectures == "all":
        selected_architectures = ["hailo8", "hailo8l", "hailo10h"]
    
    if selected_run_methods == "all":
        selected_run_methods = get_enabled_run_methods(config)
    
    # Filter architectures based on detected device
    if detected_hailo_arch:
        if detected_hailo_arch == HAILO8_ARCH:
            # Hailo8 device: can run hailo8, hailo8l (compatibility), and hailo10h (same models)
            # Keep hailo8 and hailo10h, but filter hailo8l unless explicitly testing compatibility
            if "hailo8l" in selected_architectures:
                # Hailo8L models can run on Hailo8 for compatibility testing
                # Only include if hailo8l_on_hailo8 special test is enabled
                if not config.get("hailo8l_on_hailo8_tests", {}).get("enabled", False):
                    logger.info("Hailo8L architecture in selection, but hailo8l_on_hailo8 test not enabled. "
                              "Hailo8L models can run on Hailo8 - enable special_tests.hailo8l_on_hailo8 to test.")
                    selected_architectures = [a for a in selected_architectures if a != "hailo8l"]
            # hailo10h can run on hailo8 (same models)
            logger.info(f"Hailo8 device detected - will test: {selected_architectures}")
        else:
            # For other architectures, only test the detected architecture
            if detected_hailo_arch not in selected_architectures:
                logger.warning(f"Detected architecture {detected_hailo_arch} not in selected architectures")
            selected_architectures = [detected_hailo_arch]
    
    return {
        "pipelines": selected_pipelines,
        "architectures": selected_architectures,
        "run_methods": selected_run_methods,
        "test_suites": selected_test_suites,
    }


def generate_test_cases(config: Dict, selection: Dict) -> List[Dict]:
    """Generate test cases based on configuration and selection."""
    test_cases = []
    pipelines = config.get("pipelines", {})
    exec_config = config.get("execution", {})
    default_run_time = exec_config.get("default_run_time", 10)
    
    for pipeline_name in selection["pipelines"]:
        if pipeline_name not in pipelines:
            logger.warning(f"Pipeline {pipeline_name} not found in configuration")
            continue
        
        pipeline = pipelines[pipeline_name]
        if not pipeline.get("enabled", True):
            logger.info(f"Skipping disabled pipeline: {pipeline_name}")
            continue
        
        for architecture in selection["architectures"]:
            models = get_models_for_architecture(pipeline, architecture)
            if not models:
                logger.info(f"No models for {pipeline_name} on {architecture}")
                continue
            
            for model in models:
                for run_method in selection["run_methods"]:
                    for test_suite in selection["test_suites"]:
                        test_cases.append({
                            "pipeline": pipeline_name,
                            "pipeline_config": pipeline,
                            "architecture": architecture,
                            "model": model,
                            "run_method": run_method,
                            "test_suite": test_suite,
                            "run_time": default_run_time,
                        })
    
    logger.info(f"Generated {len(test_cases)} test cases")
    return test_cases


# Initialize at module level
logger.info("Initializing test runner...")
_host_arch, _hailo_arch = detect_and_set_environment()
_config = load_config()
_selection = resolve_test_selection(_config, _hailo_arch)
_test_cases = generate_test_cases(_config, _selection)


@pytest.mark.parametrize("test_case", _test_cases, ids=lambda tc: f"{tc['pipeline']}_{tc['architecture']}_{tc['model']}_{tc['run_method']}_{tc['test_suite']}")
def test_pipeline(test_case: Dict):
    """Test a pipeline with specific configuration.
    
    This is the main test function that gets parametrized with all test cases.
    """
    pipeline_name = test_case["pipeline"]
    pipeline_config = test_case["pipeline_config"]
    architecture = test_case["architecture"]
    model = test_case["model"]
    run_method = test_case["run_method"]
    test_suite = test_case["test_suite"]
    run_time = test_case["run_time"]
    
    # Get test function
    test_func = get_pipeline_test_function(pipeline_name)
    if not test_func:
        pytest.skip(f"No test function for pipeline: {pipeline_name}")
    
    # Run test
    success, log_file = test_func(
        _config,
        model,
        architecture,
        run_method,
        test_suite=test_suite,
        run_time=run_time,
    )
    
    # Assert success
    assert success, (
        f"Pipeline {pipeline_name} with model {model} on {architecture} "
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
    logger.info(f"Selected pipelines: {_selection['pipelines']}")
    logger.info(f"Selected architectures: {_selection['architectures']}")
    logger.info(f"Selected run methods: {_selection['run_methods']}")
    logger.info(f"Selected test suites: {_selection['test_suites']}")
    logger.info(f"Total test cases: {len(_test_cases)}")
    logger.info("=" * 80)
    
    pytest.main(["-v", __file__])
