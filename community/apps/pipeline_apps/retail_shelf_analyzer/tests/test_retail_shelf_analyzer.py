"""Pure-Python unit tests for the retail shelf analyzer app.

Covers the device-independent core logic of
``community.apps.pipeline_apps.retail_shelf_analyzer.retail_shelf_analyzer``:

* ``assign_zone`` — horizontal-band zone assignment by normalized y-center,
  including band boundaries, the y=0/y=1 edges, num_zones=1, even N-way splits,
  and y values just outside [0, 1].
* ``EXCLUDED_LABELS`` filtering inside ``app_callback`` (e.g. "person").
* Per-zone product counting and confidence filtering in ``app_callback``.
* The demo-model warning predicate (HEF name contains "4_classes"/"visdrone"
  triggers a warning).

The app module imports ``gi``/``hailo`` and the Hailo GStreamer helpers at
import time, and ``retail_shelf_analyzer.py`` also reaches into ``hailo`` at
runtime (``get_roi_from_buffer`` / ``HAILO_DETECTION``). Those heavy/device
modules are stubbed before importing the app so the suite runs headless in its
own pytest process. No device, GStreamer, inference, or network access occurs.
"""

import sys
from unittest.mock import MagicMock

import pytest

pytestmark = pytest.mark.community

# --- Stub heavy / device modules before importing the app under test --------
# ``hailo`` is stubbed with a plain MagicMock at first; the specific symbols the
# callback uses (``HAILO_DETECTION``, ``get_roi_from_buffer``) are wired per-test
# via the ``hailo_stub`` fixture so we can feed in fake detections.
for mod_name in [
    "gi",
    "gi.repository",
    "gi.repository.Gst",
    "cv2",
    "hailo",
    "hailo_apps.python.core.common.hailo_logger",
    "hailo_apps.python.core.gstreamer.gstreamer_app",
]:
    if mod_name not in sys.modules:
        sys.modules[mod_name] = MagicMock()
sys.modules["gi"].require_version = lambda *a, **kw: None


class _StubAppCallbackBase:
    """Mimics app_callback_class enough for RetailShelfCallbackData."""

    def __init__(self):
        self.frame_count = 0
        self.use_frame = False
        self.window_title = ""

    def get_count(self):
        return self.frame_count

    def increment(self):
        self.frame_count += 1

    def set_frame(self, frame):
        self._frame = frame


sys.modules[
    "hailo_apps.python.core.gstreamer.gstreamer_app"
].app_callback_class = _StubAppCallbackBase


# Give the stubbed logger a real-ish interface so app_callback's
# ``hailo_logger.info/warning(...)`` calls don't blow up.
sys.modules["hailo_apps.python.core.common.hailo_logger"].get_logger = (
    lambda *a, **kw: MagicMock()
)

from community.apps.pipeline_apps.retail_shelf_analyzer import (  # noqa: E402
    retail_shelf_analyzer as rsa,
)
from community.apps.pipeline_apps.retail_shelf_analyzer.retail_shelf_analyzer import (  # noqa: E402
    EXCLUDED_LABELS,
    RetailShelfCallbackData,
    assign_zone,
)


# ============================================================
# Fakes — minimal stand-ins for the hailo bbox / detection / ROI objects.
# ============================================================
class FakeBBox:
    """Mimics hailo bbox: ymin()/height() are all assign_zone needs."""

    def __init__(self, ymin, height):
        self._ymin = ymin
        self._height = height

    def ymin(self):
        return self._ymin

    def height(self):
        return self._height


class FakeDetection:
    """Mimics a hailo detection object used by assign_zone + app_callback."""

    def __init__(self, ymin=0.0, height=0.0, label="product", confidence=1.0):
        self._bbox = FakeBBox(ymin, height)
        self._label = label
        self._confidence = confidence

    def get_bbox(self):
        return self._bbox

    def get_label(self):
        return self._label

    def get_confidence(self):
        return self._confidence


def det_at_ycenter(y_center, label="product", confidence=1.0):
    """Build a detection whose vertical center is exactly ``y_center``.

    assign_zone computes y_center = ymin + height/2. With height=0 the center
    is simply ymin, which keeps the boundary arithmetic exact.
    """
    return FakeDetection(ymin=y_center, height=0.0, label=label, confidence=confidence)


