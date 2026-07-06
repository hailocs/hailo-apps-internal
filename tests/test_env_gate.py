"""Tests for the device/arch gate helpers in conftest.

These helpers let every version-matrix cell collect cleanly and skip (with a
reason) what the current device/arch can't run, instead of raising at import or
collection time.
"""

from tests.conftest import current_arch, device_present


def test_current_arch_never_raises():
    a = current_arch()
    assert a in (None, "hailo8", "hailo8l", "hailo10h")


def test_device_present_returns_bool():
    assert isinstance(device_present(), bool)
