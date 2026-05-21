"""GStreamer pipeline for Vampire Mirror v2.

Subclasses the instance segmentation pipeline (YOLOv5-Seg + ByteTrack)
and adds vampire-mirror-specific CLI arguments. The app-specific vampire
logic runs in the Python callback, not in the pipeline.
"""

import argparse
import setproctitle

from hailo_apps.python.core.common.hailo_logger import get_logger
from hailo_apps.python.core.common.parser import get_pipeline_parser
from hailo_apps.python.pipeline_apps.instance_segmentation.instance_segmentation_pipeline import (
    GStreamerInstanceSegmentationApp,
)
from community.apps.pipeline_apps.vampire_mirror.frame_geometry import FrameGeometry

logger = get_logger(__name__)


class VampireMirrorPipeline(GStreamerInstanceSegmentationApp):
    """Vampire Mirror pipeline — instance segmentation + tracking + vampire args."""

    def __init__(self, app_callback_fn, user_data, parser=None):
        setproctitle.setproctitle("vampire_mirror")
        if parser is None:
            parser = get_pipeline_parser()

        # Public attributes: plumbed into the pipeline string by get_pipeline_string().
        # Initialised here — BEFORE super().__init__() — so that get_pipeline_string()
        # can read them when called from create_pipeline() inside super().__init__().
        # The caller (main()) may overwrite these AFTER construction by calling
        # create_pipeline() explicitly, which rebuilds self.pipeline with the correct
        # shm fragment inserted.
        self.vampire_bg_shm_a: str = ""
        self.vampire_bg_shm_b: str = ""
        self.vampire_bg_shm_idx: str = ""
        self.vampire_bg_w: int = 0
        self.vampire_bg_h: int = 0

        # Mirror crop parameters — set after super().__init__() so that
        # options_menu (parsed CLI args) is available.  Defaults used until then.
        self.mirror_crop_left: int = 0
        self.mirror_crop_right: int = 0
        self.mirror_crop_top: int = 0
        self.mirror_crop_bottom: int = 0

        # Suppress the automatic create_pipeline() call inside
        # GStreamerInstanceSegmentationApp.__init__().  We defer pipeline creation
        # to the explicit create_pipeline() call in main() so that the caller can
        # populate the vampire_bg_shm_* attributes first.
        self._defer_pipeline_creation = True

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

        parser.add_argument(
            "--bg-process",
            action=argparse.BooleanOptionalAction,
            default=True,
            help=(
                "Run the background EMA in a subprocess and draw vampires via "
                "the hailovampire_overlay C++ element (default: on). "
                "--no-bg-process is a debug fallback that runs the EMA in-process "
                "and disables the vampire-invisibility effect."
            ),
        )

        parser.add_argument(
            "--show-overlay",
            action=argparse.BooleanOptionalAction,
            default=False,
            help=(
                "Draw the hailooverlay bounding-box / segmentation overlay on the "
                "displayed frame (default: off — a real mirror has no debug graphics). "
                "Use --show-overlay to re-enable for debugging."
            ),
        )

        # Vampire mask buffer (dilation of the segmentation mask before background
        # compositing). Bigger values = wider invisibility halo around vampires —
        # useful for hiding segmentation jitter at the body outline.
        parser.add_argument(
            "--dilate-radius",
            type=int,
            default=25,
            help="Vampire mask dilation kernel radius in px (default: 25).",
        )
        parser.add_argument(
            "--dilate-iterations",
            type=int,
            default=3,
            help="Vampire mask dilation iterations (default: 3).",
        )

        super().__init__(app_callback_fn, user_data, parser)

        # Compute portrait center-crop coordinates from CLI args.
        # vertical_pad=0 assumes a standard camera (no letterboxing). The
        # callback's detect_vertical_padding is still invoked for the
        # is_in_mirror() check but no longer drives the displayed crop.
        width = self.options_menu.width if self.options_menu.width else 1280
        height = self.options_menu.height if self.options_menu.height else 720
        ratio_parts = self.options_menu.mirror_ratio.split(":")
        mirror_ratio = (int(ratio_parts[0]), int(ratio_parts[1]))
        geometry = FrameGeometry(
            width, height,
            mirror_ratio=mirror_ratio,
            vertical_pad=0,
            vertical_margin=5,
        )
        self.mirror_crop_left   = geometry.crop_x1
        self.mirror_crop_right  = width - geometry.crop_x2
        self.mirror_crop_top    = geometry.crop_y1
        self.mirror_crop_bottom = height - geometry.crop_y2
        logger.info(
            "Mirror crop: source=%dx%d, mirror=%dx%d, "
            "videocrop left=%d right=%d top=%d bottom=%d",
            width, height, geometry.mirror_width, geometry.mirror_height,
            self.mirror_crop_left, self.mirror_crop_right,
            self.mirror_crop_top, self.mirror_crop_bottom,
        )

        # Callback still needs the numpy frame view (to build person_mask and
        # forward to bg_service), but we do NOT use the framework's
        # display_user_data_frame subprocess — the GStreamer sink renders the
        # frame directly after hailovampire_overlay paints it.
        self.options_menu.use_frame = False
        user_data.use_frame = True

    def create_pipeline(self):
        """Defer pipeline creation until explicitly called by main().

        GStreamerInstanceSegmentationApp.__init__() calls create_pipeline()
        before the caller has a chance to set the vampire_bg_shm_* attributes.
        We skip the automatic call and let main() call create_pipeline() after
        setting those attributes.
        """
        if getattr(self, "_defer_pipeline_creation", False):
            self._defer_pipeline_creation = False  # only skip the first (automatic) call
            logger.debug("Pipeline creation deferred; waiting for shm attributes to be set")
            return
        super().create_pipeline()

    def get_pipeline_string(self):
        """Build the pipeline with full camera resolution.

        The parent GStreamerInstanceSegmentationApp forces 640x640 source,
        but we want the widest camera resolution for maximum FOV and buffer
        zones.  The INFERENCE_PIPELINE_WRAPPER handles resizing to the
        model's 640x640 input internally, so a non-square source is fine.

        If shm parameters are set (vampire_bg_shm_a etc.), the
        hailovampire_overlay element is spliced in after identity_callback
        and before the display pipeline.
        """
        # Restore user-requested resolution (or camera default)
        width = getattr(self.options_menu, "width", None)
        height = getattr(self.options_menu, "height", None)
        self.video_width = width if width is not None else 1280
        self.video_height = height if height is not None else 720
        logger.info(
            "Source resolution: %dx%d (overriding instance-seg 640x640 default)",
            self.video_width, self.video_height,
        )
        pipeline_str = super().get_pipeline_string()

        if self.vampire_bg_shm_a:
            fragment = (
                f" ! hailovampire_overlay name=vampire_fx "
                f"bg-shm-a-name={self.vampire_bg_shm_a} "
                f"bg-shm-b-name={self.vampire_bg_shm_b} "
                f"bg-idx-shm-name={self.vampire_bg_shm_idx} "
                f"bg-width={self.vampire_bg_w} bg-height={self.vampire_bg_h} "
                f"dilate-radius={self.options_menu.dilate_radius} "
                f"dilate-iterations={self.options_menu.dilate_iterations}"
            )
            # The parent pipeline puts identity_callback before the display fragment.
            # We splice the overlay AFTER identity_callback so it sees the vampire
            # classification tags the Python callback attaches.
            marker = "identity name=identity_callback"
            if marker in pipeline_str:
                idx = pipeline_str.index(marker)
                # Walk forward past any trailing properties (e.g. signal-handoffs=true).
                end = pipeline_str.find(" ! ", idx)
                if end < 0:
                    logger.warning(
                        "Could not find ' ! ' after identity_callback; "
                        "vampire overlay not inserted"
                    )
                else:
                    pipeline_str = pipeline_str[:end] + fragment + pipeline_str[end:]
                    logger.info("Inserted hailovampire_overlay into pipeline")
            else:
                logger.warning(
                    "identity_callback element not found in pipeline string; "
                    "vampire overlay not inserted"
                )

        # Mirror crop splice — applied AFTER hailooverlay so that bbox drawing
        # happens at full source resolution (1280x720) while the normalized bbox
        # coords still match that aspect ratio. videocrop does not rewrite the
        # bbox metadata, so any downstream consumer of normalized coords would
        # be misaligned if videocrop ran first. Bboxes in the buffer zones get
        # cropped away with the buffer pixels — the intended behavior.
        crop_fragment = (
            f" ! videocrop name=mirror_crop "
            f"left={self.mirror_crop_left} right={self.mirror_crop_right} "
            f"top={self.mirror_crop_top} bottom={self.mirror_crop_bottom}"
        )
        crop_marker = "hailooverlay name=hailo_display_overlay"
        if crop_marker in pipeline_str:
            idx = pipeline_str.index(crop_marker)
            end = pipeline_str.find(" ! ", idx)
            if end >= 0:
                pipeline_str = pipeline_str[:end] + crop_fragment + pipeline_str[end:]
                logger.info("Inserted videocrop into pipeline (after hailooverlay)")
            else:
                logger.warning(
                    "Could not find ' ! ' after %s; videocrop not inserted", crop_marker
                )
        else:
            logger.warning("No splice marker found for videocrop; portrait crop not applied")

        # Bypass the hailooverlay bbox / segmentation drawing by swapping it for a
        # passthrough identity element. Done after the videocrop splice so the
        # original element name is still available as a splice marker above.
        if not self.options_menu.show_overlay:
            new_str = pipeline_str.replace(
                "hailooverlay name=hailo_display_overlay",
                "identity name=hailo_display_overlay",
                1,
            )
            if new_str != pipeline_str:
                pipeline_str = new_str
                logger.info("Bypassed hailooverlay (overlay drawing disabled)")
            else:
                logger.warning(
                    "hailooverlay element not found in pipeline string; "
                    "overlay bypass had no effect"
                )

        logger.debug("Pipeline string after vampire splice:\n%s", pipeline_str)
        return pipeline_str
