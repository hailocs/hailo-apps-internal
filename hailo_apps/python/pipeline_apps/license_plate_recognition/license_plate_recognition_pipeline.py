import gi

gi.require_version("Gst", "1.0")
from gi.repository import Gst

from pathlib import Path
import os

import setproctitle

from hailo_apps.python.core.common.core import get_pipeline_parser, get_resource_path
from hailo_apps.python.core.common.defines import (
    TAPPAS_POSTPROC_PATH_DEFAULT,
    TAPPAS_POSTPROC_PATH_KEY,
)
from hailo_apps.python.core.common.defines import (
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

# LPR defaults (this app is not yet wired into core/common/defines.py).
LPR_APP_TITLE = "Hailo LPR App"
LPR_PIPELINE = "license_plate_recognition"

# Default resources (override via CLI args). Keep defaults self-contained where possible.
DEFAULT_VEHICLE_MODEL_NAME = "yolov5m_vehicles"
DEFAULT_PLATE_MODEL_NAME = "yolov8n_relu6_global_lp_det"

DEFAULT_YOLO_POSTPROCESS_SO = "libyolo_hailortpp_postprocess.so"
DEFAULT_VEHICLE_POSTPROCESS_FUNCTION = "yolov5m_vehicles"
DEFAULT_PLATE_POSTPROCESS_FUNCTION = "filter"

# LPR uses dedicated croppers that expect vehicle detections (car/vehicle) and nested license_plate detections.
DEFAULT_LPR_CROPPERS_SO = "liblpr_croppers.so"
DEFAULT_VEHICLE_CROPPER_FUNCTION = "vehicles_without_ocr"
DEFAULT_LP_CROPPER_FUNCTION = "license_plate_no_quality"
DEFAULT_LP_FULLFRAME_CROPPER_FUNCTION = "license_plate_fullframe"

DEFAULT_LPR_OVERLAY_SO = "liblpr_overlay.so"
DEFAULT_LPR_OCRSINK_SO = "liblpr_ocrsink.so"
DEFAULT_LPR_LP_CROPSINK_SO = "liblp_crop_saver.so"

DEFAULT_DISPLAY_SYNC = False
DEFAULT_DISPLAY_QUEUE_SIZE = 10
DEFAULT_DISPLAY_QUEUE_LEAKY = "downstream"

_APP_DIR = Path(__file__).resolve().parent
_CONFIGS_DIR = _APP_DIR / "configs"
DEFAULT_VEHICLE_JSON_PATH = str(_CONFIGS_DIR / "yolov5m_vehicles.json")
DEFAULT_PLATE_JSON_PATH = str(_CONFIGS_DIR / f"{DEFAULT_PLATE_MODEL_NAME}.json")


class GStreamerLPRApp(GStreamerApp):
    def __init__(self, app_callback, user_data, parser=None):
        # Use default CLI parser if none is supplied
        if parser is None:
            parser = get_pipeline_parser()
        parser.add_argument(
            "--pipeline",
            default="optimized_direct",
            choices=[
                "simple",
                "complex",
                "optimized",
                "optimized_direct",
                "optimized_direct_display_end",
                "full",
                "candidate",
                "vehicle_and_lp",
                "vehicle_and_lp_crop",
                "vehicle_only",
                "lp_only_crops",
                "lp_and_ocr",
                "lp_and_ocr_direct",
                "lp_only",
                "ocr_only",
            ],
            help="Pipeline variant",
        )
        parser.add_argument(
            "--ocr-mode",
            default="paddle_ocr",
            choices=["paddle_ocr", "legacy"],
            help="OCR mode: 'paddle_ocr' (uses paddleocr_recognize) or 'legacy' (uses filter_letterbox)",
        )
        parser.add_argument(
            "--vehicle-model",
            default=DEFAULT_VEHICLE_MODEL_NAME,
            help="Vehicle detection model name (without .hef)",
        )
        parser.add_argument(
            "--plate-model",
            default=DEFAULT_PLATE_MODEL_NAME,
            help="License-plate detection model name (without .hef)",
        )
        parser.add_argument(
            "--vehicle-json",
            default=DEFAULT_VEHICLE_JSON_PATH,
            help="Vehicle detection JSON config (path or resources/json filename)",
        )
        parser.add_argument(
            "--plate-json",
            default=DEFAULT_PLATE_JSON_PATH,
            help="Plate detection JSON config (path or resources/json filename)",
        )
        parser.add_argument(
            "--yolo-postprocess-so",
            default=DEFAULT_YOLO_POSTPROCESS_SO,
            help="YOLO postprocess shared object filename",
        )
        parser.add_argument(
            "--vehicle-postprocess-function",
            default=DEFAULT_VEHICLE_POSTPROCESS_FUNCTION,
            help="Vehicle detection postprocess function name",
        )
        parser.add_argument(
            "--plate-postprocess-function",
            default=DEFAULT_PLATE_POSTPROCESS_FUNCTION,
            help="Plate detection postprocess function name",
        )
        parser.add_argument(
            "--croppers-so",
            default=DEFAULT_LPR_CROPPERS_SO,
            help="Croppers shared object filename",
        )
        parser.add_argument(
            "--vehicle-cropper-function",
            default=DEFAULT_VEHICLE_CROPPER_FUNCTION,
            help="Vehicle cropper function name (runs plate detection on vehicle crops)",
        )
        parser.add_argument(
            "--lp-cropper-function",
            default=DEFAULT_LP_CROPPER_FUNCTION,
            help="License-plate cropper function name (feeds OCR on cropped license plates)",
        )
        parser.add_argument(
            "--overlay-so",
            default=DEFAULT_LPR_OVERLAY_SO,
            help="Overlay shared object filename (optional; depends on installed resources)",
        )
        parser.add_argument(
            "--ocrsink-so",
            default=DEFAULT_LPR_OCRSINK_SO,
            help="OCR sink shared object filename (optional; depends on installed resources)",
        )
        parser.add_argument(
            "--lp-cropsink-so",
            default=DEFAULT_LPR_LP_CROPSINK_SO,
            help="LP crop saver shared object filename (optional; depends on installed resources)",
        )
        parser.add_argument(
            "--save-vehicle-crops",
            action="store_true",
            default=True,
            help="Save cropped vehicle images to disk (per track, until LP is found)",
        )
        parser.add_argument(
            "--save-lp-crops",
            action="store_true",
            default=True,
            help="Save cropped license-plate images to disk (per track, first LP found)",
        )
        parser.add_argument(
            "--crops-dir",
            default="lpr_crops",
            help="Output directory for saved crops",
        )
        parser.add_argument(
            "--disable-found-lp-gate",
            action="store_true",
            help="Disable per-track found_lp gating (keeps running LP detection even after LP is found)",
        )
        parser.add_argument(
            "--print-pipeline",
            action="store_true",
            help="Print the GStreamer pipeline in gst-launch-1.0 CLI format and exit",
        )
        super().__init__(parser, user_data)

        self.batch_size = 2
        nms_score_threshold = 0.3
        nms_iou_threshold = 0.45
        self.pipeline_type = self.options_menu.pipeline
        self.ocr_mode = getattr(self.options_menu, "ocr_mode", "paddle_ocr")
        self.silent_logs = os.getenv("HAILO_LPR_SILENT", "0").lower() not in ("0", "", "false", "no")
        self.print_pipeline_mode = getattr(self.options_menu, "print_pipeline", False) or self.silent_logs
        # Pass LPR-specific options through user_data so the callback can access them
        self.user_data.save_vehicle_crops = bool(getattr(self.options_menu, "save_vehicle_crops", False))
        self.user_data.save_lp_crops = bool(getattr(self.options_menu, "save_lp_crops", False))
        self.user_data.crops_dir = str(getattr(self.options_menu, "crops_dir", "lpr_crops"))
        self.user_data.disable_found_lp_gate = bool(getattr(self.options_menu, "disable_found_lp_gate", False))
        # Ensure frames are available to the callback when crop saving is enabled
        if self.user_data.save_vehicle_crops or self.user_data.save_lp_crops:
            self.user_data.use_frame = True
            os.environ["HAILO_LPR_SAVE_CROPS"] = "1"
            os.environ["HAILO_LPR_CROPS_DIR"] = self.user_data.crops_dir
        else:
            os.environ["HAILO_LPR_SAVE_CROPS"] = "0"

        # Prefer a dedicated demo video when user didn't set --input
        if self.options_menu.input is None:
            self.video_source = get_resource_path(
                pipeline_name=LPR_PIPELINE,
                resource_type=RESOURCES_VIDEOS_DIR_NAME,
                model="lpr_video.mp4",
            )

        # Vehicle detection resources
        vehicle_model = self.options_menu.vehicle_model
        if not self.print_pipeline_mode:
            print("Vehicle model:", vehicle_model)
        self.vehicle_hef_path = get_resource_path(
            pipeline_name=LPR_PIPELINE,
            resource_type=RESOURCES_MODELS_DIR_NAME,
            arch=self.arch,
            model=vehicle_model,
        )
        self.vehicle_post_process_so = self._resolve_so_path(
            self.options_menu.yolo_postprocess_so, fallback_name=DEFAULT_YOLO_POSTPROCESS_SO
        )
        self.vehicle_post_function_name = self.options_menu.vehicle_postprocess_function
        self.vehicle_json = self._resolve_json_path(self.options_menu.vehicle_json, fallback_name=f"{vehicle_model}.json")
        self.vehicle_cropper_function = self.options_menu.vehicle_cropper_function

        # License-plate detection resources
        plate_model = self.options_menu.plate_model
        self.license_det_hef_path = get_resource_path(
            pipeline_name=LPR_PIPELINE,
            resource_type=RESOURCES_MODELS_DIR_NAME,
            arch=self.arch,
            model=plate_model,
        )
        self.license_det_post_process_so = self._resolve_so_path(
            self.options_menu.yolo_postprocess_so, fallback_name=DEFAULT_YOLO_POSTPROCESS_SO
        )
        self.license_det_post_function_name = self.options_menu.plate_postprocess_function
        self.license_json = self._resolve_json_path(self.options_menu.plate_json, fallback_name=f"{plate_model}.json")

        # OCR resources - support both paddle_ocr and legacy modes
        if self.ocr_mode == "paddle_ocr":
            self.ocr_hef_path = get_resource_path(
                pipeline_name=LPR_PIPELINE,
                resource_type=RESOURCES_MODELS_DIR_NAME,
                arch=self.arch,
                model=OCR_RECOGNITION_MODEL_NAME,
            )
            self.ocr_post_process_so = get_resource_path(
                pipeline_name=LPR_PIPELINE,
                resource_type=RESOURCES_SO_DIR_NAME,
                model=OCR_POSTPROCESS_SO_FILENAME,
            )
            self.ocr_post_function_name = OCR_RECOGNITION_POSTPROCESS_FUNCTION
        else:
            # Legacy OCR: treat it as a YOLO-like model + postprocess function
            self.ocr_hef_path = get_resource_path(
                pipeline_name=LPR_PIPELINE,
                resource_type=RESOURCES_MODELS_DIR_NAME,
                arch=self.arch,
                model=OCR_RECOGNITION_MODEL_NAME,
            )
            self.ocr_post_process_so = self._resolve_so_path(
                self.options_menu.yolo_postprocess_so, fallback_name=DEFAULT_YOLO_POSTPROCESS_SO
            )
            self.ocr_post_function_name = "filter_letterbox"

        # Overlay / croppers / sinks (filenames depend on installed resources)
        self.lpr_overlay_so = self._resolve_so_path(self.options_menu.overlay_so, fallback_name=DEFAULT_LPR_OVERLAY_SO)
        self.lpr_ocrsink_so = self._resolve_so_path(self.options_menu.ocrsink_so, fallback_name=DEFAULT_LPR_OCRSINK_SO)
        self.lpr_croppers_so = self._resolve_so_path(self.options_menu.croppers_so, fallback_name=DEFAULT_LPR_CROPPERS_SO)
        self.lpr_quality_est_function = self.options_menu.lp_cropper_function
        self.lpr_lp_cropsink_so = self._resolve_so_path(self.options_menu.lp_cropsink_so, fallback_name=DEFAULT_LPR_LP_CROPSINK_SO)

        self.app_callback = app_callback

        self.thresholds_str = (
            f"nms-score-threshold={nms_score_threshold} "
            f"nms-iou-threshold={nms_iou_threshold} "
            f"output-format-type=HAILO_FORMAT_TYPE_FLOAT32"
        )

        # Set process title
        setproctitle.setproctitle(LPR_APP_TITLE)
        hailo_logger.debug("Process title set to %s", LPR_APP_TITLE)

        self.create_pipeline()
        hailo_logger.debug("Pipeline created")

        # If --print-pipeline is set, print the CLI format and exit
        if getattr(self.options_menu, "print_pipeline", False):
            self.print_pipeline_cli()
            import sys
            sys.exit(0)

    @staticmethod
    def _resolve_json_path(value: str | None, fallback_name: str) -> Path | None:
        """
        Resolve a JSON config path.

        Rules:
        - If `value` is an existing path (absolute or relative), use it.
        - Else treat `value` (or fallback) as a filename under resources/json.
        """
        candidate = value or fallback_name
        if not candidate:
            return None

        candidate_path = Path(candidate)
        if candidate_path.is_absolute() and candidate_path.exists():
            return candidate_path
        rel_path = Path.cwd() / candidate_path
        if rel_path.exists():
            return rel_path

        # Fall back to resources/json
        return get_resource_path(
            pipeline_name=LPR_PIPELINE,
            resource_type=RESOURCES_JSON_DIR_NAME,
            model=candidate,
        )

    @staticmethod
    def _resolve_so_path(value: str | None, fallback_name: str) -> Path | None:
        """
        Resolve a shared-object (.so) path.

        Rules:
        - If `value` is an existing path (absolute or relative), use it.
        - Else treat `value` (or fallback) as a filename under resources/so.
        """
        candidate = value or fallback_name
        if not candidate:
            return None

        candidate_path = Path(candidate)
        if candidate_path.is_absolute() and candidate_path.exists():
            return candidate_path
        rel_path = Path.cwd() / candidate_path
        if rel_path.exists():
            return rel_path

        return get_resource_path(
            pipeline_name=LPR_PIPELINE,
            resource_type=RESOURCES_SO_DIR_NAME,
            model=candidate,
        )

    def print_pipeline_cli(self):
        """
        Print the GStreamer pipeline in gst-launch-1.0 CLI format.
        
        Output includes:
        - Pipeline variant name
        - Full gst-launch-1.0 command ready to copy/paste
        - All available pipeline variants for reference
        """
        pipeline_string = self.get_pipeline_string()
        
        # Clean up the pipeline string for CLI (remove excessive whitespace)
        cli_pipeline = " ".join(pipeline_string.split())
        
        print("\n" + "=" * 80)
        print(f"PIPELINE VARIANT: {self.pipeline_type}")
        print("=" * 80)
        
        print("\n--- GStreamer CLI Command ---\n")
        print(f"gst-launch-1.0 {cli_pipeline}")
        
        print("\n--- Pipeline String (formatted) ---\n")
        # Pretty print with each element on its own line
        formatted = pipeline_string.replace(" ! ", " ! \\\n    ")
        print(f"gst-launch-1.0 \\\n    {formatted}")
        
        print("\n--- Available Pipeline Variants ---\n")
        variants = [
            ("simple", "Full LPR: Vehicle → Tracker → LP → OCR with display aggregators"),
            ("complex", "Full LPR: Explicit low-level GStreamer elements"),
            ("optimized", "Full LPR: Parallel display/processing with quality filter"),
            ("optimized_direct", "Full LPR: Parallel display/processing, no quality filter"),
            ("optimized_direct_display_end", "Full LPR: Direct pipeline with display at end, reduced queues"),
            ("full", "Full LPR: Vehicle + LP + OCR in a single sequential pipeline"),
            ("candidate", "Full LPR: Hardcoded paths (debugging)"),
            ("vehicle_and_lp", "Vehicle + LP detection only (no OCR)"),
            ("vehicle_and_lp_crop", "Vehicle + LP detection with LP crop display + saving (no OCR)"),
            ("vehicle_only", "Vehicle detection only"),
            ("lp_only", "LP detection on full frame only"),
            ("lp_only_crops", "LP detection + crop saving (no display)"),
            ("lp_and_ocr", "Full-frame LP + OCR (no vehicle detection)"),
            ("lp_and_ocr_direct", "Full-frame LP + OCR with explicit elements"),
            ("ocr_only", "OCR model only (testing)"),
        ]
        for name, desc in variants:
            marker = " <-- CURRENT" if name == self.pipeline_type else ""
            print(f"  --pipeline {name:20s} : {desc}{marker}")
        
        print("\n" + "=" * 80)
        print("To use a different pipeline, run with: --pipeline <variant_name>")
        print("=" * 80 + "\n")

    def get_pipeline_string(self):
        if self.pipeline_type == "simple":
            if not self.print_pipeline_mode:
                print("Getting simple pipeline string")
            return self.get_pipeline_string_simple()
        if self.pipeline_type == "optimized":
            if not self.print_pipeline_mode:
                print("Getting optimized pipeline string")
            return self.get_pipeline_string_optimized()
        if self.pipeline_type == "optimized_direct":
            if not self.print_pipeline_mode:
                print("Getting optimized_direct pipeline string (no LP quality estimation)")
            return self.get_pipeline_string_optimized_direct()
        if self.pipeline_type == "optimized_direct_display_end":
            if not self.print_pipeline_mode:
                print("Getting optimized_direct_display_end pipeline string (display at end, reduced queues)")
            return self.get_pipeline_string_optimized_direct_display_end()
        if self.pipeline_type == "candidate":
            if not self.print_pipeline_mode:
                print("Getting candidate pipeline string")
            return self.get_pipeline_string_candidate()
        if self.pipeline_type == "vehicle_and_lp":
            if not self.print_pipeline_mode:
                print("Getting vehicle_and_lp pipeline string")
            return self.get_pipeline_string_vehicle_and_lp()
        if self.pipeline_type == "vehicle_and_lp_crop":
            if not self.print_pipeline_mode:
                print("Getting vehicle_and_lp_crop pipeline string")
            return self.get_pipeline_string_vehicle_and_lp_crop()
        if self.pipeline_type == "lp_only":
            if not self.print_pipeline_mode:
                print("Getting lp_only pipeline string")
            return self.get_pipeline_string_lp_only()
        if self.pipeline_type == "vehicle_only":
            if not self.print_pipeline_mode:
                print("Getting vehicle_only pipeline string")
            return self.get_pipeline_string_vehicle_only()
        if self.pipeline_type == "ocr_only":
            if not self.print_pipeline_mode:
                print("Getting ocr_only pipeline string")
            return self.get_pipeline_string_ocr_only()
        if self.pipeline_type == "lp_only_crops":
            if not self.print_pipeline_mode:
                print("Getting lp_only_crops pipeline string")
            return self.get_pipeline_string_lp_only_crops()
        if self.pipeline_type == "lp_and_ocr":
            if not self.print_pipeline_mode:
                print("Getting lp_and_ocr pipeline string")
            return self.get_pipeline_string_lp_and_ocr()
        if self.pipeline_type == "lp_and_ocr_direct":
            if not self.print_pipeline_mode:
                print("Getting lp_and_ocr_direct pipeline string")
            return self.get_pipeline_string_lp_and_ocr_direct()
        if self.pipeline_type == "full":
            if not self.print_pipeline_mode:
                print("Getting full pipeline string")
            return self.get_pipeline_string_full()
        if not self.print_pipeline_mode:
            print("Getting complex pipeline string")
        return self.get_pipeline_string_complex()

    def on_eos(self):
        hailo_logger.info("End of Stream - stopping (no loop for LPR app)")
        self.shutdown()

    def get_pipeline_string_simple(self):
        # 1) Source
        source_pipeline = SOURCE_PIPELINE(
            video_source=self.video_source,
            video_width=self.video_width,
            video_height=self.video_height,
            frame_rate=self.frame_rate,
            sync=self.sync,
            decode_queue_max_size_buffers=3,
            decode_caps="video/x-raw",
        )

        # 2) Vehicle detection
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

        # 3) Tracking
        tracker_pipeline = TRACKER_PIPELINE(
            class_id=-1,               # Track all classes
            kalman_dist_thr=0.5,
            iou_thr=0.6,
            keep_tracked_frames=2,
            keep_lost_frames=2,
            keep_past_metadata=True,
            name="hailo_tracker",
        )

        # 4) Plate detection (inner pipe for cropper)
        plate_detection = INFERENCE_PIPELINE(
            hef_path=self.license_det_hef_path,
            post_process_so=self.license_det_post_process_so,
            post_function_name=self.license_det_post_function_name,
            config_json=self.license_json,
            additional_params=self.thresholds_str,
            batch_size=4,
            scheduler_timeout_ms=100,
            name="plate_detection",
        )

        # 5) Vehicle cropper w/ plate detection
        vehicle_cropper = CROPPER_PIPELINE(
            inner_pipeline=plate_detection,
            so_path=self.lpr_croppers_so,
            function_name=self.vehicle_cropper_function,  
            internal_offset=True,
            name="vehicle_cropper",
        )

        # 6) OCR (runs on cropped license plates)
        ocr_detection = INFERENCE_PIPELINE(
            hef_path=self.ocr_hef_path,
            post_process_so=self.ocr_post_process_so,
            post_function_name=self.ocr_post_function_name,
            batch_size=8,
            scheduler_timeout_ms=100,
            name="ocr_detection",
        )

        # 7) License plate cropper (crops license plates and runs OCR on them)
        lp_cropper = CROPPER_PIPELINE(
            inner_pipeline=ocr_detection,
            so_path=self.lpr_croppers_so,
            function_name=self.lpr_quality_est_function,
            internal_offset=True,
            name="lp_cropper",
        )

        # 8) Display
        display_pipeline = DISPLAY_PIPELINE(
            video_sink=self.video_sink,
            sync="false",
            show_fps=self.show_fps,
            overlay_so=self.lpr_overlay_so,
            queue_max_size_buffers=DEFAULT_DISPLAY_QUEUE_SIZE,
            queue_leaky="no",
        )

        # Full graph: Vehicle Detection -> LP Detection -> OCR
        # Structure: vehicle_cropper outputs vehicles with LP detections nested
        # Then lp_cropper crops the LP regions and runs OCR on them
        pipeline_string = (
            f"{source_pipeline} ! "
            f"{vehicle_detection_wrapper} ! "
            f"{tracker_pipeline} ! "
            f"tee name=context_tee "

            # Processing branch: vehicle crop -> LP det -> LP crop -> OCR -> sink
            f"context_tee. ! {vehicle_cropper} ! "
            f"tee name=vehicle_cropper_tee "
            f"hailoaggregator name=agg2 "
            f"vehicle_cropper_tee. ! queue ! agg2.sink_0 "
            f"vehicle_cropper_tee. ! queue ! {lp_cropper} ! queue ! agg2.sink_1 "
            f"agg2. ! queue ! "
            f"tee name=postproc_tee "

            # Display branch: merge original frames + full metadata (vehicle + LP + OCR)
            f"postproc_tee. ! queue ! hailoaggregator name=display_agg "
            f"context_tee. ! queue ! display_agg.sink_1 "
            f"display_agg. ! queue ! {display_pipeline} "

            # OCR sink branch (Python callback via identity_callback)
            f"postproc_tee. ! queue ! "
            f"identity name=identity_callback ! "
            f"hailofilter use-gst-buffer=true "
            f"so-path={self.lpr_ocrsink_so} "
            f"qos=false ! "
            f"fakesink sync=false async=false"
        )
        if not self.print_pipeline_mode:
            print(pipeline_string)
        return pipeline_string

    def get_pipeline_string_lp_only(self):
        # 1) Source
        source_pipeline = SOURCE_PIPELINE(
            video_source=self.video_source,
            video_width=self.video_width,
            video_height=self.video_height,
            frame_rate=self.frame_rate,
            sync=self.sync,
        )

        # 2) License plate detection on full frame
        plate_detection = INFERENCE_PIPELINE(
            hef_path=self.license_det_hef_path,
            post_process_so=self.license_det_post_process_so,
            post_function_name=self.license_det_post_function_name,
            config_json=self.license_json,
            additional_params=self.thresholds_str,
            batch_size=4,
            scheduler_timeout_ms=100,
            name="plate_detection",
        )
        plate_detection_wrapper = INFERENCE_PIPELINE_WRAPPER(plate_detection)

        # 3) LP crop saver (C++ filter with access to GstVideoFrame)
        lp_crop_saver = (
            "hailofilter use-gst-buffer=true "
            f"so-path={self.lpr_lp_cropsink_so} "
        )

        # 4) User callback (optional; keeps identity_callback available)
        user_callback = USER_CALLBACK_PIPELINE()

        # 5) Display with standard overlay
        display_pipeline = DISPLAY_PIPELINE(
            video_sink=self.video_sink,
            sync=self.sync,
            show_fps=self.show_fps,
            overlay_so=self.lpr_overlay_so,
            queue_max_size_buffers=DEFAULT_DISPLAY_QUEUE_SIZE,
            queue_leaky=DEFAULT_DISPLAY_QUEUE_LEAKY,
        )

        pipeline_string = (
            f"{source_pipeline} ! "
            f"{plate_detection_wrapper} ! "
            f"{lp_crop_saver} ! "
            f"{user_callback} ! "
            f"{display_pipeline}"
        )

        if not self.print_pipeline_mode:
            print(pipeline_string)
        return pipeline_string

    def get_pipeline_string_lp_and_ocr(self):
        """
        License plate detection (full frame) + OCR.
        Uses a full-frame LP cropper (license_plate_fullframe) to feed OCR.
        """
        source_pipeline = SOURCE_PIPELINE(
            video_source=self.video_source,
            video_width=self.video_width,
            video_height=self.video_height,
            frame_rate=self.frame_rate,
            sync=self.sync,
        )

        plate_detection = INFERENCE_PIPELINE(
            hef_path=self.license_det_hef_path,
            post_process_so=self.license_det_post_process_so,
            post_function_name=self.license_det_post_function_name,
            config_json=self.license_json,
            additional_params=self.thresholds_str,
            batch_size=4,
            scheduler_timeout_ms=100,
            name="plate_detection",
        )
        plate_detection_wrapper = INFERENCE_PIPELINE_WRAPPER(
            plate_detection,
            bypass_max_size_buffers=30,
            name="plate_wrapper",
        )

        lp_tracker = TRACKER_PIPELINE(
            class_id=-1,
            kalman_dist_thr=0.5,
            iou_thr=0.6,
            keep_tracked_frames=2,
            keep_lost_frames=2,
            keep_past_metadata=True,
            name="hailo_tracker",
        )

        ocr_detection = INFERENCE_PIPELINE(
            hef_path=self.ocr_hef_path,
            post_process_so=self.ocr_post_process_so,
            post_function_name=self.ocr_post_function_name,
            batch_size=8,
            scheduler_timeout_ms=100,
            name="ocr_detection",
        )

        lp_cropper = CROPPER_PIPELINE(
            inner_pipeline=ocr_detection,
            so_path=self.lpr_croppers_so,
            function_name=DEFAULT_LP_FULLFRAME_CROPPER_FUNCTION,
            internal_offset=True,
            name="lp_cropper",
        )

        display_pipeline = DISPLAY_PIPELINE(
            video_sink=self.video_sink,
            sync="false",
            show_fps=self.show_fps,
            overlay_so=self.lpr_overlay_so,
            queue_max_size_buffers=DEFAULT_DISPLAY_QUEUE_SIZE,
            queue_leaky=DEFAULT_DISPLAY_QUEUE_LEAKY,
        )

        pipeline_string = (
            f"{source_pipeline} ! "
            f"{plate_detection_wrapper} ! "
            f"{lp_tracker} ! "
            f"tee name=main_tee "
            f"main_tee. ! {QUEUE('display_q', max_size_buffers=DEFAULT_DISPLAY_QUEUE_SIZE, leaky='downstream')} ! "
            f"{display_pipeline} "
            f"main_tee. ! {QUEUE('processing_q', max_size_buffers=10)} ! "
            f"{lp_cropper} ! "
            f"{QUEUE('post_ocr_q', max_size_buffers=5)} ! "
            f"identity name=identity_callback ! "
            f"hailofilter use-gst-buffer=true "
            f"so-path={self.lpr_ocrsink_so} "
            f"qos=false ! "
            f"fakesink sync=false async=false"
        )

        if not self.print_pipeline_mode:
            print(pipeline_string)
        return pipeline_string

    def get_pipeline_string_lp_and_ocr_direct(self):
        """
        License plate detection (full frame) + OCR using a direct, explicit pipeline string.
        This variant forces decodebin to output video only to ignore audio pads.
        """
        show_fps = "True" if self.show_fps else "False"
        pipeline_string = (
            f'filesrc location="{self.video_source}" name=source ! '
            f'queue name=source_queue_decode leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! '
            f'decodebin name=source_decodebin caps=video/x-raw ! '
            f'queue name=source_scale_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! '
            f'videoscale name=source_videoscale n-threads=2 ! '
            f'queue name=source_convert_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! '
            f'videoconvert n-threads=3 name=source_convert qos=false ! '
            f'video/x-raw, pixel-aspect-ratio=1/1, format=RGB, width={self.video_width}, height={self.video_height} ! '
            f'videorate name=source_videorate ! '
            f'capsfilter name=source_fps_caps caps="video/x-raw, framerate={self.frame_rate}/1" ! '
            f'queue name=plate_detection_scale_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! '
            f'videoscale name=plate_detection_videoscale n-threads=2 qos=false ! '
            f'queue name=plate_detection_convert_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! '
            f'video/x-raw, pixel-aspect-ratio=1/1 ! '
            f'videoconvert name=plate_detection_videoconvert n-threads=2 ! '
            f'queue name=plate_detection_hailonet_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! '
            f'hailonet name=plate_detection_hailonet '
            f'hef-path={self.license_det_hef_path} '
            f'batch-size=4 '
            f'vdevice-group-id=SHARED '
            f'scheduler-timeout-ms=100 '
            f'nms-score-threshold=0.3 '
            f'nms-iou-threshold=0.45 '
            f'output-format-type=HAILO_FORMAT_TYPE_FLOAT32 '
            f'force-writable=true ! '
            f'queue name=plate_detection_hailofilter_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! '
            f'hailofilter name=plate_detection_hailofilter '
            f'so-path={self.license_det_post_process_so} '
            f'config-path={self.license_json} '
            f'function-name={self.license_det_post_function_name} '
            f'qos=false ! '
            f'queue name=plate_detection_output_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! '
            f'hailotracker name=hailo_tracker class-id=-1 kalman-dist-thr=0.5 iou-thr=0.6 '
            f'init-iou-thr=0.7 keep-new-frames=2 keep-tracked-frames=2 keep-lost-frames=2 keep-past-metadata=True '
            f'qos=False ! '
            f'queue name=hailo_tracker_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! '
            f'tee name=main_tee '
            f'main_tee. ! queue name=display_q leaky=downstream max-size-buffers=10 max-size-bytes=0 max-size-time=0 ! '
            f'queue name=hailo_display_overlay_q leaky=downstream max-size-buffers=10 max-size-bytes=0 max-size-time=0 ! '
            f'hailooverlay name=hailo_display_overlay ! '
            f'queue name=hailo_display_videoconvert_q leaky=downstream max-size-buffers=10 max-size-bytes=0 max-size-time=0 ! '
            f'videoconvert name=hailo_display_videoconvert n-threads=2 qos=false ! '
            f'queue name=hailo_display_q leaky=downstream max-size-buffers=10 max-size-bytes=0 max-size-time=0 ! '
            f'fpsdisplaysink name=hailo_display video-sink=autovideosink sync=false '
            f'text-overlay={show_fps} signal-fps-measurements=true '
            f'main_tee. ! queue name=processing_q leaky=no max-size-buffers=10 max-size-bytes=0 max-size-time=0 ! '
            f'queue name=lp_cropper_input_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! '
            f'hailocropper name=lp_cropper_cropper '
            f'so-path={self.lpr_croppers_so} '
            f'function-name={self.lpr_quality_est_function} '
            f'use-letterbox=true no-scaling-bbox=true internal-offset=true resize-method=bilinear '
            f'! queue name=ocr_detection_scale_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! '
            f'videoscale name=ocr_detection_videoscale n-threads=2 qos=false ! '
            f'queue name=ocr_detection_convert_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! '
            f'video/x-raw, pixel-aspect-ratio=1/1 ! '
            f'videoconvert name=ocr_detection_videoconvert n-threads=2 ! '
            f'queue name=ocr_detection_hailonet_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! '
            f'hailonet name=ocr_detection_hailonet '
            f'hef-path={self.ocr_hef_path} '
            f'batch-size=8 '
            f'vdevice-group-id=SHARED '
            f'scheduler-timeout-ms=100 '
            f'force-writable=true ! '
            f'queue name=ocr_detection_hailofilter_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! '
            f'hailofilter name=ocr_detection_hailofilter '
            f'so-path={self.ocr_post_process_so} '
            f'function-name={self.ocr_post_function_name} '
            f'qos=false ! '
            f'queue name=ocr_detection_output_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! '
            f'queue name=post_ocr_q leaky=no max-size-buffers=5 max-size-bytes=0 max-size-time=0 ! '
            f'identity name=identity_callback ! '
            f'hailofilter use-gst-buffer=true '
            f'so-path={self.lpr_ocrsink_so} '
            f'qos=false ! '
            f'fakesink sync=false async=false'
        )
        if not self.print_pipeline_mode:
            print(pipeline_string)
        return pipeline_string

    def get_pipeline_string_lp_only_crops(self):
        """
        License plate detection (full frame) + crop saving (no OCR, no display).
        Uses license_plate_fullframe to save LP crops from full-frame detections.
        """
        source_pipeline = SOURCE_PIPELINE(
            video_source=self.video_source,
            video_width=self.video_width,
            video_height=self.video_height,
            frame_rate=self.frame_rate,
            sync=self.sync,
        )

        plate_detection = INFERENCE_PIPELINE(
            hef_path=self.license_det_hef_path,
            post_process_so=self.license_det_post_process_so,
            post_function_name=self.license_det_post_function_name,
            config_json=self.license_json,
            additional_params=self.thresholds_str,
            batch_size=4,
            scheduler_timeout_ms=100,
            name="plate_detection",
        )
        plate_detection_wrapper = INFERENCE_PIPELINE_WRAPPER(
            plate_detection,
            bypass_max_size_buffers=30,
            name="plate_wrapper",
        )

        lp_cropper = CROPPER_PIPELINE(
            inner_pipeline=f"{QUEUE('lp_cropper_passthrough_q')} ! identity name=lp_cropper_passthrough",
            so_path=self.lpr_croppers_so,
            function_name=DEFAULT_LP_FULLFRAME_CROPPER_FUNCTION,
            internal_offset=True,
            name="lp_cropper",
        )

        user_callback_pipeline = USER_CALLBACK_PIPELINE()

        pipeline_string = (
            f"{source_pipeline} ! "
            f"{plate_detection_wrapper} ! "
            f"{lp_cropper} ! "
            f"{user_callback_pipeline} ! "
            f"fakesink sync=false async=false"
        )

        if not self.print_pipeline_mode:
            print(pipeline_string)
        return pipeline_string

    def get_pipeline_string_candidate(self):
        # Construct libwhole_buffer.so path similar to INFERENCE_PIPELINE_WRAPPER
        tappas_post_process_dir = os.environ.get(TAPPAS_POSTPROC_PATH_KEY, TAPPAS_POSTPROC_PATH_DEFAULT)
        whole_buffer_crop_so = os.path.join(
            tappas_post_process_dir, "cropping_algorithms/libwhole_buffer.so"
        ) if tappas_post_process_dir else "/usr/lib/x86_64-linux-gnu/hailo/tappas/post_processes/cropping_algorithms/libwhole_buffer.so"
        
        pipeline_string = (
            f'filesrc location="{self.video_source}" name=source ! '
            "queue name=source_queue_decode leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! "
            "decodebin name=source_decodebin ! "
            "queue name=source_scale_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! "
            "videoscale name=source_videoscale n-threads=2 ! "
            "queue name=source_convert_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! "
            "videoconvert n-threads=3 name=source_convert qos=false ! "
            "video/x-raw, pixel-aspect-ratio=1/1, format=RGB, width=1280, height=720 ! "
            "videorate name=source_videorate ! "
            "capsfilter name=source_fps_caps caps=\"video/x-raw, framerate=15/1\" ! "
            "queue name=vehicle_wrapper_input_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! "
            f"hailocropper name=vehicle_wrapper_crop "
            f"so-path={whole_buffer_crop_so} "
            "function-name=create_crops use-letterbox=true resize-method=inter-area internal-offset=true "
            "hailoaggregator name=vehicle_wrapper_agg "
            "vehicle_wrapper_crop. ! queue name=vehicle_wrapper_bypass_q leaky=no max-size-buffers=30 "
            "max-size-bytes=0 max-size-time=0 ! vehicle_wrapper_agg.sink_0 "
            "vehicle_wrapper_crop. ! queue name=vehicle_detection_scale_q leaky=no max-size-buffers=3 "
            "max-size-bytes=0 max-size-time=0 ! "
            "videoscale name=vehicle_detection_videoscale n-threads=2 qos=false ! "
            "queue name=vehicle_detection_convert_q leaky=no max-size-buffers=3 max-size-bytes=0 "
            "max-size-time=0 ! "
            "video/x-raw, pixel-aspect-ratio=1/1 ! "
            "videoconvert name=vehicle_detection_videoconvert n-threads=2 qos=false ! "
            "queue name=vehicle_detection_hailonet_q leaky=no max-size-buffers=3 max-size-bytes=0 "
            "max-size-time=0 ! "
            f"hailonet name=vehicle_detection_hailonet "
            f"hef-path={self.vehicle_hef_path} batch-size=2 "
            "vdevice-group-id=SHARED scheduler-timeout-ms=66 nms-score-threshold=0.3 "
            "nms-iou-threshold=0.45 output-format-type=HAILO_FORMAT_TYPE_FLOAT32 force-writable=true ! "
            "queue name=vehicle_detection_hailofilter_q leaky=no max-size-buffers=3 max-size-bytes=0 "
            "max-size-time=0 ! "
            f"hailofilter name=vehicle_detection_hailofilter "
            f"so-path={self.vehicle_post_process_so} "
            f"config-path={self.vehicle_json} "
            "function-name=yolov5m_vehicles qos=false ! "
            "queue name=vehicle_detection_output_q leaky=no max-size-buffers=3 max-size-bytes=0 "
            "max-size-time=0 ! "
            "vehicle_wrapper_agg.sink_1 "
            "vehicle_wrapper_agg. ! queue name=vehicle_wrapper_output_q leaky=no max-size-buffers=3 "
            "max-size-bytes=0 max-size-time=0 ! "
            "hailotracker name=vehicle_tracker class-id=-1 kalman-dist-thr=0.5 iou-thr=0.6 "
            "init-iou-thr=0.7 keep-new-frames=2 keep-tracked-frames=5 keep-lost-frames=3 "
            "keep-past-metadata=True qos=False ! "
            "queue name=vehicle_tracker_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! "
            "tee name=main_tee "
            "main_tee. ! queue name=lpr_display_q leaky=downstream max-size-buffers=10 "
            "max-size-bytes=0 max-size-time=50000000 ! "
            "hailooverlay name=lpr_display_overlay line-thickness=3 font-thickness=1 qos=false ! "
            f"hailofilter use-gst-buffer=true so-path={self.lpr_overlay_so} qos=false ! "
            "queue name=lpr_display_convert_q leaky=downstream max-size-buffers=10 "
            "max-size-bytes=0 max-size-time=50000000 ! "
            "videoconvert name=lpr_display_videoconvert n-threads=2 qos=false ! "
            "queue name=lpr_display_sink_q leaky=downstream max-size-buffers=10 "
            "max-size-bytes=0 max-size-time=50000000 ! "
            "fpsdisplaysink name=lpr_display video-sink=autovideosink sync=false text-overlay=False "
            "signal-fps-measurements=true "
            "main_tee. ! queue name=processing_q leaky=downstream max-size-buffers=4 "
            "max-size-bytes=0 max-size-time=50000000 ! "
            "queue name=vehicle_cropper_input_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! "
            "hailocropper name=vehicle_cropper_cropper "
            f"so-path={self.lpr_croppers_so} function-name=vehicles_without_ocr "
            "use-letterbox=true no-scaling-bbox=true internal-offset=true resize-method=bilinear "
            "hailoaggregator name=vehicle_cropper_agg "
            "vehicle_cropper_cropper. ! queue name=vehicle_cropper_bypass_q leaky=downstream "
            "max-size-buffers=30 max-size-bytes=0 max-size-time=0 ! vehicle_cropper_agg.sink_0 "
            "vehicle_cropper_cropper. ! queue name=plate_detection_scale_q leaky=no max-size-buffers=3 "
            "max-size-bytes=0 max-size-time=0 ! "
            "videoscale name=plate_detection_videoscale n-threads=2 qos=false ! "
            "queue name=plate_detection_convert_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! "
            "video/x-raw, pixel-aspect-ratio=1/1 ! "
            "videoconvert name=plate_detection_videoconvert n-threads=2 qos=false ! "
            "queue name=plate_detection_hailonet_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! "
            f"hailonet name=plate_detection_hailonet "
            f"hef-path={self.license_det_hef_path} "
            "batch-size=4 vdevice-group-id=SHARED scheduler-timeout-ms=66 nms-score-threshold=0.3 "
            "nms-iou-threshold=0.45 output-format-type=HAILO_FORMAT_TYPE_FLOAT32 force-writable=true ! "
            "queue name=plate_detection_hailofilter_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! "
            f"hailofilter name=plate_detection_hailofilter "
            f"so-path={self.license_det_post_process_so} "
            f"config-path={self.license_json} "
            "function-name=yolov8n_relu6_license_plate qos=false ! "
            "queue name=plate_detection_output_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! "
            "vehicle_cropper_agg.sink_1 "
            "vehicle_cropper_agg. ! queue name=vehicle_cropper_output_q leaky=no max-size-buffers=3 "
            "max-size-bytes=0 max-size-time=0 ! "
            "queue name=pre_lp_crop_q leaky=downstream max-size-buffers=4 max-size-bytes=0 max-size-time=50000000 ! "
            "queue name=lp_cropper_input_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! "
            "hailocropper name=lp_cropper_cropper "
            f"so-path={self.lpr_croppers_so} "
            "function-name=license_plate_no_quality use-letterbox=true no-scaling-bbox=true "
            "internal-offset=true resize-method=bilinear "
            "hailoaggregator name=lp_cropper_agg "
            "lp_cropper_cropper. ! queue name=lp_cropper_bypass_q leaky=downstream max-size-buffers=30 "
            "max-size-bytes=0 max-size-time=0 ! lp_cropper_agg.sink_0 "
            "lp_cropper_cropper. ! queue name=ocr_detection_scale_q leaky=no max-size-buffers=3 "
            "max-size-bytes=0 max-size-time=0 ! "
            "videoscale name=ocr_detection_videoscale n-threads=2 qos=false ! "
            "queue name=ocr_detection_convert_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! "
            "video/x-raw, pixel-aspect-ratio=1/1 ! "
            "videoconvert name=ocr_detection_videoconvert n-threads=2 qos=false ! "
            "queue name=ocr_detection_hailonet_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! "
            f"hailonet name=ocr_detection_hailonet "
            f"hef-path={self.ocr_hef_path} batch-size=8 "
            "vdevice-group-id=SHARED scheduler-timeout-ms=66 force-writable=true ! "
            "queue name=ocr_detection_hailofilter_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! "
            f"hailofilter name=ocr_detection_hailofilter "
            f"so-path={self.ocr_post_process_so} "
            f"function-name={self.ocr_post_function_name} qos=false ! "
            "queue name=ocr_detection_output_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! "
            "lp_cropper_agg.sink_1 "
            "lp_cropper_agg. ! queue name=lp_cropper_output_q leaky=no max-size-buffers=3 max-size-bytes=0 "
            "max-size-time=0 ! "
            "queue name=post_ocr_q leaky=downstream max-size-buffers=2 max-size-bytes=0 max-size-time=50000000 ! "
            "identity name=identity_callback ! "
            f"hailofilter use-gst-buffer=true so-path={self.lpr_ocrsink_so} qos=false ! "
            "fakesink sync=false async=false"
        )

        if not self.print_pipeline_mode:
            print(pipeline_string)
        return pipeline_string

    def get_pipeline_string_vehicle_and_lp(self):
        """
        Vehicle & LP Detection pipeline: Runs vehicle detection, then license plate detection on vehicle crops.
        Includes tracking so per-track state (e.g., found_lp) can be maintained in the Python callback.
        Displays results with bounding boxes for both vehicles and plates.
        No OCR - just detection visualization.
        """
        # 1) Source
        source_pipeline = SOURCE_PIPELINE(
            video_source=self.video_source,
            video_width=self.video_width,
            video_height=self.video_height,
            frame_rate=self.frame_rate,
            sync=self.sync,
        )

        # 2) Vehicle detection with wrapper (maintains original resolution)
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

        # 3) Tracker (enables per-vehicle unique IDs)
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

        # 4) Plate detection (inner pipeline for cropping detected vehicles)
        plate_detection = INFERENCE_PIPELINE(
            hef_path=self.license_det_hef_path,
            post_process_so=self.license_det_post_process_so,
            post_function_name=self.license_det_post_function_name,
            config_json=self.license_json,
            additional_params=self.thresholds_str,
            batch_size=8,
            scheduler_timeout_ms=100,
            name="plate_detection",
        )

        # 5) Crop vehicles and run plate detection on each
        vehicle_cropper = CROPPER_PIPELINE(
            inner_pipeline=plate_detection,
            so_path=self.lpr_croppers_so,
            function_name=self.vehicle_cropper_function,
            internal_offset=True,
            name="vehicle_cropper",
        )

        # 6) User callback (for per-track found_lp, crop saving, etc.)
        user_callback = "identity name=identity_callback"

        # 7) Display with overlay
        display_pipeline = DISPLAY_PIPELINE(
            video_sink=self.video_sink,
            sync="false",
            show_fps=self.show_fps,
            overlay_so=self.lpr_overlay_so,
            queue_max_size_buffers=DEFAULT_DISPLAY_QUEUE_SIZE,
            queue_leaky=DEFAULT_DISPLAY_QUEUE_LEAKY,
        )

        # Sequential pipeline: Vehicle detection -> Tracker -> Plate detection on vehicles -> Callback -> Display
        pipeline_string = (
            f"{source_pipeline} ! "
            f"{vehicle_detection_wrapper} ! "
            f"{tracker_pipeline} ! "
            f"{vehicle_cropper} ! "
            f"{user_callback} ! "
            f"{display_pipeline}"
        )

        if not self.print_pipeline_mode:
            print(pipeline_string)
        return pipeline_string

    def get_pipeline_string_vehicle_and_lp_crop(self):
        """
        Vehicle & LP Detection pipeline with LP crop saving (no OCR).
        Same display behavior as vehicle_and_lp, plus license-plate crop saving.
        """
        # 1) Source
        source_pipeline = SOURCE_PIPELINE(
            video_source=self.video_source,
            video_width=self.video_width,
            video_height=self.video_height,
            frame_rate=self.frame_rate,
            sync=self.sync,
        )

        # 2) Vehicle detection with wrapper (maintains original resolution)
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

        # 3) Tracker (enables per-vehicle unique IDs)
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

        # 4) Plate detection (inner pipeline for cropping detected vehicles)
        plate_detection = INFERENCE_PIPELINE(
            hef_path=self.license_det_hef_path,
            post_process_so=self.license_det_post_process_so,
            post_function_name=self.license_det_post_function_name,
            config_json=self.license_json,
            additional_params=self.thresholds_str,
            batch_size=8,
            scheduler_timeout_ms=100,
            name="plate_detection",
        )

        # 5) Crop vehicles and run plate detection on each
        vehicle_cropper = CROPPER_PIPELINE(
            inner_pipeline=plate_detection,
            so_path=self.lpr_croppers_so,
            function_name=self.vehicle_cropper_function,
            internal_offset=True,
            name="vehicle_cropper",
        )

        # 6) LP crop saver (C++ filter with access to GstVideoFrame)
        lp_crop_saver = (
            "hailofilter use-gst-buffer=true "
            f"so-path={self.lpr_lp_cropsink_so} "
        )

        # 7) User callback (for per-track found_lp, crop saving, etc.)
        user_callback = USER_CALLBACK_PIPELINE()

        # 8) Display with overlay (same as vehicle_and_lp)
        display_pipeline = DISPLAY_PIPELINE(
            video_sink=self.video_sink,
            sync="false",
            show_fps=self.show_fps,
            overlay_so=self.lpr_overlay_so,
            queue_max_size_buffers=DEFAULT_DISPLAY_QUEUE_SIZE,
            queue_leaky=DEFAULT_DISPLAY_QUEUE_LEAKY,
        )

        pipeline_string = (
            f"{source_pipeline} ! "
            f"{vehicle_detection_wrapper} ! "
            f"{tracker_pipeline} ! "
            f"{vehicle_cropper} ! "
            f"{lp_crop_saver} ! "
            f"{user_callback} ! "
            f"{display_pipeline}"
        )

        if not self.print_pipeline_mode:
            print(pipeline_string)
        return pipeline_string

    def get_pipeline_string_vehicle_only(self):
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

        display_pipeline = DISPLAY_PIPELINE(
            video_sink=self.video_sink,
            sync="false",
            show_fps=self.show_fps,
            overlay_so=self.lpr_overlay_so,
            queue_max_size_buffers=DEFAULT_DISPLAY_QUEUE_SIZE,
            queue_leaky=DEFAULT_DISPLAY_QUEUE_LEAKY,
        )

        pipeline_string = (
            f"{source_pipeline} ! "
            f"{vehicle_detection_wrapper} ! "
            f"{display_pipeline}"
        )
        if not self.print_pipeline_mode:
            print(pipeline_string)
        return pipeline_string

    def get_pipeline_string_optimized(self):
        """
        Optimized LPR pipeline with smarter queue sizing and parallel display/processing.

        Notes:
        - Display branch is leaky to avoid blocking.
        - Processing branch runs vehicle->plate->OCR and emits OCR results via the ocrsink filter.
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
        vehicle_detection_wrapper = INFERENCE_PIPELINE_WRAPPER(
            vehicle_detection,
            name="vehicle_wrapper",
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

        plate_detection = INFERENCE_PIPELINE(
            hef_path=self.license_det_hef_path,
            post_process_so=self.license_det_post_process_so,
            post_function_name=self.license_det_post_function_name,
            config_json=self.license_json,
            additional_params=self.thresholds_str,
            batch_size=4,
            scheduler_timeout_ms=100,
            name="plate_detection",
        )

        vehicle_cropper = CROPPER_PIPELINE(
            inner_pipeline=plate_detection,
            so_path=self.lpr_croppers_so,
            function_name=self.vehicle_cropper_function,
            internal_offset=True,
            name="vehicle_cropper",
        )

        ocr_detection = INFERENCE_PIPELINE(
            hef_path=self.ocr_hef_path,
            post_process_so=self.ocr_post_process_so,
            post_function_name=self.ocr_post_function_name,
            batch_size=8,
            scheduler_timeout_ms=100,
            name="ocr_detection",
        )

        lp_cropper = CROPPER_PIPELINE(
            inner_pipeline=ocr_detection,
            so_path=self.lpr_croppers_so,
            function_name=self.lpr_quality_est_function,
            internal_offset=True,
            bypass_max_size_buffers=20,
            bypass_leaky="downstream",
            name="lp_cropper",
        )

        display_pipeline = DISPLAY_PIPELINE(
            video_sink=self.video_sink,
            sync="false",
            show_fps=self.show_fps,
            overlay_so=self.lpr_overlay_so,
            queue_max_size_buffers=DEFAULT_DISPLAY_QUEUE_SIZE,
            queue_leaky=DEFAULT_DISPLAY_QUEUE_LEAKY,
        )

        pipeline_string = (
            f"{source_pipeline} ! "
            f"{vehicle_detection_wrapper} ! "
            f"{tracker_pipeline} ! "
            f"tee name=main_tee "
            # Display branch (leaky to avoid blocking)
            f"main_tee. ! {QUEUE('display_q', max_size_buffers=5, leaky='downstream')} ! "
            f"{display_pipeline} "
            # Processing branch (vehicle -> plate -> OCR)
            f"main_tee. ! {QUEUE('processing_q', max_size_buffers=10)} ! "
            f"{vehicle_cropper} ! "
            f"{QUEUE('pre_lp_crop_q', max_size_buffers=10)} ! "
            f"{lp_cropper} ! "
            f"{QUEUE('post_ocr_q', max_size_buffers=5)} ! "
            f"identity name=identity_callback ! "
            f"hailofilter use-gst-buffer=true "
            f"so-path={self.lpr_ocrsink_so} "
            f"qos=false ! "
            f"fakesink sync=false async=false"
        )

        if not self.print_pipeline_mode:
            print(pipeline_string)
        return pipeline_string

    def get_pipeline_string_optimized_direct(self):
        """
        Optimized LPR pipeline WITHOUT LP quality estimation.
        
        Same as 'optimized' but uses 'license_plate_no_quality' instead of
        'license_plate_quality_estimation', sending ALL detected license plates
        directly to OCR without quality filtering.
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
        vehicle_detection_wrapper = INFERENCE_PIPELINE_WRAPPER(
            vehicle_detection,
            name="vehicle_wrapper",
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

        plate_detection = INFERENCE_PIPELINE(
            hef_path=self.license_det_hef_path,
            post_process_so=self.license_det_post_process_so,
            post_function_name=self.license_det_post_function_name,
            config_json=self.license_json,
            additional_params=self.thresholds_str,
            batch_size=4,
            scheduler_timeout_ms=100,
            name="plate_detection",
        )

        vehicle_cropper_function = f"{self.vehicle_cropper_function}_op"
        vehicle_cropper = CROPPER_PIPELINE(
            inner_pipeline=plate_detection,
            so_path=self.lpr_croppers_so,
            function_name=vehicle_cropper_function,
            internal_offset=True,
            name="vehicle_cropper",
        )

        ocr_post_function_name = self.ocr_post_function_name

        ocr_detection = INFERENCE_PIPELINE(
            hef_path=self.ocr_hef_path,
            post_process_so=self.ocr_post_process_so,
            post_function_name=ocr_post_function_name,
            batch_size=8,
            scheduler_timeout_ms=100,
            name="ocr_detection",
        )

        # Use license_plate_no_quality instead of license_plate_quality_estimation
        lp_cropper = CROPPER_PIPELINE(
            inner_pipeline=ocr_detection,
            so_path=self.lpr_croppers_so,
            function_name="license_plate_no_quality_no_gates_op",
            internal_offset=True,
            name="lp_cropper",
        )

        display_pipeline = DISPLAY_PIPELINE(
            video_sink=self.video_sink,
            sync="false",
            show_fps=self.show_fps,
            overlay_so=self.lpr_overlay_so,
            queue_max_size_buffers=DEFAULT_DISPLAY_QUEUE_SIZE,
            queue_leaky=DEFAULT_DISPLAY_QUEUE_LEAKY,
        )

        pipeline_string = (
            f"{source_pipeline} ! "
            f"{vehicle_detection_wrapper} ! "
            f"{tracker_pipeline} ! "
            f"tee name=main_tee "
            # Display branch (leaky to avoid blocking)
            f"main_tee. ! {QUEUE('display_q', max_size_buffers=DEFAULT_DISPLAY_QUEUE_SIZE)} ! "
            f"{display_pipeline} "
            # Processing branch (vehicle -> plate -> OCR, no quality filter)
            f"main_tee. ! {QUEUE('processing_q', max_size_buffers=10)} ! "
            f"{vehicle_cropper} ! "
            f"{QUEUE('pre_lp_crop_q', max_size_buffers=10)} ! "
            f"{lp_cropper} ! "
            f"{QUEUE('post_ocr_q', max_size_buffers=5)} ! "
            f"identity name=identity_callback ! "
            f"hailofilter use-gst-buffer=true "
            f"so-path={self.lpr_ocrsink_so} "
            f"qos=false ! "
            f"fakesink sync=false async=false"
        )

        if not self.print_pipeline_mode:
            print(pipeline_string)
        return pipeline_string

    def get_pipeline_string_optimized_direct_display_end(self):
        """
        Optimized LPR pipeline WITHOUT LP quality estimation.

        Direct pipeline with display at the end, fewer explicit queues,
        and scheduler priorities targeting a 30/5/5 FPS ratio
        (vehicle/plate/OCR hailonets).
        """
        source_pipeline = SOURCE_PIPELINE(
            video_source=self.video_source,
            video_width=self.video_width,
            video_height=self.video_height,
            frame_rate=self.frame_rate,
            sync=self.sync,
        )

        # Hailonet scheduler priorities bias compute for a ~30/5/5 ratio.
        vehicle_sched_params = f"{self.thresholds_str} scheduling-algorithm=1"
        plate_sched_params = f"{self.thresholds_str} scheduling-algorithm=1"
        ocr_sched_params = "scheduling-algorithm=1"

        vehicle_detection = INFERENCE_PIPELINE(
            hef_path=self.vehicle_hef_path,
            post_process_so=self.vehicle_post_process_so,
            post_function_name=self.vehicle_post_function_name,
            config_json=self.vehicle_json,
            additional_params=vehicle_sched_params,
            batch_size=2,
            scheduler_timeout_ms=100,
            scheduler_priority=30,
            name="vehicle_detection",
        )
        vehicle_detection_wrapper = INFERENCE_PIPELINE_WRAPPER(
            vehicle_detection,
            name="vehicle_wrapper",
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

        plate_detection = INFERENCE_PIPELINE(
            hef_path=self.license_det_hef_path,
            post_process_so=self.license_det_post_process_so,
            post_function_name=self.license_det_post_function_name,
            config_json=self.license_json,
            additional_params=plate_sched_params,
            batch_size=4,
            scheduler_timeout_ms=100,
            scheduler_priority=5,
            name="plate_detection",
        )

        vehicle_cropper_function = f"{self.vehicle_cropper_function}_op"
        vehicle_cropper = CROPPER_PIPELINE(
            inner_pipeline=plate_detection,
            so_path=self.lpr_croppers_so,
            function_name=vehicle_cropper_function,
            internal_offset=True,
            name="vehicle_cropper",
        )

        ocr_post_function_name = self.ocr_post_function_name

        ocr_detection = INFERENCE_PIPELINE(
            hef_path=self.ocr_hef_path,
            post_process_so=self.ocr_post_process_so,
            post_function_name=ocr_post_function_name,
            additional_params=ocr_sched_params,
            batch_size=8,
            scheduler_timeout_ms=100,
            scheduler_priority=5,
            name="ocr_detection",
        )

        # Use license_plate_no_quality instead of license_plate_quality_estimation
        lp_cropper = CROPPER_PIPELINE(
            inner_pipeline=ocr_detection,
            so_path=self.lpr_croppers_so,
            function_name="license_plate_no_quality_op",  # No quality filtering
            internal_offset=True,
            name="lp_cropper",
        )

        display_pipeline = DISPLAY_PIPELINE(
            video_sink=self.video_sink,
            sync="false",
            show_fps=self.show_fps,
            overlay_so=self.lpr_overlay_so,
            queue_max_size_buffers=DEFAULT_DISPLAY_QUEUE_SIZE,
            queue_leaky=DEFAULT_DISPLAY_QUEUE_LEAKY,
        )

        pipeline_string = (
            f"{source_pipeline} ! "
            f"{vehicle_detection_wrapper} ! "
            f"{tracker_pipeline} ! "
            f"{vehicle_cropper} ! "
            f"{lp_cropper} ! "
            f"identity name=identity_callback ! "
            f"hailofilter use-gst-buffer=true "
            f"so-path={self.lpr_ocrsink_so} "
            f"qos=false ! "
            f"{display_pipeline}"
        )

        if not self.print_pipeline_mode:
            print(pipeline_string)
        return pipeline_string

    def get_pipeline_string_ocr_only(self):
        source_pipeline = SOURCE_PIPELINE(
            video_source=self.video_source,
            video_width=self.video_width,
            video_height=self.video_height,
            frame_rate=self.frame_rate,
            sync=self.sync,
        )

        ocr_detection = INFERENCE_PIPELINE(
            hef_path=self.ocr_hef_path,
            post_process_so=self.ocr_post_process_so,
            post_function_name=self.ocr_post_function_name,
            scheduler_timeout_ms=100,
            name="ocr_detection",
        )
        ocr_detection_wrapper = INFERENCE_PIPELINE_WRAPPER(ocr_detection)

        # OCR results are best consumed via the Python callback on identity_callback.
        pipeline_string = (
            f"{source_pipeline} ! "
            f"{ocr_detection_wrapper} ! "
            f"identity name=identity_callback ! "
            f"fakesink sync=false async=false"
        )
        if not self.print_pipeline_mode:
            print(pipeline_string)
        return pipeline_string

    def get_pipeline_string_complex(self):
        # 1) Source
        source_pipeline = SOURCE_PIPELINE(
            video_source=self.video_source,
            video_width=self.video_width,
            video_height=self.video_height,
            frame_rate=self.frame_rate,
            sync=self.sync,
        )

        # 2) Vehicle detection (explicit stages)
        vehicle_detection = (
            f"{QUEUE('vehicle_pre_scale_q', max_size_buffers=3)} ! "
            f"videoscale name=vehicle_videoscale n-threads=2 qos=false ! "
            f"{QUEUE('vehicle_pre_convert_q', max_size_buffers=3)} ! "
            f"video/x-raw, pixel-aspect-ratio=1/1 ! "
            f"videoconvert name=vehicle_videoconvert n-threads=2 ! "
            f"{QUEUE('vehicle_pre_hailonet_q', max_size_buffers=3)} ! "
            f"hailonet name=vehicle_hailonet "
            f"hef-path={self.vehicle_hef_path} "
            f"batch-size=2 "
            f"vdevice-group-id=SHARED scheduling-algorithm=1 scheduler-threshold=1 scheduler-timeout-ms=100 "
            f"{self.thresholds_str} force-writable=true ! "
            f"{QUEUE('vehicle_post_hailonet_q', max_size_buffers=3)} ! "
            f"hailofilter name=vehicle_hailofilter "
            f"so-path={self.vehicle_post_process_so} "
            f"function-name={self.vehicle_post_function_name} "
            f"config-path={self.vehicle_json} qos=false ! "
            f"{QUEUE('vehicle_post_filter_q', max_size_buffers=3)} "
        )

        # 3) Tracker
        tracker_pipeline = (
            f"hailotracker name=hailo_tracker "
            f"keep-past-metadata=true kalman-dist-thr=0.5 iou-thr=0.6 "
            f"keep-tracked-frames=2 keep-lost-frames=2 ! "
            f"{QUEUE('tracker_post_q', max_size_buffers=5)} "
        )

        # 4) Plate detection (inner)
        plate_detection_inner = (
            f"hailonet name=plate_hailonet "
            f"hef-path={self.license_det_hef_path} "
            f"batch-size=4 "
            f"vdevice-group-id=SHARED scheduling-algorithm=1 scheduler-threshold=5 scheduler-timeout-ms=100 "
            f"{self.thresholds_str} force-writable=true ! "
            f"{QUEUE('plate_post_hailonet_q', max_size_buffers=3)} ! "
            f"hailofilter name=plate_hailofilter "
            f"so-path={self.license_det_post_process_so} "
            f"config-path={self.license_json} "
            f"function-name={self.license_det_post_function_name} qos=false ! "
            f"{QUEUE('plate_post_filter_q', max_size_buffers=3)} "
        )

        # 5) OCR (inner)
        ocr_detection_inner = (
            f"hailonet name=ocr_hailonet "
            f"hef-path={self.ocr_hef_path} "
            f"batch-size=8 "
            f"vdevice-group-id=SHARED scheduling-algorithm=1 scheduler-threshold=1 scheduler-timeout-ms=100 "
            f"force-writable=true ! "
            f"{QUEUE('ocr_post_hailonet_q', max_size_buffers=3)} ! "
            f"hailofilter name=ocr_hailofilter "
            f"so-path={self.ocr_post_process_so} "
            f"function-name={self.ocr_post_function_name} "
            f"qos=false ! "
            f"{QUEUE('ocr_post_filter_q', max_size_buffers=3)} "
        )

        # Full graph (explicit queues/aggregators)
        pipeline_string = (
            f"{source_pipeline} ! "
            f"{vehicle_detection} ! "
            f"{tracker_pipeline} ! "
            f"tee name=context_tee "

            # Processing branch: crop -> plate det -> agg1
            f"context_tee. ! {QUEUE('processing_branch_q', max_size_buffers=5)} ! "
            f"hailocropper "
            f"so-path={self.lpr_croppers_so} "
            f"function-name={self.vehicle_cropper_function} "
            f"internal-offset=true drop-uncropped-buffers=false name=cropper1 "
            f"hailoaggregator name=agg1 "
            f"cropper1. ! {QUEUE('cropper1_bypass_q', max_size_buffers=30)} ! agg1.sink_0 "
            f"cropper1. ! {QUEUE('cropper1_process_q', max_size_buffers=3)} ! "
            f"{plate_detection_inner} ! agg1.sink_1 "
            f"agg1. ! {QUEUE('agg1_output_q', max_size_buffers=5)} ! "

            # Second crop -> OCR -> agg2
            f"hailocropper "
            f"so-path={self.lpr_croppers_so} "
            f"function-name={self.lpr_quality_est_function} "
            f"internal-offset=true drop-uncropped-buffers=false name=cropper2 "
            f"hailoaggregator name=agg2 "
            f"cropper2. ! {QUEUE('cropper2_bypass_q', max_size_buffers=30)} ! agg2.sink_0 "
            f"cropper2. ! {QUEUE('cropper2_process_q', max_size_buffers=3)} ! "
            f"{ocr_detection_inner} ! agg2.sink_1 "
            f"agg2. ! {QUEUE('agg2_output_q', max_size_buffers=5)} ! "

            f"tee name=postproc_tee "

            # Display branch: merge original frames + full metadata (vehicle + LP + OCR)
            f"postproc_tee. ! {QUEUE('display_meta_q', max_size_buffers=10)} ! hailoaggregator name=display_agg "
            f"context_tee. ! {QUEUE('display_bypass_q', max_size_buffers=10)} ! display_agg.sink_1 "
            f"display_agg. ! {QUEUE('display_branch_q', max_size_buffers=10)} ! "
            f"videobox top=1 bottom=1 ! {QUEUE('display_videobox_q')} ! "
            f"hailooverlay line-thickness=3 font-thickness=1 qos=false ! "
            f"hailofilter use-gst-buffer=true "
            f"so-path={self.lpr_overlay_so} "
            f"qos=false ! "
            f"videoconvert ! "
            f"fpsdisplaysink name=hailo_display "
            f"video-sink={self.video_sink} "
            f"sync=false "
            f"text-overlay={'True' if self.show_fps else 'False'} "
            f"signal-fps-measurements=true "

            # Final sink
            f"postproc_tee. ! {QUEUE('final_sink_q', max_size_buffers=5)} ! "
            f"identity name=identity_callback ! "
            f"hailofilter use-gst-buffer=true "
            f"so-path={self.lpr_ocrsink_so} "
            f"qos=false ! "
            f"fakesink sync=false async=false"
        )
        if not self.print_pipeline_mode:
            print(pipeline_string)
        return pipeline_string

    def get_pipeline_string_full(self):
        """
        Vehicle & LP Detection pipeline: Runs vehicle detection, then license plate detection on vehicle crops.
        Includes tracking so per-track state (e.g., found_lp) can be maintained in the Python callback.
        Displays results with bounding boxes for both vehicles and plates.
        Adds OCR by cropping license plates and running the OCR model.
        """
        # 1) Source
        source_pipeline = SOURCE_PIPELINE(
            video_source=self.video_source,
            video_width=self.video_width,
            video_height=self.video_height,
            frame_rate=self.frame_rate,
            sync=self.sync,
        )

        # 2) Vehicle detection with wrapper (maintains original resolution)
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

        # 3) Tracker (enables per-vehicle unique IDs)
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

        # 4) Plate detection (inner pipeline for cropping detected vehicles)
        plate_detection = INFERENCE_PIPELINE(
            hef_path=self.license_det_hef_path,
            post_process_so=self.license_det_post_process_so,
            post_function_name=self.license_det_post_function_name,
            config_json=self.license_json,
            additional_params=self.thresholds_str,
            batch_size=8,
            scheduler_timeout_ms=100,
            name="plate_detection",
        )

        # 5) Crop vehicles and run plate detection on each
        vehicle_cropper = CROPPER_PIPELINE(
            inner_pipeline=plate_detection,
            so_path=self.lpr_croppers_so,
            function_name=self.vehicle_cropper_function,
            internal_offset=True,
            name="vehicle_cropper",
        )

        # 6) OCR (runs on cropped license plates)
        ocr_detection = INFERENCE_PIPELINE(
            hef_path=self.ocr_hef_path,
            post_process_so=self.ocr_post_process_so,
            post_function_name=self.ocr_post_function_name,
            batch_size=8,
            scheduler_timeout_ms=100,
            name="ocr_detection",
        )

        # 7) License plate cropper (crops license plates and runs OCR on them)
        lp_cropper = CROPPER_PIPELINE(
            inner_pipeline=ocr_detection,
            so_path=self.lpr_croppers_so,
            function_name=self.lpr_quality_est_function,
            internal_offset=True,
            name="lp_cropper",
        )

        # 8) User callback (for per-track found_lp, crop saving, etc.)
        user_callback = "identity name=identity_callback"

        # 9) Display with overlay
        display_pipeline = DISPLAY_PIPELINE(
            video_sink=self.video_sink,
            sync="false",
            show_fps=self.show_fps,
            overlay_so=self.lpr_overlay_so,
            queue_max_size_buffers=DEFAULT_DISPLAY_QUEUE_SIZE,
            queue_leaky=DEFAULT_DISPLAY_QUEUE_LEAKY,
        )

        # Branching pipeline: display stays on vehicle+LP detections, OCR runs on a side branch.
        pipeline_string = (
            f"{source_pipeline} ! "
            f"{vehicle_detection_wrapper} ! "
            f"{tracker_pipeline} ! "
            f"{vehicle_cropper} ! "
            f"tee name=post_lp_tee "
            f"post_lp_tee. ! {QUEUE('display_q', max_size_buffers=DEFAULT_DISPLAY_QUEUE_SIZE, leaky='downstream')} ! "
            f"{display_pipeline} "
            f"post_lp_tee. ! {QUEUE('ocr_q', max_size_buffers=5)} ! "
            f"{lp_cropper} ! "
            f"{QUEUE('post_ocr_q', max_size_buffers=5)} ! "
            f"{user_callback} ! "
            f"hailofilter use-gst-buffer=true "
            f"so-path={self.lpr_ocrsink_so} "
            f"qos=false ! "
            f"fakesink sync=false async=false"
        )

        if not self.print_pipeline_mode:
            print(pipeline_string)
        return pipeline_string

def main():
    hailo_logger.info("Starting Hailo LPR App...")
    user_data = app_callback_class()
    app_callback = dummy_callback
    app = GStreamerLPRApp(app_callback, user_data)
    app.run()


if __name__ == "__main__":
    main()