class _FakeROI:
    def __init__(self, detections):
        self._detections = detections

    def get_objects_typed(self, _type):
        return self._detections


@pytest.fixture
def hailo_stub():
    """Wire the stubbed ``hailo`` module so app_callback can read detections.

    Returns a setter ``feed(detections)`` that makes ``get_roi_from_buffer``
    return an ROI yielding exactly those detections.
    """
    hailo_mod = sys.modules["hailo"]
    state = {"detections": []}

    hailo_mod.HAILO_DETECTION = "HAILO_DETECTION"
    hailo_mod.get_roi_from_buffer = lambda _buf: _FakeROI(state["detections"])

    def feed(detections):
        state["detections"] = list(detections)

    return feed


# ============================================================
# assign_zone — band assignment by normalized y-center
# ============================================================
class TestAssignZone:
    def test_top_band(self):
        # y-center 0.1 in 3 zones -> int(0.1*3)=0 (top shelf).
        assert assign_zone(det_at_ycenter(0.1), 3) == 0

    def test_middle_band(self):
        # 0.5 * 3 = 1.5 -> int -> 1 (middle shelf).
        assert assign_zone(det_at_ycenter(0.5), 3) == 1

    def test_bottom_band(self):
        # 0.9 * 3 = 2.7 -> int -> 2 (bottom shelf, num_zones-1).
        assert assign_zone(det_at_ycenter(0.9), 3) == 2

    def test_uses_bbox_center_not_ymin(self):
        # ymin=0.0, height=0.8 -> center 0.4 -> int(0.4*3)=1, NOT zone 0.
        d = FakeDetection(ymin=0.0, height=0.8)
        assert assign_zone(d, 3) == 1

    # --- edges ---------------------------------------------------------------
    def test_y_zero_maps_to_top_zone(self):
        assert assign_zone(det_at_ycenter(0.0), 3) == 0

    def test_y_one_clamped_to_bottom_zone(self):
        # 1.0 * 3 = 3 -> would be index 3 (out of range); clamp -> num_zones-1.
        assert assign_zone(det_at_ycenter(1.0), 3) == 2

    def test_single_zone_everything_maps_to_zero(self):
        for y in (0.0, 0.25, 0.5, 0.75, 1.0):
            assert assign_zone(det_at_ycenter(y), 1) == 0

    def test_exact_band_boundary_rounds_up_to_next_zone(self):
        # Band boundary in 3 zones is at y=1/3. int(1/3*3)=int(1.0)=1.
        # The boundary belongs to the LOWER band (zone 1), not zone 0.
        assert assign_zone(det_at_ycenter(1.0 / 3.0), 3) == 1

    def test_second_band_boundary(self):
        # Second boundary at y=2/3 -> int(2.0)=2.
        assert assign_zone(det_at_ycenter(2.0 / 3.0), 3) == 2

    def test_even_split_across_n_zones(self):
        # For N zones, a center at the mid of band k lands in zone k.
        n = 5
        for k in range(n):
            mid = (k + 0.5) / n
            assert assign_zone(det_at_ycenter(mid), n) == k

    def test_each_band_lower_edge_lands_in_that_band(self):
        # The lower (top) edge of band k is at k/N; int((k/N)*N)=k.
        n = 4
        for k in range(n):
            assert assign_zone(det_at_ycenter(k / n), n) == k

    # --- y just outside [0, 1] -----------------------------------------------
    def test_y_just_above_one_clamped(self):
        # Detection center slightly past the bottom; clamp keeps it in range.
        assert assign_zone(det_at_ycenter(1.05), 3) == 2

    def test_y_far_above_one_still_clamped(self):
        assert assign_zone(det_at_ycenter(5.0), 3) == 2

    def test_y_negative_is_not_clamped_low(self):
        # Documents current behavior: assign_zone only clamps the HIGH end.
        # A negative y-center yields a negative zone index (caller must keep
        # detections in-frame). int(-0.1*3) = int(-0.3) = 0, but a larger
        # negative goes below 0.
        assert assign_zone(det_at_ycenter(-0.5), 3) == -1


