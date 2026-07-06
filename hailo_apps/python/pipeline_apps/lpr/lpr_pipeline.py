# LPR pipeline: builds the GStreamer pipeline string for the chosen
# detector backbone. Two backbones are supported (see `BACKBONES` below);
# the OCR stage (LPRNet or paddle_ocr_v5) is invariant.
#
#   yolov8n        : yolov8n_384x640 (4 classes, "license_plate" direct)         → OCR
#   yolov8n_tiled  : same yolov8n, but each video frame is split into 5 tiles
#                    (4 quadrants + 1 full frame) and run through the network
#                    in a batch of 5 before aggregation
#
# region imports
from pathlib import Path

import setproctitle

from hailo_apps.python.core.common.core import (
    get_pipeline_parser,
    get_resource_path,
    handle_list_models_flag,
)
from hailo_apps.python.core.common.defines import (
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
BACKBONE_YOLOV8N = "yolov8n"
BACKBONE_YOLOV8N_TILED = "yolov8n_tiled"
BACKBONES = (BACKBONE_YOLOV8N, BACKBONE_YOLOV8N_TILED)

# --- yolov8n postprocess (single 4-class detector) -------------------------
# Generic yolo postprocess that picks the NMS tensor by regex (works across
# different network-name prefixes) and reads labels from a JSON config.
YOLOV8N_DETECTION_POSTPROCESS_SO = "libyolo_hailortpp_postprocess.so"
YOLOV8N_DETECTION_POSTPROCESS_FUNC = "filter"
YOLOV8N_DETECTION_LABELS_JSON = "hailo_4_classes.json"

# Filename of the 4-class yolov8n license-plate detector HEF. Listed in
# resources_config.yaml under lpr → default so install.sh fetches it from S3.
# Lands at the standard /usr/local/hailo/resources/models/<arch>/ install path.
YOLOV8N_DETECTOR_HEF_NAME = "hailo_yolov8n_384_640.hef"


class GStreamerLPRApp(GStreamerApp):
    """GStreamer LPR pipeline that supports two detector backbones.

    The backbone (yolov8n / yolov8n_tiled) is chosen at construction
    time and decides:
      - the pipeline-string shape (single inference vs 5-tile multi-scale)
      - the hailonet batch size
    The user callback receives the same buffer + ROI metadata in both
    cases; it inspects detections labelled 'license_plate' at the top level.
    """

    def __init__(self, app_callback, user_data, parser=None,
                 backbone: str = BACKBONE_YOLOV8N):
        if parser is None:
            parser = get_pipeline_parser()

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

        # Batch size + frame-rate tuning is backbone-dependent because
        # single-yolov8n runs one inference per frame and tiled-yolov8n
        # runs five.
        if backbone == BACKBONE_YOLOV8N:
            self.batch_size = 1
        else:  # yolov8n_tiled
            self.batch_size = 5     # 1 full frame + 4 quadrants
        if self.arch == HAILO8L_ARCH:
            self.frame_rate = min(self.frame_rate, 17)

        nms_score_threshold = 0.25
        nms_iou_threshold = 0.45
        self.thresholds_str = (
            f"nms-score-threshold={nms_score_threshold} "
            f"nms-iou-threshold={nms_iou_threshold} "
            f"output-format-type=HAILO_FORMAT_TYPE_FLOAT32"
        )

        self._setup_yolov8n_models()

        self.app_callback = app_callback
        self.create_pipeline()

    # ----- end-of-stream behaviour ------------------------------------------
    def on_eos(self):
        """Disable the file-source rebuild loop for LPR.

        Unlike single-network apps, LPR holds a *second* HailoRT device for
        OCR — a ``HailoInfer`` instance created in the ``app_callback`` and
        kept alive in ``user_data``. The base class loops file sources by
        tearing down the GStreamer pipeline and probing for a free
        ``VDevice`` before rebuilding; but the OCR device is never released
        on that path, so the rebuild fails with
        ``HAILO_OUT_OF_PHYSICAL_DEVICES`` on the second iteration. Rather
        than loop, shut down cleanly at end-of-stream for every source type.
        """
        hailo_logger.debug("LPR on_eos(): looping disabled, shutting down")
        self.shutdown()

    # ----- model setup ------------------------------------------------------
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
                f"  - pass --hef-path <path-to-hef>."
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

    # ----- backbone-specific pipeline fragment ------------------------------
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
