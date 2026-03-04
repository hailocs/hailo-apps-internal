# region imports
# Standard library imports
import sys
import setproctitle

# Local application-specific imports
from hailo_apps.python.core.common.core import (
    get_pipeline_parser,
    get_resource_path,
    handle_list_models_flag,
    configure_multi_model_hef_path,
    resolve_hef_paths,
)
from hailo_apps.python.core.common.defines import (
    GESTURE_DETECTION_APP_TITLE,
    GESTURE_DETECTION_PIPELINE,
    HAND_LANDMARK_POSTPROCESS_SO_FILENAME,
    HAND_LANDMARK_POSTPROCESS_FUNCTION,
    HAND_CROP_POSTPROCESS_SO_FILENAME,
    HAND_CROP_POSTPROCESS_FUNCTION,
    POSE_ESTIMATION_POSTPROCESS_SO_FILENAME,
    POSE_ESTIMATION_POSTPROCESS_FUNCTION,
    RESOURCES_SO_DIR_NAME,
    HAILO10H_ARCH,
)
from hailo_apps.python.core.common.hailo_logger import get_logger
from hailo_apps.python.core.gstreamer.gstreamer_app import GStreamerApp
from hailo_apps.python.core.gstreamer.gstreamer_helper_pipelines import (
    QUEUE,
    SOURCE_PIPELINE,
    INFERENCE_PIPELINE,
    INFERENCE_PIPELINE_WRAPPER,
    TRACKER_PIPELINE,
    CROPPER_PIPELINE,
    USER_CALLBACK_PIPELINE,
    DISPLAY_PIPELINE,
)

hailo_logger = get_logger(__name__)
# endregion imports


class GStreamerGestureDetectionApp(GStreamerApp):
    def __init__(self, app_callback, user_data, parser=None):
        if parser is None:
            parser = get_pipeline_parser()

        # Configure --hef-path for multi-model support (pose estimation + hand landmark)
        configure_multi_model_hef_path(parser)

        # Handle --list-models flag before full initialization
        handle_list_models_flag(parser, GESTURE_DETECTION_PIPELINE)

        hailo_logger.info("Initializing GStreamer Gesture Detection App...")

        super().__init__(parser, user_data)
        setproctitle.setproctitle(GESTURE_DETECTION_APP_TITLE)

        # Verify architecture - hand_landmark_lite is only available for hailo10h
        if self.arch != HAILO10H_ARCH:
            hailo_logger.error(
                "Gesture detection requires hailo10h. Detected: %s", self.arch
            )
            print(
                f"ERROR: Gesture detection pipeline requires hailo10h architecture. "
                f"Detected: {self.arch}. "
                f"The hand_landmark_lite model is only available for hailo10h.",
                file=sys.stderr,
            )
            sys.exit(1)

        # Model parameters
        if self.batch_size == 1:
            self.batch_size = 2

        # Resolve HEF paths for multi-model app (pose estimation + hand landmark)
        models = resolve_hef_paths(
            hef_paths=self.options_menu.hef_path,
            app_name=GESTURE_DETECTION_PIPELINE,
            arch=self.arch,
        )
        self.hef_path_pose = models[0].path
        self.hef_path_hand_landmark = models[1].path
        hailo_logger.debug("Pose HEF: %s", self.hef_path_pose)
        hailo_logger.debug("Hand Landmark HEF: %s", self.hef_path_hand_landmark)

        # Post-processing shared objects
        self.post_process_so_pose = get_resource_path(
            pipeline_name=None,
            resource_type=RESOURCES_SO_DIR_NAME,
            arch=self.arch,
            model=POSE_ESTIMATION_POSTPROCESS_SO_FILENAME,
        )
        self.post_process_so_hand_landmark = get_resource_path(
            pipeline_name=None,
            resource_type=RESOURCES_SO_DIR_NAME,
            arch=self.arch,
            model=HAND_LANDMARK_POSTPROCESS_SO_FILENAME,
        )
        self.post_process_so_hand_cropper = get_resource_path(
            pipeline_name=None,
            resource_type=RESOURCES_SO_DIR_NAME,
            arch=self.arch,
            model=HAND_CROP_POSTPROCESS_SO_FILENAME,
        )

        self.app_callback = app_callback
        self.create_pipeline()
        hailo_logger.info("Pipeline created successfully.")

    def get_pipeline_string(self):
        hailo_logger.debug("Building gesture detection pipeline string...")

        source_pipeline = SOURCE_PIPELINE(
            video_source=self.video_source,
            video_width=self.video_width,
            video_height=self.video_height,
            frame_rate=self.frame_rate,
            sync=self.sync,
        )

        # Stage 1: YOLOv8 pose estimation
        pose_inference = INFERENCE_PIPELINE(
            hef_path=self.hef_path_pose,
            post_process_so=self.post_process_so_pose,
            post_function_name=POSE_ESTIMATION_POSTPROCESS_FUNCTION,
            batch_size=self.batch_size,
        )
        pose_inference_wrapper = INFERENCE_PIPELINE_WRAPPER(pose_inference)

        # Tracker for person detections (class_id=0 for person)
        tracker_pipeline = TRACKER_PIPELINE(class_id=0)

        # Stage 2: Hand landmark inference inside cropper
        hand_landmark_inference = INFERENCE_PIPELINE(
            hef_path=self.hef_path_hand_landmark,
            post_process_so=self.post_process_so_hand_landmark,
            post_function_name=HAND_LANDMARK_POSTPROCESS_FUNCTION,
            batch_size=1,
            name="hand_landmark_inference",
        )

        # Cropper: crops hand regions from pose wrist keypoints, then runs hand landmark
        cropper_pipeline = CROPPER_PIPELINE(
            inner_pipeline=hand_landmark_inference,
            so_path=self.post_process_so_hand_cropper,
            function_name=HAND_CROP_POSTPROCESS_FUNCTION,
            internal_offset=True,
        )

        user_callback_pipeline = USER_CALLBACK_PIPELINE()
        display_pipeline = DISPLAY_PIPELINE(
            video_sink=self.video_sink, sync=self.sync, show_fps=self.show_fps
        )

        pipeline_string = (
            f"{source_pipeline} ! "
            f"{pose_inference_wrapper} ! "
            f"{tracker_pipeline} ! "
            f"{cropper_pipeline} ! "
            f"{user_callback_pipeline} ! "
            f"{display_pipeline}"
        )
        hailo_logger.debug("Pipeline string: %s", pipeline_string)
        return pipeline_string
