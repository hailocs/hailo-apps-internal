"""Pure-Python unit tests for the document_text_extractor standalone app.

These tests exercise the app's own glue logic — the per-frame JSON results
assembly, the confidence-threshold -> binarization-threshold wiring, the
per-frame OCR accumulation/emit logic, and the visualization compositing — with
all heavy / native dependencies (paddle, hailo, the paddle_ocr_utils chain)
stubbed so the suite runs headless in its own process. No device, inference,
network, or PaddleOCR dependency is touched.
"""

import queue
import sys
import threading
from unittest.mock import MagicMock

import numpy as np
import pytest

pytestmark = pytest.mark.community

# ---------------------------------------------------------------------------
# Stub the heavy / deferred dependency chain BEFORE importing the app.
#
# The app's module-level imports only touch the core framework (which is
# available on the test machine), but to be robust against environments where
# HailoRT / paddle native bits are missing we pre-stub the chain that the app
# defers (`paddle`, `shapely`, `pyclipper`) and the paddle_ocr_utils package the
# app pulls in lazily via _import_ocr_utils(). The OCR utils are never exercised
# with their real implementation here — the tests inject fakes directly.
# ---------------------------------------------------------------------------
for _mod_name in [
    "hailo_platform",
    "hailo_platform.pyhailort",
    "hailo_platform.pyhailort.pyhailort",
    "paddle",
    "shapely",
    "pyclipper",
]:
    if _mod_name not in sys.modules:
        sys.modules[_mod_name] = MagicMock()

from community.apps.standalone_apps.document_text_extractor import (  # noqa: E402
    document_text_extractor as app,
)


@pytest.fixture(autouse=True)
def _reset_global_json_results():
    """The app aggregates JSON into a module-level list guarded by a lock.

    Reset it around every test so cases don't leak `image_index`/results into
    each other (the index is derived from len(all_json_results)).
    """
    app.all_json_results.clear()
    yield
    app.all_json_results.clear()


# A tiny stand-in for an OpenCV/numpy image. `.copy()` and `np.hstack` are the
# only ops the app performs on frames in the pure paths under test.
def _frame(h=20, w=30):
    return np.zeros((h, w, 3), dtype=np.uint8)


# ---------------------------------------------------------------------------
# APP_NAME aliasing sanity
# ---------------------------------------------------------------------------
class TestAppNameAlias:
    def test_app_name_is_paddle_ocr_alias(self):
        # The app reuses the paddle_ocr core app's model resolution, so the
        # resource key MUST stay aliased to "paddle_ocr".
        assert app.APP_NAME == "paddle_ocr"


# ---------------------------------------------------------------------------
# Module-level state / clean import
# ---------------------------------------------------------------------------
class TestModuleImportsCleanly:
    def test_global_results_containers_present(self):
        assert isinstance(app.all_json_results, list)
        assert isinstance(app.json_results_lock, type(threading.Lock()))

    def test_key_callables_present(self):
        for name in (
            "document_result_handler",
            "_visualize_document_ocr",
            "detection_postprocess",
            "ocr_postprocess",
            "run_inference_pipeline",
            "check_ocr_dependencies",
        ):
            assert callable(getattr(app, name)), name


# ---------------------------------------------------------------------------
# document_result_handler — JSON assembly, text decoding, corrector wiring
# ---------------------------------------------------------------------------
def _fake_eval_postprocess(pairs):
    """Build a fake ocr_eval_postprocess.

    `pairs` is the list of (text, confidence) tuples to return, one per call,
    in order. Each call returns a list whose first element is the pair (the app
    reads pp_res[0]). A `None`/empty entry simulates "no recognition".
    """
    it = iter(pairs)

    def _fn(raw):
        nxt = next(it)
        if nxt is None:
            return []
        return [nxt]

    return _fn


