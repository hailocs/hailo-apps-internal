import os
import gi

# Reason: Disable VAAPI hardware decoding to prevent black screen issues caused by
# incorrect 3D metadata (views=2) output from the driver for some video files.
# This forces the use of software decoders (like avdec_h264) which work correctly.
os.environ["GST_PLUGIN_FEATURE_RANK"] = "vaapidecodebin:NONE"

gi.require_version("Gst", "1.0")

import setproctitle

from hailo_apps.python.core.common.core import (
    get_pipeline_parser,
    get_resource_path,
    handle_list_models_flag,
    resolve_hef_paths,
)
from hailo_apps.python.core.common.hef_utils import get_hef_labels_json
from hailo_apps.python.core.common.defines import (
    LPR_APP_TITLE,
    LPR_CROPPERS_SO_FILENAME,
    LPR_OCRSINK_SO_FILENAME,
    LPR_PIPELINE,
    LPR_PLATE_MODEL_NAME,
    LPR_PLATE_POSTPROCESS_FUNCTION,
    LPR_VIDEO_NAME,
    LPR_YOLO_POSTPROCESS_SO_FILENAME,
    OCR_POSTPROCESS_SO_FILENAME,
    OCR_RECOGNITION_MODEL_NAME,
    LPR_OCR_POSTPROCESS_FUNCTION,
    RESOURCES_JSON_DIR_NAME,
    RESOURCES_SO_DIR_NAME,
    RESOURCES_VIDEOS_DIR_NAME,
)
from hailo_apps.python.core.common.hailo_logger import get_logger
from hailo_apps.python.core.gstreamer.gstreamer_app import (
    GStreamerApp,
    app_callback_class,
    dummy_callback,
)
from hailo_apps.python.core.gstreamer.gstreamer_helper_pipelines import (
    CROPPER_PIPELINE,
    DISPLAY_PIPELINE,
    INFERENCE_PIPELINE,
    INFERENCE_PIPELINE_WRAPPER,
    QUEUE,
    SOURCE_PIPELINE,
    TRACKER_PIPELINE,
    USER_CALLBACK_PIPELINE,
)
hailo_logger = get_logger(__name__)


