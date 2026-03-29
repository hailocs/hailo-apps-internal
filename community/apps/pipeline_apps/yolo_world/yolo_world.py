import os
os.environ["GST_PLUGIN_FEATURE_RANK"] = "vaapidecodebin:NONE"

import cv2
import numpy as np

import gi
gi.require_version("Gst", "1.0")
from gi.repository import Gst

from community.apps.pipeline_apps.yolo_world.yolo_world_pipeline import (
    GStreamerYoloWorldApp,
)
from community.apps.pipeline_apps.yolo_world.yolo_world_inference import (
    YoloWorldInference,
)
from community.apps.pipeline_apps.yolo_world.text_embedding_manager import (
    TextEmbeddingManager,
)
from community.apps.pipeline_apps.yolo_world.postprocess import postprocess
from hailo_apps.python.core.common.buffer_utils import (
    get_caps_from_pad,
    get_numpy_from_buffer,
)
from hailo_apps.python.core.common.hailo_logger import get_logger
from hailo_apps.python.core.gstreamer.gstreamer_app import app_callback_class

logger = get_logger(__name__)

# Colors for drawing bounding boxes (BGR for OpenCV)
COLORS = [
    (255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0),
    (255, 0, 255), (0, 255, 255), (128, 0, 0), (0, 128, 0),
    (0, 0, 128), (128, 128, 0), (128, 0, 128), (0, 128, 128),
]


class YoloWorldCallbackData(app_callback_class):
    def __init__(self):
        super().__init__()
        self.inference_engine = None
        self.embedding_manager = None
        self.confidence_threshold = 0.3
        self._last_embeddings_id = None


def app_callback(element, buffer, user_data):
    if buffer is None:
        return

    pad = element.get_static_pad("src")
    fmt, width, height = get_caps_from_pad(pad)

    if fmt is None or width is None or height is None:
        return

    frame = get_numpy_from_buffer(buffer, fmt, width, height)
    if frame is None:
        return

    engine = user_data.inference_engine
    manager = user_data.embedding_manager

    # Check if embeddings have been updated
    current_embeddings = manager.get_embeddings()
    if current_embeddings is not user_data._last_embeddings_id:
        engine.update_text_embeddings(current_embeddings)
        user_data._last_embeddings_id = current_embeddings
        logger.info("Inference engine updated with new embeddings")

    # Run inference — frame should already be 640x640 from pipeline videoscale
    outputs = engine.run(frame)

    # Postprocess
    labels = manager.get_labels()
    num_classes = manager.get_num_classes()
    detections = postprocess(
        outputs,
        score_threshold=user_data.confidence_threshold,
        iou_threshold=0.7,
        num_classes=num_classes,
    )

    # Draw detections on frame
    if user_data.use_frame:
        for det in detections:
            x1, y1, x2, y2 = det["bbox"]
            cls_id = det["class_id"]
            score = det["score"]
            label = labels[cls_id] if cls_id < len(labels) else f"class_{cls_id}"
            color = COLORS[cls_id % len(COLORS)]

            # Convert normalized coords to pixels
            px1 = int(x1 * width)
            py1 = int(y1 * height)
            px2 = int(x2 * width)
            py2 = int(y2 * height)

            cv2.rectangle(frame, (px1, py1), (px2, py2), color, 2)
            text = f"{label}: {score:.2f}"
            cv2.putText(
                frame, text, (px1, max(15, py1 - 8)),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1,
            )

        # Show active classes at top
        active_text = f"Classes: {', '.join(labels[:5])}"
        if len(labels) > 5:
            active_text += f" +{len(labels) - 5} more"
        cv2.putText(
            frame, active_text, (10, 25),
            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1,
        )

        frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
        user_data.set_frame(frame)

    # Log periodically
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

    # Initialize text embedding manager
    user_data.embedding_manager = TextEmbeddingManager(
        prompts=opts.prompts,
        prompts_file=opts.prompts_file,
        embeddings_file=opts.embeddings_file,
        watch=opts.watch_prompts,
    )

    # Initialize inference engine
    user_data.inference_engine = YoloWorldInference(
        hef_path=app.hef_path,
        text_embeddings=user_data.embedding_manager.get_embeddings(),
    )
    user_data._last_embeddings_id = user_data.embedding_manager.get_embeddings()

    try:
        app.run()
    finally:
        user_data.inference_engine.close()
        user_data.embedding_manager.stop()


if __name__ == "__main__":
    main()
