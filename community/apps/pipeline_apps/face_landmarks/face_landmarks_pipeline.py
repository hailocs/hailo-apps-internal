"""GStreamer pipeline for face landmarks detection.

Two pipeline modes:

**gstreamer** (default): Full cascade — all inference on Hailo in GStreamer.
    SOURCE → SCRFD (hailonet) → TRACKER → CROPPER(face_landmarks_lite + postprocess) → CALLBACK → DISPLAY
    Landmarks arrive as HAILO_LANDMARKS in the callback. CPU only draws.

**python**: SCRFD in GStreamer, landmarks via InferVStreams in the callback.
    SOURCE → SCRFD (hailonet) → TRACKER → CALLBACK(InferVStreams) → DISPLAY
    Callback crops faces and runs face_landmarks_lite on Hailo from Python.
"""

import os
import sys

os.environ["GST_PLUGIN_FEATURE_RANK"] = "vaapidecodebin:NONE"

import setproctitle

from hailo_apps.python.core.common.core import (
    get_pipeline_parser,
    get_resource_path,
    handle_list_models_flag,
    resolve_hef_path,
)
from hailo_apps.python.core.common.defines import (
    FACE_RECOGNITION_PIPELINE,
    FACE_DETECTION_POSTPROCESS_SO_FILENAME,
    FACE_DETECTION_JSON_NAME,
    FACE_CROP_POSTPROCESS_SO_FILENAME,
    RESOURCES_SO_DIR_NAME,
    RESOURCES_JSON_DIR_NAME,
    RESOURCES_VIDEOS_DIR_NAME,
    FACE_RECOGNITION_VIDEO_NAME,
    BASIC_PIPELINES_VIDEO_EXAMPLE_NAME,
    SCRFD_10G_POSTPROCESS_FUNCTION,
    SCRFD_2_5G_POSTPROCESS_FUNCTION,
    HAILO8_ARCH,
    HAILO8L_ARCH,
    HAILO10H_ARCH,
)
from hailo_apps.python.core.common.hailo_logger import get_logger
from hailo_apps.python.core.gstreamer.gstreamer_app import GStreamerApp
from hailo_apps.python.core.gstreamer.gstreamer_helper_pipelines import (
    QUEUE,
    INFERENCE_PIPELINE,
    INFERENCE_PIPELINE_WRAPPER,
    TRACKER_PIPELINE,
    USER_CALLBACK_PIPELINE,
    DISPLAY_PIPELINE,
    CROPPER_PIPELINE,
)

logger = get_logger(__name__)

# face_landmarks_postprocess SO — built from postprocess/ subdir
_POSTPROCESS_BUILD = os.path.join(
    os.path.dirname(__file__), "postprocess", "build", "libface_landmarks_postprocess.so",
)
_POSTPROCESS_SYSTEM = "/usr/local/hailo/resources/so/libface_landmarks_postprocess.so"

_MESH_ALIGN_BUILD = os.path.join(
    os.path.dirname(__file__), "postprocess", "build", "libface_mesh_align.so",
)
_MESH_ALIGN_SYSTEM = "/usr/local/hailo/resources/so/libface_mesh_align.so"


def _find_landmarks_postprocess_so() -> str:
    """Find the face_landmarks_postprocess SO (local build first, then system)."""
    if os.path.isfile(_POSTPROCESS_BUILD):
        return _POSTPROCESS_BUILD
    if os.path.isfile(_POSTPROCESS_SYSTEM):
        return _POSTPROCESS_SYSTEM
    raise FileNotFoundError(
        "libface_landmarks_postprocess.so not found. "
        "Build it: cd postprocess && ./build.sh"
    )


def _find_mesh_align_so() -> str | None:
    """Find the face_mesh_align SO (local build first, then system). None if missing."""
    if os.path.isfile(_MESH_ALIGN_BUILD):
        return _MESH_ALIGN_BUILD
    if os.path.isfile(_MESH_ALIGN_SYSTEM):
        return _MESH_ALIGN_SYSTEM
    return None


def _find_landmarks_hef(arch: str) -> str:
    """Find face_landmarks_lite.hef in the resources directory."""
    resources_root = os.environ.get("HAILO_RESOURCES_PATH", "/usr/local/hailo/resources")
    hef_path = os.path.join(resources_root, "models", arch, "face_landmarks_lite.hef")
    if not os.path.isfile(hef_path):
        raise FileNotFoundError(
            f"face_landmarks_lite.hef not found at {hef_path}. "
            "Download it from the Hailo Model Zoo."
        )
    return hef_path


