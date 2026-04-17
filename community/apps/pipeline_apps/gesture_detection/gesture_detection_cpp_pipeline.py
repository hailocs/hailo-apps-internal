"""
Full C++ GStreamer gesture detection pipeline using Hailo-8.

All pre/post processing runs in C++ shared libraries via hailofilter,
inference runs on the Hailo-8 NPU via hailonet (persistent streaming mode).

Architecture:
  source → [palm detection inference + postprocess] →
           [hailocropper(palm_croppers) →
               inner: videoscale(224x224) → affine_warp → hailonet(hand_landmark) → postprocess
           → hailoaggregator] →
           hailofilter(gesture_classification) → hailooverlay → display

Key design: The inner pipeline forces the crop to 224x224 BEFORE the affine warp.
This ensures the warp and model operate in the same square pixel space, so the
inverse rotation in normalized [0,1] coords is a simple rotation around (0.5, 0.5).

Usage:
    python -m community.apps.pipeline_apps.gesture_detection.gesture_detection_cpp_pipeline
    python -m community.apps.pipeline_apps.gesture_detection.gesture_detection_cpp_pipeline --input /dev/video0
"""

import os

os.environ["GST_PLUGIN_FEATURE_RANK"] = "vaapidecodebin:NONE"

import setproctitle

from hailo_apps.python.core.common.core import get_pipeline_parser
from hailo_apps.python.core.common.defines import SHARED_VDEVICE_GROUP_ID
from hailo_apps.python.core.common.hailo_logger import get_logger
from hailo_apps.python.core.gstreamer.gstreamer_app import GStreamerApp, app_callback_class
from hailo_apps.python.core.gstreamer.gstreamer_helper_pipelines import (
    QUEUE,
    SOURCE_PIPELINE,
    INFERENCE_PIPELINE,
    INFERENCE_PIPELINE_WRAPPER,
    USER_CALLBACK_PIPELINE,
    DISPLAY_PIPELINE,
)

hailo_logger = get_logger(__name__)

from .download_models import ensure_models

# Resolve .so paths: prefer local build, fall back to system install
_APP_DIR = os.path.dirname(os.path.abspath(__file__))
_LOCAL_SO_DIR = os.path.join(_APP_DIR, "postprocess", "build")
_SYSTEM_SO_DIR = "/usr/local/hailo/resources/so"


def _find_so(name):
    """Find a postprocess .so: local build first, then system install."""
    local = os.path.join(_LOCAL_SO_DIR, name)
    if os.path.isfile(local):
        return local
    system = os.path.join(_SYSTEM_SO_DIR, name)
    if os.path.isfile(system):
        return system
    raise FileNotFoundError(
        f"{name} not found. Run postprocess/build.sh or install to {_SYSTEM_SO_DIR}"
    )


PALM_DETECTION_POST_SO = _find_so("libpalm_detection_postprocess.so")
PALM_CROPPERS_SO = _find_so("libpalm_croppers.so")
HAND_AFFINE_WARP_SO = _find_so("libhand_affine_warp.so")
HAND_LANDMARK_POST_SO = _find_so("libhand_landmark_postprocess.so")
GESTURE_CLASSIFICATION_SO = _find_so("libgesture_classification.so")


class GestureCallbackData(app_callback_class):
    """Minimal callback data — all processing is in C++."""
    def __init__(self):
        super().__init__()


def app_callback(element, buffer, user_data):
    """Optional user callback — metadata is already attached by C++ filters."""
    return


