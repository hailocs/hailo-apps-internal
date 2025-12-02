# Test Framework Documentation

## Overview

The Hailo Apps Infrastructure test framework is a comprehensive, configuration-driven testing system designed to validate all pipeline applications across different architectures, models, and execution methods. The framework uses a centralized YAML configuration file (`test_config.yaml`) to control test execution, making it easy to customize which tests run without modifying code.

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
├── test_config.yaml          # Central configuration file
├── test_runner.py             # Main test orchestrator
├── test_sanity_check.py       # Environment and dependency checks
├── all_tests.py              # Pipeline-specific test functions
├── test_utils.py             # Utility functions for test execution
└── README.md                 # This file
```

### How It Works

1. **Initialization** (`test_runner.py`):
   - Detects host architecture (x86, ARM, RPi)
   - Detects Hailo device architecture (hailo8, hailo8l, hailo10h)
   - Sets environment variables if needed
   - Loads and validates configuration from `test_config.yaml`

2. **Configuration Parsing**:
   - Reads control section (top) - what to run
   - Reads configurations section (bottom) - available options
   - Merges them based on enabled flags
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
test_config.yaml
    ↓
test_runner.py (loads & validates)
    ↓
resolve_test_selection() (determines what to run)
    ↓
generate_test_cases() (creates test combinations)
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

The `test_config.yaml` file is divided into two main sections:

### 1. Control Section (Top)

This section controls **what to run**. It includes:

- **Execution settings**: Run times, timeouts
- **Logging configuration**: Log directories and levels
- **Test profiles**: Quick selection presets
- **Test selection**: Fine-grained control
- **Enabled flags**: Enable/disable pipelines, run methods, special tests

### 2. Configurations Section (Bottom)

This section contains **all available options**:

- **Pipeline definitions**: All pipelines with their models per architecture
- **Run methods**: Available execution methods
- **Test suites**: Different test scenarios
- **Test profile configurations**: What each profile includes
- **Special test configs**: Hailo8L-on-Hailo8, retraining, human verification, sanity checks
- **Resource paths**: Default resource locations

The framework merges these sections: the control section decides what to enable from the configurations section.

## Configuration Options

### Execution Settings

```yaml
execution:
  default_run_time: 10              # Default test duration in seconds
  term_timeout: 5                   # Termination timeout in seconds
  human_verification_run_time: 25   # Duration for human verification tests
```

### Logging Configuration

```yaml
logging:
  base_dir: "logs"                   # Base log directory
  level: "INFO"                      # Log level (DEBUG, INFO, WARNING, ERROR)
  format: "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
  subdirectories:
    hef_tests: "logs/hef_tests"
    h8l_on_h8: "logs/h8l_on_h8_tests"
    h8l_on_h8_comprehensive: "logs/h8l_on_h8_comprehensive"
    human_verification: "logs/human_verification"
```

### Test Profiles

Quick selection presets. Enable one or more:

```yaml
test_profiles:
  all:
    enabled: false                   # Run all available tests
  quick:
    enabled: false                   # Quick smoke test
  all_pipelines:
    enabled: false                   # Test all pipelines
  detection_only:
    enabled: false                   # Test only detection pipeline
  hailo8_only:
    enabled: false                   # Test only Hailo8 architecture
  hailo8l_only:
    enabled: false                   # Test only Hailo8L architecture
  hailo10h_only:
    enabled: false                   # Test only Hailo10H architecture
  hailo8l_on_hailo8:
    enabled: false                   # Test Hailo8L models on Hailo8 device
  human_verification:
    enabled: false                   # Human verification tests (25s each)
  retraining:
    enabled: false                   # Retraining pipeline tests
```

### Fine-Grained Test Selection

Override profiles with specific selections:

```yaml
test_selection:
  pipelines: "all"                   # "all" or list: ["detection", "pose_estimation"]
  architectures: "all"               # "all" or list: ["hailo8", "hailo8l", "hailo10h"]
  run_methods: "all"                 # "all" or list: ["module", "pythonpath", "cli"]
  test_suites: ["default", "video_file"]  # List of test suite names
```

### Pipeline Control

Enable/disable specific pipelines:

```yaml
enabled_pipelines:
  detection: true
  pose_estimation: true
  depth: true
  instance_segmentation: true
  simple_detection: true
  face_recognition: true
  multisource: true
  reid_multisource: true
  tiling: true
```

### Run Method Control

Enable/disable execution methods:

```yaml
enabled_run_methods:
  module: true        # Run as Python module: python -m <module>
  pythonpath: true   # Run script with PYTHONPATH set
  cli: true          # Run using CLI command (e.g., hailo-detect)
```

### Special Tests

Enable/disable special test categories:

```yaml
special_tests:
  hailo8l_on_hailo8: true      # Hailo8L compatibility tests
  retraining: true              # Retraining pipeline tests
  human_verification: true      # Human verification tests
  sanity_checks: true           # Environment sanity checks
