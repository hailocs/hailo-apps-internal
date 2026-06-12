# region imports
# Standard library imports
from pathlib import Path

import setproctitle

from hailo_apps.python.core.common.core import (
    get_pipeline_parser,
    get_resource_path,
    handle_list_models_flag,
    resolve_hef_path,
)
from hailo_apps.python.core.common.defines import (
    DETECTION_PIPELINE,
    DETECTION_POSTPROCESS_FUNCTION,
    DETECTION_POSTPROCESS_SO_FILENAME,
    RESOURCES_SO_DIR_NAME,
)
from hailo_apps.python.core.common.hef_utils import get_hef_labels_json

from hailo_apps.python.core.common.hailo_logger import get_logger
from hailo_apps.python.core.gstreamer.gstreamer_app import (
    GStreamerApp,
    app_callback_class,
    dummy_callback,
)
from hailo_apps.python.core.gstreamer.gstreamer_helper_pipelines import (
    DISPLAY_PIPELINE,
    INFERENCE_PIPELINE,
    INFERENCE_PIPELINE_WRAPPER,
    SOURCE_PIPELINE,
    TRACKER_PIPELINE,
    USER_CALLBACK_PIPELINE,
)

hailo_logger = get_logger(__name__)

# endregion imports

# -----------------------------------------------------------------------------------------------
# Line Crossing Counter GStreamer Application
# -----------------------------------------------------------------------------------------------

APP_TITLE = "hailo-line-crossing-counter"


class GStreamerLineCrossingCounterApp(GStreamerApp):
    def __init__(self, app_callback, user_data, parser=None):
        if parser is None:
            parser = get_pipeline_parser()
        parser.add_argument(
            "--labels-json",
            default=None,
            help="Path to custom labels JSON file",
        )
        parser.add_argument(
            "--line-x",
            type=float,
            default=0.5,
            help="X-position of the virtual counting line in normalized coordinates [0.0-1.0]. Default: 0.5 (middle of frame). 0.0 = left edge, 1.0 = right edge.",
        )
        parser.add_argument(
            "--zone-width",
            type=float,
            default=0.1,
            help="Width of the counting zone centered on the line, in normalized coordinates [0.0-1.0]. Default: 0.1 (10%% of frame width). A person must enter this zone from one side and exit from the other to be counted.",
        )

        # Handle --list-models flag before full initialization
        handle_list_models_flag(parser, DETECTION_PIPELINE)

        # Default --use-frame to True for this app: the line crossing overlay
        # (zone, bboxes, center points, counts) is rendered via OpenCV in the
        # callback, so the user-frame window is the primary display. The GStreamer
        # video sink is set to fakesink to save compute.
        parser.set_defaults(use_frame=True)

        hailo_logger.info("Initializing GStreamer Line Crossing Counter App...")

        super().__init__(parser, user_data)

        # Use fakesink for the GStreamer display pipeline — all visualization
        # is done in the user-frame OpenCV window via the callback.
        self.video_sink = "fakesink"

        hailo_logger.debug(
            "Parent GStreamerApp initialized | arch=%s | input=%s | fps=%s | sync=%s | show_fps=%s",
            self.arch,
            self.video_source,
            self.frame_rate,
            self.sync,
            self.show_fps,
        )

        # Override batch_size if not set via parser (default is 2 for detection)
        if self.batch_size == 1:
            self.batch_size = 2
        nms_score_threshold = 0.3
        nms_iou_threshold = 0.45

        # Resolve HEF path with smart lookup and auto-download
        self.hef_path = resolve_hef_path(
            self.hef_path,
            app_name=DETECTION_PIPELINE,
            arch=self.arch,
        )

        # Set the post-processing shared object file
        self.post_process_so = get_resource_path(
            DETECTION_PIPELINE, RESOURCES_SO_DIR_NAME, self.arch, DETECTION_POSTPROCESS_SO_FILENAME
        )

        self.post_function_name = DETECTION_POSTPROCESS_FUNCTION

        # User-defined label JSON file
        self.labels_json = self.options_menu.labels_json
        if self.labels_json is None:
            self.labels_json = get_hef_labels_json(self.hef_path)
            if self.labels_json is not None:
                hailo_logger.info("Auto detected Labels JSON: %s", self.labels_json)

        hailo_logger.info(
            "Resources | hef=%s | post_so=%s | post_fn=%s | labels_json=%s",
            self.hef_path,
            self.post_process_so,
            self.post_function_name,
            self.labels_json,
        )

        # Validate resource paths
        if self.hef_path is None or not Path(self.hef_path).exists():
            hailo_logger.error("HEF path is invalid or missing: %s", self.hef_path)
        if self.post_process_so is None or not Path(self.post_process_so).exists():
            hailo_logger.error(
                "Post-process .so path is invalid or missing: %s", self.post_process_so
            )

        self.app_callback = app_callback

        self.thresholds_str = (
            f"nms-score-threshold={nms_score_threshold} "
            f"nms-iou-threshold={nms_iou_threshold} "
            f"output-format-type=HAILO_FORMAT_TYPE_FLOAT32"
        )
        hailo_logger.debug("Postprocess thresholds: %s", self.thresholds_str)

        # Store the line-x position for the callback to access
        self.line_x = self.options_menu.line_x

        # Set the process title
        setproctitle.setproctitle(APP_TITLE)
        hailo_logger.debug("Process title set to %s", APP_TITLE)

        self.create_pipeline()
        hailo_logger.debug("Pipeline created")

    def get_pipeline_string(self):
        source_pipeline = SOURCE_PIPELINE(
            video_source=self.video_source,
            video_width=self.video_width,
            video_height=self.video_height,
            frame_rate=self.frame_rate,
            sync=self.sync,
        )
        detection_pipeline = INFERENCE_PIPELINE(
            hef_path=self.hef_path,
            post_process_so=self.post_process_so,
            post_function_name=self.post_function_name,
            batch_size=self.batch_size,
            config_json=self.labels_json,
            additional_params=self.thresholds_str,
        )
        detection_pipeline_wrapper = INFERENCE_PIPELINE_WRAPPER(detection_pipeline)
        tracker_pipeline = TRACKER_PIPELINE(class_id=1)
        user_callback_pipeline = USER_CALLBACK_PIPELINE()
        display_pipeline = DISPLAY_PIPELINE(
            video_sink=self.video_sink, sync=self.sync, show_fps=self.show_fps
        )

        pipeline_string = (
            f"{source_pipeline} ! "
            f"{detection_pipeline_wrapper} ! "
            f"{tracker_pipeline} ! "
            f"{user_callback_pipeline} ! "
            f"{display_pipeline}"
        )
        hailo_logger.debug("Pipeline string: %s", pipeline_string)
        return pipeline_string


def main():
    hailo_logger.info("Starting Hailo Line Crossing Counter App...")
    user_data = app_callback_class()
    app_callback = dummy_callback
    app = GStreamerLineCrossingCounterApp(app_callback, user_data)
    app.run()


if __name__ == "__main__":
    main()
