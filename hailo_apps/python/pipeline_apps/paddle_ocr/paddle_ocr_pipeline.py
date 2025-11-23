# region imports
# Standard library imports
from pathlib import Path
import os

import setproctitle

from hailo_apps.hailo_app_python.core.common.core import get_default_parser, get_resource_path
from hailo_apps.hailo_app_python.core.common.defines import (
    OCR_APP_TITLE,
    OCR_PIPELINE,
    OCR_DETECTION_MODEL_NAME,
    OCR_RECOGNITION_MODEL_NAME,
    OCR_POSTPROCESS_SO_FILENAME,
    OCR_DETECTION_POSTPROCESS_FUNCTION,
    OCR_RECOGNITION_POSTPROCESS_FUNCTION,
    OCR_CROPPER_FUNCTION,
    OCR_VIDEO_NAME,
    RESOURCES_MODELS_DIR_NAME,
    RESOURCES_SO_DIR_NAME,
    RESOURCES_VIDEOS_DIR_NAME,
    REPO_ROOT,
)

# Logger
from hailo_apps.hailo_app_python.core.common.hailo_logger import get_logger
from hailo_apps.hailo_app_python.core.gstreamer.gstreamer_app import (
    GStreamerApp,
    app_callback_class,
    dummy_callback,
)
from hailo_apps.hailo_app_python.core.gstreamer.gstreamer_helper_pipelines import (
    DISPLAY_PIPELINE,
    INFERENCE_PIPELINE,
    INFERENCE_PIPELINE_WRAPPER,
    SOURCE_PIPELINE,
    USER_CALLBACK_PIPELINE,
    CROPPER_PIPELINE,
    TRACKER_PIPELINE,
)

hailo_logger = get_logger(__name__)

# endregion imports

# -----------------------------------------------------------------------------------------------
# User Gstreamer Application
# -----------------------------------------------------------------------------------------------


