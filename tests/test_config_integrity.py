"""
Configuration Integrity Tests

Validates that all configuration files (resources_config, test_definition_config,
test_control) load correctly and are consistent with each other.

Derived from verify_configs.py, integrated into pytest for CI.

Run with: pytest tests/test_config_integrity.py -v
"""

import logging
from pathlib import Path

import pytest

# ============================================================================
# IMPORTS WITH FALLBACKS
# ============================================================================

try:
    from hailo_apps.config import config_manager
    from hailo_apps.config.config_manager import ConfigPaths, ConfigError

    IMPORTS_AVAILABLE = True
except ImportError:
    IMPORTS_AVAILABLE = False
    config_manager = None
    ConfigPaths = None

REPO_ROOT = Path(__file__).resolve().parents[1]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("config-integrity-tests")


def _skip_if_no_imports():
    if not IMPORTS_AVAILABLE:
        pytest.skip("hailo_apps not importable – skipping config integrity checks")


# ============================================================================
# SECTION 1: CONFIG FILES EXIST
# ============================================================================


@pytest.mark.sanity
class TestConfigFilesExist:
    """Verify that essential configuration files are present."""

    def test_main_config_exists(self):
        _skip_if_no_imports()
        path = ConfigPaths.main_config()
        assert path.exists(), f"Main config not found: {path}"

    def test_resources_config_exists(self):
        _skip_if_no_imports()
        path = ConfigPaths.resources_config()
        assert path.exists(), f"Resources config not found: {path}"

    def test_test_definition_config_exists(self):
        _skip_if_no_imports()
        path = ConfigPaths.test_definition_config()
        assert path.exists(), f"Test definition config not found: {path}"

    def test_test_control_config_exists(self):
        """test_control.yaml is optional but should be present for full testing."""
        _skip_if_no_imports()
        path = ConfigPaths.test_control_config()
        if not path.exists():
            logger.warning("test_control.yaml not found (optional)")
        # No assertion – file is optional


# ============================================================================
# SECTION 2: CONFIGS LOAD SUCCESSFULLY
# ============================================================================


@pytest.mark.sanity
class TestConfigsLoadable:
    """Verify that each config can be parsed without errors."""

    def test_main_config_loads(self):
        _skip_if_no_imports()
        main = config_manager.get_main_config()
        assert isinstance(main, dict), "Main config did not return a dict"
        assert "valid_versions" in main, "Main config missing 'valid_versions' key"

    def test_resources_config_loads(self):
        _skip_if_no_imports()
        apps = config_manager.get_available_apps()
        assert isinstance(apps, list), "get_available_apps() did not return a list"
        assert len(apps) > 0, "No apps found in resources config"

    def test_test_definition_config_loads(self):
        _skip_if_no_imports()
        defined = config_manager.get_defined_apps()
        assert isinstance(defined, list), "get_defined_apps() did not return a list"
        assert len(defined) > 0, "No apps found in test definition config"

    def test_test_suites_load(self):
        _skip_if_no_imports()
        suites = config_manager.get_all_test_suites()
        assert isinstance(suites, (list, dict)), "get_all_test_suites() returned unexpected type"
        assert len(suites) > 0, "No test suites defined"


# ============================================================================
# SECTION 3: CROSS-VALIDATION
# ============================================================================


@pytest.mark.sanity
class TestConfigCrossValidation:
    """Cross-validate references between config files."""

    def test_custom_test_apps_exist_in_definitions(self):
        """Every app listed in test_control custom_tests must exist in test_definition_config."""
        _skip_if_no_imports()
        custom_apps = set(config_manager.get_custom_test_apps().keys())
        defined_apps = set(config_manager.get_defined_apps())

        missing = custom_apps - defined_apps
        assert not missing, (
            f"Apps in test_control custom_tests but not in test_definition_config: {missing}"
        )

    def test_referenced_suites_exist(self):
        """Every test suite referenced by an app definition must be defined."""
        _skip_if_no_imports()
        all_suites = set(config_manager.get_all_test_suites())
        referenced = set()

        for app_name in config_manager.get_defined_apps():
            app_def = config_manager.get_app_definition(app_name)
            if app_def:
                referenced.update(app_def.default_test_suites)
                referenced.update(app_def.extra_test_suites)

        missing = referenced - all_suites
        assert not missing, (
            f"Test suites referenced by apps but not defined: {missing}"
        )

    def test_app_consistency_resources_vs_definitions(self):
        """Warn (not fail) if apps diverge between resources_config and test_definition_config."""
        _skip_if_no_imports()
        resource_apps = set(config_manager.get_available_apps())
        definition_apps = set(config_manager.get_defined_apps())

        only_resources = resource_apps - definition_apps
        only_definitions = definition_apps - resource_apps

        if only_resources:
            logger.warning(
                "Apps in resources_config but not in test definitions: %s", only_resources
            )
        if only_definitions:
            logger.warning(
                "Apps in test definitions but not in resources_config: %s", only_definitions
            )

    def test_control_combinations_exist_in_definitions(self):
        """Test combinations in test_control must exist in test_definition_config."""
        _skip_if_no_imports()
        control_config = config_manager.get_test_control_config()
        if not control_config:
            pytest.skip("No test_control config")

        control_combos = set(control_config.get("test_combinations", {}).keys())
        definition_combos = set(config_manager.get_all_test_run_combinations())

        missing = control_combos - definition_combos
        assert not missing, (
            f"Test combinations in test_control but not in definitions: {missing}"
        )
