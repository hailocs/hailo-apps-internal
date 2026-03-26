# region imports
import os

os.environ["GST_PLUGIN_FEATURE_RANK"] = "vaapidecodebin:NONE"

import gi

gi.require_version("Gst", "1.0")

import cv2
import hailo
from gi.repository import Gst

from community.apps.pipeline_apps.hotdog_not_hotdog.hotdog_not_hotdog_pipeline import (
    GStreamerHotdogApp,
)
from hailo_apps.python.core.common.buffer_utils import (
    get_caps_from_pad,
    get_numpy_from_buffer,
)
from hailo_apps.python.core.common.hailo_logger import get_logger
from hailo_apps.python.core.gstreamer.gstreamer_app import app_callback_class

hailo_logger = get_logger(__name__)
# endregion imports


class HotdogCallbackData(app_callback_class):
    """Callback state for the hotdog/not-hotdog classifier."""

    def __init__(self):
        super().__init__()
        self.last_label = "?"
        self.last_confidence = 0.0
        self.last_clip_class = "?"


def app_callback(element, buffer, user_data):
    """Read CLIP classification and draw the verdict on the frame."""
    if buffer is None:
        return

    # Extract classification from ROI metadata.
    # The winning CLIP class determines the verdict:
    # "hotdog" → HOTDOG!, anything else (food/person/animal/object/room) → NOT HOTDOG!
    roi = hailo.get_roi_from_buffer(buffer)
    classifications = roi.get_objects_typed(hailo.HAILO_CLASSIFICATION)
    if classifications:
        best = classifications[0]
        clip_label = best.get_label()
        clip_confidence = best.get_confidence()
        if clip_label == "hotdog":
            user_data.last_label = "hotdog"
            user_data.last_confidence = clip_confidence
        else:
            user_data.last_label = "not hotdog"
            user_data.last_confidence = clip_confidence
        user_data.last_clip_class = clip_label

    # Draw overlay when --use-frame is active
    if user_data.use_frame:
        pad = element.get_static_pad("src")
        fmt, width, height = get_caps_from_pad(pad)
        if fmt and width and height:
            frame = get_numpy_from_buffer(buffer, fmt, width, height)
            frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
            _draw_verdict(frame, user_data.last_label, user_data.last_confidence)
            user_data.set_frame(frame)

    # Periodic console output (every 30 frames)
    if user_data.get_count() % 30 == 0:
        verdict = user_data.last_label.upper()
        clip_class = user_data.last_clip_class
        conf = user_data.last_confidence
        print(f"Frame {user_data.get_count()} | {verdict} (clip_class={clip_class}, {conf:.0%})")


def _draw_verdict(frame, label, confidence):
    """Draw a big bold verdict on the frame."""
    h, w = frame.shape[:2]
    is_hotdog = label.lower() == "hotdog"

    # Choose color and text
    color = (0, 200, 0) if is_hotdog else (0, 0, 220)  # Green or Red (BGR)
    text = "HOTDOG!" if is_hotdog else "NOT HOTDOG!"
    conf_text = f"{confidence:.0%}"

    # Semi-transparent banner at bottom
    banner_h = int(h * 0.18)
    overlay = frame.copy()
    cv2.rectangle(overlay, (0, h - banner_h), (w, h), color, -1)
    cv2.addWeighted(overlay, 0.6, frame, 0.4, 0, frame)

    # Main verdict text — centered
    font = cv2.FONT_HERSHEY_DUPLEX
    scale = min(w, h) / 300.0  # Scale text to frame size
    thickness = max(2, int(scale * 2))
    text_size = cv2.getTextSize(text, font, scale, thickness)[0]
    text_x = (w - text_size[0]) // 2
    text_y = h - banner_h // 2 + text_size[1] // 4
    # Shadow
    cv2.putText(frame, text, (text_x + 2, text_y + 2), font, scale, (0, 0, 0), thickness + 2)
    # Foreground
    cv2.putText(frame, text, (text_x, text_y), font, scale, (255, 255, 255), thickness)

    # Confidence below main text
    conf_scale = scale * 0.5
    conf_size = cv2.getTextSize(conf_text, font, conf_scale, thickness)[0]
    conf_x = (w - conf_size[0]) // 2
    conf_y = text_y + int(text_size[1] * 0.9)
    cv2.putText(frame, conf_text, (conf_x, conf_y), font, conf_scale, (255, 255, 255), max(1, thickness - 1))


def main():
    user_data = HotdogCallbackData()
    app = GStreamerHotdogApp(app_callback, user_data)
    app.run()


if __name__ == "__main__":
    main()