class GStreamerGestureCppApp(GStreamerApp):
    """Full C++ GStreamer pipeline for gesture detection."""

    def __init__(self, app_callback, user_data, parser=None):
        if parser is None:
            parser = get_pipeline_parser()

        parser.add_argument(
            "--palm-hef", default=None,
            help="Path to palm detection HEF model (auto-resolved per arch if omitted)",
        )
        parser.add_argument(
            "--hand-hef", default=None,
            help="Path to hand landmark HEF model (auto-resolved per arch if omitted)",
        )

        hailo_logger.info("Initializing C++ Gesture Detection Pipeline...")
        super().__init__(parser, user_data)
        setproctitle.setproctitle("gesture_detection_cpp")

        # Resolve arch-specific model paths
        models_dir = ensure_models(self.arch)
        self.palm_hef = self.options_menu.palm_hef or os.path.join(
            models_dir, "palm_detection_lite.hef")
        self.hand_hef = self.options_menu.hand_hef or os.path.join(
            models_dir, "hand_landmark_lite.hef")

        self.app_callback = app_callback
        self.create_pipeline()
        hailo_logger.info("C++ pipeline created successfully.")

    def get_pipeline_string(self):
        # 1. Video source
        source_pipeline = SOURCE_PIPELINE(
            video_source=self.video_source,
            video_width=self.video_width,
            video_height=self.video_height,
            frame_rate=self.frame_rate,
            sync=self.sync,
        )

        # 2. Palm detection (wrapped to preserve original resolution)
        palm_detection_pipeline = INFERENCE_PIPELINE(
            hef_path=self.palm_hef,
            post_process_so=PALM_DETECTION_POST_SO,
            batch_size=1,
            name="palm_detection",
            letterbox=True,
        )
        palm_detection_wrapper = INFERENCE_PIPELINE_WRAPPER(
            palm_detection_pipeline,
            name="palm_wrapper",
        )

        # 3. Inner pipeline for the cropper: force 224x224 → affine warp → hailonet → postprocess
        # Key: videoscale to 224x224 BEFORE the warp ensures warp and model share
        # the same square pixel space. The inverse rotation is then a simple rotation
        # around (0.5, 0.5) in normalized coords with no aspect ratio issues.
        inner_pipeline = (
            f"{QUEUE(name='hand_scale_q')} ! "
            f"videoscale name=hand_videoscale n-threads=2 qos=false ! "
            f"video/x-raw, width=224, height=224, pixel-aspect-ratio=1/1 ! "
            f"videoconvert name=hand_videoconvert n-threads=2 ! "
            f"hailofilter so-path={HAND_AFFINE_WARP_SO} "
            f"name=hand_affine_warp use-gst-buffer=true qos=false ! "
            f"{QUEUE(name='hand_hailonet_q')} ! "
            f"hailonet name=hand_landmark_hailonet "
            f"hef-path={self.hand_hef} "
            f"batch-size=1 "
            f"vdevice-group-id={SHARED_VDEVICE_GROUP_ID} "
            f"force-writable=true ! "
            f"{QUEUE(name='hand_postproc_q')} ! "
            f"hailofilter name=hand_landmark_postproc "
            f"so-path={HAND_LANDMARK_POST_SO} qos=false ! "
            f"{QUEUE(name='hand_output_q')} "
        )

        # 4. Cropper: palm_croppers creates rotated envelope crop, sends to inner pipeline
        # use_letterbox=False: crop is stretched (no padding). Since we force 224x224
        # in the inner pipeline, the crop content fills the full 224x224 square.
        # no_scaling_bbox=True (default): no coordinate transform recorded on the ROI.
        palm_cropper_pipeline = (
            f"{QUEUE(name='palm_cropper_input_q')} ! "
            f"hailocropper name=palm_cropper "
            f"so-path={PALM_CROPPERS_SO} "
            f"function-name=palm_to_hand_crop "
            f"use-letterbox=false "
            f"no-scaling-bbox=true "
            f"internal-offset=true "
            f"hailoaggregator name=palm_agg "
            f"palm_cropper. ! "
            f"{QUEUE(name='palm_bypass_q', max_size_buffers=20)} ! palm_agg.sink_0 "
            f"palm_cropper. ! {inner_pipeline} ! palm_agg.sink_1 "
            f"palm_agg. ! {QUEUE(name='palm_cropper_output_q')} "
        )

        # 5. Gesture classification (also removes palm detections and palm_angle)
        gesture_filter = (
            f"{QUEUE(name='gesture_filter_q')} ! "
            f"hailofilter so-path={GESTURE_CLASSIFICATION_SO} "
            f"name=gesture_classification qos=false "
        )

        # 6. User callback + display
        user_callback = USER_CALLBACK_PIPELINE()
        display_pipeline = DISPLAY_PIPELINE(
            video_sink=self.video_sink,
            sync=self.sync,
            show_fps=self.show_fps,
        )

        pipeline_string = (
            f"{source_pipeline} ! "
            f"{palm_detection_wrapper} ! "
            f"{palm_cropper_pipeline} ! "
            f"{gesture_filter} ! "
            f"{user_callback} ! "
            f"{display_pipeline}"
        )

        hailo_logger.debug("Pipeline string: %s", pipeline_string)
        return pipeline_string


def main():
    hailo_logger.info("Starting C++ Gesture Detection Pipeline.")
    user_data = GestureCallbackData()
    app = GStreamerGestureCppApp(app_callback, user_data)
    app.run()


if __name__ == "__main__":
    main()
