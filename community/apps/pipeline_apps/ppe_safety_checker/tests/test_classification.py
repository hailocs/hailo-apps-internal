"""Unit tests for the SAFE / VIOLATION / UNKNOWN classification decision.

The decision lives in
``GStreamerPPESafetyCheckerApp.matching_identity_callback()``:

  * A match that did NOT pass the CLIP threshold is skipped entirely
    (``UNKNOWN``) — the worker keeps whatever prior classification they had,
    so a single low-confidence frame can't flip the bbox color back to neutral.
  * A confident positive match -> ``SAFE: <text>``.
  * A confident negative match -> ``VIOLATION: <text>``.
  * The new classification is added BEFORE the old ones are removed, so the
    detection is never momentarily classification-less.

These tests drive the REAL callback with fakes for ``hailo``, ``numpy``, the
text_image_matcher, the match objects, and the detection objects — no Hailo
device, no inference, no GStreamer.
"""

import sys
from unittest.mock import MagicMock

import pytest

pytestmark = pytest.mark.community

# ----------------------------------------------------------------------------
# Build fakes for the native modules. We need real-ish behavior for a couple
# of `hailo`/`numpy` calls used by the callback, so we install purpose-built
# stub modules rather than bare MagicMocks.
# ----------------------------------------------------------------------------


class _FakeClassification:
    """Stand-in for hailo.HailoClassification."""

    def __init__(self, class_name, label, confidence):
        self.class_name = class_name
        self.label = label
        self.confidence = confidence

    # The user-callback uses these; provide them for completeness.
    def get_label(self):
        return self.label

    def get_confidence(self):
        return self.confidence


class _FakeMatrix:
    def __init__(self, data):
        self._data = data

    def get_data(self):
        return self._data


class _FakeDetection:
    """Records add/remove of classification objects in call order."""

    HAILO_MATRIX = "HAILO_MATRIX"
    HAILO_CLASSIFICATION = "HAILO_CLASSIFICATION"

    def __init__(self, matrix_data=(0.1, 0.2, 0.3), prior_labels=None):
        self._objects = {
            self.HAILO_MATRIX: [_FakeMatrix(list(matrix_data))] if matrix_data is not None else [],
            self.HAILO_CLASSIFICATION: list(prior_labels or []),
        }
        self.op_log = []  # ("add"/"remove", obj)

    def get_objects_typed(self, type_token):
        return list(self._objects.get(type_token, []))

    def add_object(self, obj):
        self.op_log.append(("add", obj))
        self._objects[self.HAILO_CLASSIFICATION].append(obj)

    def remove_object(self, obj):
        self.op_log.append(("remove", obj))
        self._objects[self.HAILO_CLASSIFICATION].remove(obj)

    def current_labels(self):
        return [c.label for c in self._objects[self.HAILO_CLASSIFICATION]]


class _FakeROI:
    def __init__(self, detections):
        self._detections = detections

    def get_objects_typed(self, type_token):
        if type_token == _FakeDetection.HAILO_DETECTION:
            return list(self._detections)
        return []


# Token constants on the fake hailo module.
_FakeDetection.HAILO_DETECTION = "HAILO_DETECTION"


class _FakeMatch:
    def __init__(self, row_idx, text, similarity, negative, passed_threshold):
        self.row_idx = row_idx
        self.text = text
        self.similarity = similarity
        self.negative = negative
        self.passed_threshold = passed_threshold


class _FakeMatcher:
    """Returns a preset list of matches from match()."""

    def __init__(self, matches):
        self._matches = matches
        self.match_calls = []

    def match(self, embeddings_np, report_all=False):
        self.match_calls.append((embeddings_np, report_all))
        return list(self._matches)


def _install_fake_hailo():
    fake = MagicMock(name="hailo")
    fake.HAILO_DETECTION = _FakeDetection.HAILO_DETECTION
    fake.HAILO_MATRIX = _FakeDetection.HAILO_MATRIX
    fake.HAILO_CLASSIFICATION = _FakeDetection.HAILO_CLASSIFICATION
    fake.HailoClassification = _FakeClassification
    fake._roi_to_return = None

    def _get_roi(buffer):
        return fake._roi_to_return

    fake.get_roi_from_buffer = _get_roi
    return fake


