"""Unit tests for the aerial_object_counter standalone app.

Pure-Python only: no Hailo device, no inference, no network. The OBB decode
itself lives in the reused ``oriented_object_detection`` module and is *not*
re-tested here; instead we stub ``obb_postprocess`` and exercise this app's own
counting glue, image_index bookkeeping, JSON summary, the count-overlay data
prep, and the save-output gating.
"""

import json
import os
import queue
import sys
import threading
from unittest.mock import MagicMock

import numpy as np
import pytest

pytestmark = pytest.mark.community

# HailoRT may not be available on the test machine — stub the platform modules
# so importing the app (which transitively imports HailoInfer) cannot fail.
for _mod_name in [
    "hailo_platform",
    "hailo_platform.pyhailort",
    "hailo_platform.pyhailort.pyhailort",
]:
    if _mod_name not in sys.modules:
        sys.modules[_mod_name] = MagicMock()

from community.apps.standalone_apps.aerial_object_counter import (
    aerial_object_counter as app,
)
from community.apps.standalone_apps.aerial_object_counter import (
    aerial_object_counter_post_process as pp,
)
from community.apps.standalone_apps.aerial_object_counter.aerial_object_counter import (
    CountingVisualizer,
    oriented_object_detection_preprocess,
    counting_visualize,
)
from community.apps.standalone_apps.aerial_object_counter.aerial_object_counter_post_process import (
    draw_counting_overlay,
    _draw_count_summary,
    inference_result_handler,
)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
DOTA_LABELS = ["plane", "ship", "harbor", "bridge", "vehicle"]


def make_box(cx=50.0, cy=50.0, w=20.0, h=10.0, angle=0.0):
    """An OBB tuple in the ((cx, cy), (w, h), angle_deg) layout cv2 expects."""
    return ((float(cx), float(cy)), (float(w), float(h)), float(angle))


def make_frame(h=120, w=160):
    return np.zeros((h, w, 3), dtype=np.uint8)


def stub_obb(monkeypatch, boxes, classes, scores):
    """Make both modules' ``obb_postprocess`` return a fixed decode result.

    ``CountingVisualizer.process_frame`` imports obb_postprocess lazily from the
    post_process module, and ``inference_result_handler`` uses the name bound in
    that module too, so patching there covers both call sites.
    """
    fake = lambda frame, infer, cfg: (boxes, classes, scores)
    monkeypatch.setattr(pp, "obb_postprocess", fake)
    monkeypatch.setattr(app, "obb_postprocess", fake, raising=False)


# --------------------------------------------------------------------------- #
# Clean-import smoke test (deps stubbed)
# --------------------------------------------------------------------------- #
class TestCleanImport:
    def test_modules_import_headless(self):
        assert app is not None
        assert pp is not None

    def test_app_name_is_loadbearing_obb(self):
        # APP_NAME drives HEF resolution and must stay the OBB app's name.
        assert app.APP_NAME == "oriented_object_detection"

    def test_obb_config_path_points_at_reused_package(self):
        assert app.OBB_CONFIG_PATH.endswith("config.json")
        assert "oriented_object_detection" in app.OBB_CONFIG_PATH


# --------------------------------------------------------------------------- #
# CountingVisualizer — counting logic, image_index, dedup-free accumulation
# --------------------------------------------------------------------------- #
class TestCountingPerClass:
    def test_single_object_single_class(self, monkeypatch):
        stub_obb(monkeypatch, [make_box()], [0], [0.9])
        viz = CountingVisualizer(DOTA_LABELS, {}, output_dir="/unused")
        viz.process_frame(make_frame(), infer_results=object())
        entry = viz.image_results[0]
        assert entry["total_objects"] == 1
        assert entry["counts_per_class"] == {"plane": 1}

    def test_multiple_classes_counted_separately(self, monkeypatch):
        # 2 planes, 3 ships, 1 harbor
        classes = [0, 0, 1, 1, 1, 2]
        boxes = [make_box() for _ in classes]
        scores = [0.5] * len(classes)
        stub_obb(monkeypatch, boxes, classes, scores)
        viz = CountingVisualizer(DOTA_LABELS, {}, output_dir="/unused")
        viz.process_frame(make_frame(), object())
        entry = viz.image_results[0]
        assert entry["total_objects"] == 6
        assert entry["counts_per_class"] == {"plane": 2, "ship": 3, "harbor": 1}

    def test_zero_detections(self, monkeypatch):
        stub_obb(monkeypatch, [], [], [])
        viz = CountingVisualizer(DOTA_LABELS, {}, output_dir="/unused")
        viz.process_frame(make_frame(), object())
        entry = viz.image_results[0]
        assert entry["total_objects"] == 0
        assert entry["counts_per_class"] == {}

    def test_class_id_out_of_label_range_falls_back(self, monkeypatch):
        # cls_id 99 has no label -> "class_99"
        stub_obb(monkeypatch, [make_box(), make_box()], [99, 0], [0.3, 0.3])
        viz = CountingVisualizer(DOTA_LABELS, {}, output_dir="/unused")
        viz.process_frame(make_frame(), object())
        counts = viz.image_results[0]["counts_per_class"]
        assert counts == {"class_99": 1, "plane": 1}

    def test_empty_label_list_uses_fallback_names(self, monkeypatch):
        stub_obb(monkeypatch, [make_box()], [0], [0.9])
        viz = CountingVisualizer([], {}, output_dir="/unused")
        viz.process_frame(make_frame(), object())
        assert viz.image_results[0]["counts_per_class"] == {"class_0": 1}