class GStreamerLPRApp(GStreamerApp):
    """
    License Plate Recognition GStreamer application.

    Implements a 2-stage LPR pipeline: plate detection on full frame -> OCR on plate crops.
    """

    def __init__(self, app_callback, user_data, parser=None):
        if parser is None:
            parser = get_pipeline_parser()

        handle_list_models_flag(parser, LPR_PIPELINE)

        super().__init__(parser, user_data)

        self.video_width = 1920
        self.video_height = 1080

        self.app_callback = app_callback

        resolved_models = resolve_hef_paths(
            hef_paths=None,
            app_name=LPR_PIPELINE,
            arch=self.arch,
        )
        resolved_map = {model.name: model.path for model in resolved_models}

        # Plate detection model detects license plates directly on full frame
        self.plate_model_name = LPR_PLATE_MODEL_NAME
        self.ocr_model_name = OCR_RECOGNITION_MODEL_NAME

        self.plate_hef_path = resolved_map.get(self.plate_model_name)
        self.ocr_hef_path = resolved_map.get(self.ocr_model_name)

        if self.plate_hef_path is None or self.ocr_hef_path is None:
            hailo_logger.warning(
                "One or more default LPR models missing; falling back to resolved order from resources"
            )
            if len(resolved_models) >= 1 and self.plate_hef_path is None:
                self.plate_model_name = resolved_models[0].name
                self.plate_hef_path = resolved_models[0].path
            if len(resolved_models) >= 2 and self.ocr_hef_path is None:
                self.ocr_model_name = resolved_models[1].name
                self.ocr_hef_path = resolved_models[1].path

        if self.options_menu.input is None:
            self.video_source = get_resource_path(
                pipeline_name=LPR_PIPELINE,
                resource_type=RESOURCES_VIDEOS_DIR_NAME,
                model=LPR_VIDEO_NAME,
            )

        self.yolo_post_process_so = get_resource_path(
            pipeline_name=LPR_PIPELINE,
            resource_type=RESOURCES_SO_DIR_NAME,
            arch=self.arch,
            model=LPR_YOLO_POSTPROCESS_SO_FILENAME,
        )
        self.ocr_post_process_so = get_resource_path(
            pipeline_name=LPR_PIPELINE,
            resource_type=RESOURCES_SO_DIR_NAME,
            arch=self.arch,
            model=OCR_POSTPROCESS_SO_FILENAME,
        )
        self.croppers_so = get_resource_path(
            pipeline_name=LPR_PIPELINE,
            resource_type=RESOURCES_SO_DIR_NAME,
            arch=self.arch,
            model=LPR_CROPPERS_SO_FILENAME,
        )
        self.ocrsink_so = get_resource_path(
            pipeline_name=LPR_PIPELINE,
            resource_type=RESOURCES_SO_DIR_NAME,
            arch=self.arch,
            model=LPR_OCRSINK_SO_FILENAME,
        )

        self.plate_post_function_name = LPR_PLATE_POSTPROCESS_FUNCTION
        self.ocr_post_function_name = LPR_OCR_POSTPROCESS_FUNCTION

        self.plate_post_process_so = self.yolo_post_process_so

        self._build_pipeline()

    def _build_pipeline(self):
        """Build the LPR pipeline string."""
        self.thresholds_str = (
            "nms-score-threshold=0.3 "
            "nms-iou-threshold=0.45 "
            "output-format-type=HAILO_FORMAT_TYPE_FLOAT32"
        )

        # Plate detection model labels JSON
        self.plate_json = get_hef_labels_json(self.plate_hef_path)
        if self.plate_json is None:
            hailo_logger.warning(
                "Could not auto-detect labels JSON for plate model, falling back to model-specific JSON"
            )
            self.plate_json = get_resource_path(
                pipeline_name=LPR_PIPELINE,
                resource_type=RESOURCES_JSON_DIR_NAME,
                model=f"{self.plate_model_name}.json",
            )
        else:
            hailo_logger.info("Auto detected Plate Labels JSON: %s", self.plate_json)

        # OCR model uses its own JSON
        self.ocr_json = get_resource_path(
            pipeline_name=LPR_PIPELINE,
            resource_type=RESOURCES_JSON_DIR_NAME,
            model=f"{self.ocr_model_name}.json",
        )

        hailo_logger.info(
            "LPR resources | plate=%s (%s) | ocr=%s (%s)",
            self.plate_model_name,
            self.plate_hef_path,
            self.ocr_model_name,
            self.ocr_hef_path,
        )
        setproctitle.setproctitle(LPR_APP_TITLE)

        self.create_pipeline()

    def on_eos(self):
        """Handle end of stream: exit after first video pass instead of looping."""
        hailo_logger.info("LPR pipeline completed - shutting down")
        self.shutdown()

    def get_pipeline_string(self):
        """
        Build and return the full LPR pipeline string.

        Pipeline stages:
        1. Source: video input
        2. Plate detection: detect license plates on full frame (YOLOv8n)
        3. Tracker: track license plates across frames
        4. LP cropper: crop license plate regions and run OCR
        5. OCR sink: process and deduplicate OCR results
        6. Display: render output with overlays

        Returns:
            str: GStreamer pipeline string
        """
        source_pipeline = SOURCE_PIPELINE(
            video_source=self.video_source,
            video_width=self.video_width,
            video_height=self.video_height,
            frame_rate=self.frame_rate,
            sync=self.sync,
        )

        # Stage 1: Detect license plates directly on full frame
        plate_detection = INFERENCE_PIPELINE(
            hef_path=self.plate_hef_path,
            post_process_so=self.plate_post_process_so,
            post_function_name=self.plate_post_function_name,
            config_json=self.plate_json,
            additional_params=self.thresholds_str,
            batch_size=2,
            scheduler_timeout_ms=66,
            name="plate_detection",
        )
        plate_detection_wrapper = INFERENCE_PIPELINE_WRAPPER(plate_detection)

        # Track license plates across frames
        tracker_pipeline = TRACKER_PIPELINE(
            class_id=-1,
            kalman_dist_thr=0.7,
            iou_thr=0.8,
            init_iou_thr=0.9,
            keep_new_frames=2,
            keep_tracked_frames=6,
            keep_lost_frames=2,
            keep_past_metadata=True,
            name="hailo_tracker",
        )

        # Stage 2: Crop license plates and run OCR
        ocr_recognition = INFERENCE_PIPELINE(
            hef_path=self.ocr_hef_path,
            post_process_so=self.ocr_post_process_so,
            post_function_name=self.ocr_post_function_name,
            config_json=self.ocr_json,
            batch_size=8,
            scheduler_timeout_ms=33,
            name="ocr_recognition",
        )

        lp_cropper = CROPPER_PIPELINE(
            inner_pipeline=ocr_recognition,
            so_path=self.croppers_so,
            function_name="license_plate_cropper",
            internal_offset=True,
            name="lp_cropper",
        )

        ocrsink_pipeline = (
            f"{QUEUE(name='lpr_ocrsink_q')} ! "
            f"hailofilter use-gst-buffer=true so-path={self.ocrsink_so} qos=false "
        )
        user_callback_pipeline = USER_CALLBACK_PIPELINE()

        display_pipeline = DISPLAY_PIPELINE(
            video_sink=self.video_sink,
            sync=self.sync,
            show_fps=self.show_fps,
        )

        pipeline_string = (
            f"{source_pipeline} ! "
            f"{plate_detection_wrapper} ! "
            f"{tracker_pipeline} ! "
            f"{lp_cropper} ! "
            f"{ocrsink_pipeline} ! "
            f"{user_callback_pipeline} ! "
            f"{display_pipeline}"
        )
        hailo_logger.debug(f"Pipeline string:\n gst-launch-1.0 {pipeline_string}")
        return pipeline_string

    # ===================================================================


def main():
    user_data = app_callback_class()
    app = GStreamerLPRApp(dummy_callback, user_data)
    app.run()


if __name__ == "__main__":
    main()
