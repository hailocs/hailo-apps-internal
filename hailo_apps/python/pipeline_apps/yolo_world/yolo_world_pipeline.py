"""GStreamer pipeline for YOLO World v2s.

Standard SOURCE → leaky-queue → user-callback → hailooverlay → DISPLAY.
The user callback drives HailoRT directly (the YOLO World HEF is dual-input
and unsupported by hailonet) and attaches detections as `hailo.HailoDetection`
metadata that `hailooverlay` renders.

Pacing notes:
- `SOURCE_PIPELINE` already scales/converts to `self.video_width × video_height`,
  so we set both to 640 in `__init__` and skip the redundant videoscale.
- A leaky-downstream queue between source and the user-callback absorbs the
  rate mismatch when the callback (~16 FPS) is slower than the source.
- We force `sync="false"` on the display so frames render as fast as the
  callback produces them rather than being dropped as "late" against PTS.
"""
from pathlib import Path

import setproctitle

from hailo_apps.python.core.common.core import (
    get_pipeline_parser,
    resolve_hef_path,
)
from hailo_apps.python.core.common.defines import (
    HAILO10H_ARCH,
    YOLO_WORLD_APP_TITLE,
    YOLO_WORLD_PIPELINE,
)
from hailo_apps.python.core.common.hailo_logger import get_logger
from hailo_apps.python.core.gstreamer.gstreamer_app import (
    GStreamerApp,
    app_callback_class,
    dummy_callback,
)
from hailo_apps.python.core.gstreamer.gstreamer_helper_pipelines import (
    DISPLAY_PIPELINE,
    QUEUE,
    USER_CALLBACK_PIPELINE,
)

logger = get_logger(__name__)


class GStreamerYoloWorldApp(GStreamerApp):
    def __init__(self, app_callback, user_data, parser=None):
        if parser is None:
            parser = get_pipeline_parser()

        parser.add_argument(
            "--prompts",
            type=str,
            default=None,
            help='Comma-separated class names, e.g. "cat,dog,person"',
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
        parser.add_argument(
            "--profile",
            action="store_true",
            default=False,
            help="Log rolling per-stage callback latencies + FPS (no-op when off)",
        )
        parser.add_argument(
            "--interactive",
            action="store_true",
            default=False,
            help="Live-prompt control: type class names in the terminal to "
                 "re-detect them on the fly, with a per-class presence tally.",
        )

        # Detections are attached as Hailo metadata and drawn by hailooverlay;
        # the user-frame copy path is unnecessary.
        parser.set_defaults(use_frame=False)

        logger.info("Initializing GStreamer YOLO World App...")
        super().__init__(parser, user_data)

        # YOLO World requires the dual-input HEF — Hailo-10H only.
        if self.arch != HAILO10H_ARCH:
            logger.error(
                "YOLO World requires Hailo-10H (detected: %s).", self.arch,
            )
            import sys
            sys.exit(1)

        # Make SOURCE_PIPELINE deliver native 640x640 RGB. Mirrors the pattern in
        # detection_simple — only overrides the parser's default 1280x720, so
        # explicit --video-width/--video-height from the user still wins.
        if self.video_width == 1280:
            self.video_width = 640
        if self.video_height == 720:
            self.video_height = 640

        # Default the source frame rate to 30 when the user hasn't pinned one.
        # SOURCE_PIPELINE only applies the framerate cap when both sync is on
        # and frame_rate is set, so without this the file decodes as fast as
        # possible and the leaky queue drops everything before the callback.
        if self.frame_rate is None:
            self.frame_rate = 30


        self.hef_path = resolve_hef_path(
            self.hef_path,
            app_name=YOLO_WORLD_PIPELINE,
            arch=self.arch,
        )
        if self.hef_path is None or not Path(self.hef_path).exists():
            logger.error("HEF path is invalid or missing: %s", self.hef_path)
        logger.info("HEF path: %s", self.hef_path)

        self.app_callback = app_callback
        setproctitle.setproctitle(YOLO_WORLD_APP_TITLE)
        self.create_pipeline()
        logger.debug("Pipeline created")

    def get_pipeline_string(self):
        source_pipeline = self.get_source_pipeline()
        # `identity sync=true` paces buffers against the pipeline clock so the
        # file source runs at wallclock rate (live sources are pre-paced so
        # this is a near no-op for them). Combined with a leaky-downstream
        # queue, this lets the callback consume at its own pace while the
        # source keeps real-time rhythm.
        pacer = "identity name=yw_pacer sync=true"
        callback_queue = QUEUE(
            name="yw_callback_q", max_size_buffers=2, leaky="downstream",
        )
        user_callback_pipeline = USER_CALLBACK_PIPELINE()
        # Display sync stays "false" so the sink renders every callback output
        # immediately instead of dropping it as late vs PTS.
        display_pipeline = DISPLAY_PIPELINE(
            video_sink=self.video_sink, sync="false", show_fps=self.show_fps
        )

        pipeline_string = (
            f"{source_pipeline} ! "
            f"{pacer} ! "
            f"{callback_queue} ! "
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
