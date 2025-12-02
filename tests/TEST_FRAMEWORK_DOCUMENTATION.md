# Test Framework Documentation

## Table of Contents
1. [Overview](#overview)
2. [Test Structure](#test-structure)
3. [Configuration Files](#configuration-files)
4. [How to Use](#how-to-use)
5. [How to Add an App to Testing](#how-to-add-an-app-to-testing)
6. [Test Suite Modes](#test-suite-modes)
7. [Model Selection](#model-selection)
8. [Examples](#examples)

---

## Overview

The test framework is a flexible, configuration-driven system for testing Hailo pipeline applications. It supports:
- **Test Suite Modes**: Control which test suites to run (None, default, extra, all)
- **Model Selection**: Control which models to test (default, extra, all)
- **Multiple Run Methods**: pythonpath, cli, module
- **Architecture Support**: hailo8, hailo8l, hailo10h
- **Test Combinations**: Predefined test run configurations

---

## Test Structure

### Directory Structure

```
hailo-apps-infra/
├── tests/
│   ├── test_control.yaml          # Control configuration (what to run)
│   ├── test_runner.py              # Main test runner
│   ├── all_tests.py                # Test execution functions
│   ├── test_utils.py               # Test utilities
│   └── verify_configs.py           # Config verification script
└── hailo_apps/
    └── config/
        ├── test_definition_config.yaml  # Definition configuration (how to run)
        └── resources_config.yaml        # Resources configuration (models, videos, etc.)
```

### Configuration Files

#### 1. `test_control.yaml` (in `tests/`)
Controls **what** to run:
- Control parameters (run time, timeouts)
- Logging configuration
- Test combinations (enabled/disabled)
- Custom per-app tests
- Special tests
- Run methods

#### 2. `test_definition_config.yaml` (in `hailo_apps/config/`)
Defines **how** to run:
- App definitions (module, script, cli)
- Test suites (flag combinations)
- Test run combinations
- Resources

#### 3. `resources_config.yaml` (in `hailo_apps/config/`)
Defines **resources**:
- Models per app and architecture
- Videos and images
- JSON configuration files

---

## Configuration Files

### test_control.yaml

Controls test execution:

```yaml
# Control parameters
control_parameters:
  default_run_time: 24  # seconds
  term_timeout: 10      # seconds
  human_verification_run_time: 48

# Logging configuration
logging:
  base_dir: "./logs"
  level: "INFO"
  subdirs:
    per_app:
      detection:
        default: "./logs/detection/default"
        extra: "./logs/detection/extra"
        all: "./logs/detection/all"

# Test combinations (predefined test runs)
test_combinations:
  ci_run:
    enabled: false
  all_default:
    enabled: false
  all_extra:
    enabled: false

# Custom per-app tests
custom_tests:
  enabled: false
  apps:
    detection:
      test_suite_mode: "all"      # None | default | extra | all
      model_selection: "all"      # default | extra | all
      description: "Object Detection Pipeline"

# Run methods
run_methods:
  pythonpath:
    enabled: true
    priority: 1
  cli:
    enabled: false
    priority: 2
  module:
    enabled: false
    priority: 3
```

### test_definition_config.yaml

Defines test structure:

```yaml
# App definitions
apps:
  detection:
    name: "Object Detection Pipeline"
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
      - "pipeline_disable_sync"

# Test suites (flag combinations)
test_suites:
  basic_show_fps:
    flags:
      - "--show-fps"
    description: "Basic test with FPS display"
  
  input_video_with_hef:
    flags:
      - "--input"
      - "${VIDEO_PATH}"
      - "--hef-path"
      - "${HEF_PATH}"
      - "--show-fps"
    description: "Video file with explicit HEF path"

# Test run combinations
test_run_combinations:
  ci_run:
    name: "CI Run"
    apps:
      - detection
      - simple_detection
    test_suite_mode: "all"      # None | default | extra | all
    model_selection: "all"      # default | extra | all
    description: "CI run with all apps"
```

---

## How to Use

### Running Tests

#### Option 1: Using Test Combinations

1. Edit `test_control.yaml`:
```yaml
test_combinations:
  ci_run:
    enabled: true  # Enable this combination
```

2. Run tests:
```bash
cd hailo-apps-infra
pytest tests/test_runner.py -v
```

#### Option 2: Using Custom Per-App Tests

1. Edit `test_control.yaml`:
```yaml
custom_tests:
  enabled: true
  apps:
    detection:
      test_suite_mode: "default"  # Run default test suites
      model_selection: "default"  # Test default models only
```

2. Run tests:
```bash
pytest tests/test_runner.py -v
```

### Verifying Configuration

Before running tests, verify your configuration:

```bash
python3 tests/verify_configs.py
```

This will check:
- All configuration files can be loaded
- Test combinations match between files
- All referenced test suites exist
- All apps are properly defined

---

## How to Add an App to Testing

### Step 1: Add App to `test_definition_config.yaml`

Add your app definition:

```yaml
apps:
  your_app_name:
    name: "Your App Name"
    description: "Description of your app"
    module: "hailo_apps.python.pipeline_apps.your_app.your_app_pipeline"
    script: "hailo_apps/python/pipeline_apps/your_app/your_app_pipeline.py"
    cli: "hailo-your-app"
    default_test_suites:
      - "basic_show_fps"
      - "basic_input_video"
      - "basic_input_usb"
      - "input_video_with_hef"
    extra_test_suites:
      - "pipeline_disable_sync"
      # Add app-specific test suites here
```

### Step 2: Add App to `resources_config.yaml`

Add models for your app:

```yaml
your_app_name:
  models:
    hailo8:
      default:
        name: your_model_name
        source: mz  # or s3
      extra:
        - name: another_model
          source: mz
    hailo8l:
      default:
        name: your_model_name
        source: mz
    hailo10h:
      default:
        name: your_model_name
        source: mz
```

### Step 3: Add App to `test_control.yaml`

Add logging directories and custom test configuration:

```yaml
logging:
  subdirs:
    per_app:
      your_app_name:
        default: "./logs/your_app_name/default"
        extra: "./logs/your_app_name/extra"
        all: "./logs/your_app_name/all"

custom_tests:
  apps:
    your_app_name:
      test_suite_mode: "default"
      model_selection: "default"
      description: "Your App Description"
```

### Step 4: Add Test Function (if needed)

If your app needs special test handling, add a function in `all_tests.py`:

```python
def run_your_app_test(
    config: Dict,
    model: str,
    architecture: str,
    run_method: str,
    test_suite: str = "default",
    extra_args: Optional[List[str]] = None,
    run_time: Optional[int] = None,
    term_timeout: Optional[int] = None,
) -> Tuple[bool, str]:
    """Run your app pipeline test."""
    pipeline_config = config["pipelines"]["your_app_name"]
    # ... test implementation
    return success, log_file
```

Then register it in `PIPELINE_TEST_FUNCTIONS`:

```python
PIPELINE_TEST_FUNCTIONS = {
    # ... existing apps
    "your_app_name": run_your_app_test,
}
```

### Step 5: Add App to Test Combinations (optional)

Add your app to test run combinations in `test_definition_config.yaml`:

```yaml
test_run_combinations:
  ci_run:
    apps:
      - detection
      - your_app_name  # Add here
```

### Step 6: Verify Configuration

Run the verification script:

```bash
python3 tests/verify_configs.py
```

---

## Test Suite Modes

Test suite modes control which test suites are executed:

| Mode | Description |
|------|-------------|
| `None` | No test suites run (skip app) |
| `default` | Run only default test suites |
| `extra` | Run only extra test suites |
| `all` | Run both default and extra test suites |

### Example

```yaml
custom_tests:
  apps:
    detection:
      test_suite_mode: "default"  # Only run default_test_suites
      model_selection: "default"
```

This will run:
- `basic_show_fps`
- `basic_input_video`
- `basic_input_usb`
- `input_video_with_hef`

But NOT:
- `input_video_with_labels` (extra)
- `pipeline_disable_sync` (extra)

---

## Model Selection

Model selection controls which models are tested:

| Selection | Description |
|-----------|-------------|
| `default` | Test only default model(s) |
| `extra` | Test only extra models |
| `all` | Test both default and extra models |

### Example

```yaml
custom_tests:
  apps:
    detection:
      test_suite_mode: "default"
      model_selection: "all"  # Test all models
```

This will test:
- Default model: `yolov8m` (hailo8)
- Extra models: `yolov5m_wo_spp`, `yolov8s`, `yolov11n`, etc.

---

## Examples

### Example 1: Quick Smoke Test

Run only default test suites with default models:

```yaml
# test_control.yaml
custom_tests:
  enabled: true
  apps:
    detection:
      test_suite_mode: "default"
      model_selection: "default"
```

### Example 2: Comprehensive Testing

Run all test suites with all models:

```yaml
# test_control.yaml
custom_tests:
  enabled: true
  apps:
    detection:
      test_suite_mode: "all"
      model_selection: "all"
```

### Example 3: Skip an App

Skip testing an app:

```yaml
# test_control.yaml
custom_tests:
  enabled: true
  apps:
    detection:
      test_suite_mode: "None"  # Skip this app
      model_selection: "default"
```

### Example 4: Test Only Extra Features

Test only extra test suites with extra models:

```yaml
# test_control.yaml
custom_tests:
  enabled: true
  apps:
    detection:
      test_suite_mode: "extra"
      model_selection: "extra"
```

### Example 5: Using Test Combinations

Enable a predefined test combination:

```yaml
# test_control.yaml
test_combinations:
  ci_run:
    enabled: true  # Enable CI run
```

This will use the configuration from `test_definition_config.yaml`:

```yaml
# test_definition_config.yaml
test_run_combinations:
  ci_run:
    apps:
      - detection
      - simple_detection
      # ... all apps
    test_suite_mode: "all"
    model_selection: "all"
```

---

## Test Suite Naming Convention

Test suites follow a naming convention aligned with `FLAG_COMBINATIONS.md`:

- **Basic**: `basic_*` - Basic flag combinations
- **Input**: `input_*` - Input source combinations
- **Pipeline**: `pipeline_*` - Pipeline flag combinations
- **App-specific**: `{app}_*` - App-specific flags (e.g., `face_*`, `tiling_*`, `clip_*`)
- **Combined**: Descriptive names for complex combinations

Examples:
- `basic_show_fps` - Basic FPS display
- `input_video_with_hef` - Video input with HEF path
- `pipeline_disable_sync` - Pipeline sync disabled
- `face_mode_train` - Face recognition training mode
- `full_combination_video_hef_labels_sync` - Full combination

---

## Placeholders

Test suites can use placeholders that are resolved at runtime:

- `${VIDEO_PATH}` - Resolved to video file path for the app
- `${HEF_PATH}` - Resolved to HEF file path for the model
- `${LABELS_JSON_PATH}` - Resolved to labels JSON path for the app
- `${RESOURCES_ROOT}` - Resolved to resources root directory

Example:

```yaml
test_suites:
  input_video_with_hef:
    flags:
      - "--input"
      - "${VIDEO_PATH}"      # Resolved to: /usr/local/hailo/resources/videos/example.mp4
      - "--hef-path"
      - "${HEF_PATH}"        # Resolved to: /usr/local/hailo/resources/models/hailo8/yolov8m.hef
      - "--show-fps"
```

---

## Troubleshooting

### No test cases generated

1. Check if `custom_tests.enabled: true` or a test combination is enabled
2. Verify `test_suite_mode` is not `None`
3. Check if models exist in `resources_config.yaml` for the architecture
4. Verify test suites are defined in `test_definition_config.yaml`

### Test suite not found

1. Verify the test suite name exists in `test_definition_config.yaml`
2. Check if it's in `default_test_suites` or `extra_test_suites` for the app
3. Ensure `test_suite_mode` includes the suite (default/extra/all)

### Model not found

1. Verify the model exists in `resources_config.yaml`
2. Check if `model_selection` includes the model (default/extra/all)
3. Ensure the architecture is supported

### Configuration errors

Run the verification script:
```bash
python3 tests/verify_configs.py
```

This will identify:
- Missing configuration files
- Invalid test suite references
- Missing apps in definitions
- Mismatched test combinations

---

## Best Practices

1. **Start with default**: Use `test_suite_mode: "default"` and `model_selection: "default"` for quick tests
2. **Use test combinations**: Create reusable test combinations for common scenarios
3. **Verify before running**: Always run `verify_configs.py` before executing tests
4. **Organize test suites**: Group related test suites logically (basic, input, pipeline, app-specific)
5. **Document app-specific suites**: Add clear descriptions for app-specific test suites
6. **Use placeholders**: Use placeholders (${VIDEO_PATH}, ${HEF_PATH}) instead of hardcoded paths

---

## Summary

The test framework provides:
- ✅ Flexible test suite selection (None, default, extra, all)
- ✅ Flexible model selection (default, extra, all)
- ✅ Configuration-driven testing
- ✅ Multiple run methods (pythonpath, cli, module)
- ✅ Architecture support (hailo8, hailo8l, hailo10h)
- ✅ Predefined test combinations
- ✅ Per-app custom configurations
- ✅ Comprehensive logging

For questions or issues, refer to the configuration files or run the verification script.

