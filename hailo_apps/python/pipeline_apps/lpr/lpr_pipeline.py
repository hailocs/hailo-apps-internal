# LPR pipeline: builds the GStreamer pipeline string for the chosen
# detector backbone. Three backbones are supported (see `BACKBONES` below);
# the OCR stage (LPRNet or paddle_ocr_v5) is invariant.
#
#   cascade        : yolov5m_vehicles → tracker → vehicle-cropper(tiny_yolov4_lp) → OCR
#   yolov8n        : yolov8n_384x640 (4 classes, "license_plate" direct)         → OCR
#   yolov8n_tiled  : same yolov8n, but each video frame is split into 5 tiles
#                    (4 quadrants + 1 full frame) and run through the network
#                    in a batch of 5 before aggregation
#
# region imports
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
    HAILO8L_ARCH,
    LPR_VIDEO_NAME,
    RESOURCES_JSON_DIR_NAME,
    RESOURCES_ROOT_PATH_DEFAULT,
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
    SOURCE_PIPELINE,
    TILE_CROPPER_PIPELINE,
    TRACKER_PIPELINE,
    USER_CALLBACK_PIPELINE,
)

hailo_logger = get_logger(__name__)

# endregion imports

LPR_APP_TITLE = "Hailo LPR App"
LPR_PIPELINE = "lpr"

# Backbone identifiers — matches the CLI --backbone choices.
BACKBONE_CASCADE = "cascade"
BACKBONE_YOLOV8N = "yolov8n"
BACKBONE_YOLOV8N_TILED = "yolov8n_tiled"
BACKBONES = (BACKBONE_CASCADE, BACKBONE_YOLOV8N, BACKBONE_YOLOV8N_TILED)

# --- Cascade-specific postprocess (vehicle det + LP det) -------------------
VEHICLE_DETECTION_POSTPROCESS_SO = "libyolo_hailortpp_postprocess.so"
VEHICLE_DETECTION_POSTPROCESS_FUNC = "yolov5m_vehicles"
# Custom LP postprocess that handles UINT8/UINT16/FLOAT32 across all archs.
LP_DETECTION_POSTPROCESS_SO = "libyolov4_lp_postprocess.so"
LP_DETECTION_POSTPROCESS_FUNC = "tiny_yolov4_license_plates"
VEHICLE_CROPPER_FUNC = "all_detections"

# --- yolov8n-specific postprocess (single 4-class detector) ----------------
# Generic yolo postprocess that picks the NMS tensor by regex (works across
# different network-name prefixes) and reads labels from a JSON config.
YOLOV8N_DETECTION_POSTPROCESS_SO = "libyolo_hailortpp_postprocess.so"
YOLOV8N_DETECTION_POSTPROCESS_FUNC = "filter"
YOLOV8N_DETECTION_LABELS_JSON = "hailo_4_classes.json"

# Filename of the 4-class yolov8n license-plate detector HEF. Listed in
# resources_config.yaml under lpr → extra so install.sh fetches it from S3
# alongside the cascade HEFs. The resolved file lives at the standard
# /usr/local/hailo/resources/models/<arch>/hailo_yolov8n_384_640.hef path
# that install.sh writes to.
YOLOV8N_DETECTOR_HEF_NAME = "hailo_yolov8n_384_640.hef"


