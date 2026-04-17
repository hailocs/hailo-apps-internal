"""
GStreamer pipeline for gesture-controlled mouse.

Uses the full C++ gesture detection pipeline (palm detection + hand landmark +
gesture classification) with a user callback that maps hand position to mouse
cursor movement and gestures to mouse actions.

Architecture:
  source -> palm detection (hailonet + postprocess) ->
         -> hailocropper(palm_croppers) ->
               inner: videoscale(224x224) -> affine_warp -> hailonet(hand_landmark) -> postprocess
         -> hailoaggregator ->
         -> gesture_classification -> user_callback (mouse control) -> display
"""

import os

os.environ["GST_PLUGIN_FEATURE_RANK"] = "vaapidecodebin:NONE"

import setproctitle

from hailo_apps.python.core.common.core import get_pipeline_parser
from hailo_apps.python.core.common.defines import SHARED_VDEVICE_GROUP_ID
from hailo_apps.python.core.common.hailo_logger import get_logger
from hailo_apps.python.core.gstreamer.gstreamer_app import GStreamerApp
from hailo_apps.python.core.gstreamer.gstreamer_helper_pipelines import (
    QUEUE,
    SOURCE_PIPELINE,
    INFERENCE_PIPELINE,
    INFERENCE_PIPELINE_WRAPPER,
    USER_CALLBACK_PIPELINE,
    DISPLAY_PIPELINE,
)

hailo_logger = get_logger(__name__)

# Reuse the community gesture_detection download/model infrastructure
from community.apps.pipeline_apps.gesture_detection.download_models import ensure_models

# Post-process shared libraries
SO_DIR = "/usr/local/hailo/resources/so"
PALM_DETECTION_POST_SO = os.path.join(SO_DIR, "libpalm_detection_postprocess.so")
PALM_CROPPERS_SO = os.path.join(SO_DIR, "libpalm_croppers.so")
HAND_AFFINE_WARP_SO = os.path.join(SO_DIR, "libhand_affine_warp.so")
HAND_LANDMARK_POST_SO = os.path.join(SO_DIR, "libhand_landmark_postprocess.so")
GESTURE_CLASSIFICATION_SO = os.path.join(SO_DIR, "libgesture_classification.so")


class GStreamerGestureMouseApp(GStreamerApp):
    """Full C++ gesture detection pipeline with mouse control callback."""

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
        parser.add_argument(
            "--smoothing", type=float, default=0.4,
            help="Cursor smoothing factor (0=no smoothing, 1=max smoothing)",
        )
        parser.add_argument(
            "--pinch-threshold", type=float, default=0.06,
            help="Pinch distance threshold for click (normalized, 0-1)",
        )
        parser.add_argument(
            "--speed", type=float, default=1.5,
            help="Cursor speed multiplier",
        )
        parser.add_argument(
            "--no-click", action="store_true",
            help="Disable click actions (cursor movement only)",
        )

        hailo_logger.info("Initializing Gesture Mouse Pipeline...")
        super().__init__(parser, user_data)
        setproctitle.setproctitle("gesture_mouse")

        # Resolve arch-specific gesture model paths
        models_dir = ensure_models(self.arch)
        self.palm_hef = self.options_menu.palm_hef or os.path.join(
            models_dir, "palm_detection_lite.hef")
        self.hand_hef = self.options_menu.hand_hef or os.path.join(
            models_dir, "hand_landmark_lite.hef")

        self.app_callback = app_callback
        self.create_pipeline()
        hailo_logger.info("Gesture mouse pipeline created.")

    def get_pipeline_string(self):
        source_pipeline = SOURCE_PIPELINE(
            video_source=self.video_source,
            video_width=self.video_width,
            video_height=self.video_height,
            frame_rate=self.frame_rate,
            sync=self.sync,
        )

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

        gesture_filter = (
            f"{QUEUE(name='gesture_filter_q')} ! "
            f"hailofilter so-path={GESTURE_CLASSIFICATION_SO} "
            f"name=gesture_classification qos=false "
        )

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
