# Developer Guide

This section is for developers who want to build their own custom applications or extend the existing ones.

## Overview

The Developer Guide provides comprehensive technical documentation for building AI applications on the Hailo platform. Whether you're creating new applications, adding custom post-processing functions, retraining models, or debugging pipelines, these guides will help you get started.

## Guides

*   **[Application Development](./app_development.md)**: The primary guide for developers. It covers the core concepts of the Python framework and how to build new applications.
*   **[GStreamer Helper Pipelines Reference](./gstreamer_helper_pipelines.md)**: Comprehensive reference documentation for all helper functions in the `gstreamer_helper_pipelines.py` module.
*   **[Writing a C++ Post-Process](./writing_postprocess.md)**: A step-by-step tutorial for creating custom C++ post-processing functions for new or unsupported neural networks.
*   **[Retraining Models](./retraining_example.md)**: A step-by-step tutorial for retraining models.
*   **[Debugging with GST Shark](./debugging_with_gst_shark.md)**: Debugging tool for GStreamer pipelines.

## Environment overrides

Set `hailo_arch=hailo8` / `hailo8l` / `hailo10h` to pin the architecture
instead of auto-detecting it. Honored by `set_env` and by HEF resolution
at runtime — useful for CI and multi-arch dev boxes.

## Additional Resources

*   [Main Documentation](../README.md) - Return to the main documentation index
*   [User Guide](../user_guide/README.md) - Installation and usage guides for end-users