class TestDocumentResultHandler:
    def test_returns_hstacked_frame_of_double_width(self):
        frame = _frame(20, 30)
        boxes = [(1, 1, 5, 5)]
        infer_results = [object()]  # one raw OCR output
        ocr_eval = _fake_eval_postprocess([("hello", 0.91)])

        out = app.document_result_handler(
            frame, infer_results, boxes, ocr_eval, None, save_json=False
        )
        # left.copy() + right.copy() hstacked -> width doubles, height same.
        assert out.shape == (20, 60, 3)
        assert out.dtype == np.uint8

    def test_json_structure_keys_and_bbox(self):
        frame = _frame()
        boxes = [(3, 7, 11, 13)]
        infer_results = [object()]
        ocr_eval = _fake_eval_postprocess([("Invoice", 0.876543)])

        app.document_result_handler(
            frame, infer_results, boxes, ocr_eval, None, save_json=True
        )

        assert len(app.all_json_results) == 1
        entry = app.all_json_results[0]
        assert set(entry.keys()) == {"image_index", "text_regions"}
        assert entry["image_index"] == 0
        region = entry["text_regions"][0]
        assert set(region.keys()) == {"text", "confidence", "bbox"}
        assert region["text"] == "Invoice"
        # confidence is rounded to 4 decimals.
        assert region["confidence"] == round(0.876543, 4)
        assert region["bbox"] == {"x": 3, "y": 7, "width": 11, "height": 13}

    def test_bbox_values_are_ints(self):
        frame = _frame()
        # numpy-typed box coords must be coerced to plain ints in the JSON.
        boxes = [(np.int64(2), np.int64(4), np.int64(6), np.int64(8))]
        infer_results = [object()]
        ocr_eval = _fake_eval_postprocess([("x", 0.5)])

        app.document_result_handler(
            frame, infer_results, boxes, ocr_eval, None, save_json=True
        )
        bbox = app.all_json_results[0]["text_regions"][0]["bbox"]
        for v in bbox.values():
            assert type(v) is int

    def test_empty_text_region_is_skipped(self):
        frame = _frame()
        boxes = [(0, 0, 5, 5), (1, 1, 5, 5)]
        infer_results = [object(), object()]
        # First decodes to whitespace-only (skipped after strip), second valid.
        ocr_eval = _fake_eval_postprocess([("   ", 0.4), ("ok", 0.8)])

        app.document_result_handler(
            frame, infer_results, boxes, ocr_eval, None, save_json=True
        )
        regions = app.all_json_results[0]["text_regions"]
        assert len(regions) == 1
        assert regions[0]["text"] == "ok"

    def test_text_is_stripped(self):
        frame = _frame()
        boxes = [(0, 0, 5, 5)]
        infer_results = [object()]
        ocr_eval = _fake_eval_postprocess([("  padded  ", 0.7)])

        app.document_result_handler(
            frame, infer_results, boxes, ocr_eval, None, save_json=True
        )
        assert app.all_json_results[0]["text_regions"][0]["text"] == "padded"

    def test_no_recognition_yields_zero_confidence_default(self):
        # When ocr_eval_postprocess returns nothing, the app appends ("", 0.0);
        # that empty text is then skipped in the JSON region list.
        frame = _frame()
        boxes = [(0, 0, 5, 5)]
        infer_results = [object()]
        ocr_eval = _fake_eval_postprocess([None])

        app.document_result_handler(
            frame, infer_results, boxes, ocr_eval, None, save_json=True
        )
        assert app.all_json_results[0]["text_regions"] == []

    def test_save_json_false_does_not_aggregate(self):
        frame = _frame()
        boxes = [(0, 0, 5, 5)]
        infer_results = [object()]
        ocr_eval = _fake_eval_postprocess([("text", 0.9)])

        app.document_result_handler(
            frame, infer_results, boxes, ocr_eval, None, save_json=False
        )
        assert app.all_json_results == []

    def test_corrector_applied_to_json_text(self):
        frame = _frame()
        boxes = [(0, 0, 5, 5)]
        infer_results = [object()]
        ocr_eval = _fake_eval_postprocess([("teh", 0.9)])

        corrector = MagicMock()
        corrector.correct_text.return_value = "the"

        app.document_result_handler(
            frame, infer_results, boxes, ocr_eval, corrector, save_json=True
        )
        # Corrector is applied both for the JSON text and again for the overlay
        # render (_visualize_document_ocr), so it is invoked on "teh" each time.
        corrector.correct_text.assert_called_with("teh")
        assert corrector.correct_text.call_count >= 1
        assert app.all_json_results[0]["text_regions"][0]["text"] == "the"

    def test_image_index_increments_across_calls(self):
        frame = _frame()
        boxes = [(0, 0, 5, 5)]
        for n in range(3):
            ocr_eval = _fake_eval_postprocess([(f"t{n}", 0.5)])
            app.document_result_handler(
                frame, [object()], boxes, ocr_eval, None, save_json=True
            )
        assert [e["image_index"] for e in app.all_json_results] == [0, 1, 2]

    def test_zero_confidence_value_preserved(self):
        frame = _frame()
        boxes = [(0, 0, 5, 5)]
        infer_results = [object()]
        ocr_eval = _fake_eval_postprocess([("text", 0.0)])

        app.document_result_handler(
            frame, infer_results, boxes, ocr_eval, None, save_json=True
        )
        assert app.all_json_results[0]["text_regions"][0]["confidence"] == 0.0

    def test_empty_detections_yields_empty_regions(self):
        # No boxes / no infer results -> a JSON entry with empty text_regions.
        frame = _frame()
        ocr_eval = _fake_eval_postprocess([])

        out = app.document_result_handler(
            frame, [], [], ocr_eval, None, save_json=True
        )
        assert app.all_json_results[0]["text_regions"] == []
        # Still returns a valid double-width composite.
        assert out.shape == (20, 60, 3)


