"""Unit tests for the user-facing app_callback counting logic.

``app_callback`` in ppe_safety_checker.py walks every detection's
classifications and bumps ``safe_count`` / ``violation_count`` / ``total_checks``
based on a substring match of the status constant in the classification label.
This file exercises that pure-Python accounting with fake roi/detection/
classification objects — no Hailo device, no GStreamer.
"""

import sys
from unittest.mock import MagicMock

import pytest

pytestmark = pytest.mark.community


# ----------------------------------------------------------------------------
# Fakes for the native objects the callback touches.
# ----------------------------------------------------------------------------
class _FakeClassification:
    def __init__(self, label):
        self._label = label

    def get_label(self):
        return self._label


class _FakeDetection:
    def __init__(self, labels):
        self._classifications = [_FakeClassification(l) for l in labels]

    def get_objects_typed(self, _type_token):
        return list(self._classifications)


class _FakeROI:
    def __init__(self, detections):
        self._detections = detections

    def get_objects_typed(self, _type_token):
        return list(self._detections)


def _install_fake_hailo():
    fake = MagicMock(name="hailo")
    fake.HAILO_DETECTION = "HAILO_DETECTION"
    fake.HAILO_CLASSIFICATION = "HAILO_CLASSIFICATION"
    fake._roi = None
    fake.get_roi_from_buffer = lambda buffer: fake._roi
    return fake


_fake_hailo = _install_fake_hailo()
sys.modules["hailo"] = _fake_hailo
for mod_name in ["gi", "gi.repository", "gi.repository.Gst", "setproctitle"]:
    sys.modules.setdefault(mod_name, MagicMock())
sys.modules["gi"].require_version = lambda *a, **kw: None

# Stub the app_callback_class base so PPESafetyCallback can be constructed
# without the real GStreamerApp machinery.
_gstreamer_app = sys.modules.setdefault(
    "hailo_apps.python.core.gstreamer.gstreamer_app", MagicMock()
)


class _StubBase:
    def __init__(self):
        pass


# Only override if the real module didn't import (kept device-free either way).
if isinstance(_gstreamer_app, MagicMock):
    _gstreamer_app.app_callback_class = _StubBase

from community.apps.pipeline_apps.ppe_safety_checker.ppe_safety_checker_pipeline import (  # noqa: E402
    PPESafetyCallback,
)
from community.apps.pipeline_apps.ppe_safety_checker.ppe_safety_checker import (  # noqa: E402
    app_callback,
)


def _run(detections):
    user_data = PPESafetyCallback()
    _fake_hailo._roi = _FakeROI(detections)
    app_callback(element=None, buffer=object(), user_data=user_data)
    return user_data


class TestPPESafetyCallbackState:
    def test_initial_counts_zero(self):
        ud = PPESafetyCallback()
        assert ud.safe_count == 0
        assert ud.violation_count == 0
        assert ud.total_checks == 0


class TestCounting:
    def test_safe_label_increments_safe(self):
        ud = _run([_FakeDetection(["SAFE: wearing helmet"])])
        assert ud.safe_count == 1
        assert ud.violation_count == 0
        assert ud.total_checks == 1

    def test_violation_label_increments_violation(self):
        ud = _run([_FakeDetection(["VIOLATION: no helmet"])])
        assert ud.safe_count == 0
        assert ud.violation_count == 1
        assert ud.total_checks == 1

    def test_mixed_detections(self):
        ud = _run([
            _FakeDetection(["SAFE: a"]),
            _FakeDetection(["VIOLATION: b"]),
            _FakeDetection(["SAFE: c"]),
        ])
        assert ud.safe_count == 2
        assert ud.violation_count == 1
        assert ud.total_checks == 3

    def test_unknown_label_counts_as_check_only(self):
        # A label that is neither SAFE nor VIOLATION still bumps total_checks
        # but neither safe nor violation.
        ud = _run([_FakeDetection(["UNKNOWN: nope"])])
        assert ud.safe_count == 0
        assert ud.violation_count == 0
        assert ud.total_checks == 1

    def test_multiple_classifications_on_one_detection(self):
        ud = _run([_FakeDetection(["SAFE: a", "VIOLATION: b"])])
        assert ud.safe_count == 1
        assert ud.violation_count == 1
        assert ud.total_checks == 2


class TestEdgeCases:
    def test_none_buffer_noop(self):
        ud = PPESafetyCallback()
        app_callback(element=None, buffer=None, user_data=ud)
        assert ud.total_checks == 0

    def test_none_roi_noop(self):
        ud = PPESafetyCallback()
        _fake_hailo._roi = None
        app_callback(element=None, buffer=object(), user_data=ud)
        assert ud.total_checks == 0

    def test_no_detections_noop(self):
        ud = _run([])
        assert ud.total_checks == 0

    def test_detection_without_classifications(self):
        ud = _run([_FakeDetection([])])
        assert ud.total_checks == 0
