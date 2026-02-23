# region imports
import os
from pathlib import Path

import setproctitle

from hailo_apps.python.core.common.core import (
    configure_multi_model_hef_path,
    get_pipeline_parser,
    get_resource_path,
    handle_list_models_flag,
    resolve_hef_paths,
)
from hailo_apps.python.core.common.defines import (
    ALL_DETECTIONS_CROPPER_POSTPROCESS_SO_FILENAME,
    BASIC_PIPELINES_VIDEO_EXAMPLE_NAME,
    DEFAULT_LOCAL_RESOURCES_PATH,
    LPR_VIDEO_NAME,
    RESOURCES_SO_DIR_NAME,
    RESOURCES_VIDEOS_DIR_NAME,
    TAPPAS_POSTPROC_PATH_KEY,
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
    SOURCE_PIPELINE,
    TRACKER_PIPELINE,
    USER_CALLBACK_PIPELINE,
)

hailo_logger = get_logger(__name__)

# endregion imports

# App constants
LPR_APP_TITLE = "Hailo LPR App"
LPR_PIPELINE = "lpr"

# Vehicle detection postprocess (from repo resources/so/)
VEHICLE_DETECTION_POSTPROCESS_SO = "libyolo_hailortpp_postprocess.so"
VEHICLE_DETECTION_POSTPROCESS_FUNC = "yolov5m_vehicles"

# License plate detection postprocess (from TAPPAS)
LP_DETECTION_POSTPROCESS_SO = "libyolo_post.so"
LP_DETECTION_POSTPROCESS_FUNC = "tiny_yolov4_license_plates"

# LP detection config JSON
LP_DETECTION_CONFIG_JSON = "yolov4_license_plate.json"

# Cropper functions
VEHICLE_CROPPER_FUNC = "all_detections"  # repo: 1 vehicle/frame, fair rotation


class GStreamerLPRApp(GStreamerApp):
    def __init__(self, app_callback, user_data, parser=None):
        if parser is None:
            parser = get_pipeline_parser()

        configure_multi_model_hef_path(parser)
        handle_list_models_flag(parser, LPR_PIPELINE)

        super().__init__(parser, user_data)
        setproctitle.setproctitle(LPR_APP_TITLE)

        if BASIC_PIPELINES_VIDEO_EXAMPLE_NAME in self.video_source:
            self.video_source = get_resource_path(
                pipeline_name=None, resource_type=RESOURCES_VIDEOS_DIR_NAME,
                arch=self.arch, model=LPR_VIDEO_NAME,
            )

        self.batch_size = 2
        nms_score_threshold = 0.3
        nms_iou_threshold = 0.45

        # Resolve HEF paths: vehicle detection, LP detection, OCR
        models = resolve_hef_paths(
            hef_paths=self.options_menu.hef_path,
            app_name=LPR_PIPELINE,
            arch=self.arch,
        )
        self.vehicle_detection_hef = models[0].path
        self.lp_detection_hef = models[1].path

        # Resolve postprocess .so paths
        self.vehicle_detection_post_so = get_resource_path(
            pipeline_name=None, resource_type=RESOURCES_SO_DIR_NAME,
            arch=self.arch, model=VEHICLE_DETECTION_POSTPROCESS_SO,
        )
        tappas_post_dir = os.environ.get(TAPPAS_POSTPROC_PATH_KEY, "")
        self.lp_detection_post_so = os.path.join(tappas_post_dir, LP_DETECTION_POSTPROCESS_SO)

        # Cropper .so paths
        self.vehicle_cropper_so = get_resource_path(
            pipeline_name=None, resource_type=RESOURCES_SO_DIR_NAME,
            arch=self.arch, model=ALL_DETECTIONS_CROPPER_POSTPROCESS_SO_FILENAME,
        )
        # LP detection config JSON
        self.lp_detection_config_json = Path(DEFAULT_LOCAL_RESOURCES_PATH) / LP_DETECTION_CONFIG_JSON

        self.app_callback = app_callback

        self.thresholds_str = (
            f"nms-score-threshold={nms_score_threshold} "
            f"nms-iou-threshold={nms_iou_threshold} "
            f"output-format-type=HAILO_FORMAT_TYPE_FLOAT32"
        )

        self.create_pipeline()

    def get_pipeline_string(self):
        source_pipeline = SOURCE_PIPELINE(
            video_source=self.video_source,
            video_width=self.video_width,
            video_height=self.video_height,
            frame_rate=self.frame_rate,
            sync=self.sync,
        )

        # Stage 1: Vehicle detection (full-frame)
        vehicle_detection_pipeline = INFERENCE_PIPELINE(
            hef_path=self.vehicle_detection_hef,
            post_process_so=self.vehicle_detection_post_so,
            post_function_name=VEHICLE_DETECTION_POSTPROCESS_FUNC,
            batch_size=self.batch_size,
            additional_params=self.thresholds_str,
            name="vehicle_detection",
        )
        vehicle_detection_wrapper = INFERENCE_PIPELINE_WRAPPER(
            vehicle_detection_pipeline, name="vehicle_detection_wrapper"
        )

        # Tracker for vehicles
        tracker_pipeline = TRACKER_PIPELINE(
            class_id=-1,
            kalman_dist_thr=0.5,
            iou_thr=0.6,
            keep_tracked_frames=2,
            keep_lost_frames=2,
            keep_past_metadata=True,
            name="hailo_tracker",
        )

        # Stage 2: Crop vehicles → LP detection
        lp_detection_pipeline = INFERENCE_PIPELINE(
            hef_path=self.lp_detection_hef,
            post_process_so=self.lp_detection_post_so,
            post_function_name=LP_DETECTION_POSTPROCESS_FUNC,
            batch_size=self.batch_size,
            config_json=self.lp_detection_config_json,
            name="lp_detection",
        )
        vehicle_cropper = CROPPER_PIPELINE(
            inner_pipeline=lp_detection_pipeline,
            so_path=self.vehicle_cropper_so,
            function_name=VEHICLE_CROPPER_FUNC,
            internal_offset=True,
            name="vehicle_cropper",
        )

        # OCR (LPRNet) runs in Python callback via HailoRT API, not in the pipeline
        user_callback_pipeline = USER_CALLBACK_PIPELINE()

        # Display with overlay — bounding boxes drawn on video
        display_pipeline = DISPLAY_PIPELINE(
            video_sink=self.video_sink,
            sync=self.sync,
            show_fps=self.show_fps,
        )

        pipeline_string = (
            f"{source_pipeline} ! "
            f"{vehicle_detection_wrapper} ! "
            f"{tracker_pipeline} ! "
            f"{vehicle_cropper} ! "
            f"{user_callback_pipeline} ! "
            f"{display_pipeline}"
        )
        return pipeline_string


def main():
    hailo_logger.info("Starting Hailo LPR App...")
    user_data = app_callback_class()
    app = GStreamerLPRApp(dummy_callback, user_data)
    app.run()


if __name__ == "__main__":
    main()