# ---------------------------------------------------------------------------
# _visualize_document_ocr — compositing
# ---------------------------------------------------------------------------
class TestVisualizeDocumentOcr:
    def test_output_is_double_width_hstack(self):
        img = _frame(40, 50)
        boxes = [(2, 2, 10, 8)]
        labels = ["hi"]
        out = app._visualize_document_ocr(img, boxes, labels, None)
        assert out.shape == (40, 100, 3)
        assert out.dtype == np.uint8

    def test_left_half_is_untouched_original(self):
        img = np.full((30, 30, 3), 64, dtype=np.uint8)
        boxes = [(0, 0, 20, 20)]
        labels = ["text"]
        out = app._visualize_document_ocr(img, boxes, labels, None)
        left = out[:, :30, :]
        # The original (left) panel must be unmodified.
        assert np.array_equal(left, img)

    def test_right_half_modified_when_text_drawn(self):
        img = np.zeros((30, 30, 3), dtype=np.uint8)
        boxes = [(2, 2, 20, 20)]
        labels = ["text"]
        out = app._visualize_document_ocr(img, boxes, labels, None)
        right = out[:, 30:, :]
        # A filled white rectangle + red text were drawn -> not all zeros.
        assert right.sum() > 0

    def test_empty_label_leaves_right_untouched(self):
        img = np.full((30, 30, 3), 17, dtype=np.uint8)
        boxes = [(2, 2, 20, 20)]
        labels = ["   "]  # whitespace only -> skipped
        out = app._visualize_document_ocr(img, boxes, labels, None)
        right = out[:, 30:, :]
        assert np.array_equal(right, img)

    def test_no_boxes_returns_side_by_side_copies(self):
        img = np.full((25, 25, 3), 9, dtype=np.uint8)
        out = app._visualize_document_ocr(img, [], [], None)
        assert out.shape == (25, 50, 3)
        assert np.array_equal(out[:, :25, :], img)
        assert np.array_equal(out[:, 25:, :], img)


# ---------------------------------------------------------------------------
# detection_postprocess — the confidence-threshold -> bin_thresh wiring
# ---------------------------------------------------------------------------
class _RecordingCropFn:
    """Fake get_cropped_text_images that records the bin_thresh it received and
    returns a configurable number of crops + matching boxes."""

    def __init__(self, num_crops=0):
        self.received_bin_thresh = None
        self.received_dims = None
        self.num_crops = num_crops
        self.call_count = 0

    def __call__(self, heatmap, orig_img, model_height, model_width, bin_thresh=0.3):
        self.received_bin_thresh = bin_thresh
        self.received_dims = (model_height, model_width)
        self.call_count += 1
        crops = [np.zeros((4, 4, 3), dtype=np.uint8) for _ in range(self.num_crops)]
        boxes = [(i, i, 2, 2) for i in range(self.num_crops)]
        return crops, boxes


def _identity_resize(crop):
    return crop


def _run_detection_postprocess(crop_fn, num_input_items=1, num_crops=0, bin_thresh=0.3,
                               stop_event=None):
    """Drive detection_postprocess in-thread: feed N detection results then a
    terminating None, and collect what it pushed onto the OCR + vis queues."""
    det_q = queue.Queue()
    ocr_q = queue.Queue()
    vis_q = queue.Queue()
    if stop_event is None:
        stop_event = threading.Event()

    ocr_results_dict = {}
    ocr_expected_counts = {}

    # result has shape (H, W, C); the app slices result[:, :, 0].
    fake_result = np.zeros((4, 4, 1), dtype=np.float32)
    for _ in range(num_input_items):
        det_q.put((_frame(), fake_result))
    det_q.put(None)

    app.detection_postprocess(
        det_q, ocr_q, vis_q,
        model_height=8, model_width=16,
        stop_event=stop_event,
        get_cropped_text_images=crop_fn,
        resize_with_padding=_identity_resize,
        ocr_results_dict=ocr_results_dict,
        ocr_expected_counts=ocr_expected_counts,
        bin_thresh=bin_thresh,
    )
    return ocr_q, vis_q, ocr_expected_counts