class TestImageIndex:
    def test_index_increments_per_frame(self, monkeypatch):
        stub_obb(monkeypatch, [make_box()], [0], [0.9])
        viz = CountingVisualizer(DOTA_LABELS, {}, output_dir="/unused")
        assert viz.image_index == 0
        viz.process_frame(make_frame(), object())
        assert viz.image_index == 1
        viz.process_frame(make_frame(), object())
        assert viz.image_index == 2

    def test_image_names_are_sequential_and_zero_padded(self, monkeypatch):
        stub_obb(monkeypatch, [], [], [])
        viz = CountingVisualizer(DOTA_LABELS, {}, output_dir="/unused")
        for _ in range(3):
            viz.process_frame(make_frame(), object())
        names = [e["image"] for e in viz.image_results]
        assert names == ["image_0001.jpg", "image_0002.jpg", "image_0003.jpg"]

    def test_no_cross_frame_dedup_each_frame_independent(self, monkeypatch):
        """Counts must NOT be deduplicated across frames — identical detections
        on two frames produce two independent per-image entries."""
        stub_obb(monkeypatch, [make_box(), make_box()], [1, 1], [0.8, 0.8])
        viz = CountingVisualizer(DOTA_LABELS, {}, output_dir="/unused")
        viz.process_frame(make_frame(), object())
        viz.process_frame(make_frame(), object())
        assert len(viz.image_results) == 2
        for e in viz.image_results:
            assert e["counts_per_class"] == {"ship": 2}


# --------------------------------------------------------------------------- #
# write_json_summary — global aggregation across frames
# --------------------------------------------------------------------------- #
class TestWriteJsonSummary:
    def test_aggregates_globals_across_images(self, monkeypatch, tmp_path):
        out = tmp_path / "counts.json"
        viz = CountingVisualizer(
            DOTA_LABELS, {}, output_dir=str(tmp_path), json_output_path=str(out)
        )
        # Frame 1: 2 planes, 1 ship
        stub_obb(monkeypatch, [make_box()] * 3, [0, 0, 1], [0.9] * 3)
        viz.process_frame(make_frame(), object())
        # Frame 2: 1 plane, 2 harbors
        stub_obb(monkeypatch, [make_box()] * 3, [0, 2, 2], [0.9] * 3)
        viz.process_frame(make_frame(), object())

        viz.write_json_summary()
        data = json.loads(out.read_text())

        assert data["total_images"] == 2
        assert data["total_objects"] == 6
        assert data["global_counts_per_class"] == {"plane": 3, "ship": 1, "harbor": 2}
        assert len(data["per_image"]) == 2

    def test_summary_with_no_images(self, monkeypatch, tmp_path):
        out = tmp_path / "empty.json"
        viz = CountingVisualizer(
            DOTA_LABELS, {}, output_dir=str(tmp_path), json_output_path=str(out)
        )
        viz.write_json_summary()
        data = json.loads(out.read_text())
        assert data["total_images"] == 0
        assert data["total_objects"] == 0
        assert data["global_counts_per_class"] == {}
        assert data["per_image"] == []

    def test_default_json_path_inside_output_dir(self, tmp_path):
        viz = CountingVisualizer(DOTA_LABELS, {}, output_dir=str(tmp_path))
        assert viz.json_output_path == os.path.join(str(tmp_path), "count_summary.json")

    def test_explicit_json_path_overrides_default(self, tmp_path):
        custom = str(tmp_path / "nested" / "my.json")
        viz = CountingVisualizer(DOTA_LABELS, {}, output_dir=str(tmp_path), json_output_path=custom)
        assert viz.json_output_path == custom

    def test_summary_creates_missing_parent_dirs(self, monkeypatch, tmp_path):
        nested = tmp_path / "a" / "b" / "c" / "out.json"
        viz = CountingVisualizer(
            DOTA_LABELS, {}, output_dir=str(tmp_path), json_output_path=str(nested)
        )
        stub_obb(monkeypatch, [make_box()], [0], [0.9])
        viz.process_frame(make_frame(), object())
        viz.write_json_summary()
        assert nested.exists()