# ============================================================
# EXCLUDED_LABELS — module-level set contents
# ============================================================
class TestExcludedLabelsSet:
    def test_person_is_excluded(self):
        assert "person" in EXCLUDED_LABELS

    def test_typical_product_label_not_excluded(self):
        assert "product" not in EXCLUDED_LABELS
        assert "bottle" not in EXCLUDED_LABELS

    def test_excluded_set_is_animals_plus_person(self):
        # Sanity: the documented COCO animal classes + person.
        assert {"person", "cat", "dog", "bird"}.issubset(EXCLUDED_LABELS)


# ============================================================
# app_callback — per-zone counting, excluded labels, confidence filter
# ============================================================
def _make_user_data(num_zones=3, empty_threshold=2, confidence_threshold=0.4):
    ud = RetailShelfCallbackData()
    ud.num_zones = num_zones
    ud.empty_threshold = empty_threshold
    ud.confidence_threshold = confidence_threshold
    return ud


class TestAppCallbackCounting:
    def test_none_buffer_is_noop(self, hailo_stub):
        ud = _make_user_data()
        # Should return cleanly without touching zone_counts.
        assert rsa.app_callback(None, None, ud) is None

    def test_products_counted_into_correct_zones(self, hailo_stub):
        ud = _make_user_data(num_zones=3)
        hailo_stub([
            det_at_ycenter(0.1),   # zone 0
            det_at_ycenter(0.1),   # zone 0
            det_at_ycenter(0.5),   # zone 1
            det_at_ycenter(0.9),   # zone 2
        ])
        rsa.app_callback(None, object(), ud)
        assert ud.zone_counts == {0: 2, 1: 1, 2: 1}

    def test_zero_detections_all_zones_zero(self, hailo_stub):
        ud = _make_user_data(num_zones=3)
        hailo_stub([])
        rsa.app_callback(None, object(), ud)
        assert ud.zone_counts == {0: 0, 1: 0, 2: 0}

    def test_excluded_label_not_counted(self, hailo_stub):
        ud = _make_user_data(num_zones=2)
        hailo_stub([
            det_at_ycenter(0.25, label="person"),   # excluded
            det_at_ycenter(0.25, label="product"),  # counted, zone 0
        ])
        rsa.app_callback(None, object(), ud)
        assert ud.zone_counts == {0: 1, 1: 0}

    def test_all_excluded_yields_zero_counts(self, hailo_stub):
        ud = _make_user_data(num_zones=2)
        hailo_stub([
            det_at_ycenter(0.1, label="person"),
            det_at_ycenter(0.6, label="dog"),
            det_at_ycenter(0.9, label="cat"),
        ])
        rsa.app_callback(None, object(), ud)
        assert ud.zone_counts == {0: 0, 1: 0}

    def test_low_confidence_filtered(self, hailo_stub):
        ud = _make_user_data(num_zones=2, confidence_threshold=0.4)
        hailo_stub([
            det_at_ycenter(0.25, confidence=0.39),  # below -> dropped
            det_at_ycenter(0.25, confidence=0.41),  # above -> kept
        ])
        rsa.app_callback(None, object(), ud)
        assert ud.zone_counts == {0: 1, 1: 0}

    def test_confidence_at_threshold_is_kept(self, hailo_stub):
        # Predicate is ``confidence < threshold`` -> equality is NOT dropped.
        ud = _make_user_data(num_zones=1, confidence_threshold=0.4)
        hailo_stub([det_at_ycenter(0.5, confidence=0.4)])
        rsa.app_callback(None, object(), ud)
        assert ud.zone_counts == {0: 1}

    def test_single_zone_aggregates_everything(self, hailo_stub):
        ud = _make_user_data(num_zones=1)
        hailo_stub([
            det_at_ycenter(0.0),
            det_at_ycenter(0.5),
            det_at_ycenter(1.0),
        ])
        rsa.app_callback(None, object(), ud)
        assert ud.zone_counts == {0: 3}

    def test_empty_zone_alert_increments_when_below_threshold(self, hailo_stub):
        # threshold=2; only zone 1 reaches it, zones 0 and 2 are below -> alert.
        ud = _make_user_data(num_zones=3, empty_threshold=2)
        hailo_stub([
            det_at_ycenter(0.5),  # zone 1
            det_at_ycenter(0.5),  # zone 1
        ])
        rsa.app_callback(None, object(), ud)
        assert ud.empty_zone_alerts == 1

    def test_no_alert_when_all_zones_meet_threshold(self, hailo_stub):
        ud = _make_user_data(num_zones=2, empty_threshold=1)
        hailo_stub([
            det_at_ycenter(0.25),  # zone 0
            det_at_ycenter(0.75),  # zone 1
        ])
        rsa.app_callback(None, object(), ud)
        assert ud.empty_zone_alerts == 0

    def test_alert_counter_accumulates_across_frames(self, hailo_stub):
        ud = _make_user_data(num_zones=2, empty_threshold=5)
        hailo_stub([det_at_ycenter(0.25)])
        rsa.app_callback(None, object(), ud)
        rsa.app_callback(None, object(), ud)
        # Both frames have understocked zones -> two alerts.
        assert ud.empty_zone_alerts == 2

    def test_zone_counts_reset_between_frames(self, hailo_stub):
        ud = _make_user_data(num_zones=2)
        hailo_stub([det_at_ycenter(0.25), det_at_ycenter(0.25)])
        rsa.app_callback(None, object(), ud)
        assert ud.zone_counts == {0: 2, 1: 0}
        # Next frame: products moved to the other zone.
        hailo_stub([det_at_ycenter(0.75)])
        rsa.app_callback(None, object(), ud)
        assert ud.zone_counts == {0: 0, 1: 1}

    def test_defaults_used_when_attrs_missing(self, hailo_stub):
        # A bare callback-data object (no num_zones/threshold attrs) falls back
        # to the getattr defaults: 3 zones, threshold 2, confidence 0.4.
        ud = RetailShelfCallbackData()
        hailo_stub([
            det_at_ycenter(0.1, confidence=0.3),  # below default 0.4 -> dropped
            det_at_ycenter(0.5, confidence=0.9),  # zone 1
        ])
        rsa.app_callback(None, object(), ud)
        assert ud.zone_counts == {0: 0, 1: 1, 2: 0}


