"""GStreamer pipeline for Vampire Mirror v2.

Subclasses the instance segmentation pipeline (YOLOv5-Seg + ByteTrack)
and adds vampire-mirror-specific CLI arguments. The app-specific vampire
logic runs in the Python callback, not in the pipeline.
"""

import setproctitle

from hailo_apps.python.core.common.hailo_logger import get_logger
from hailo_apps.python.core.common.parser import get_pipeline_parser
from hailo_apps.python.pipeline_apps.instance_segmentation.instance_segmentation_pipeline import (
    GStreamerInstanceSegmentationApp,
)

logger = get_logger(__name__)


class VampireMirrorPipeline(GStreamerInstanceSegmentationApp):
    """Vampire Mirror pipeline — instance segmentation + tracking + vampire args."""

    def __init__(self, app_callback_fn, user_data, parser=None):
        setproctitle.setproctitle("vampire_mirror")
        if parser is None:
            parser = get_pipeline_parser()

        # Mirror display
        parser.add_argument(
            "--mirror-ratio",
            type=str,
            default="3:4",
            help="Portrait mirror aspect ratio as W:H (default: 3:4).",
        )

        # Background
        parser.add_argument(
            "--bg-alpha",
            type=float,
            default=0.05,
            help="Background EMA blending factor (default: 0.05). Higher = faster adaptation.",
        )
        parser.add_argument(
            "--bg-capture-frames",
            type=int,
            default=30,
            help="Number of initial frames for background capture (default: 30).",
        )

        # Face recognition (placeholder for future)
        parser.add_argument(
            "--no-face-recognition",
            action="store_true",
            help="Disable face recognition (everyone visible, just a mirror with effects).",
        )
        parser.add_argument(
            "--face-threshold",
            type=float,
            default=0.5,
            help="Face recognition confidence threshold (default: 0.5).",
        )
        parser.add_argument(
            "--vampires-dir",
            type=str,
            default=None,
            help=(
                "Directory containing vampire face images for enrollment. "
                "Structure: vampires_dir/<name>/image1.jpg."
            ),
        )
        parser.add_argument(
            "--database-dir",
            type=str,
            default=None,
            help="Directory for the vampire face database. Default: <app_dir>/database.",
        )

        super().__init__(app_callback_fn, user_data, parser)

        # Force use_frame so the callback can access and modify frames
        self.options_menu.use_frame = True
        user_data.use_frame = True
