import gi

gi.require_version("Gst", "1.0")
from gi.repository import Gst

import hailo
try:
    from hailo import HailoTracker
except Exception:  # pragma: no cover
    HailoTracker = None

import setproctitle

from hailo_apps.python.core.common.core import (
    get_pipeline_parser,
    get_resource_path,
    handle_list_models_flag,
    resolve_hef_paths,
)
from hailo_apps.python.core.common.defines import (
    LPR_APP_TITLE,
    LPR_CROPPERS_SO_FILENAME,
    LPR_LP_CROPPER_FUNCTION,
    LPR_LP_FULLFRAME_CROPPER_FUNCTION,
    LPR_LP_CROPSINK_SO_FILENAME,
    LPR_OCRSINK_SO_FILENAME,
    LPR_OVERLAY_SO_FILENAME,
    LPR_PIPELINE,
    LPR_PLATE_MODEL_NAME,
    LPR_PLATE_POSTPROCESS_FUNCTION,
    LPR_VEHICLE_CROPPER_FUNCTION,
    LPR_VEHICLE_MODEL_NAME,
    LPR_VEHICLE_POSTPROCESS_FUNCTION,
    LPR_VIDEO_NAME,
    LPR_YOLO_POSTPROCESS_SO_FILENAME,
    LPR_LP_NO_QUALITY_CROPPER_FUNCTION,
    OCR_POSTPROCESS_SO_FILENAME,
    OCR_RECOGNITION_MODEL_NAME,
    OCR_RECOGNITION_POSTPROCESS_FUNCTION,
    RESOURCES_JSON_DIR_NAME,
    RESOURCES_MODELS_DIR_NAME,
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
    def __init__(self, app_callback, user_data, parser=None):
        if parser is None:
            parser = get_pipeline_parser()

        parser.add_argument(
            "--pipeline",
            default="vlpoc",
            choices=[
                "vlp",
                "vlpoc",
                "vlpoc_ocrsink",
                "v",
                "lp",
            ],
            help="Pipeline variant",
        )
        parser.add_argument(
            "--print-pipeline",
            action="store_true",
            help="Print the selected pipeline string and exit without running",
        )

        handle_list_models_flag(parser, LPR_PIPELINE)

        super().__init__(parser, user_data)

        self.pipeline_type = self.options_menu.pipeline
        self.app_callback = app_callback

        resolved_models = resolve_hef_paths(
            hef_paths=None,
            app_name=LPR_PIPELINE,
            arch=self.arch,
        )
        resolved_map = {model.name: model.path for model in resolved_models}

        self.vehicle_model_name = LPR_VEHICLE_MODEL_NAME
        self.plate_model_name = LPR_PLATE_MODEL_NAME
        self.ocr_model_name = OCR_RECOGNITION_MODEL_NAME

        self.vehicle_hef_path = resolved_map.get(self.vehicle_model_name)
        self.plate_hef_path = resolved_map.get(self.plate_model_name)
        self.ocr_hef_path = resolved_map.get(self.ocr_model_name)

        if self.vehicle_hef_path is None or self.plate_hef_path is None or self.ocr_hef_path is None:
            hailo_logger.warning(
                "One or more default LPR models missing; falling back to resolved order from resources"
            )
            if len(resolved_models) >= 1 and self.vehicle_hef_path is None:
                self.vehicle_model_name = resolved_models[0].name
                self.vehicle_hef_path = resolved_models[0].path
            if len(resolved_models) >= 2 and self.plate_hef_path is None:
                self.plate_model_name = resolved_models[1].name
                self.plate_hef_path = resolved_models[1].path
            if len(resolved_models) >= 3 and self.ocr_hef_path is None:
                self.ocr_model_name = resolved_models[2].name
                self.ocr_hef_path = resolved_models[2].path

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
        self.overlay_so = get_resource_path(
            pipeline_name=LPR_PIPELINE,
            resource_type=RESOURCES_SO_DIR_NAME,
            arch=self.arch,
            model=LPR_OVERLAY_SO_FILENAME,
        )
        self.ocrsink_so = get_resource_path(
            pipeline_name=LPR_PIPELINE,
            resource_type=RESOURCES_SO_DIR_NAME,
            arch=self.arch,
            model=LPR_OCRSINK_SO_FILENAME,
        )
        self.lp_cropsink_so = get_resource_path(
            pipeline_name=LPR_PIPELINE,
            resource_type=RESOURCES_SO_DIR_NAME,
            arch=self.arch,
            model=LPR_LP_CROPSINK_SO_FILENAME,
        )

        self.vehicle_post_function_name = LPR_VEHICLE_POSTPROCESS_FUNCTION
        self.plate_post_function_name = LPR_PLATE_POSTPROCESS_FUNCTION
        self.ocr_post_function_name = OCR_RECOGNITION_POSTPROCESS_FUNCTION
        self.vehicle_cropper_function = LPR_VEHICLE_CROPPER_FUNCTION
        self.lp_cropper_function = LPR_LP_CROPPER_FUNCTION
        self.lp_fullframe_cropper_function = LPR_LP_FULLFRAME_CROPPER_FUNCTION
        if self.pipeline_type == "vlpoc":
            self.lp_cropper_function = LPR_LP_NO_QUALITY_CROPPER_FUNCTION

        self.vehicle_post_process_so = self.yolo_post_process_so
        self.plate_post_process_so = self.yolo_post_process_so

        self.thresholds_str = (
            "nms-score-threshold=0.3 "
            "nms-iou-threshold=0.45 "
            "output-format-type=HAILO_FORMAT_TYPE_FLOAT32"
        )

        self.vehicle_json = get_resource_path(
            pipeline_name=LPR_PIPELINE,
            resource_type=RESOURCES_JSON_DIR_NAME,
            model=f"{self.vehicle_model_name}.json",
        )
        self.plate_json = get_resource_path(
            pipeline_name=LPR_PIPELINE,
            resource_type=RESOURCES_JSON_DIR_NAME,
            model=f"{self.plate_model_name}.json",
        )
        self.ocr_json = get_resource_path(
            pipeline_name=LPR_PIPELINE,
            resource_type=RESOURCES_JSON_DIR_NAME,
            model=f"{self.ocr_model_name}.json",
        )

        hailo_logger.info(
            "LPR resources | vehicle=%s (%s) | plate=%s (%s) | ocr=%s (%s)",
            self.vehicle_model_name,
            self.vehicle_hef_path,
            self.plate_model_name,
            self.plate_hef_path,
            self.ocr_model_name,
            self.ocr_hef_path,
        )
        setproctitle.setproctitle(LPR_APP_TITLE)

        self.print_pipeline_only = getattr(self.options_menu, "print_pipeline", False)
        self.pipeline_string = None
        if self.print_pipeline_only:
            self.pipeline_string = self.get_pipeline_string()
            return

        self.create_pipeline()

    def on_eos(self):
        hailo_logger.info("LPR on_eos: resetting tracker and user state before rebuild")
        if HailoTracker is not None:
            try:
                tracker = HailoTracker.get_instance()
                for name in tracker.get_trackers_list():
                    tracker.remove_jde_tracker(name)
            except Exception as exc:  # pragma: no cover - defensive
                hailo_logger.debug("Failed to reset tracker on EOS: %s", exc)
        if hasattr(self, "user_data") and hasattr(self.user_data, "reset_state"):
            try:
                self.user_data.reset_state()
            except Exception as exc:  # pragma: no cover
                hailo_logger.debug("Failed to reset user_data on EOS: %s", exc)
        super().on_eos()

    def get_pipeline_string(self):
        if self.pipeline_type == "v":
            pipeline_string = self.get_vehicle_pipeline_string()
            print(pipeline_string)
            return pipeline_string
        if self.pipeline_type == "lp":
            pipeline_string = self.get_license_plate_pipeline_string()
            print(pipeline_string)
            return pipeline_string
        if self.pipeline_type == "vlp":
            pipeline_string = self.get_vehicle_and_license_plate_pipeline_string()
            print(pipeline_string)
            return pipeline_string
        if self.pipeline_type == "vlpoc":
            pipeline_string = self.get_full_pipeline_string()
            print(pipeline_string)
            return pipeline_string
        if self.pipeline_type == "vlpoc_ocrsink":
            pipeline_string = self.get_full_pipeline_with_ocrsink_string()
            print(pipeline_string)
            return pipeline_string
        raise ValueError(f"Unsupported pipeline type: {self.pipeline_type}")

    def run(self):
        if getattr(self, "print_pipeline_only", False):
            # Pipeline string already printed in get_pipeline_string
            if self.pipeline_string is None:
                self.pipeline_string = self.get_pipeline_string()
            return
        return super().run()

    def get_vehicle_pipeline_string(self):
        source_pipeline = SOURCE_PIPELINE(
            video_source=self.video_source,
            video_width=self.video_width,
            video_height=self.video_height,
            frame_rate=self.frame_rate,
            sync=self.sync,
        )
        vehicle_inference_pipeline = INFERENCE_PIPELINE(
            hef_path=self.vehicle_hef_path,
            post_process_so=self.vehicle_post_process_so,
            post_function_name=self.vehicle_post_function_name,
            config_json=self.vehicle_json,
            additional_params=self.thresholds_str,
            batch_size=2,
            name="vehicle_detection",
        )
        vehicle_inference_pipeline_wrapper = INFERENCE_PIPELINE_WRAPPER(vehicle_inference_pipeline)
        vehicle_tracker_pipeline = TRACKER_PIPELINE(class_id=-1)
        user_callback_pipeline = USER_CALLBACK_PIPELINE()

        display_pipeline = DISPLAY_PIPELINE(
            video_sink=self.video_sink,
            sync=self.sync,
            show_fps=self.show_fps,
        )

        pipeline_string = (
            f"{source_pipeline} ! "
            f"{vehicle_inference_pipeline_wrapper} ! "
            f"{vehicle_tracker_pipeline} ! "
            f"{user_callback_pipeline} ! "
            f"{display_pipeline}"
        )

        return pipeline_string

    def get_license_plate_pipeline_string(self):
        source_pipeline = SOURCE_PIPELINE(
            video_source=self.video_source,
            video_width=self.video_width,
            video_height=self.video_height,
            frame_rate=self.frame_rate,
            sync=self.sync,
        )
        license_plate_inference = INFERENCE_PIPELINE(
            hef_path=self.plate_hef_path,
            post_process_so=self.plate_post_process_so,
            post_function_name=self.plate_post_function_name,
            config_json=self.plate_json,
            additional_params=self.thresholds_str,
            batch_size=2,
            name="license_plate_detection",
        )
        license_plate_inference_wrapper = INFERENCE_PIPELINE_WRAPPER(license_plate_inference)
        lp_tracker_pipeline = TRACKER_PIPELINE(class_id=-1)
        user_callback_pipeline = USER_CALLBACK_PIPELINE()
        display_pipeline = DISPLAY_PIPELINE(
            video_sink=self.video_sink,
            sync=self.sync,
            show_fps=self.show_fps,
        )

        pipeline_string = (
            f"{source_pipeline} ! "
            f"{license_plate_inference_wrapper} ! "
            f"{lp_tracker_pipeline} ! "
            f"{user_callback_pipeline} ! "
            f"{display_pipeline}"
        )

        return pipeline_string

    def get_vehicle_and_license_plate_pipeline_string(self):
        """
        Vehicle & LP Detection pipeline: Runs vehicle detection, then license plate detection on vehicle crops.
        Displays both detection layers.
        """
        source_pipeline = SOURCE_PIPELINE(
            video_source=self.video_source,
            video_width=self.video_width,
            video_height=self.video_height,
            frame_rate=self.frame_rate,
            sync=self.sync,
        )

        vehicle_detection = INFERENCE_PIPELINE(
            hef_path=self.vehicle_hef_path,
            post_process_so=self.vehicle_post_process_so,
            post_function_name=self.vehicle_post_function_name,
            config_json=self.vehicle_json,
            additional_params=self.thresholds_str,
            batch_size=2,
            scheduler_timeout_ms=100,
            name="vehicle_detection",
        )
        vehicle_detection_wrapper = INFERENCE_PIPELINE_WRAPPER(vehicle_detection)

        tracker_pipeline = TRACKER_PIPELINE(
            class_id=-1,
            kalman_dist_thr=0.5,
            iou_thr=0.6,
            init_iou_thr=0.7,
            keep_tracked_frames=3,
            keep_lost_frames=2,
            keep_past_metadata=True,
            name="vehicle_tracker",
        )

        plate_detection = INFERENCE_PIPELINE(
            hef_path=self.plate_hef_path,
            post_process_so=self.plate_post_process_so,
            post_function_name=self.plate_post_function_name,
            config_json=self.plate_json,
            additional_params=self.thresholds_str,
            batch_size=8,
            scheduler_timeout_ms=100,
            name="plate_detection",
        )

        vehicle_cropper = CROPPER_PIPELINE(
            inner_pipeline=plate_detection,
            so_path=self.croppers_so,
            function_name=self.vehicle_cropper_function,
            internal_offset=True,
            name="vehicle_cropper",
        )

        user_callback = USER_CALLBACK_PIPELINE()

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
            f"{user_callback} ! "
            f"{display_pipeline}"
        )

        return pipeline_string

    def get_full_pipeline_string(self):
        """
        Full LPR: vehicle detection -> plate detection on vehicle crops -> OCR on plate crops.
        """
        source_pipeline = SOURCE_PIPELINE(
            video_source=self.video_source,
            video_width=self.video_width,
            video_height=self.video_height,
            frame_rate=self.frame_rate,
            sync=self.sync,
        )

        vehicle_detection = INFERENCE_PIPELINE(
            hef_path=self.vehicle_hef_path,
            post_process_so=self.vehicle_post_process_so,
            post_function_name=self.vehicle_post_function_name,
            config_json=self.vehicle_json,
            additional_params=self.thresholds_str,
            batch_size=2,
            scheduler_timeout_ms=100,
            name="vehicle_detection",
        )
        vehicle_detection_wrapper = INFERENCE_PIPELINE_WRAPPER(vehicle_detection)

        tracker_pipeline = TRACKER_PIPELINE(
            class_id=-1,
            kalman_dist_thr=0.5,
            iou_thr=0.6,
            init_iou_thr=0.7,
            keep_tracked_frames=3,
            keep_lost_frames=2,
            keep_past_metadata=True,
            name="vehicle_tracker",
        )

        plate_detection = INFERENCE_PIPELINE(
            hef_path=self.plate_hef_path,
            post_process_so=self.plate_post_process_so,
            post_function_name=self.plate_post_function_name,
            config_json=self.plate_json,
            additional_params=self.thresholds_str,
            batch_size=8,
            scheduler_timeout_ms=100,
            name="plate_detection",
        )

        vehicle_cropper = CROPPER_PIPELINE(
            inner_pipeline=plate_detection,
            so_path=self.croppers_so,
            function_name=self.vehicle_cropper_function,
            internal_offset=True,
            name="vehicle_cropper",
        )

        ocr_detection = INFERENCE_PIPELINE(
            hef_path=self.ocr_hef_path,
            post_process_so=self.ocr_post_process_so,
            post_function_name=self.ocr_post_function_name,
            config_json=self.ocr_json,
            batch_size=8,
            scheduler_timeout_ms=100,
            name="ocr_detection",
        )

        lp_cropper = CROPPER_PIPELINE(
            inner_pipeline=ocr_detection,
            so_path=self.croppers_so,
            function_name="license_plate_no_quality_two_best",
            internal_offset=True,
            name="lp_cropper",
        )

        user_callback = USER_CALLBACK_PIPELINE()

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
            f"{lp_cropper} ! "
            f"{user_callback} ! "
            f"{display_pipeline}"
        )

        return pipeline_string

    def get_full_pipeline_with_ocrsink_string(self):
        """
        Full LPR: vehicle detection -> plate detection -> OCR, with C++ ocrsink + overlay (no user callback).
        """
        source_pipeline = SOURCE_PIPELINE(
            video_source=self.video_source,
            video_width=self.video_width,
            video_height=self.video_height,
            frame_rate=self.frame_rate,
            sync=self.sync,
        )

        vehicle_detection = INFERENCE_PIPELINE(
            hef_path=self.vehicle_hef_path,
            post_process_so=self.vehicle_post_process_so,
            post_function_name=self.vehicle_post_function_name,
            config_json=self.vehicle_json,
            additional_params=self.thresholds_str,
            batch_size=2,
            scheduler_timeout_ms=100,
            name="vehicle_detection",
        )
        vehicle_detection_wrapper = INFERENCE_PIPELINE_WRAPPER(vehicle_detection)

        tracker_pipeline = TRACKER_PIPELINE(
            class_id=-1,
            kalman_dist_thr=0.5,
            iou_thr=0.6,
            init_iou_thr=0.7,
            keep_tracked_frames=3,
            keep_lost_frames=2,
            keep_past_metadata=True,
            name="hailo_tracker",
        )

        plate_detection = INFERENCE_PIPELINE(
            hef_path=self.plate_hef_path,
            post_process_so=self.plate_post_process_so,
            post_function_name=self.plate_post_function_name,
            config_json=self.plate_json,
            additional_params=self.thresholds_str,
            batch_size=8,
            scheduler_timeout_ms=100,
            name="plate_detection",
        )

        vehicle_cropper = CROPPER_PIPELINE(
            inner_pipeline=plate_detection,
            so_path=self.croppers_so,
            function_name=self.vehicle_cropper_function,
            internal_offset=True,
            name="vehicle_cropper",
        )

        ocr_detection = INFERENCE_PIPELINE(
            hef_path=self.ocr_hef_path,
            post_process_so=self.ocr_post_process_so,
            post_function_name=self.ocr_post_function_name,
            config_json=self.ocr_json,
            batch_size=8,
            scheduler_timeout_ms=200,
            name="ocr_detection",
        )

        lp_cropper = CROPPER_PIPELINE(
            inner_pipeline=ocr_detection,
            so_path=self.croppers_so,
            function_name=self.lp_cropper_function,
            internal_offset=True,
            name="lp_cropper",
        )

        ocrsink_pipeline = (
            f"{QUEUE(name='lpr_ocrsink_q')} ! "
            f"hailofilter use-gst-buffer=true so-path={self.ocrsink_so} qos=false ! "
        )

        display_pipeline = (
            f"{QUEUE(name='lpr_display_overlay_q')} ! "
            f"hailooverlay name=lpr_display_overlay ! "
            f"{QUEUE(name='lpr_display_filter_q')} ! "
            f"hailofilter use-gst-buffer=true so-path={self.overlay_so} qos=false ! "
            f"{QUEUE(name='lpr_display_videoconvert_q')} ! "
            f"videoconvert name=lpr_display_videoconvert n-threads=2 qos=false ! "
            f"{QUEUE(name='lpr_display_q')} ! "
            f"fpsdisplaysink name=hailo_display video-sink={self.video_sink} sync={self.sync} "
            f"text-overlay={self.show_fps} signal-fps-measurements=true "
        )

        pipeline_string = (
            f"{source_pipeline} ! "
            f"{vehicle_detection_wrapper} ! "
            f"{tracker_pipeline} ! "
            f"{vehicle_cropper} ! "
            f"{lp_cropper} ! "
            f"{ocrsink_pipeline} "
            f"{display_pipeline}"
        )

        return pipeline_string


def main():
    user_data = app_callback_class()
    app = GStreamerLPRApp(dummy_callback, user_data)
    app.run()


if __name__ == "__main__":
    main()
