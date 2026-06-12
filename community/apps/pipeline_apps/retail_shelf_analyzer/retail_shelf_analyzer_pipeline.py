# region imports
# Standard library imports
import setproctitle
from pathlib import Path
from typing import Optional, Any

# Local application-specific imports
from hailo_apps.python.core.common.core import get_pipeline_parser, handle_list_models_flag
from hailo_apps.python.core.common.defines import TILING_PIPELINE, TILING_POSTPROCESS_SO_FILENAME, TILING_POSTPROCESS_FUNCTION, RESOURCES_SO_DIR_NAME
from hailo_apps.python.core.gstreamer.gstreamer_helper_pipelines import (
    SOURCE_PIPELINE, INFERENCE_PIPELINE, USER_CALLBACK_PIPELINE,
    DISPLAY_PIPELINE, TILE_CROPPER_PIPELINE
)
from hailo_apps.python.core.gstreamer.gstreamer_app import GStreamerApp, app_callback_class, dummy_callback
from hailo_apps.python.core.common.hailo_logger import get_logger
from hailo_apps.python.pipeline_apps.tiling.configuration import TilingConfiguration
from hailo_apps.python.core.common.hef_utils import get_hef_labels_json

hailo_logger = get_logger(__name__)
# endregion imports

# Application title
RETAIL_SHELF_ANALYZER_TITLE = "hailo-retail-shelf-analyzer"


