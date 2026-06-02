"""YOLO World entry point.

Wires the text-embedding manager to the GStreamer pipeline and the HailoRT
inference engine. The per-frame callback runs YOLO World inference, decodes
output tensors, and attaches detections as Hailo metadata for native overlay.
"""
import os
import threading
from collections import Counter, deque

os.environ.setdefault("GST_PLUGIN_FEATURE_RANK", "vaapidecodebin:NONE")

import gi  # noqa: E402

gi.require_version("Gst", "1.0")
from gi.repository import Gst  # noqa: E402,F401  -- imported for plugin init side-effects

import hailo  # noqa: E402

from hailo_apps.python.core.common.buffer_utils import (  # noqa: E402
    get_caps_from_pad,
    get_numpy_from_buffer,
)
from hailo_apps.python.core.common.hailo_logger import get_logger  # noqa: E402
from hailo_apps.python.core.gstreamer.gstreamer_app import app_callback_class  # noqa: E402
from hailo_apps.python.pipeline_apps.yolo_world.live_control import LivePromptController  # noqa: E402
from hailo_apps.python.pipeline_apps.yolo_world.postprocess import postprocess  # noqa: E402
from hailo_apps.python.pipeline_apps.yolo_world.prompt_suggester import PromptSuggester  # noqa: E402
from hailo_apps.python.core.common.callback_profiler import CallbackProfiler  # noqa: E402
from hailo_apps.python.pipeline_apps.yolo_world.text_embedding_manager import (  # noqa: E402
    TextEmbeddingManager,
)
from hailo_apps.python.pipeline_apps.yolo_world.yolo_world_inference import (  # noqa: E402
    YoloWorldInference,
)
from hailo_apps.python.pipeline_apps.yolo_world.yolo_world_pipeline import (  # noqa: E402
    GStreamerYoloWorldApp,
)

logger = get_logger(__name__)


class YoloWorldCallbackData(app_callback_class):
    def __init__(self):
        super().__init__()
        self.inference_engine = None
        self.embedding_manager = None
        self.confidence_threshold = 0.3
        self._last_embeddings_id = None
        self.profiler = CallbackProfiler(enabled=False)
        self.detect_threshold = 0.3   # threshold fed to postprocess (== confidence_threshold;
                                      # GStreamer hailotracker handles temporal stability downstream)
        self.frame_buffer = None      # deque of recent frames (interactive probe)
        self.engine_lock = threading.Lock()  # guards the shared detector engine
        self._counts_lock = threading.Lock()
        self._latest_counts = {}

    def record_class_counts(self, counts):
        with self._counts_lock:
            self._latest_counts = counts

    def snapshot_class_counts(self):
        with self._counts_lock:
            return dict(self._latest_counts)


