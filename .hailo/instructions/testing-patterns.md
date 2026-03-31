# Testing Patterns

> How to write and run tests for hailo-apps applications.

## Test Framework

- **Framework**: pytest
- **Config**: `tests/conftest.py` with custom markers and fixtures
- **Runner**: `python3 -m pytest tests/` or `./run_tests.sh`

## Test Markers

```python
@pytest.mark.sanity          # Basic sanity checks
@pytest.mark.installation    # Verify installation
@pytest.mark.resources       # Verify resource files exist
@pytest.mark.requires_device # Requires Hailo hardware
@pytest.mark.requires_gstreamer  # Requires GStreamer
```

## Session Fixtures Available

| Fixture | Description |
|---|---|
| `resources_config` | Parsed resources_config.yaml |
| `detected_hailo_arch` | Auto-detected Hailo architecture |
| `detected_host_arch` | Host CPU architecture (x86_64/aarch64) |
| `resources_root_path` | `/usr/local/hailo/resources/` |
| `expected_models_for_arch` | Models for current architecture |
| `expected_videos` | Expected video files |
| `expected_images` | Expected image files |
| `expected_so_files` | Expected postprocess .so files |

## Test Patterns

### Sanity Test
```python
@pytest.mark.sanity
class TestMyApp:
    def test_import(self):
        """Verify app module can be imported."""
        from hailo_apps.python.gen_ai_apps.my_app import my_app
        assert hasattr(my_app, 'MyAppClass')

    def test_constants_defined(self):
        """Verify app constants are registered."""
        from hailo_apps.python.core.common.defines import MY_APP_NAME
        assert MY_APP_NAME == "my_app"
```

### Integration Test (Requires Device)
```python
@pytest.mark.requires_device
class TestMyAppInference:
    def test_single_inference(self, detected_hailo_arch):
        """Run single inference and verify output format."""
        # Setup
        hef_path = resolve_hef_path(None, app_name=MY_APP, arch=detected_hailo_arch)
        backend = Backend(hef_path=str(hef_path))

        # Execute
        result = backend.inference(test_image, "Describe the image")

        # Verify
        assert 'answer' in result
        assert 'time' in result
        assert len(result['answer']) > 0

        # Cleanup
        backend.close()
```

### Parametrized Tests
```python
@pytest.mark.parametrize("input_source", ["usb", "rpi", "test.mp4"])
def test_source_type_detection(input_source):
    source_type = get_source_type(input_source)
    assert source_type is not None
```

## Test Teardown

Tests that use hardware resources need cleanup delays:
- USB camera tests: 1s delay
- Multi-model tests: 2s delay  
- Default pipeline tests: 0.5s delay

These are automatically handled by `conftest.py`.

## Running Tests

```bash
# All tests
python3 -m pytest tests/

# Sanity only
python3 -m pytest tests/ -m sanity

# Specific test file
python3 -m pytest tests/test_sanity_check.py -v

# Skip hardware-dependent tests
python3 -m pytest tests/ -m "not requires_device"
```