class GStreamerLPRApp(GStreamerApp):
    """GStreamer LPR pipeline that supports three detector backbones.

    The backbone (cascade / yolov8n / yolov8n_tiled) is chosen at construction
    time and decides:
      - which HEF(s) are loaded
      - the pipeline-string shape (cropper-cascaded vs single inference vs
        5-tile multi-scale inference)
      - the hailonet batch size
    The user callback receives the same buffer + ROI metadata in all three
    cases; it inspects `user_data.backbone` to know whether to look for
    'car' detections with LP sub-detections (cascade) or 'license_plate'
    detections at the top level (yolov8n / yolov8n_tiled).
    """

    def __init__(self, app_callback, user_data, parser=None,
                 backbone: str = BACKBONE_CASCADE):
        if parser is None:
            parser = get_pipeline_parser()

        if backbone == BACKBONE_CASCADE:
            configure_multi_model_hef_path(parser)
        handle_list_models_flag(parser, LPR_PIPELINE)
        super().__init__(parser, user_data)
        setproctitle.setproctitle(LPR_APP_TITLE)

        if backbone not in BACKBONES:
            raise ValueError(
                f"Unknown backbone '{backbone}'. Choose one of: {BACKBONES}")
        self.backbone = backbone

        if BASIC_PIPELINES_VIDEO_EXAMPLE_NAME in self.video_source:
            self.video_source = get_resource_path(
                pipeline_name=None, resource_type=RESOURCES_VIDEOS_DIR_NAME,
                arch=self.arch, model=LPR_VIDEO_NAME,
            )

        # Batch size + frame-rate tuning is backbone-dependent because the
        # cascade runs two inferences per frame, single-yolov8n runs one,
        # and tiled-yolov8n runs five.
        if backbone == BACKBONE_CASCADE:
            self.batch_size = 1 if self.arch == HAILO8L_ARCH else 2
        elif backbone == BACKBONE_YOLOV8N:
            self.batch_size = 1
        else:  # yolov8n_tiled
            self.batch_size = 5     # 1 full frame + 4 quadrants
        if self.arch == HAILO8L_ARCH:
            self.frame_rate = min(self.frame_rate, 17)

        nms_score_threshold = 0.3
        nms_iou_threshold = 0.45
        self.thresholds_str = (
            f"nms-score-threshold={nms_score_threshold} "
            f"nms-iou-threshold={nms_iou_threshold} "
            f"output-format-type=HAILO_FORMAT_TYPE_FLOAT32"
        )

        # Resolve HEFs based on backbone.
        if backbone == BACKBONE_CASCADE:
            self._setup_cascade_models()
        else:
            self._setup_yolov8n_models()

        self.app_callback = app_callback
        self.create_pipeline()

    # ----- model setup ------------------------------------------------------
    def _setup_cascade_models(self):
        models = resolve_hef_paths(
            hef_paths=self.options_menu.hef_path,
            app_name=LPR_PIPELINE, arch=self.arch,
        )
        self.vehicle_detection_hef = models[0].path
        self.lp_detection_hef = models[1].path

        self.vehicle_detection_post_so = get_resource_path(
            pipeline_name=None, resource_type=RESOURCES_SO_DIR_NAME,
            arch=self.arch, model=VEHICLE_DETECTION_POSTPROCESS_SO,
        )
        self.lp_detection_post_so = get_resource_path(
            pipeline_name=None, resource_type=RESOURCES_SO_DIR_NAME,
            arch=self.arch, model=LP_DETECTION_POSTPROCESS_SO,
        )
        self.vehicle_cropper_so = get_resource_path(
            pipeline_name=None, resource_type=RESOURCES_SO_DIR_NAME,
            arch=self.arch, model=ALL_DETECTIONS_CROPPER_POSTPROCESS_SO_FILENAME,
        )

    def _setup_yolov8n_models(self):
        # --hef-path wins; else resolve via the standard install-time path that
        # install.sh writes to when resources_config.yaml lists this model
        # under lpr → default. Same convention the paddle OCR HEF uses.
        cli_hef = getattr(self.options_menu, "hef_path", None)
        if cli_hef:
            self.yolov8n_hef = (
                cli_hef[0] if isinstance(cli_hef, (list, tuple)) else cli_hef
            )
        else:
            self.yolov8n_hef = str(
                Path(RESOURCES_ROOT_PATH_DEFAULT) / "models"
                / self.arch / YOLOV8N_DETECTOR_HEF_NAME
            )
        if not Path(self.yolov8n_hef).exists():
            raise FileNotFoundError(
                f"yolov8n LP detector HEF not found: {self.yolov8n_hef}.\n"
                f"  - Run sudo ./install.sh to download it from S3, or\n"
                f"  - pass --hef-path <path-to-hef>, or\n"
                f"  - fall back to --backbone cascade (requires --all install)."
            )

        self.yolov8n_post_so = get_resource_path(
            pipeline_name=None, resource_type=RESOURCES_SO_DIR_NAME,
            arch=self.arch, model=YOLOV8N_DETECTION_POSTPROCESS_SO,
        )
        self.yolov8n_labels_json = get_resource_path(
            pipeline_name=None, resource_type=RESOURCES_JSON_DIR_NAME,
            arch=self.arch, model=YOLOV8N_DETECTION_LABELS_JSON,
        )

    # ----- pipeline string --------------------------------------------------
    def get_pipeline_string(self):
        source_pipeline = SOURCE_PIPELINE(
            video_source=self.video_source,
            video_width=self.video_width,
            video_height=self.video_height,
            frame_rate=self.frame_rate,
            sync=self.sync,
        )

        if self.backbone == BACKBONE_CASCADE:
            detect_and_track = self._cascade_detect_and_track()
        else:
            detect_and_track = self._yolov8n_detect_and_track()

        user_callback_pipeline = USER_CALLBACK_PIPELINE()
        display_pipeline = DISPLAY_PIPELINE(
            video_sink=self.video_sink, sync=self.sync, show_fps=self.show_fps,
        )

        return (
            f"{source_pipeline} ! "
            f"{detect_and_track} ! "
            f"{user_callback_pipeline} ! "
            f"{display_pipeline}"
        )

    # ----- backbone-specific pipeline fragments ----------------------------
    def _cascade_detect_and_track(self):
        """yolov5m_vehicles → tracker → cropper(tiny_yolov4_lp)."""
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
        tracker_pipeline = TRACKER_PIPELINE(
            class_id=-1, kalman_dist_thr=0.5, iou_thr=0.6,
            keep_tracked_frames=2, keep_lost_frames=2,
            keep_past_metadata=True, name="hailo_tracker",
        )
        lp_detection_pipeline = INFERENCE_PIPELINE(
            hef_path=self.lp_detection_hef,
            post_process_so=self.lp_detection_post_so,
            post_function_name=LP_DETECTION_POSTPROCESS_FUNC,
            batch_size=self.batch_size,
            name="lp_detection",
            additional_params="output-format-type=HAILO_FORMAT_TYPE_FLOAT32",
        )
        vehicle_cropper = CROPPER_PIPELINE(
            inner_pipeline=lp_detection_pipeline,
            so_path=self.vehicle_cropper_so,
            function_name=VEHICLE_CROPPER_FUNC,
            internal_offset=True, name="vehicle_cropper",
        )
        return (
            f"{vehicle_detection_wrapper} ! "
            f"{tracker_pipeline} ! "
            f"{vehicle_cropper}"
        )

    def _yolov8n_detect_and_track(self):
        """Single yolov8n_384x640 (with or without tiling) → tracker."""
        detection_pipeline = INFERENCE_PIPELINE(
            hef_path=self.yolov8n_hef,
            post_process_so=self.yolov8n_post_so,
            post_function_name=YOLOV8N_DETECTION_POSTPROCESS_FUNC,
            config_json=str(self.yolov8n_labels_json),
            batch_size=self.batch_size,
            additional_params=self.thresholds_str,
            name="lp_detection",
        )

        if self.backbone == BACKBONE_YOLOV8N_TILED:
            # Multi-scale tiling: 2x2 main grid (4 quadrants) + scale_level=1
            # additional (1x1, full frame) = 5 tiles total. The aggregator
            # merges overlapping detections from adjacent tiles
            # (iou_threshold) and prefers the right scale near tile borders
            # (border_threshold). internal_offset=True keeps detection coords
            # in source-frame space.
            detection_wrapper = TILE_CROPPER_PIPELINE(
                detection_pipeline,
                name="lp_detection_tile_cropper",
                internal_offset=True,
                scale_level=1,           # additional 1x1 (full-frame tile)
                tiling_mode=1,           # multi-scale
                tiles_along_x_axis=2,
                tiles_along_y_axis=2,    # main 2x2 = 4 quadrants
                overlap_x_axis=0.10,
                overlap_y_axis=0.10,
                iou_threshold=0.30,
                border_threshold=0.15,
            )
        else:  # BACKBONE_YOLOV8N — single full-frame inference
            detection_wrapper = INFERENCE_PIPELINE_WRAPPER(
                detection_pipeline, name="lp_detection_wrapper"
            )

        tracker_pipeline = TRACKER_PIPELINE(
            class_id=-1, kalman_dist_thr=0.5, iou_thr=0.6,
            keep_tracked_frames=2, keep_lost_frames=2,
            keep_past_metadata=True, name="hailo_tracker",
        )
        return f"{detection_wrapper} ! {tracker_pipeline}"


def main():
    hailo_logger.info("Starting Hailo LPR App...")
    user_data = app_callback_class()
    app = GStreamerLPRApp(dummy_callback, user_data)
    app.run()


if __name__ == "__main__":
    main()