# ----------------------------------------------------------------------------
# Install fake native modules BEFORE importing the app module.
# ----------------------------------------------------------------------------
_fake_hailo = _install_fake_hailo()
sys.modules["hailo"] = _fake_hailo
for mod_name in ["gi", "gi.repository", "gi.repository.Gst", "setproctitle"]:
    if mod_name not in sys.modules or isinstance(sys.modules[mod_name], MagicMock):
        sys.modules.setdefault(mod_name, MagicMock())
sys.modules["gi"].require_version = lambda *a, **kw: None

from community.apps.pipeline_apps.ppe_safety_checker.ppe_safety_checker_pipeline import (  # noqa: E402
    GStreamerPPESafetyCheckerApp,
    PPE_STATUS_SAFE,
    PPE_STATUS_VIOLATION,
)


class _FakeApp:
    """Minimal app instance exposing only what matching_identity_callback uses."""

    def __init__(self, matches):
        self.text_image_matcher = _FakeMatcher(matches)


def _run_callback(detections, matches):
    """Invoke the real matching_identity_callback with fakes wired up.

    Returns the fake app (so tests can inspect matcher.match_calls)."""
    _fake_hailo._roi_to_return = _FakeROI(detections)
    app = _FakeApp(matches)
    GStreamerPPESafetyCheckerApp.matching_identity_callback(
        app, element=None, buffer=object(), user_data=None
    )
    return app


class TestConfidentSafe:
    def test_confident_safe_adds_safe_label(self):
        det = _FakeDetection()
        match = _FakeMatch(
            row_idx=0, text="wearing helmet", similarity=0.9,
            negative=False, passed_threshold=True,
        )
        _run_callback([det], [match])
        labels = det.current_labels()
        assert len(labels) == 1
        assert labels[0].startswith(PPE_STATUS_SAFE)
        assert "wearing helmet" in labels[0]

    def test_safe_classification_carries_similarity_as_confidence(self):
        det = _FakeDetection()
        match = _FakeMatch(0, "ok", 0.77, negative=False, passed_threshold=True)
        _run_callback([det], [match])
        cls = det.get_objects_typed(_FakeDetection.HAILO_CLASSIFICATION)[0]
        assert cls.get_confidence() == pytest.approx(0.77)
        assert cls.class_name == "ppe_status"


class TestConfidentViolation:
    def test_confident_violation_adds_violation_label(self):
        det = _FakeDetection()
        match = _FakeMatch(
            row_idx=0, text="no helmet", similarity=0.85,
            negative=True, passed_threshold=True,
        )
        _run_callback([det], [match])
        labels = det.current_labels()
        assert len(labels) == 1
        assert labels[0].startswith(PPE_STATUS_VIOLATION)
        assert "no helmet" in labels[0]


class TestSubThresholdUnknown:
    def test_subthreshold_does_not_add_classification(self):
        # No prior label, sub-threshold match -> UNKNOWN -> nothing added.
        det = _FakeDetection()
        match = _FakeMatch(
            row_idx=0, text="maybe", similarity=0.1,
            negative=False, passed_threshold=False,
        )
        _run_callback([det], [match])
        assert det.current_labels() == []
        assert det.op_log == []  # neither add nor remove happened

    def test_subthreshold_does_not_overwrite_prior_label(self):
        # REGRESSION: the worker already had a confident VIOLATION label from a
        # previous frame. A new low-confidence frame must NOT clear it.
        prior = _FakeClassification("ppe_status", "VIOLATION: no vest", 0.9)
        det = _FakeDetection(prior_labels=[prior])
        match = _FakeMatch(
            row_idx=0, text="unsure", similarity=0.05,
            negative=False, passed_threshold=False,
        )
        _run_callback([det], [match])
        # The prior label is still the only classification.
        assert det.current_labels() == ["VIOLATION: no vest"]
        assert det.op_log == []  # untouched