# --------------------------------------------------------------------------- #
# Letterbox preprocess geometry (pure numpy/cv2, no device)
# --------------------------------------------------------------------------- #
class TestPreprocessGeometry:
    def test_output_is_exact_model_size_square(self):
        img = np.zeros((480, 640, 3), dtype=np.uint8)
        out = oriented_object_detection_preprocess(img, model_w=640, model_h=640, config_data={})
        assert out.shape == (640, 640, 3)

    def test_padding_color_is_114(self):
        # Wide image letterboxed into a square => top/bottom padding bands are gray.
        img = np.full((100, 400, 3), 255, dtype=np.uint8)
        out = oriented_object_detection_preprocess(img, model_w=640, model_h=640, config_data={})
        # The very top row must be pure padding (114,114,114).
        assert out.shape == (640, 640, 3)
        assert (out[0, :] == 114).all()

    def test_already_square_input(self):
        img = np.zeros((640, 640, 3), dtype=np.uint8)
        out = oriented_object_detection_preprocess(img, 640, 640, {})
        assert out.shape == (640, 640, 3)

    def test_non_square_target(self):
        img = np.zeros((300, 300, 3), dtype=np.uint8)
        out = oriented_object_detection_preprocess(img, model_w=512, model_h=256, config_data={})
        assert out.shape == (256, 512, 3)


# --------------------------------------------------------------------------- #
# draw_counting_overlay / _draw_count_summary — overlay data prep (real cv2,
# small images, headless-safe: no imshow).
# --------------------------------------------------------------------------- #
class TestDrawOverlay:
    def test_returns_same_array_object_mutated_in_place(self):
        img = make_frame()
        out = draw_counting_overlay(
            img, [make_box()], [0], [0.9], DOTA_LABELS, {"plane": 1}, 1
        )
        assert out is img  # function annotates in place and returns the frame
        assert out.shape == (120, 160, 3)
        assert out.dtype == np.uint8

    def test_zero_detections_draws_no_objects_banner(self):
        img = make_frame()
        out = draw_counting_overlay(img, [], [], [], DOTA_LABELS, {}, 0)
        assert out.shape == (120, 160, 3)
        # Overlay box was drawn -> some pixels are no longer all-zero.
        assert out.sum() > 0

    def test_draw_summary_zero_count_path(self):
        img = make_frame()
        out = _draw_count_summary(img, {}, 0)
        assert out is img
        assert out.sum() > 0

    def test_draw_summary_multi_class_sorted_by_count(self):
        # Should not raise with many classes; sorting key is -count.
        img = make_frame(200, 300)
        out = _draw_count_summary(img, {"ship": 5, "plane": 2, "harbor": 9}, 16)
        assert out.shape == (200, 300, 3)

    def test_overlay_handles_class_without_label(self):
        img = make_frame()
        # cls_id 42 not in labels -> uses the "C42" fallback text path.
        out = draw_counting_overlay(
            img, [make_box()], [42], [0.5], DOTA_LABELS, {"class_42": 1}, 1
        )
        assert out.shape == (120, 160, 3)

    def test_overlay_multiple_boxes(self):
        img = make_frame(240, 320)
        boxes = [make_box(60, 60, 30, 20, 30.0), make_box(150, 150, 40, 25, -15.0)]
        out = draw_counting_overlay(
            img, boxes, [0, 1], [0.7, 0.8], DOTA_LABELS,
            {"plane": 1, "ship": 1}, 2
        )
        assert out.shape == (240, 320, 3)


