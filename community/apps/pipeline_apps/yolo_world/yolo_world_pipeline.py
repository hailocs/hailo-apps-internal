from pathlib import Path

import setproctitle

from hailo_apps.python.core.common.core import (
    get_pipeline_parser,
    resolve_hef_path,
)
from hailo_apps.python.core.common.defines import HAILO10H_ARCH
from hailo_apps.python.core.common.hailo_logger import get_logger
from hailo_apps.python.core.gstreamer.gstreamer_app import (
    GStreamerApp,
    app_callback_class,
    dummy_callback,
)
from hailo_apps.python.core.gstreamer.gstreamer_helper_pipelines import (
    DISPLAY_PIPELINE,
    SOURCE_PIPELINE,
    USER_CALLBACK_PIPELINE,
)

logger = get_logger(__name__)

APP_TITLE = "hailo-yolo-world"
YOLO_WORLD_PIPELINE = "yolo_world"


class GStreamerYoloWorldApp(GStreamerApp):
    def __init__(self, app_callback, user_data, parser=None):
        if parser is None:
            parser = get_pipeline_parser()

        parser.add_argument(
            "--prompts",
            type=str,
            default=None,
            help='Comma-separated class names for detection, e.g. "cat,dog,person"',
        )
        parser.add_argument(
            "--prompts-file",
            type=str,
            default=None,
            help="Path to JSON file with class name list",
        )
        parser.add_argument(
            "--embeddings-file",
            type=str,
            default=None,
            help="Path to cached embeddings JSON (default: embeddings.json in app dir)",
        )
        parser.add_argument(
            "--confidence-threshold",
            type=float,
            default=0.3,
            help="Detection confidence threshold (default: 0.3)",
        )
        parser.add_argument(
            "--watch-prompts",
            action="store_true",
            default=False,
            help="Watch prompts-file for changes and reload at runtime",
        )

        # Default to use_frame=True since we render detections via OpenCV
        parser.set_defaults(use_frame=True)

        logger.info("Initializing GStreamer YOLO World App...")

        super().__init__(parser, user_data)

        # Validate architecture — YOLO World requires Hailo-10H
        SUPPORTED_ARCHS = [HAILO10H_ARCH]
        if self.arch not in SUPPORTED_ARCHS:
            supported = ", ".join(SUPPORTED_ARCHS)
            logger.error(
                "YOLO World requires Hailo-10H (detected: %s). "
                "Supported architectures: %s",
                self.arch, supported,
            )
            import sys
            sys.exit(1)

        # Use fakesink — all visualization via OpenCV in callback
        self.video_sink = "fakesink"

        # Resolve HEF path
        self.hef_path = resolve_hef_path(
            self.hef_path,
            app_name=YOLO_WORLD_PIPELINE,
            arch=self.arch,
        )
        if self.hef_path is None or not Path(self.hef_path).exists():
            logger.error("HEF path is invalid or missing: %s", self.hef_path)

        logger.info("HEF path: %s", self.hef_path)

        self.app_callback = app_callback

        setproctitle.setproctitle(APP_TITLE)

        self.create_pipeline()
        logger.debug("Pipeline created")

    def get_pipeline_string(self):
        source_pipeline = SOURCE_PIPELINE(
            video_source=self.video_source,
            video_width=self.video_width,
            video_height=self.video_height,
            frame_rate=self.frame_rate,
            sync=self.sync,
        )
        user_callback_pipeline = USER_CALLBACK_PIPELINE()
        display_pipeline = DISPLAY_PIPELINE(
            video_sink=self.video_sink, sync=self.sync, show_fps=self.show_fps
        )

        pipeline_string = (
            f"{source_pipeline} ! "
            f"videoscale ! video/x-raw,width=640,height=640 ! "
            f"{user_callback_pipeline} ! "
            f"{display_pipeline}"
        )
        logger.debug("Pipeline string: %s", pipeline_string)
        return pipeline_string


def main():
    logger.info("Starting YOLO World App...")
    user_data = app_callback_class()
    app = GStreamerYoloWorldApp(dummy_callback, user_data)
    app.run()


if __name__ == "__main__":
    main()
