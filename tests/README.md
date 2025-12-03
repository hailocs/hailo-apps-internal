# Test Framework Documentation

## Overview

The Hailo Apps Infrastructure test framework is a comprehensive, configuration-driven testing system designed to validate all pipeline applications across different architectures, models, and execution methods. The framework uses three YAML configuration files to control test execution, making it easy to customize which tests run without modifying code:

- **`test_control.yaml`** - Controls what tests to run (test combinations, custom tests, run methods)
- **`test_definition_config.yaml`** - Defines test suites, app configurations, and test combinations
- **`resources_config.yaml`** - Defines models and resources for each app and architecture

## Table of Contents

1. [Architecture](#architecture)
2. [Configuration File Structure](#configuration-file-structure)
3. [Configuration Options](#configuration-options)
4. [Running Tests](#running-tests)
5. [Test Types](#test-types)
6. [Logging](#logging)
7. [Examples](#examples)
8. [Troubleshooting](#troubleshooting)

## Architecture

### Test Framework Components

```
tests/
├── test_control.yaml          # Test execution control (what to run)
├── test_runner.py             # Main test orchestrator
├── test_sanity_check.py       # Environment and dependency checks
├── all_tests.py              # Pipeline-specific test functions
├── test_utils.py             # Utility functions for test execution
└── README.md                 # This file

hailo_apps/config/
├── test_definition_config.yaml  # Test definitions (suites, apps, combinations)
└── resources_config.yaml        # Resources configuration (models, videos, etc.)
```

### How It Works

1. **Initialization** (`test_runner.py`):
   - Detects host architecture (x86, ARM, RPi)
   - Detects Hailo device architecture (hailo8, hailo8l, hailo10h)
   - Sets environment variables if needed
   - Loads and validates configuration from:
     - `test_control.yaml` (test execution control)
     - `test_definition_config.yaml` (test definitions)
     - `resources_config.yaml` (resources and models)

2. **Configuration Parsing**:
   - Reads `test_control.yaml` - what to run (test combinations, custom tests)
   - Reads `test_definition_config.yaml` - available test suites and app definitions
   - Reads `resources_config.yaml` - models and resources for each app
   - Merges configurations based on enabled flags
   - Validates the merged configuration

3. **Test Generation**:
   - Resolves test selection based on profiles or fine-grained settings
   - Filters based on detected hardware
   - Generates test cases as combinations of:
     - Pipelines × Architectures × Models × Run Methods × Test Suites

4. **Test Execution**:
   - Each test case runs a pipeline with specific parameters
   - Tests are executed using pytest parametrization
   - Results are logged to organized directories

### Data Flow

```
test_control.yaml + test_definition_config.yaml + resources_config.yaml
    ↓
test_runner.py (loads & validates all configs)
    ↓
generate_test_cases() (creates test combinations from configs)
    ↓
pytest parametrization (executes tests)
    ↓
all_tests.py (pipeline-specific functions)
    ↓
test_utils.py (execution utilities)
    ↓
Log files & Results
```

## Configuration File Structure

The test framework uses three separate configuration files:

### 1. `test_control.yaml` (Test Execution Control)

This file controls **what to run**. It includes:

- **Control parameters**: Run times, timeouts
- **Logging configuration**: Log directories and levels
- **Test combinations**: Predefined test combinations (ci_run, all_extra, all_default)
- **Custom tests**: Per-app test configuration (test_suite_mode, model_selection)
- **Run methods**: Enable/disable execution methods (pythonpath, cli, module)
- **Special tests**: Enable/disable special test categories

### 2. `test_definition_config.yaml` (Test Definitions)

This file contains **all available test options**:

- **App definitions**: All pipelines with their module/script/cli paths
- **Test suites**: Different test scenarios with their arguments
- **Test run combinations**: Predefined combinations of apps, test suites, and models
- **Test suite modes**: default, extra, all

### 3. `resources_config.yaml` (Resources Configuration)

This file defines **models and resources**:

- **App models**: Models for each app per architecture (hailo8, hailo8l, hailo10h)
- **Model selection**: default, extra, all models
- **Videos**: Shared video files for all apps
- **Images**: Shared image files for all apps
- **JSON files**: Configuration JSON files per app

The framework merges these configurations: `test_control.yaml` decides what to enable from `test_definition_config.yaml`, and `resources_config.yaml` provides the models and resources.

## Configuration Options

### Execution Settings (test_control.yaml)

```yaml
control_parameters:
  default_run_time: 24              # Default test duration in seconds
  term_timeout: 10                  # Termination timeout in seconds
  human_verification_run_time: 48    # Duration for human verification tests
```

### Logging Configuration (test_control.yaml)

```yaml
logging:
  base_dir: "./logs"                 # Base log directory
  level: "INFO"                      # Log level (DEBUG, INFO, WARNING, ERROR)
  format: "[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s"
  subdirs:
    per_app:
      detection:
        default: "./logs/detection/default"
        extra: "./logs/detection/extra"
        all: "./logs/detection/all"
      # ... more apps
```

### Test Combinations (test_control.yaml)

Predefined test combinations. Enable one or more:

```yaml
test_combinations:
  ci_run:
    enabled: false                   # CI/CD test run
  all_extra:
    enabled: false                   # All apps with extra models
  all_default:
    enabled: false                   # All apps with default models
```

### Custom Tests (test_control.yaml)

Per-app test configuration:

```yaml
custom_tests:
  enabled: false                     # Enable custom tests
  apps:
    detection:
      test_suite_mode: "all"         # None | default | extra | all
      model_selection: "all"         # default | extra | all
    pose_estimation:
      test_suite_mode: "default"
      model_selection: "default"
    # ... more apps
```

### Run Methods (test_control.yaml)

Enable/disable execution methods:

```yaml
run_methods:
  pythonpath:
    enabled: true     # Run script with PYTHONPATH set (primary method)
    priority: 1
  cli:
    enabled: false    # Run using CLI command (e.g., hailo-detect)
    priority: 2
  module:
    enabled: false    # Run as Python module: python -m <module>
    priority: 3
```

### Special Tests (test_control.yaml)

Enable/disable special test categories:

```yaml
special_tests:
  h8l_on_h8:
    enabled: true     # Hailo8L compatibility tests on Hailo8 device
  sanity_checks:
    enabled: true     # Environment sanity checks
  human_verification:
    enabled: true     # Human verification tests
  golden_tests:
    enabled: true     # Golden reference tests
```

### App Definitions (test_definition_config.yaml)

Each app is defined with:

```yaml
apps:
  detection:
    name: "Object Detection Pipeline"
    description: "Object Detection Pipeline"
    module: "hailo_apps.python.pipeline_apps.detection.detection_pipeline"
    script: "hailo_apps/python/pipeline_apps/detection/detection_pipeline.py"
    cli: "hailo-detect"
    default_test_suites:
      - "basic_show_fps"
      - "basic_input_video"
      - "basic_input_usb"
      - "input_video_with_hef"
    extra_test_suites:
      - "input_video_with_labels"
      - "input_video_hef_labels"
      # ... more suites
```

### Test Suites (test_definition_config.yaml)

Test suites define different execution scenarios:

```yaml
test_suites:
  basic_show_fps:
    description: "Show FPS output"
    flags: ["--show-fps"]
  basic_input_video:
    description: "Use video file as input"
    flags: ["--input", "${VIDEO_PATH}"]
  input_video_with_hef:
    description: "Use video file with HEF path"
    flags: ["--input", "${VIDEO_PATH}", "--hef-path", "${HEF_PATH}"]
  # ... more suites
```

### Resources Configuration (resources_config.yaml)

Models and resources are defined per app:

```yaml
detection:
  models:
    hailo8:
      default:
        name: yolov8m
        source: mz
      extra:
        - name: yolov5m_wo_spp
          source: mz
        - name: yolov8s
          source: mz
    hailo8l:
      default:
        name: yolov8s
        source: mz
      extra:
        - name: yolov6n
          source: mz
  json:
    - name: hailo_4_classes.json
      source: s3

videos:
  - name: example.mp4
    source: s3
  - name: example_640.mp4
    source: s3
```

### Placeholders

The following placeholders are automatically replaced in test suite arguments:

- `${RESOURCES_ROOT}` - Replaced with `/usr/local/hailo/resources` (or configured path)
- `${HEF_PATH}` - Replaced with actual HEF file path
- `${HAILO_ARCH}` - Replaced with detected Hailo architecture
- `${HOST_ARCH}` - Replaced with detected host architecture

### Sanity Checks Configuration

Sanity checks can optionally use `test_config.yaml` (if it exists) for configuration, but will use defaults if not found. The sanity check now uses `resources_config.yaml` to determine expected resources.

## Running Tests

### Basic Usage

1. **Edit `tests/test_control.yaml`** to configure what tests to run:
   - Enable a test combination (e.g., `test_combinations.ci_run.enabled: true`), OR
   - Enable custom tests (`custom_tests.enabled: true`) and configure per-app settings
2. **Run the test runner**:
   ```bash
   pytest tests/test_runner.py -v
   ```

### Running Specific Test Files

```bash
# Run sanity checks only
pytest tests/test_sanity_check.py -v

# Run all tests in tests directory
pytest tests/ -v

# Run with more verbose output
pytest tests/test_runner.py -vv

# Run with output capture disabled (see print statements)
pytest tests/test_runner.py -v -s
```

### Using pytest Options

```bash
# Run specific test by name pattern
pytest tests/test_runner.py -k "detection" -v

# Run tests and stop on first failure
pytest tests/test_runner.py -x

# Run tests with coverage
pytest tests/test_runner.py --cov=hailo_apps --cov-report=html

# Run tests in parallel (if pytest-xdist installed)
pytest tests/test_runner.py -n auto
```

## Test Types

### 1. Pipeline Tests

Tests each pipeline with each model on each architecture using each run method.

**Generated from**: Enabled pipelines × Architectures × Models × Run Methods × Test Suites

**Example test case**: `detection_hailo8_yolov8m_cli_default`

**What it tests**:
- Pipeline can be executed
- No critical errors occur
- Pipeline runs for the configured duration
- Proper termination

### 2. Sanity Check Tests

Validates the test environment before running pipeline tests.

**Tests**:
- Hailo runtime installation
- Resource directory existence
- Python environment and packages
- GStreamer installation and plugins
- Hailo GStreamer elements
- Architecture-specific environment
- Package installation
- Environment variables

**Run separately**:
```bash
pytest tests/test_sanity_check.py -v
```

### 3. Hailo8L on Hailo8 Tests

Tests Hailo8L models running on Hailo8 devices (compatibility testing).

**Configuration**: `hailo8l_on_hailo8_tests` section

**When enabled**: Set `special_tests.hailo8l_on_hailo8: true`

### 4. Human Verification Tests

Tests that run for 25 seconds to allow human visual verification of output.

**Configuration**: `human_verification` section

**When enabled**: Set `special_tests.human_verification: true` or use `test_profiles.human_verification.enabled: true`

### 5. Retraining Tests

Tests the retraining pipeline functionality.

**Configuration**: `retraining` section

**When enabled**: Set `special_tests.retraining: true` or use `test_profiles.retraining.enabled: true`

## Logging

### Log File Organization

Log files are organized by test type in subdirectories:

```
logs/
├── detection_hailo8_yolov8m_cli_default.log
├── detection_hailo8_yolov8m_module_video_file.log
├── hef_tests/
│   └── ...
├── h8l_on_h8_tests/
│   └── ...
├── h8l_on_h8_comprehensive/
│   └── ...
└── human_verification/
    └── ...
```

### Log File Naming

Log files are named using the pattern:
```
{pipeline}_{architecture}_{model}_{run_method}_{test_suite}.log
```

Example: `detection_hailo8_yolov8m_cli_video_file.log`

### Log Content

Each log file contains:
- Command executed
- Standard output from the pipeline
- Standard error from the pipeline
- Execution duration
- Termination status

## Examples

### Example 1: Enable Custom Tests for Detection

Edit `test_control.yaml`:

```yaml
custom_tests:
  enabled: true
  apps:
    detection:
      test_suite_mode: "default"  # Run default test suites
      model_selection: "default"  # Use default models
```

Then run:
```bash
pytest tests/test_runner.py -v
```

### Example 2: Enable Test Combination

Edit `test_control.yaml`:

```yaml
test_combinations:
  all_default:
    enabled: true  # Run all apps with default models and test suites
```

### Example 3: Custom Tests for Multiple Apps

Edit `test_control.yaml`:

```yaml
custom_tests:
  enabled: true
  apps:
    detection:
      test_suite_mode: "all"      # All test suites
      model_selection: "default"  # Default models only
    pose_estimation:
      test_suite_mode: "default"
      model_selection: "extra"    # Extra models only
```

### Example 4: Enable Specific Run Method

Edit `test_control.yaml`:

```yaml
run_methods:
  pythonpath:
    enabled: true
  cli:
    enabled: true   # Also enable CLI method
  module:
    enabled: false
```

### Example 7: Run Sanity Checks Before Tests

```bash
# First, run sanity checks
pytest tests/test_sanity_check.py -v

# Then, if sanity checks pass, run pipeline tests
pytest tests/test_runner.py -v
```

## Troubleshooting

### No Tests Generated

**Problem**: pytest reports no tests collected.

**Solutions**:
1. Check that at least one test profile is enabled OR `test_selection` is configured
2. Verify pipelines are enabled in `enabled_pipelines`
3. Check that models are configured for the selected architectures
4. Ensure run methods are enabled in `enabled_run_methods`

### Tests Skipped

**Problem**: Tests are being skipped.

**Solutions**:
1. Verify the detected Hailo architecture matches selected architectures
2. Check that required models exist in the resources directory
3. Ensure test suites are properly configured
4. Check for skip conditions in test code

### Configuration Errors

**Problem**: Configuration validation fails.

**Solutions**:
1. Validate YAML syntax in all three config files:
   - `tests/test_control.yaml`
   - `hailo_apps/config/test_definition_config.yaml`
   - `hailo_apps/config/resources_config.yaml`
2. Run `python tests/verify_configs.py` to verify all configs can be loaded
3. Check that all required sections exist
4. Verify app names match between config files
5. Ensure indentation is correct (YAML is sensitive to indentation)

### Missing Resources

**Problem**: Tests fail due to missing resources.

**Solutions**:
1. Run sanity checks: `pytest tests/test_sanity_check.py -v`
2. Check `required_resources` in `sanity_checks` section
3. Verify resource paths in `resources` section
4. Ensure resources are downloaded/installed

### Import Errors

**Problem**: Import errors when running tests.

**Solutions**:
1. Ensure the package is installed: `pip install -e .`
2. Check Python path is set correctly
3. Verify all dependencies are installed
4. Run sanity checks to verify environment

### Architecture Mismatch

**Problem**: Tests fail because detected architecture doesn't match selection.

**Solutions**:
1. Check detected architecture in test output
2. Update `test_selection.architectures` to match detected architecture
3. For Hailo8 devices, enable `hailo8l_on_hailo8` special test if testing Hailo8L models

### Log Files Not Created

**Problem**: Log files are not being created.

**Solutions**:
1. Check log directory permissions
2. Verify `logging.base_dir` in configuration
3. Ensure directory exists or can be created
4. Check disk space

## Advanced Usage

### Custom Test Suites

Add custom test suites to `test_definition_config.yaml`:

```yaml
test_suites:
  my_custom_suite:
    description: "My custom test scenario"
    flags: ["--input", "usb", "--show-fps", "--disable-sync"]
```

Then reference it in an app's `default_test_suites` or `extra_test_suites` in `test_definition_config.yaml`.

### Adding New Pipelines

1. Add app definition to `test_definition_config.yaml`:
```yaml
apps:
  my_new_pipeline:
    name: "My New Pipeline"
    description: "My New Pipeline"
    module: "hailo_apps.python.pipeline_apps.my_new_pipeline.pipeline"
    script: "hailo_apps/python/pipeline_apps/my_new_pipeline/pipeline.py"
    cli: "hailo-my-new-pipeline"
    default_test_suites:
      - "basic_show_fps"
      - "basic_input_video"
    extra_test_suites:
      - "input_video_with_hef"
```

2. Add models to `resources_config.yaml`:
```yaml
my_new_pipeline:
  models:
    hailo8:
      default:
        name: model1
        source: mz
      extra:
        - name: model2
          source: mz
```

3. Add test function to `all_tests.py`:
```python
def run_my_new_pipeline_test(...):
    # Implementation
```

4. Add to `PIPELINE_TEST_FUNCTIONS` mapping in `all_tests.py`

5. Enable in `test_control.yaml` under `custom_tests.apps` or in a test combination

### Environment Variables

The test runner automatically sets:
- `HOST_ARCH`: Detected host architecture
- `HAILO_ARCH`: Detected Hailo architecture

These are written to `.env` file if not already present.

## Best Practices

1. **Run sanity checks first**: Always run `test_sanity_check.py` before pipeline tests
2. **Start with quick profile**: Use `quick` profile for initial validation
3. **Use specific selections**: For CI/CD, use fine-grained `test_selection` instead of profiles
4. **Check logs**: Review log files when tests fail
5. **Validate config**: Ensure YAML syntax is correct before running tests
6. **Resource management**: Ensure sufficient disk space for log files
7. **Architecture awareness**: Be aware of which architectures your device supports

## Contributing

When adding new tests or modifying the test framework:

1. Update configuration files:
   - `test_control.yaml` - Add test combinations or custom test configs
   - `test_definition_config.yaml` - Add app definitions or test suites
   - `resources_config.yaml` - Add models and resources
2. Add test functions to `all_tests.py` if needed
3. Update utility functions in `test_utils.py` if needed
4. Update this README with new features
5. Run `python tests/verify_configs.py` to verify configurations

## See Also

- `test_control.yaml` - Test execution control configuration
- `test_definition_config.yaml` - Test definitions and app configurations
- `resources_config.yaml` - Resources and models configuration
- `verify_configs.py` - Script to verify all configuration files
- `TEST_FRAMEWORK_DOCUMENTATION.md` - Additional test framework documentation