# --------------------------------------------------------------------------- #
# inference_result_handler — callback-compatible counting glue
# --------------------------------------------------------------------------- #
class TestInferenceResultHandler:
    def test_returns_annotated_frame(self, monkeypatch):
        stub_obb(monkeypatch, [make_box(), make_box()], [0, 1], [0.9, 0.8])
        img = make_frame()
        out = inference_result_handler(img, object(), DOTA_LABELS, {})
        assert isinstance(out, np.ndarray)
        assert out.shape == (120, 160, 3)

    def test_handles_zero_detections(self, monkeypatch):
        stub_obb(monkeypatch, [], [], [])
        img = make_frame()
        out = inference_result_handler(img, object(), DOTA_LABELS, {})
        assert out.shape == (120, 160, 3)


# --------------------------------------------------------------------------- #
# counting_visualize — the save-output gating (the `or True` was removed).
# Disk write must honor save_output. We drive the loop directly with a fake
# queue and patch cv2.imwrite to record calls; no display.
# --------------------------------------------------------------------------- #
class _RecordingVisualizer:
    """Stand-in for CountingVisualizer: records frames, no OBB decode."""

    def __init__(self):
        self.image_index = 0
        self.processed = 0

    def process_frame(self, original_frame, infer_results):
        self.image_index += 1
        self.processed += 1
        return original_frame


def _run_loop(items, save_output, monkeypatch, output_dir):
    """Feed `items` then a sentinel None through counting_visualize and return
    the list of (path) imwrite was called with."""
    writes = []
    monkeypatch.setattr(app.cv2, "imwrite", lambda path, frame: writes.append(path))
    # Guard: display path must never run in headless tests.
    monkeypatch.setattr(app.cv2, "imshow", lambda *a, **k: (_ for _ in ()).throw(AssertionError("imshow called")))

    q = queue.Queue()
    for it in items:
        q.put(it)
    q.put(None)

    viz = _RecordingVisualizer()
    counting_visualize(
        output_queue=q,
        save_output=save_output,
        output_dir=output_dir,
        counting_viz=viz,
        fps_tracker=None,
        output_resolution=None,
        stop_event=threading.Event(),
        no_display=True,
    )
    return writes, viz


class TestSaveOutputGating:
    def test_save_output_true_writes_each_frame(self, monkeypatch, tmp_path):
        items = [(make_frame(), object()), (make_frame(), object())]
        writes, viz = _run_loop(items, True, monkeypatch, str(tmp_path))
        assert viz.processed == 2
        assert len(writes) == 2  # one imwrite per frame
        assert all(str(tmp_path) in p for p in writes)
        assert writes[0].endswith("annotated_0001.jpg")
        assert writes[1].endswith("annotated_0002.jpg")

    def test_save_output_false_writes_nothing(self, monkeypatch, tmp_path):
        items = [(make_frame(), object()), (make_frame(), object())]
        writes, viz = _run_loop(items, False, monkeypatch, str(tmp_path))
        assert viz.processed == 2          # frames still processed (still counted)
        assert writes == []                # but NOTHING written to disk

    def test_no_items_no_writes(self, monkeypatch, tmp_path):
        writes, viz = _run_loop([], True, monkeypatch, str(tmp_path))
        assert viz.processed == 0
        assert writes == []

    def test_stop_event_set_skips_processing(self, monkeypatch, tmp_path):
        # When stop_event is already set, items are drained without processing.
        writes = []
        monkeypatch.setattr(app.cv2, "imwrite", lambda path, frame: writes.append(path))
        q = queue.Queue()
        q.put((make_frame(), object()))
        q.put(None)
        viz = _RecordingVisualizer()
        ev = threading.Event()
        ev.set()
        counting_visualize(
            output_queue=q, save_output=True, output_dir=str(tmp_path),
            counting_viz=viz, fps_tracker=None, output_resolution=None,
            stop_event=ev, no_display=True,
        )
        assert viz.processed == 0
        assert writes == []


# --------------------------------------------------------------------------- #
# Edge cases: None inputs
# --------------------------------------------------------------------------- #
class TestNoneInputs:
    def test_process_frame_with_none_decode_classes_raises_cleanly(self, monkeypatch):
        """If the (stubbed) decode hands back None for classes, iterating it must
        fail with a TypeError rather than silently miscounting."""
        stub_obb(monkeypatch, [], None, [])
        viz = CountingVisualizer(DOTA_LABELS, {}, output_dir="/unused")
        with pytest.raises(TypeError):
            viz.process_frame(make_frame(), object())

    def test_counting_visualize_none_sentinel_terminates(self, monkeypatch, tmp_path):
        # A lone None must terminate the loop immediately.
        writes, viz = _run_loop([], True, monkeypatch, str(tmp_path))
        assert viz.processed == 0