class GStreamerOCRApp(GStreamerApp):
    def __init__(self, app_callback, user_data, parser=None):
        if parser is None:
            parser = get_default_parser()
        
        hailo_logger.info("Initializing GStreamer OCR App...")

        # Call the parent class constructor
        super().__init__(parser, user_data)

        hailo_logger.debug(
            "Parent GStreamerApp initialized | arch=%s | input=%s | fps=%s | sync=%s | show_fps=%s",
            getattr(self.options_menu, "arch", None),
            getattr(self, "video_source", None),
            getattr(self, "frame_rate", None),
            getattr(self, "sync", None),
            getattr(self, "show_fps", None),
        )

        # Set Hailo parameters
        self.batch_size = 1

        # OCR Detection model (detects text regions - bounding boxes)
        if self.options_menu.hef_path is not None:
            self.ocr_det_hef_path = self.options_menu.hef_path
        else:
            self.ocr_det_hef_path = get_resource_path(
                pipeline_name=None,
                resource_type=RESOURCES_MODELS_DIR_NAME,
                arch=self.arch,
                model=OCR_DETECTION_MODEL_NAME
            )

        # OCR Recognition model (recognizes text in cropped regions)
        self.ocr_rec_hef_path = get_resource_path(
            pipeline_name=None,
            resource_type=RESOURCES_MODELS_DIR_NAME,
            arch=self.arch,
            model=OCR_RECOGNITION_MODEL_NAME
        )

        # Post-processing shared object file (contains both detection and recognition functions)
        self.post_process_so = get_resource_path(
            pipeline_name=None,
            resource_type=RESOURCES_SO_DIR_NAME,
            arch=self.arch,
            model=OCR_POSTPROCESS_SO_FILENAME
        )

        # Post-processing function names
        self.ocr_det_post_function = OCR_DETECTION_POSTPROCESS_FUNCTION
        self.ocr_rec_post_function = OCR_RECOGNITION_POSTPROCESS_FUNCTION
        self.cropper_function = OCR_CROPPER_FUNCTION

        # Video source - use get_resource_path if default video, otherwise use user input
        if self.video_source is None:
            video_path = get_resource_path(
                pipeline_name=None,
                resource_type=RESOURCES_VIDEOS_DIR_NAME,
                arch=self.arch,
                model=OCR_VIDEO_NAME
            )
            self.video_source = str(video_path) if video_path else None
        
        # OCR detection model expects 960x544 input - resize video to match model input size
        self.video_width = 960
        self.video_height = 544

        hailo_logger.info(
            "Resources | ocr_det_hef=%s | ocr_rec_hef=%s | post_so=%s | det_fn=%s | rec_fn=%s | cropper_fn=%s",
            self.ocr_det_hef_path,
            self.ocr_rec_hef_path,
            self.post_process_so,
            self.ocr_det_post_function,
            self.ocr_rec_post_function,
            self.cropper_function,
        )

        # OCR config file - located in local_resources alongside frequency dictionary
        ocr_config_name = "ocr_config.json"
        ocr_config_path = Path(REPO_ROOT) / "local_resources" / ocr_config_name
        self.ocr_config_path = str(ocr_config_path) if ocr_config_path.exists() else None
        
        if not ocr_config_path.exists():
            hailo_logger.warning("OCR config file not found at: %s", ocr_config_path)

        # Validate resource paths
        if self.ocr_det_hef_path is None or not Path(self.ocr_det_hef_path).exists():
            hailo_logger.error("OCR Detection HEF path is invalid or missing: %s", self.ocr_det_hef_path)
        if self.ocr_rec_hef_path is None or not Path(self.ocr_rec_hef_path).exists():
            hailo_logger.error("OCR Recognition HEF path is invalid or missing: %s", self.ocr_rec_hef_path)
        if self.post_process_so is None or not Path(self.post_process_so).exists():
            hailo_logger.error("Post-process .so path is invalid or missing: %s", self.post_process_so)

        self.app_callback = app_callback

        # Set the process title
        setproctitle.setproctitle(OCR_APP_TITLE)
        hailo_logger.debug("Process title set to %s", OCR_APP_TITLE)

        # Create the pipeline
        self.create_pipeline()
        hailo_logger.debug("Pipeline created")


    def get_pipeline_string(self):
        """Returns the OCR pipeline with detection and recognition."""
        # Full pipeline with detection and recognition
        # 1. Source pipeline
        source_pipeline = SOURCE_PIPELINE(
            video_source=self.video_source,
            video_width=self.video_width,
            video_height=self.video_height,
            frame_rate=self.frame_rate,
            sync=self.sync,
        )

        # 2. OCR Detection pipeline - detects text regions (bounding boxes)
        ocr_det_pipeline = INFERENCE_PIPELINE(
            hef_path=str(self.ocr_det_hef_path) if self.ocr_det_hef_path else None,
            post_process_so=str(self.post_process_so) if self.post_process_so else None,
            post_function_name=self.ocr_det_post_function,
            batch_size=self.batch_size,
            name="ocr_detection",
        )
        
        # Wrap detection to preserve original frame size
        ocr_det_wrapper = INFERENCE_PIPELINE_WRAPPER(ocr_det_pipeline)

        # 2.5. Tracker pipeline - tracks text regions across frames
        tracker_pipeline = TRACKER_PIPELINE(class_id=-1, name="ocr_tracker")

        # 3. OCR Recognition pipeline - recognizes text in cropped regions
        ocr_rec_pipeline = INFERENCE_PIPELINE(
            hef_path=str(self.ocr_rec_hef_path) if self.ocr_rec_hef_path else None,
            post_process_so=str(self.post_process_so) if self.post_process_so else None,
            post_function_name=self.ocr_rec_post_function,
            batch_size=self.batch_size,
            config_json=self.ocr_config_path,
            name="ocr_recognition",
        )

        # 4. Cropper pipeline - crops detected text regions and feeds them to OCR recognition
        ocr_cropper = CROPPER_PIPELINE(
            inner_pipeline=ocr_rec_pipeline,
            so_path=str(self.post_process_so) if self.post_process_so else None,
            function_name=self.cropper_function,
            internal_offset=True,
            name="ocr_cropper",
        )

        # 5. User callback pipeline
        user_callback_pipeline = USER_CALLBACK_PIPELINE()

        # 6. Display pipeline
        display_pipeline = DISPLAY_PIPELINE(
            video_sink=self.video_sink, sync=self.sync, show_fps=self.show_fps
        )

        # Full pipeline: Source -> OCR Detection -> Tracker -> Cropper (with OCR Recognition) -> Callback -> Display
        pipeline_string = (
            f"{source_pipeline} ! "
            f"{ocr_det_wrapper} ! "
            f"{tracker_pipeline} ! "
            f"{ocr_cropper} ! "
            f"{user_callback_pipeline} ! "
            f"{display_pipeline}"
        )
        
        return pipeline_string


def main():
    # Create an instance of the user app callback class
    hailo_logger.info("Starting Hailo OCR App...")
    user_data = app_callback_class()
    app_callback = dummy_callback
    app = GStreamerOCRApp(app_callback, user_data)
    app.run()


if __name__ == "__main__":
    main()