def _drain(q):
    items = []
    while not q.empty():
        items.append(q.get())
    return items


class TestDetectionPostprocessThresholdWiring:
    def test_bin_thresh_passed_through_default(self):
        crop_fn = _RecordingCropFn(num_crops=0)
        _run_detection_postprocess(crop_fn, num_crops=0, bin_thresh=0.3)
        assert crop_fn.received_bin_thresh == 0.3

    def test_custom_threshold_flows_into_crop_fn(self):
        crop_fn = _RecordingCropFn(num_crops=0)
        _run_detection_postprocess(crop_fn, bin_thresh=0.75)
        assert crop_fn.received_bin_thresh == 0.75

    def test_threshold_boundary_zero(self):
        crop_fn = _RecordingCropFn(num_crops=0)
        _run_detection_postprocess(crop_fn, bin_thresh=0.0)
        assert crop_fn.received_bin_thresh == 0.0

    def test_threshold_boundary_one(self):
        crop_fn = _RecordingCropFn(num_crops=0)
        _run_detection_postprocess(crop_fn, bin_thresh=1.0)
        assert crop_fn.received_bin_thresh == 1.0

    def test_model_dims_passed_through(self):
        crop_fn = _RecordingCropFn(num_crops=0)
        _run_detection_postprocess(crop_fn)
        assert crop_fn.received_dims == (8, 16)

    def test_empty_detections_emit_empty_vis_tuple(self):
        # Zero crops -> the frame is forwarded to vis with empty results/boxes.
        crop_fn = _RecordingCropFn(num_crops=0)
        ocr_q, vis_q, expected = _run_detection_postprocess(crop_fn, num_crops=0)
        vis_items = _drain(vis_q)
        assert len(vis_items) == 1
        frame, results, boxes = vis_items[0]
        assert results == [] and boxes == []
        # One frame_id registered with expected count 0.
        assert list(expected.values()) == [0]

    def test_crops_are_pushed_to_ocr_queue(self):
        crop_fn = _RecordingCropFn(num_crops=3)
        ocr_q, vis_q, expected = _run_detection_postprocess(crop_fn, num_crops=3)
        ocr_items = _drain(ocr_q)
        # 3 crops pushed + terminating None.
        assert ocr_items[-1] is None
        crop_msgs = ocr_items[:-1]
        assert len(crop_msgs) == 3
        # expected_counts records 3 for the single frame.
        assert list(expected.values()) == [3]
        # Each OCR message carries (frame, [resized], (frame_id, box)).
        for frame, resized_list, (frame_id, box) in crop_msgs:
            assert isinstance(resized_list, list) and len(resized_list) == 1
            assert isinstance(frame_id, str)

    def test_terminating_none_always_forwarded(self):
        crop_fn = _RecordingCropFn(num_crops=0)
        ocr_q, _, _ = _run_detection_postprocess(crop_fn, num_input_items=0)
        # No work items, just the sentinel -> a single None forwarded.
        items = _drain(ocr_q)
        assert items == [None]

    def test_stop_event_skips_processing(self):
        crop_fn = _RecordingCropFn(num_crops=2)
        stop = threading.Event()
        stop.set()
        ocr_q, vis_q, expected = _run_detection_postprocess(
            crop_fn, num_input_items=1, num_crops=2, stop_event=stop
        )
        # With stop set, the work item is skipped; crop fn never called.
        assert crop_fn.call_count == 0
        assert _drain(ocr_q) == [None]


# ---------------------------------------------------------------------------
# ocr_postprocess — per-frame accumulation and emit-on-complete
# ---------------------------------------------------------------------------
def _run_ocr_postprocess(items, ocr_expected_counts, stop_event=None):
    """Drive ocr_postprocess in-thread with a list of OCR result items followed
    by a terminating None. Returns the vis queue and the results dict."""
    in_q = queue.Queue()
    vis_q = queue.Queue()
    if stop_event is None:
        stop_event = threading.Event()

    from collections import defaultdict
    ocr_results_dict = defaultdict(
        lambda: {"frame": None, "results": [], "boxes": [], "count": 0}
    )

    for it in items:
        in_q.put(it)
    in_q.put(None)

    app.ocr_postprocess(
        in_q, vis_q, stop_event, ocr_results_dict, ocr_expected_counts
    )
    return vis_q, ocr_results_dict


