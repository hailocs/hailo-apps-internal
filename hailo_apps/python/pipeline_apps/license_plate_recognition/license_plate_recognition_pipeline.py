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
    LPR_LP_MINIMAL_CROPPER_FUNCTION,
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
    LPR_OCR_POSTPROCESS_FUNCTION,
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
    CROPPER_PIPELINE_OPTIMIZED,
    DISPLAY_PIPELINE,
    INFERENCE_PIPELINE,
    INFERENCE_PIPELINE_OPTIMIZED,
    INFERENCE_PIPELINE_WRAPPER,
    INFERENCE_PIPELINE_WRAPPER_OPTIMIZED,
    QUEUE,
    SOURCE_PIPELINE,
    SOURCE_PIPELINE_OPTIMIZED,
    TRACKER_PIPELINE,
    USER_CALLBACK_PIPELINE,
)

hailo_logger = get_logger(__name__)


class GStreamerLPRApp(GStreamerApp):
    def __init__(self, app_callback, user_data, parser=None):
        if parser is None:
            parser = get_pipeline_parser()

        parser.add_argument(
            "-p",
            "--pipeline",
            default="vlpoc",
            choices=[
                "vlp",
                "vlpoc",
                "vlpoc_fixed",
                "vlpoc_optimized",
                "vlpoc_ocrsink",
                "vlpoc_parallel",
                "fixed",
                "f",
                "x",
                "v",
                "lp",
                "d",
                "nested",
                "n",
                "test",
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
        self.ocr_post_function_name = LPR_OCR_POSTPROCESS_FUNCTION
        # Vehicle cropping is done in C++ only by default (vehicles_roi_cropper function)
        self.vehicle_cropper_function = LPR_VEHICLE_CROPPER_FUNCTION
        self.lp_cropper_function = LPR_LP_CROPPER_FUNCTION
        self.lp_fullframe_cropper_function = LPR_LP_FULLFRAME_CROPPER_FUNCTION
        if self.pipeline_type in ("vlpoc", "vlpoc_fixed"):
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

        # Increase pipeline latency to 500ms for optimized pipeline
        # This provides more buffer headroom for the vehicle detection bottleneck
        if self.pipeline_type == "vlpoc_optimized":
            self.pipeline_latency = 500

        self.print_pipeline_only = getattr(self.options_menu, "print_pipeline", False)
        self.pipeline_string = None
        if self.print_pipeline_only:
            self.pipeline_string = self.get_pipeline_string()
            return

        self.create_pipeline()

    def on_eos(self):
        hailo_logger.info("LPR on_eos: End of stream - printing summary and exiting")
        
        # Print LPR summary from C++ ocrsink
        try:
            import ctypes
            ocrsink_lib = ctypes.CDLL("/usr/local/hailo/resources/so/liblpr_ocrsink.so")
            ocrsink_lib.lpr_print_summary()
        except Exception as exc:
            hailo_logger.debug("Failed to call lpr_print_summary: %s", exc)
        
        # For LPR pipeline, exit after first video pass instead of looping
        hailo_logger.info("LPR pipeline completed - shutting down")
        self.shutdown()

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
        if self.pipeline_type == "vlpoc_fixed":
            pipeline_string = self.get_full_pipeline_fixed_string()
            print(pipeline_string)
            return pipeline_string
        if self.pipeline_type == "vlpoc_optimized":
            pipeline_string = self.get_optimized_full_pipeline_string()
            print(pipeline_string)
            return pipeline_string
        if self.pipeline_type == "vlpoc_ocrsink" or self.pipeline_type == "d":
            pipeline_string = self.get_full_pipeline_with_ocrsink_string()
            print(pipeline_string)
            return pipeline_string
        if self.pipeline_type == "fixed" or self.pipeline_type == "f":
            pipeline_string = self.get_full_pipeline_ocrsink_fixed_string()
            print(pipeline_string)
            return pipeline_string
        if self.pipeline_type == "vlpoc_parallel":
            pipeline_string = self.get_full_pipeline_parallel_ocrsink_string()
            print(pipeline_string)
            return pipeline_string
        if self.pipeline_type == "x":
            pipeline_string = self.get_x_pipeline_string()
            print(pipeline_string)
            return pipeline_string
        if self.pipeline_type == "test":
            pipeline_string = self.get_test_pipeline_string()
            print(pipeline_string)
            return pipeline_string
        if self.pipeline_type == "nested" or self.pipeline_type == "n":
            pipeline_string = self.get_nested_pipeline_string()
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
            additional_params=self.thresholds_str,
            batch_size=8,
            name="license_plate_detection",
        )
        license_plate_inference_wrapper = INFERENCE_PIPELINE_WRAPPER(license_plate_inference)
        lp_tracker_pipeline = TRACKER_PIPELINE(class_id=1)
        ocr_detection = INFERENCE_PIPELINE(
            hef_path=self.ocr_hef_path,
            post_process_so=self.ocr_post_process_so,
            post_function_name=self.ocr_post_function_name,
            config_json=self.ocr_json,
            batch_size=8,
            name="ocr_detection",
        )
        lp_cropper = CROPPER_PIPELINE(
            inner_pipeline=ocr_detection,
            so_path=self.croppers_so,
            function_name="lp_simple_cropper",
            internal_offset=True,
            name="lp_cropper",
        )
        ocrsink_pipeline = (
            f"{QUEUE(name='lpr_ocrsink_q')} ! "
            f"hailofilter use-gst-buffer=true so-path={self.ocrsink_so} function-name=lp_only_ocrsink qos=false ! "
        )

        pipeline_string = (
            f"{source_pipeline} ! "
            f"{license_plate_inference_wrapper} ! "
            f"{lp_tracker_pipeline} ! "
            f"{lp_cropper} ! "
            f"identity name=identity_callback ! "
            f"tee name=lpr_output_tee "
            f"lpr_output_tee. ! {QUEUE(name='lpr_ocr_branch_q')} ! {ocrsink_pipeline} fakesink name=lpr_ocr_sink sync=false async=false "
            f"lpr_output_tee. ! {QUEUE(name='lpr_display_stub_q')} ! fakesink name=hailo_display sync=false async=false "
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
            function_name="license_plate_no_quality",
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

    def get_full_pipeline_fixed_string(self):
        """
        Full LPR with framerate enforcement, larger decode queue, and video-only decodebin output.
        """
        source_pipeline = SOURCE_PIPELINE(
            video_source=self.video_source,
            video_width=self.video_width,
            video_height=self.video_height,
            frame_rate=self.frame_rate,
            sync=self.sync,
            decode_queue_max_size_buffers=8,
            decode_queue_max_size_time=1_000_000_000,
            decodebin_video_only=True,
        )

        vehicle_detection = INFERENCE_PIPELINE(
            hef_path=self.vehicle_hef_path,
            post_process_so=self.vehicle_post_process_so,
            post_function_name=self.vehicle_post_function_name,
            config_json=self.vehicle_json,
            additional_params=self.thresholds_str,
            batch_size=2,
            scheduler_timeout_ms=100,
            frame_rate=self.frame_rate,
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
            frame_rate=self.frame_rate,
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
            frame_rate=self.frame_rate,
            name="ocr_detection",
        )

        lp_cropper = CROPPER_PIPELINE(
            inner_pipeline=ocr_detection,
            so_path=self.croppers_so,
            function_name="license_plate_minimal",
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

    def get_optimized_full_pipeline_string(self):
        """
        Optimized Full LPR pipeline with the following improvements:

        1. Larger source queue (10 buffers, ~333ms at 30fps)
        2. Video-only decodebin output (fixes audio memory leak)
        3. Multiqueue settings (16MB, 1s time limit)
        4. Enforced framerate at source (30 FPS, preserves timestamps)
        5. Leaky queues on all inference branches (drop old frames under backpressure)
        6. Branch-specific queue configurations:
           - Vehicle detection: 5 buffers, 166ms (tightest bottleneck at 80 FPS)
           - Plate detection: 3 buffers, 100ms (plenty of headroom at 990 FPS)
           - OCR detection: 5 buffers, 166ms (good headroom at 140+ FPS)
        7. OCR batch-size=4 (3x speedup: 140→415 FPS)
        8. Increased pipeline latency budget (500ms)
        """
        # Optimized source with larger decode queue and video-only decodebin
        source_pipeline = SOURCE_PIPELINE_OPTIMIZED(
            video_source=self.video_source,
            video_width=self.video_width,
            video_height=self.video_height,
            frame_rate=self.frame_rate,
            sync=self.sync,
        )

        # Vehicle detection - tightest bottleneck (80 FPS = 2.6x headroom)
        # Use smaller queue since this is the bottleneck
        vehicle_detection = INFERENCE_PIPELINE_OPTIMIZED(
            hef_path=self.vehicle_hef_path,
            post_process_so=self.vehicle_post_process_so,
            post_function_name=self.vehicle_post_function_name,
            config_json=self.vehicle_json,
            additional_params=self.thresholds_str,
            batch_size=1,  # No batching benefit for vehicle detection
            scheduler_timeout_ms=100,
            frame_rate=self.frame_rate,
            queue_leaky="downstream",
            queue_max_size_buffers=5,
            queue_max_size_time=166666667,  # ~5 frames at 30fps (166ms)
            name="vehicle_detection",
        )
        vehicle_detection_wrapper = INFERENCE_PIPELINE_WRAPPER_OPTIMIZED(
            vehicle_detection,
            queue_leaky="downstream",
            queue_max_size_buffers=5,
            queue_max_size_time=166666667,
        )

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

        # Plate detection - plenty of headroom (990 FPS = 33x headroom)
        # Use minimal queues since this is very fast
        plate_detection = INFERENCE_PIPELINE_OPTIMIZED(
            hef_path=self.plate_hef_path,
            post_process_so=self.plate_post_process_so,
            post_function_name=self.plate_post_function_name,
            config_json=self.plate_json,
            additional_params=self.thresholds_str,
            batch_size=1,  # No batching benefit for plate detection
            scheduler_timeout_ms=100,
            frame_rate=self.frame_rate,
            queue_leaky="downstream",
            queue_max_size_buffers=3,  # Minimal buffer needed
            queue_max_size_time=100000000,  # ~3 frames (100ms)
            name="plate_detection",
        )

        vehicle_cropper = CROPPER_PIPELINE_OPTIMIZED(
            inner_pipeline=plate_detection,
            so_path=self.croppers_so,
            function_name=self.vehicle_cropper_function,
            internal_offset=True,
            queue_leaky="downstream",
            queue_max_size_buffers=5,
            queue_max_size_time=166666667,
            name="vehicle_cropper",
        )

        # OCR detection - good headroom (140+ FPS = 4.6x headroom)
        # Use batch-size=4 for 3x speedup (140→415 FPS)
        ocr_detection = INFERENCE_PIPELINE_OPTIMIZED(
            hef_path=self.ocr_hef_path,
            post_process_so=self.ocr_post_process_so,
            post_function_name=self.ocr_post_function_name,
            config_json=self.ocr_json,
            batch_size=4,  # 3x speedup with batching
            scheduler_timeout_ms=100,  # 100ms timeout for batch accumulation
            frame_rate=self.frame_rate,
            queue_leaky="downstream",
            queue_max_size_buffers=5,
            queue_max_size_time=166666667,  # ~5 frames
            name="ocr_detection",
        )

        lp_cropper = CROPPER_PIPELINE_OPTIMIZED(
            inner_pipeline=ocr_detection,
            so_path=self.croppers_so,
            function_name="license_plate_minimal",
            internal_offset=True,
            queue_leaky="downstream",
            queue_max_size_buffers=5,
            queue_max_size_time=166666667,
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

    def get_x_pipeline_string(self):
        """
        Full LPR: vehicle detection -> plate detection -> OCR, with C++ ocrsink + overlay and user callback.
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

        user_callback = USER_CALLBACK_PIPELINE()

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
            f"{user_callback} ! "
            f"{ocrsink_pipeline} "
            f"{display_pipeline}"
        )

        return pipeline_string

    def get_full_pipeline_with_ocrsink_string(self):
        """
        Full LPR: vehicle detection -> plate detection -> OCR, with C++ ocrsink only (no display/user callback).
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
            function_name="license_plate_minimal",
            internal_offset=True,
            name="lp_cropper",
        )

        ocrsink_pipeline = (
            f"{QUEUE(name='lpr_ocrsink_q')} ! "
            f"hailofilter use-gst-buffer=true so-path={self.ocrsink_so} qos=false ! "
        )

        pipeline_string = (
            f"{source_pipeline} ! "
            f"{vehicle_detection_wrapper} ! "
            f"{tracker_pipeline} ! "
            f"{vehicle_cropper} ! "
            f"{lp_cropper} ! "
            f"{ocrsink_pipeline} "
            f"fakesink name=lpr_ocr_sink sync=false"
        )

        return pipeline_string

    def get_full_pipeline_ocrsink_fixed_string(self):
        """
        Fixed LPR pipeline: vehicle detection -> plate detection -> OCR, with C++ ocrsink.
        
        KEY FIX: The lp_cropper is NESTED INSIDE vehicle_cropper, so license_plate_vehicle_crop
        receives vehicle crops (not full frame) and can find LP detections correctly.
        
        Correct data flow:
        [Full Frame] -> vehicle_detection -> tracker -> vehicle_cropper
                                                              |
                                                        [Vehicle Crop] -> plate_detection -> lp_cropper -> ocr
                                                                                                  |
                                                                              license_plate_vehicle_crop receives VEHICLE CROP
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

        # Plate detection runs on vehicle crops
        plate_detection = INFERENCE_PIPELINE(
            hef_path=self.plate_hef_path,
            post_process_so=self.plate_post_process_so,
            post_function_name=self.plate_post_function_name,
            config_json=self.plate_json,
            additional_params=self.thresholds_str,
            batch_size=1,  # batch-size=1 for nested structure
            scheduler_timeout_ms=50,
            name="plate_detection",
        )

        # OCR runs on LP crops (from vehicle crops)
        ocr_detection = INFERENCE_PIPELINE(
            hef_path=self.ocr_hef_path,
            post_process_so=self.ocr_post_process_so,
            post_function_name=self.ocr_post_function_name,
            config_json=self.ocr_json,
            batch_size=1,  # batch-size=1 for nested structure
            scheduler_timeout_ms=50,
            name="ocr_detection",
        )

        # LP cropper wraps OCR - NESTED inside vehicle_cropper
        # license_plate_vehicle_crop expects vehicle crop input
        lp_cropper = CROPPER_PIPELINE(
            inner_pipeline=ocr_detection,
            so_path=self.croppers_so,
            function_name="license_plate_vehicle_crop",
            internal_offset=True,
            use_letterbox=True,
            name="lp_cropper",
        )

        # NESTED: plate_detection -> lp_cropper are INSIDE vehicle_cropper
        # This way lp_cropper receives vehicle crops, not full frame
        plate_and_lp_pipeline = f"{plate_detection} ! {lp_cropper}"

        # Vehicle cropper wraps both plate detection AND lp cropper
        vehicle_cropper = CROPPER_PIPELINE(
            inner_pipeline=plate_and_lp_pipeline,
            so_path=self.croppers_so,
            function_name=self.vehicle_cropper_function,
            internal_offset=True,
            bypass_max_size_buffers=1,
            name="vehicle_cropper",
        )

        ocrsink_pipeline = (
            f"{QUEUE(name='lpr_ocrsink_q')} ! "
            f"hailofilter use-gst-buffer=true so-path={self.ocrsink_so} qos=false ! "
        )

        # NESTED: lp_cropper is inside vehicle_cropper, receives vehicle crops
        pipeline_string = (
            f"{source_pipeline} ! "
            f"{vehicle_detection_wrapper} ! "
            f"{tracker_pipeline} ! "
            f"{vehicle_cropper} ! "
            f"{ocrsink_pipeline} "
            f"fakesink name=lpr_ocr_sink sync=false async=false "
        )

        return pipeline_string

    def get_full_pipeline_parallel_ocrsink_string(self):
        """
        Full LPR with a tee after plate detection:
        - Branch 1: user callback + display
        - Branch 2: OCR on plate crops -> ocrsink -> fakesink
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

        user_callback = USER_CALLBACK_PIPELINE()

        display_pipeline = DISPLAY_PIPELINE(
            video_sink=self.video_sink,
            sync=self.sync,
            show_fps=self.show_fps,
        )

        ocrsink_pipeline = (
            f"{QUEUE(name='lpr_ocrsink_q')} ! "
            f"hailofilter use-gst-buffer=true so-path={self.ocrsink_so} qos=false ! "
        )

        pipeline_string = (
            f"{source_pipeline} ! "
            f"{vehicle_detection_wrapper} ! "
            f"{tracker_pipeline} ! "
            f"{vehicle_cropper} ! "
            f"tee name=lpr_tee "
            f"lpr_tee. ! {QUEUE(name='lpr_display_q')} ! {user_callback} ! {display_pipeline} "
            f"lpr_tee. ! {QUEUE(name='lpr_ocr_q')} ! {lp_cropper} ! {ocrsink_pipeline} "
            f"fakesink name=lpr_ocr_sink sync=false async=false "
        )

        return pipeline_string

    def get_test_pipeline_string(self):
        """
        Test pipeline based on old license_plate_recognition.sh architecture:
        - Uses tee to split display and processing branches (old script style)
        - Direct hailonet calls without inference wrapper
        - Display branch: videobox → hailooverlay → lpr_overlay → fpsdisplaysink
        - Processing branch: Two-stage cropping → OCR sink → fakesink
        - Updated with current models and function names
        """
        # Source pipeline (simplified like old script)
        source = (
            f'filesrc location="{self.video_source}" name=source ! '
            'decodebin ! '
            'videoscale ! video/x-raw, pixel-aspect-ratio=1/1 ! '
            'videoconvert ! '
        )

        # Vehicle detection (direct hailonet, no wrapper - but with modern parameters)
        vehicle_detection = (
            f'{QUEUE(name="vehicle_pre_q", max_size_buffers=30)} ! '
            f'hailonet name=vehicle_hailonet '
            f'hef-path={self.vehicle_hef_path} '
            f'vdevice-group-id=SHARED scheduler-timeout-ms=100 '
            f'nms-score-threshold=0.3 nms-iou-threshold=0.45 '
            f'output-format-type=HAILO_FORMAT_TYPE_FLOAT32 force-writable=true ! '
            f'{QUEUE(name="vehicle_post_q", max_size_buffers=30)} ! '
            f'hailofilter name=vehicle_filter '
            f'so-path={self.vehicle_post_process_so} '
            f'function-name={self.vehicle_post_function_name} '
            f'config-path={self.vehicle_json} qos=false ! '
            f'{QUEUE(name="vehicle_filtered_q", max_size_buffers=30)} ! '
        )

        # Tracker
        tracker = (
            f'hailotracker name=hailo_tracker '
            f'keep-past-metadata=true kalman-dist-thr=0.5 iou-thr=0.6 '
            f'keep-tracked-frames=2 keep-lost-frames=2 ! '
            f'{QUEUE(name="post_tracker_q", max_size_buffers=30)} ! '
        )

        # Tee splits into display and processing branches
        tee_split = 'tee name=context_tee '

        # === BRANCH 1: Display Branch (like old script) ===
        display_branch = (
            'context_tee. ! '
            f'{QUEUE(name="display_q", max_size_buffers=30)} ! '
            'videobox top=1 bottom=1 ! '
            f'{QUEUE(name="pre_overlay_q", max_size_buffers=30)} ! '
            'hailooverlay line-thickness=3 font-thickness=1 qos=false ! '
            f'hailofilter use-gst-buffer=true so-path={self.overlay_so} qos=false ! '
            'videoconvert ! '
            f'fpsdisplaysink name=hailo_display video-sink={self.video_sink} '
            f'sync={self.sync} text-overlay={self.show_fps} signal-fps-measurements=true '
        )

        # === BRANCH 2: Processing Branch ===
        # Stage 1: Vehicle crops → LP Detection
        stage1_cropper_start = (
            'context_tee. ! '
            f'{QUEUE(name="processing_q", max_size_buffers=30)} ! '
            f'hailocropper name=cropper1 '
            f'so-path={self.croppers_so} '
            f'function-name={self.vehicle_cropper_function} '
            f'internal-offset=true drop-uncropped-buffers=true '
            f'hailoaggregator name=agg1 '
        )

        stage1_bypass = (
            f'cropper1. ! '
            f'{QUEUE(name="crop1_bypass_q", max_size_buffers=50)} ! '
            f'agg1. '
        )

        stage1_lp_detection = (
            f'cropper1. ! '
            f'{QUEUE(name="lp_det_pre_q", max_size_buffers=30)} ! '
            f'hailonet name=lp_detection_hailonet '
            f'hef-path={self.plate_hef_path} '
            f'vdevice-group-id=SHARED scheduler-timeout-ms=100 '
            f'nms-score-threshold=0.3 nms-iou-threshold=0.45 '
            f'output-format-type=HAILO_FORMAT_TYPE_FLOAT32 force-writable=true ! '
            f'{QUEUE(name="lp_det_post_q", max_size_buffers=30)} ! '
            f'hailofilter name=lp_detection_filter '
            f'so-path={self.plate_post_process_so} '
            f'config-path={self.plate_json} '
            f'function-name={self.plate_post_function_name} qos=false ! '
            f'{QUEUE(name="lp_det_filtered_q", max_size_buffers=30)} ! '
            f'agg1. '
        )

        # Stage 2: LP crops → OCR
        stage2_cropper_start = (
            f'agg1. ! '
            f'{QUEUE(name="post_agg1_q", max_size_buffers=30)} ! '
            f'hailocropper name=cropper2 '
            f'so-path={self.croppers_so} '
            f'function-name={self.lp_cropper_function} '
            f'internal-offset=true drop-uncropped-buffers=true '
            f'hailoaggregator name=agg2 '
        )

        stage2_bypass = (
            f'cropper2. ! '
            f'{QUEUE(name="crop2_bypass_q", max_size_buffers=50)} ! '
            f'agg2. '
        )

        stage2_ocr = (
            f'cropper2. ! '
            f'{QUEUE(name="ocr_pre_q", max_size_buffers=30)} ! '
            f'hailonet name=ocr_hailonet '
            f'hef-path={self.ocr_hef_path} '
            f'vdevice-group-id=SHARED scheduler-timeout-ms=100 force-writable=true ! '
            f'{QUEUE(name="ocr_post_q", max_size_buffers=30)} ! '
            f'hailofilter name=ocr_filter '
            f'so-path={self.ocr_post_process_so} '
            f'config-path={self.ocr_json} '
            f'function-name={self.ocr_post_function_name} qos=false ! '
            f'{QUEUE(name="ocr_filtered_q", max_size_buffers=30)} ! '
            f'agg2. '
        )

        # Final: identity callback for Python, then OCR sink to fakesink
        processing_end = (
            f'agg2. ! '
            f'{QUEUE(name="final_q", max_size_buffers=30)} ! '
            f'identity name=identity_callback ! '
            f'hailofilter use-gst-buffer=true so-path={self.ocrsink_so} qos=false ! '
            f'fakesink sync=false async=false'
        )

        # Assemble full pipeline
        pipeline_string = (
            f'{source}'
            f'{vehicle_detection}'
            f'{tracker}'
            f'{tee_split}'
            f'{display_branch} '
            f'{stage1_cropper_start}'
            f'{stage1_bypass}'
            f'{stage1_lp_detection}'
            f'{stage2_cropper_start}'
            f'{stage2_bypass}'
            f'{stage2_ocr}'
            f'{processing_end}'
        )

        return pipeline_string

    def get_nested_pipeline_string(self):
        """
        Nested LPR pipeline: lp_cropper is NESTED INSIDE vehicle_cropper.
        
        This ensures license_plate_minimal receives VEHICLE CROPS (not full frame).
        
        Data flow:
        [Full Frame] -> vehicle_detection -> tracker -> vehicle_cropper
                                                              |
                                                        [Vehicle Crop] -> plate_detection -> lp_cropper -> ocr
                                                                                                  |
                                                                              license_plate_minimal receives VEHICLE CROP
        
        Key difference from sequential pipeline:
        - Sequential: vehicle_cropper(plate_det) -> lp_cropper(ocr) - lp_cropper gets full frame
        - Nested: vehicle_cropper(plate_det -> lp_cropper(ocr)) - lp_cropper gets vehicle crop
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

        # Plate detection runs on vehicle crops
        # Use batch-size=1 to prevent blocking in nested structure
        plate_detection = INFERENCE_PIPELINE(
            hef_path=self.plate_hef_path,
            post_process_so=self.plate_post_process_so,
            post_function_name=self.plate_post_function_name,
            config_json=self.plate_json,
            additional_params=self.thresholds_str,
            batch_size=1,
            scheduler_timeout_ms=50,
            name="plate_detection",
        )

        # OCR runs on LP crops (from vehicle crops)
        # Use INFERENCE_PIPELINE with videoscale to resize LP to OCR model input
        ocr_detection = INFERENCE_PIPELINE(
            hef_path=self.ocr_hef_path,
            post_process_so=self.ocr_post_process_so,
            post_function_name=self.ocr_post_function_name,
            config_json=self.ocr_json,
            batch_size=1,
            scheduler_timeout_ms=50,
            name="ocr_detection",
        )

        # LP cropper wraps OCR - uses license_plate_minimal which expects vehicle crop
        # use_letterbox=True: OCR model needs consistent input aspect ratio
        lp_cropper = CROPPER_PIPELINE(
            inner_pipeline=ocr_detection,
            so_path=self.croppers_so,
            function_name="license_plate_minimal",  # Expects vehicle crop input
            internal_offset=True,
            use_letterbox=True,  # Keep letterbox for consistent aspect ratio
            name="lp_cropper",
        )

        # NESTED: plate_detection -> lp_cropper are INSIDE vehicle_cropper
        # This way lp_cropper receives vehicle crops, not full frame
        plate_and_lp_pipeline = f"{plate_detection} ! {lp_cropper}"

        # bypass_max_size_buffers=1 ensures one-frame-at-a-time processing
        vehicle_cropper = CROPPER_PIPELINE(
            inner_pipeline=plate_and_lp_pipeline,
            so_path=self.croppers_so,
            function_name=self.vehicle_cropper_function,
            internal_offset=True,
            bypass_max_size_buffers=1,
            name="vehicle_cropper",
        )

        # OCR sink for processing results -> fakesink
        ocrsink_pipeline = (
            f"{QUEUE(name='lpr_ocrsink_q')} ! "
            f"hailofilter use-gst-buffer=true so-path={self.ocrsink_so} qos=false ! "
            f"fakesink name=lpr_ocr_sink sync=false async=false"
        )

        pipeline_string = (
            f"{source_pipeline} ! "
            f"{vehicle_detection_wrapper} ! "
            f"{tracker_pipeline} ! "
            f"{vehicle_cropper} ! "
            f"{ocrsink_pipeline}"
        )

        return pipeline_string


def main():
    user_data = app_callback_class()
    app = GStreamerLPRApp(dummy_callback, user_data)
    app.run()


if __name__ == "__main__":
    main()
