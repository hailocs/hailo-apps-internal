#!/usr/bin/env bash
set -e

# Activate the virtual environment
source ./setup_env.sh

# Directories
TESTS_DIR="tests"
LOG_DIR="${TESTS_DIR}/tests_logs"
mkdir -p "${LOG_DIR}"

# Install pytest and timeout plugin into the venv
echo "Installing test requirements..."
python -m pip install --upgrade pip
python -m pip install -r tests/test_resources/requirements.txt

# Download necessary Hailo resources
echo "Downloading resources..."
# Download default models for all apps (for detected architecture)
python -m hailo_apps.installation.download_resources

# Download hailo8l resources for testing hailo8l models on hailo8 device
python -m hailo_apps.installation.download_resources --arch hailo8l

# Run pytest via the Python module so it's guaranteed to run in this venv
echo "Running tests..."
# Run sanity checks first if enabled
python -m pytest --log-cli-level=INFO "${TESTS_DIR}/test_sanity_check.py" || true

# Run the new test runner which uses test_control.yaml and test_definition_config.yaml
python -m pytest --log-cli-level=INFO "${TESTS_DIR}/test_runner.py" -v

echo "All tests completed successfully."