# ============================================================
# RetailShelfCallbackData — initial state
# ============================================================
class TestCallbackDataInit:
    def test_initial_zone_counts_empty(self):
        assert RetailShelfCallbackData().zone_counts == {}

    def test_initial_alerts_zero(self):
        assert RetailShelfCallbackData().empty_zone_alerts == 0


# ============================================================
# Demo-model warning predicate.
#
# The predicate lives in GStreamerRetailShelfAnalyzerApp._warn_if_demo_model,
# whose normal __init__ builds the full GStreamer/device pipeline. We exercise
# the predicate without that by constructing a bare instance via __new__ and
# calling the bound method, with the warning logger replaced by a spy.
# ============================================================
from community.apps.pipeline_apps.retail_shelf_analyzer import (  # noqa: E402
    retail_shelf_analyzer_pipeline as rsap,
)


def _warn_called_for(hef_path):
    """Run _warn_if_demo_model for ``hef_path`` and report whether it warned."""
    app = rsap.GStreamerRetailShelfAnalyzerApp.__new__(
        rsap.GStreamerRetailShelfAnalyzerApp
    )
    app.hef_path = hef_path
    spy = MagicMock()
    # Patch the module-level logger the method calls into.
    orig = rsap.hailo_logger
    rsap.hailo_logger = spy
    try:
        app._warn_if_demo_model()
    finally:
        rsap.hailo_logger = orig
    return spy.warning.called


class TestDemoModelWarning:
    def test_warns_on_4_classes_hef(self):
        assert _warn_called_for("/models/hailo_yolov8n_4_classes_vga.hef") is True

    def test_warns_on_visdrone_hef(self):
        assert _warn_called_for("/models/yolov8n_visdrone.hef") is True

    def test_case_insensitive_match(self):
        # The method lowercases the name before matching.
        assert _warn_called_for("/models/YOLOV8N_4_CLASSES_VGA.hef") is True
        assert _warn_called_for("/models/VisDrone_Detector.hef") is True

    def test_no_warning_on_product_model(self):
        assert _warn_called_for("/models/coco_yolov8n.hef") is False

    def test_no_warning_on_sku_model(self):
        assert _warn_called_for("/models/sku110k_products.hef") is False

    def test_matches_substring_not_just_exact_name(self):
        # "4_classes" anywhere in the basename triggers the warning.
        assert _warn_called_for("/x/custom_4_classes_model_v2.hef") is True