class GStreamerFaceLandmarksApp(GStreamerApp):
    """Face landmarks pipeline with two modes: 'gstreamer' (full cascade) or 'python' (InferVStreams).

    In both modes, SCRFD runs on Hailo via GStreamer hailonet for face detection.
    The difference is how face_landmarks_lite runs:
    - gstreamer: hailocropper → hailonet → hailofilter (postprocess) → HAILO_LANDMARKS
    - python: InferVStreams in the callback (see face_landmarks.py)
    """

    def __init__(self, app_callback, user_data, parser=None):
        if parser is None:
            parser = get_pipeline_parser()

        parser.add_argument(
            "--pipeline-mode",
            choices=["gstreamer", "python"],
            default="gstreamer",
            help="Pipeline mode: 'gstreamer' (full cascade, default) or 'python' (InferVStreams in callback).",
        )

        handle_list_models_flag(parser, FACE_RECOGNITION_PIPELINE)

        super().__init__(parser, user_data)
        self.app_callback = app_callback
        setproctitle.setproctitle("hailo-face-landmarks")

        self.pipeline_mode = self.options_menu.pipeline_mode

        # Replace default video with face recognition video
        if BASIC_PIPELINES_VIDEO_EXAMPLE_NAME in self.video_source:
            self.video_source = get_resource_path(
                pipeline_name=None,
                resource_type=RESOURCES_VIDEOS_DIR_NAME,
                arch=self.arch,
                model=FACE_RECOGNITION_VIDEO_NAME,
            )

        # Resolve SCRFD HEF
        self.hef_path_detection = resolve_hef_path(
            self.options_menu.hef_path,
            FACE_RECOGNITION_PIPELINE,
            self.arch,
        )
        logger.info("Detection HEF: %s", self.hef_path_detection)

        # face_landmarks_lite HEF (needed for both modes)
        self.hef_path_landmarks = _find_landmarks_hef(self.arch)
        logger.info("Landmarks HEF: %s", self.hef_path_landmarks)

        # Architecture-specific detection postprocess
        if self.arch in (HAILO8_ARCH, HAILO10H_ARCH):
            self.detection_func = SCRFD_10G_POSTPROCESS_FUNCTION
        elif self.arch == HAILO8L_ARCH:
            self.detection_func = SCRFD_2_5G_POSTPROCESS_FUNCTION
        else:
            logger.error("Unsupported architecture: %s", self.arch)
            sys.exit(1)

        # SO paths
        self.post_process_so_scrfd = get_resource_path(
            pipeline_name=None,
            resource_type=RESOURCES_SO_DIR_NAME,
            arch=self.arch,
            model=FACE_DETECTION_POSTPROCESS_SO_FILENAME,
        )
        self.post_process_so_cropper = get_resource_path(
            pipeline_name=None,
            resource_type=RESOURCES_SO_DIR_NAME,
            arch=self.arch,
            model=FACE_CROP_POSTPROCESS_SO_FILENAME,
        )

        self.batch_size = 2

        # Force use_frame so the callback can draw
        self.options_menu.use_frame = True
        user_data.use_frame = True

        logger.info("Pipeline mode: %s", self.pipeline_mode)
        self.create_pipeline()

    def get_pipeline_string(self):
        """Build the GStreamer pipeline based on pipeline_mode."""
        source = self.get_source_pipeline()

        detection_pipeline = INFERENCE_PIPELINE(
            hef_path=self.hef_path_detection,
            post_process_so=self.post_process_so_scrfd,
            post_function_name=self.detection_func,
            batch_size=self.batch_size,
            config_json=get_resource_path(
                pipeline_name=None,
                resource_type=RESOURCES_JSON_DIR_NAME,
                arch=self.arch,
                model=FACE_DETECTION_JSON_NAME,
            ),
        )
        detection_pipeline_wrapper = INFERENCE_PIPELINE_WRAPPER(detection_pipeline)

        tracker_pipeline = TRACKER_PIPELINE(
            class_id=-1,
            kalman_dist_thr=0.7,
            iou_thr=0.8,
            init_iou_thr=0.9,
            keep_new_frames=2,
            keep_tracked_frames=6,
            keep_lost_frames=8,
            keep_past_metadata=True,
            name="hailo_face_tracker",
        )

        user_callback = USER_CALLBACK_PIPELINE()
        display = DISPLAY_PIPELINE(
            video_sink=self.video_sink, sync=self.sync, show_fps=self.show_fps,
        )

        if self.pipeline_mode == "gstreamer":
            # Full cascade: SCRFD → tracker → cropper(face_mesh_align → face_landmarks_lite → postprocess) → callback
            landmarks_postprocess_so = _find_landmarks_postprocess_so()
            landmarks_inference = INFERENCE_PIPELINE(
                hef_path=self.hef_path_landmarks,
                post_process_so=landmarks_postprocess_so,
                post_function_name="filter",
                batch_size=1,
                name="face_landmarks_inference",
            )

            # face_mesh_align: rotation-aware warp using SCRFD eye keypoints.
            # Runs inside the cropper inner pipeline before the landmark hailonet.
            # If the SO is missing, fall back to unaligned (slightly off-tilt landmarks).
            mesh_align_so = _find_mesh_align_so()
            if mesh_align_so:
                inner_pipeline = (
                    f"hailofilter so-path={mesh_align_so} "
                    f"name=face_mesh_align_hailofilter use-gst-buffer=true qos=false ! "
                    f"{QUEUE(name='face_mesh_align_output_q')} ! "
                    f"{landmarks_inference}"
                )
                logger.info("Cascade: using rotation-aligned crop via face_mesh_align")
            else:
                inner_pipeline = landmarks_inference
                logger.warning(
                    "libface_mesh_align.so not found — cascade will use unaligned crops. "
                    "Build it: cd postprocess && ./build.sh"
                )

            cropper_pipeline = CROPPER_PIPELINE(
                inner_pipeline=inner_pipeline,
                so_path=self.post_process_so_cropper,
                function_name="face_recognition",
                internal_offset=True,
            )

            return (
                f"{source} ! "
                f"{detection_pipeline_wrapper} ! "
                f"{tracker_pipeline} ! "
                f"{cropper_pipeline} ! "
                f"{user_callback} ! "
                f"{display}"
            )
        else:
            # Python mode: SCRFD → tracker → callback (InferVStreams in Python)
            return (
                f"{source} ! "
                f"{detection_pipeline_wrapper} ! "
                f"{tracker_pipeline} ! "
                f"{user_callback} ! "
                f"{display}"
            )
