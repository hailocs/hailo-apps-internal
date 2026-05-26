"""Shared fixtures for hailotilecropper_dynamic E2E tests."""
import ctypes
import os
import pathlib
import pytest

INSTALLED_PLUGIN = pathlib.Path(
    "/usr/lib/x86_64-linux-gnu/gstreamer-1.0/libgsthailotilecropper_dynamic.so"
)

# Build-dir fallback: prefer this .so when it is newer than the installed one.
# __file__ is at: <repo>/hailo_apps/postprocess/cpp/hailotilecropper_dynamic/tests/e2e/
# parents[6] = repo root
_REPO_ROOT = pathlib.Path(__file__).resolve().parents[6]  # …/hailo-apps-infra
BUILD_PLUGIN = (
    _REPO_ROOT / "hailo_apps" / "postprocess" / "build.release" / "cpp"
    / "libgsthailotilecropper_dynamic.so"
)


def _preferred_plugin() -> pathlib.Path | None:
    """Return the .so to use (None if neither exists)."""
    if BUILD_PLUGIN.exists() and INSTALLED_PLUGIN.exists():
        if BUILD_PLUGIN.stat().st_mtime > INSTALLED_PLUGIN.stat().st_mtime:
            return BUILD_PLUGIN
        return INSTALLED_PLUGIN
    if BUILD_PLUGIN.exists():
        return BUILD_PLUGIN
    if INSTALLED_PLUGIN.exists():
        return INSTALLED_PLUGIN
    return None


@pytest.fixture(scope="session", autouse=True)
def _preload_plugin():
    """Preload the freshest hailotilecropper_dynamic .so before Gst.init().

    Loading via ctypes with RTLD_GLOBAL before GStreamer initialises ensures
    that GstHailoBaseCropperDyn is registered first.  GStreamer deduplicates
    plugins by name, so the system .so (which may still carry the old
    GstHailoBaseCropper) is silently skipped during the registry scan.
    This lets the test suite exercise the freshly compiled binary without
    requiring root privileges to install it.
    """
    plugin_path = _preferred_plugin()
    if plugin_path is None:
        pytest.skip(
            f"Plugin not found at {INSTALLED_PLUGIN} or {BUILD_PLUGIN}. "
            "Run `hailo-compile-postprocess` first."
        )
    # Force-load our .so into the process before anything calls Gst.init().
    ctypes.CDLL(str(plugin_path), mode=ctypes.RTLD_GLOBAL)
    os.environ.setdefault("GST_REGISTRY_UPDATE", "yes")
    yield


@pytest.fixture(scope="session")
def gst(_preload_plugin):
    import gi
    gi.require_version("Gst", "1.0")
    from gi.repository import Gst
    Gst.init(None)
    return Gst