```

### Pipeline Definitions

Each pipeline is defined with:

```yaml
pipelines:
  detection:
    name: "detection"
    description: "Object Detection Pipeline"
    module: "hailo_apps.python.pipeline_apps.detection.detection_pipeline"
    script: "hailo_apps/python/pipeline_apps/detection/detection_pipeline.py"
    cli: "hailo-detect"
    models:
      hailo8:
        - yolov5m_wo_spp
        - yolov6n
        # ... more models
      hailo8l:
        - yolov5m_wo_spp
        # ... more models
      hailo10h:
        - yolov5m_wo_spp
        # ... more models
```

### Test Suites

Test suites define different execution scenarios:

```yaml
test_suites:
  default:
    description: "Empty arguments - uses default behavior"
    args: []
  video_file:
    description: "Use video file as input"
    args: ["--input", "resources/example.mp4"]
  usb_camera:
    description: "Use USB camera as input"
    args: ["--input", "usb"]
  rpi_camera:
    description: "Use Raspberry Pi camera as input"
    args: ["--input", "rpi"]
  # ... more suites
```

### Placeholders

The following placeholders are automatically replaced in test suite arguments:

- `${RESOURCES_ROOT}` - Replaced with `/usr/local/hailo/resources` (or configured path)
- `${HEF_PATH}` - Replaced with actual HEF file path
- `${HAILO_ARCH}` - Replaced with detected Hailo architecture
- `${HOST_ARCH}` - Replaced with detected host architecture

### Sanity Checks Configuration

```yaml
sanity_checks:
  required_packages:
    - gi
    - numpy
    - opencv-python
    - hailo
  optional_packages:
    - setproctitle
    - python-dotenv
    - picamera2
  gstreamer_elements:
    critical:
      - videotestsrc
      - appsink
      - videoconvert
      - autovideosink
    hailo:
      - hailonet
      - hailofilter
  required_resources:
    - example.mp4
    - example_640.mp4
    - face_recognition.mp4
    - libdepth_postprocess.so
    - libyolo_hailortpp_postprocess.so
    - libyolov5seg_postprocess.so
    - libyolov8pose_postprocess.so
```

## Running Tests

### Basic Usage

1. **Edit `tests/test_config.yaml`** to configure what tests to run
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

### Example 1: Quick Smoke Test

Run a minimal set of tests to verify basic functionality:

```yaml
test_profiles:
  quick:
    enabled: true
```

Then run:
```bash
pytest tests/test_runner.py -v
```

### Example 2: Test Only Detection Pipeline on Hailo8

```yaml
test_profiles:
  detection_only:
    enabled: true
test_selection:
  architectures: ["hailo8"]
```

### Example 3: Test All Pipelines with CLI Only

```yaml
test_profiles:
  all_pipelines:
    enabled: true
test_selection:
  run_methods: ["cli"]
```

### Example 4: Custom Selection

```yaml
test_selection:
  pipelines: ["detection", "pose_estimation"]
  architectures: ["hailo8", "hailo10h"]
  run_methods: ["module", "cli"]
  test_suites: ["default", "video_file"]
```

### Example 5: Disable Specific Pipeline

```yaml
enabled_pipelines:
  detection: true
  face_recognition: false  # Skip face recognition tests
```

### Example 6: Test with Video File Input Only

```yaml
test_selection:
  pipelines: "all"
  architectures: "all"
  run_methods: "all"
  test_suites: ["video_file"]  # Only video file suite
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
1. Validate YAML syntax in `test_config.yaml`
2. Check that all required sections exist
3. Verify pipeline names match between sections
4. Ensure indentation is correct (YAML is sensitive to indentation)

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

Add custom test suites to the configuration:

```yaml
test_suites:
  my_custom_suite:
    description: "My custom test scenario"
    args: ["--input", "usb", "--show-fps", "--disable-sync"]
```

Then use it in `test_selection.test_suites`.

### Adding New Pipelines

1. Add pipeline definition to `pipelines` section:
```yaml
pipelines:
  my_new_pipeline:
    name: "my_new_pipeline"
    description: "My New Pipeline"
    module: "hailo_apps.python.pipeline_apps.my_new_pipeline.pipeline"
    script: "hailo_apps/python/pipeline_apps/my_new_pipeline/pipeline.py"
    cli: "hailo-my-new-pipeline"
    models:
      hailo8:
        - model1
        - model2
```

2. Add test function to `all_tests.py`:
```python
def run_my_new_pipeline_test(...):
    # Implementation
```

3. Add to `PIPELINE_TEST_FUNCTIONS` mapping in `all_tests.py`

4. Enable in `enabled_pipelines` section

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

1. Update `test_config.yaml` with new configurations
2. Add test functions to `all_tests.py` if needed
3. Update utility functions in `test_utils.py` if needed
4. Update this README with new features
5. Ensure backward compatibility with existing configurations

## See Also

- `test_config.yaml` - Full configuration file with inline documentation
- `README_TEST_RUNNER.md` - Additional test runner documentation
- `TEST_CONFIGURATION_GUIDE.md` - Detailed configuration guide