class TestOcrPostprocess:
    def test_emits_when_count_reaches_expected(self):
        fid = "frame-A"
        frame = _frame()
        expected = {fid: 2}
        items = [
            (fid, frame, "out1", (0, 0, 1, 1)),
            (fid, frame, "out2", (1, 1, 1, 1)),
        ]
        vis_q, results_dict = _run_ocr_postprocess(items, expected)
        vis_items = _drain(vis_q)
        # One completed-frame emit + terminating None.
        assert vis_items[-1] is None
        emitted = vis_items[0]
        out_frame, out_results, out_boxes = emitted
        assert out_results == ["out1", "out2"]
        assert out_boxes == [(0, 0, 1, 1), (1, 1, 1, 1)]
        # Completed frame_id is cleaned out of both dicts.
        assert fid not in results_dict
        assert fid not in expected

    def test_does_not_emit_before_expected_reached(self):
        fid = "frame-B"
        frame = _frame()
        expected = {fid: 3}
        items = [
            (fid, frame, "out1", (0, 0, 1, 1)),
            (fid, frame, "out2", (1, 1, 1, 1)),
        ]
        vis_q, results_dict = _run_ocr_postprocess(items, expected)
        vis_items = _drain(vis_q)
        # Only the terminating None — frame incomplete (2 of 3).
        assert vis_items == [None]
        assert results_dict[fid]["count"] == 2
        assert fid in expected

    def test_unknown_expected_count_does_not_emit(self):
        # If expected count is missing (None), the frame is never emitted.
        fid = "frame-C"
        items = [(fid, _frame(), "out", (0, 0, 1, 1))]
        vis_q, results_dict = _run_ocr_postprocess(items, {})
        assert _drain(vis_q) == [None]
        assert results_dict[fid]["count"] == 1

    def test_two_frames_emit_independently(self):
        fa, fb = "A", "B"
        expected = {fa: 1, fb: 1}
        items = [
            (fa, _frame(), "a0", (0, 0, 1, 1)),
            (fb, _frame(), "b0", (2, 2, 1, 1)),
        ]
        vis_q, results_dict = _run_ocr_postprocess(items, expected)
        vis_items = _drain(vis_q)
        emits = [v for v in vis_items if v is not None]
        assert len(emits) == 2
        assert {tuple(e[1]) for e in emits} == {("a0",), ("b0",)}
        assert fa not in results_dict and fb not in results_dict

    def test_accumulates_frame_reference(self):
        fid = "frame-D"
        frame = _frame(11, 13)
        expected = {fid: 1}
        items = [(fid, frame, "out", (0, 0, 1, 1))]
        vis_q, _ = _run_ocr_postprocess(items, expected)
        emitted = _drain(vis_q)[0]
        # The emitted frame is the accumulated original frame.
        assert emitted[0].shape == frame.shape

    def test_stop_event_skips_accumulation(self):
        fid = "frame-E"
        stop = threading.Event()
        stop.set()
        expected = {fid: 1}
        items = [(fid, _frame(), "out", (0, 0, 1, 1))]
        vis_q, results_dict = _run_ocr_postprocess(items, expected, stop_event=stop)
        assert _drain(vis_q) == [None]
        # Nothing accumulated.
        assert fid not in results_dict


# ---------------------------------------------------------------------------
# check_ocr_dependencies — pure dependency-gate logic
# ---------------------------------------------------------------------------
class TestCheckOcrDependencies:
    def test_passes_when_all_present(self):
        # paddle/shapely/pyclipper are stubbed into sys.modules at module top,
        # so the gate should pass without calling sys.exit.
        app.check_ocr_dependencies()  # must not raise SystemExit

    def test_exits_when_a_dependency_missing(self, monkeypatch):
        import builtins
        real_import = builtins.__import__

        def fake_import(name, *a, **k):
            if name == "pyclipper":
                raise ImportError("missing")
            return real_import(name, *a, **k)

        monkeypatch.setattr(builtins, "__import__", fake_import)
        with pytest.raises(SystemExit):
            app.check_ocr_dependencies()
