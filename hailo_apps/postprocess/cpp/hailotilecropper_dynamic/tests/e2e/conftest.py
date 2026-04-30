"""Shared fixtures for hailotilecropper_dynamic E2E tests."""
import os
import pathlib
import pytest

INSTALLED_PLUGIN = pathlib.Path(
    "/usr/lib/x86_64-linux-gnu/gstreamer-1.0/libgsthailotilecropper_dynamic.so"
)


@pytest.fixture(scope="session", autouse=True)
def _ensure_plugin_installed():
    if not INSTALLED_PLUGIN.exists():
        pytest.skip(
            f"Plugin not installed at {INSTALLED_PLUGIN}. "
            "Run `hailo-compile-postprocess` first."
        )
    # Force GStreamer to rescan in case the plugin was just installed.
    os.environ.setdefault("GST_REGISTRY_UPDATE", "yes")
    yield


@pytest.fixture(scope="session")
def gst():
    import gi
    gi.require_version("Gst", "1.0")
    from gi.repository import Gst
    Gst.init(None)
    return Gst