class TestReplacementBehavior:
    def test_confident_match_replaces_prior_label(self):
        # Worker previously VIOLATION, now a confident SAFE match -> the old
        # label is removed and the new SAFE label takes its place.
        prior = _FakeClassification("ppe_status", "VIOLATION: no vest", 0.9)
        det = _FakeDetection(prior_labels=[prior])
        match = _FakeMatch(
            row_idx=0, text="wearing vest", similarity=0.95,
            negative=False, passed_threshold=True,
        )
        _run_callback([det], [match])
        labels = det.current_labels()
        assert len(labels) == 1
        assert labels[0].startswith(PPE_STATUS_SAFE)

    def test_new_added_before_old_removed(self):
        # The detection must never be momentarily classification-less: the new
        # object is added BEFORE the old one is removed.
        prior = _FakeClassification("ppe_status", "VIOLATION: no vest", 0.9)
        det = _FakeDetection(prior_labels=[prior])
        match = _FakeMatch(0, "wearing vest", 0.95, negative=False, passed_threshold=True)
        _run_callback([det], [match])
        ops = [op for op, _ in det.op_log]
        assert ops == ["add", "remove"]
        # And the removed object is exactly the prior one.
        removed = [obj for op, obj in det.op_log if op == "remove"]
        assert removed == [prior]


class TestNoMatchAndEmpty:
    def test_no_detections_no_match_call(self):
        app = _run_callback([], [])
        # With no detections, embeddings stay None and match() is never called.
        assert app.text_image_matcher.match_calls == []

    def test_detection_without_embeddings_skipped(self):
        # A detection with no HAILO_MATRIX results contributes no embedding.
        det = _FakeDetection(matrix_data=None)
        app = _run_callback([det], [])
        assert app.text_image_matcher.match_calls == []
        assert det.current_labels() == []

    def test_none_buffer_is_noop(self):
        app = _FakeApp([])
        # Should simply return without touching the matcher.
        GStreamerPPESafetyCheckerApp.matching_identity_callback(
            app, element=None, buffer=None, user_data=None
        )
        assert app.text_image_matcher.match_calls == []

    def test_none_roi_is_noop(self):
        _fake_hailo._roi_to_return = None
        app = _FakeApp([])
        GStreamerPPESafetyCheckerApp.matching_identity_callback(
            app, element=None, buffer=object(), user_data=None
        )
        assert app.text_image_matcher.match_calls == []


class TestMultipleDetections:
    def test_match_routed_to_correct_detection_by_row_idx(self):
        det0 = _FakeDetection(matrix_data=(1.0, 1.0))
        det1 = _FakeDetection(matrix_data=(2.0, 2.0))
        # match for row 1 -> VIOLATION on det1; match for row 0 -> SAFE on det0.
        m0 = _FakeMatch(0, "wearing vest", 0.9, negative=False, passed_threshold=True)
        m1 = _FakeMatch(1, "no vest", 0.9, negative=True, passed_threshold=True)
        _run_callback([det0, det1], [m0, m1])
        assert det0.current_labels()[0].startswith(PPE_STATUS_SAFE)
        assert det1.current_labels()[0].startswith(PPE_STATUS_VIOLATION)

    def test_mixed_confident_and_subthreshold(self):
        det0 = _FakeDetection(matrix_data=(1.0,))
        det1 = _FakeDetection(matrix_data=(2.0,), prior_labels=[
            _FakeClassification("ppe_status", "SAFE: prior", 0.9)
        ])
        m0 = _FakeMatch(0, "no vest", 0.9, negative=True, passed_threshold=True)
        m1 = _FakeMatch(1, "unsure", 0.1, negative=False, passed_threshold=False)
        _run_callback([det0, det1], [m0, m1])
        # det0 got a confident violation; det1's prior SAFE is preserved.
        assert det0.current_labels()[0].startswith(PPE_STATUS_VIOLATION)
        assert det1.current_labels() == ["SAFE: prior"]