class GStreamerRetailShelfAnalyzerApp(GStreamerApp):
    """
    Retail shelf analyzer pipeline using tiled detection.

    Splits high-resolution camera frames into overlapping tiles, runs YOLOv8
    detection on each tile to find small products, and aggregates detections.
    The callback provides per-zone product counts and empty shelf alerts.
    """

    def __init__(self, app_callback: Any, user_data: Any, parser: Optional[Any] = None) -> None:
        if parser is None:
            parser = get_pipeline_parser()

        # Add tiling-specific arguments (reuse from tiling app)
        self._add_tiling_arguments(parser)

        # Add retail-shelf-specific arguments
        self._add_retail_arguments(parser)

        # Handle --list-models flag before full initialization
        handle_list_models_flag(parser, TILING_PIPELINE)

        super().__init__(parser, user_data)

        # Initialize tiling configuration (reuse tiling's TilingConfiguration)
        self.config = TilingConfiguration(
            self.options_menu,
            self.video_width,
            self.video_height,
            self.arch
        )

        # Copy configuration attributes to self for compatibility
        self._copy_config_attributes()

        # User-defined label JSON file
        self.labels_json = self.options_menu.labels_json
        if self.labels_json is None:
            self.labels_json = get_hef_labels_json(self.hef_path)
            if self.labels_json is not None:
                hailo_logger.info("Auto detected Labels JSON: %s", self.labels_json)

        # Retail-specific configuration
        self.num_zones = self.options_menu.num_zones
        self.empty_threshold = self.options_menu.empty_threshold
        self.confidence_threshold = self.options_menu.confidence_threshold

        self.app_callback = app_callback
        setproctitle.setproctitle(RETAIL_SHELF_ANALYZER_TITLE)

        # Print configuration summary
        self._print_configuration()

        self.create_pipeline()

    def _add_tiling_arguments(self, parser: Any) -> None:
        """Add tiling-specific command line arguments (same as tiling app)."""
        parser.add_argument(
            "--labels-json",
            default=None,
            help="Path to custom labels JSON file",
        )
        parser.add_argument("--tiles-x", type=int, default=None,
                            help="Number of tiles horizontally (triggers manual mode)")
        parser.add_argument("--tiles-y", type=int, default=None,
                            help="Number of tiles vertically (triggers manual mode)")
        parser.add_argument("--min-overlap", type=float, default=0.1,
                            help="Minimum overlap ratio (0.0-0.5). Default: 0.1 (10%% of tile size).")
        parser.add_argument("--multi-scale", action="store_true",
                            help="Enable multi-scale tiling with predefined grids")
        parser.add_argument("--scale-levels", type=int, default=1, choices=[1, 2, 3],
                            help="Scale levels for multi-scale mode. Default: 1")
        parser.add_argument("--iou-threshold", type=float, default=0.3,
                            help="NMS IOU threshold (default: 0.3)")
        parser.add_argument("--border-threshold", type=float, default=0.15,
                            help="Border threshold for multi-scale mode (default: 0.15)")

    def _add_retail_arguments(self, parser: Any) -> None:
        """Add retail-shelf-specific command line arguments."""
        parser.add_argument("--num-zones", type=int, default=3,
                            help="Number of horizontal shelf zones to divide the frame into (default: 3)")
        parser.add_argument("--empty-threshold", type=int, default=2,
                            help="Minimum detections per zone before it is considered 'empty' (default: 2)")
        parser.add_argument("--confidence-threshold", type=float, default=0.4,
                            help="Minimum detection confidence to count a product (default: 0.4)")

    def _copy_config_attributes(self) -> None:
        """Copy configuration attributes to self for compatibility."""
        self.video_source = self.config.video_source
        self.hef_path = self.config.hef_path
        self.model_type = self.config.model_type
        self.model_input_width = self.config.model_input_width
        self.model_input_height = self.config.model_input_height
        self.post_function = self.config.post_function
        self.post_process_so = self.config.post_process_so

        self.tiles_x = self.config.tiles_x
        self.tiles_y = self.config.tiles_y
        self.overlap_x = self.config.overlap_x
        self.overlap_y = self.config.overlap_y
        self.tile_size_x = self.config.tile_size_x
        self.tile_size_y = self.config.tile_size_y
        self.tiling_mode = self.config.tiling_mode
        self.used_larger_tiles = getattr(self.config, 'used_larger_tiles', False)
        self.min_overlap = self.config.min_overlap

        self.use_multi_scale = self.config.use_multi_scale
        self.scale_level = self.config.scale_level
        self.batch_size = self.config.batch_size

        self.iou_threshold = self.config.iou_threshold
        self.border_threshold = self.config.border_threshold

        if self.model_type == "mobilenet" and self.arch != 'hailo8' and self.batch_size == 15:
            self.frame_rate = 19

    def _print_configuration(self) -> None:
        """Print a user-friendly configuration summary."""
        print("\n" + "=" * 70)
        print("RETAIL SHELF ANALYZER CONFIGURATION")
        print("=" * 70)
        print(f"Input Resolution:     {self.video_width}x{self.video_height}")
        print(f"Model:                {Path(self.hef_path).name} ({self.model_type.upper()}, "
              f"{self.model_input_width}x{self.model_input_height})")
        print(f"\nTiling Mode:          {self.tiling_mode.upper()}")
        print(f"Tile Grid:            {self.tiles_x}x{self.tiles_y} = {self.tiles_x * self.tiles_y} tiles")
        print(f"Batch Size:           {self.batch_size}")
        print(f"\nRetail Settings:")
        print(f"  Shelf Zones:        {self.num_zones}")
        print(f"  Empty Threshold:    {self.empty_threshold} detections")
        print(f"  Confidence:         {self.confidence_threshold:.2f}")
        print("=" * 70 + "\n")

    def get_pipeline_string(self) -> str:
        """
        Build the GStreamer pipeline string with tiled detection for retail shelf analysis.

        Returns:
            str: Complete GStreamer pipeline string
        """
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
            post_function_name=self.post_function,
            batch_size=self.batch_size,
            config_json=self.labels_json
        )

        tiling_mode = 1 if self.use_multi_scale else 0
        scale_level = self.scale_level if self.use_multi_scale else 0

        tile_cropper_pipeline = TILE_CROPPER_PIPELINE(
            detection_pipeline,
            name='tile_cropper_wrapper',
            internal_offset=True,
            scale_level=scale_level,
            tiling_mode=tiling_mode,
            tiles_along_x_axis=self.tiles_x,
            tiles_along_y_axis=self.tiles_y,
            overlap_x_axis=self.overlap_x,
            overlap_y_axis=self.overlap_y,
            iou_threshold=self.iou_threshold,
            border_threshold=self.border_threshold
        )

        user_callback_pipeline = USER_CALLBACK_PIPELINE()

        display_pipeline = DISPLAY_PIPELINE(
            video_sink=self.video_sink,
            sync=self.sync,
            show_fps=self.show_fps
        )

        pipeline_string = (
            f'{source_pipeline} ! '
            f'{tile_cropper_pipeline} ! '
            f'{user_callback_pipeline} ! '
            f'{display_pipeline}'
        )

        hailo_logger.debug("Pipeline string: %s", pipeline_string)
        return pipeline_string


def main() -> None:
    user_data = app_callback_class()
    app_callback = dummy_callback
    app = GStreamerRetailShelfAnalyzerApp(app_callback, user_data)
    app.run()


if __name__ == "__main__":
    print("Starting Retail Shelf Analyzer Pipeline...")
    main()