def app_callback(element, buffer, user_data):
    if buffer is None:
        return

    t_start = user_data.profiler.start()

    pad = element.get_static_pad("src")
    fmt, width, height = get_caps_from_pad(pad)
    if fmt is None or width is None or height is None:
        return

    frame = get_numpy_from_buffer(buffer, fmt, width, height)
    if frame is None:
        return
    if user_data.frame_buffer is not None:
        user_data.frame_buffer.append(frame)   # recent frames for the ?probe
    t_after_copy = user_data.profiler.mark(t_start, "caps_and_copy")

    engine = user_data.inference_engine
    manager = user_data.embedding_manager

    # Re-bind embeddings tensor in the inference engine when it changes.
    current_embeddings = manager.get_embeddings()
    if current_embeddings is not user_data._last_embeddings_id:
        engine.update_text_embeddings(current_embeddings)
        user_data._last_embeddings_id = current_embeddings
        logger.info("Inference engine updated with new embeddings")

    # The lock spans engine.run() + postprocess. `engine.run()` returns *views*
    # into pre-allocated output buffers; if the interactive ?probe acquired the
    # lock between run() and postprocess, it would swap embeddings and re-run
    # the engine, overwriting those buffers mid-read. Postprocess materializes
    # owned detection dicts, so downstream elements can read them safely.
    with user_data.engine_lock:
        outputs = engine.run(frame)
        t_after_infer = user_data.profiler.mark(t_after_copy, "infer")
        labels = manager.get_labels()
        num_classes = manager.get_num_classes()
        detections = postprocess(
            outputs,
            score_threshold=user_data.detect_threshold,
            num_classes=num_classes,
        )
    t_after_post = user_data.profiler.mark(t_after_infer, "postprocess")

    # hailooverlay reads detections off the buffer ROI.
    roi = hailo.get_roi_from_buffer(buffer)
    for det in detections:
        x1, y1, x2, y2 = det["bbox"]
        cls_id = det["class_id"]
        label = labels[cls_id] if cls_id < len(labels) else f"class_{cls_id}"
        bbox = hailo.HailoBBox(float(x1), float(y1), float(x2 - x1), float(y2 - y1))
        roi.add_object(hailo.HailoDetection(bbox, label, float(det["score"])))
    user_data.profiler.mark(t_after_post, "attach")
    user_data.profiler.frame_done(t_start)

    # Per-class tally for the interactive live-prompt status bar.
    user_data.record_class_counts(
        Counter(labels[d["class_id"]] for d in detections if d["class_id"] < len(labels))
    )

    frame_idx = user_data.get_count()
    if frame_idx % 30 == 0 and detections:
        det_summary = ", ".join(
            f"{labels[d['class_id']]}: {d['score']:.2f}" for d in detections[:5]
        )
        logger.debug("Frame %d: %d detections — %s", frame_idx, len(detections), det_summary)


def main():
    logger.info("Starting YOLO World App.")
    user_data = YoloWorldCallbackData()
    user_data.window_title = "YOLO World — Zero-Shot Detection"

    app = GStreamerYoloWorldApp(app_callback, user_data)

    opts = app.options_menu
    user_data.confidence_threshold = opts.confidence_threshold
    user_data.profiler = CallbackProfiler(enabled=opts.profile)

    # Temporal stability is handled by the GStreamer hailotracker element
    # downstream of the user-callback (see TRACKER_PIPELINE in
    # yolo_world_pipeline.py). Postprocess threshold runs at ~half the user
    # confidence threshold so weak detections still reach the tracker;
    # hailotracker's keep_new_frames acts as the "confirm before showing"
    # gate, and keep_lost_frames sustains tracks across detection gaps.
    user_data.detect_threshold = max(0.1, 0.5 * opts.confidence_threshold)

    user_data.embedding_manager = TextEmbeddingManager(
        prompts=opts.prompts,
        prompts_file=opts.prompts_file,
        embeddings_file=opts.embeddings_file,
        watch=opts.watch_prompts,
    )

    user_data.inference_engine = YoloWorldInference(
        hef_path=app.hef_path,
        text_embeddings=user_data.embedding_manager.get_embeddings(),
    )
    user_data._last_embeddings_id = user_data.embedding_manager.get_embeddings()

    controller = None
    if getattr(opts, "interactive", False):
        # Suggester reuses the manager's CLIP encoder; frame buffer + factory power
        # the detection-aware "?word" probe.
        suggester = PromptSuggester(user_data.embedding_manager.encoder)
        user_data.frame_buffer = deque(maxlen=24)
        controller = LivePromptController(
            user_data.embedding_manager, user_data,
            suggester=suggester,
            frame_buffer=user_data.frame_buffer,
            engine=user_data.inference_engine,     # reuse the live engine (single VDevice)
            engine_lock=user_data.engine_lock,
        )
        controller.start()

    try:
        app.run()
    finally:
        if controller is not None:
            controller.stop()
        user_data.inference_engine.close()
        user_data.embedding_manager.stop()


if __name__ == "__main__":
    main()
