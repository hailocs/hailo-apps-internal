# region imports
from pathlib import Path

import setproctitle

from hailo_apps.python.core.common.core import (
    get_pipeline_parser,
    get_resource_path,
)
from hailo_apps.python.core.common.defines import (
    HAND_LANDMARK_POSTPROCESS_SO_FILENAME,
    RESOURCES_SO_DIR_NAME,
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
    USER_CALLBACK_PIPELINE,
)

hailo_logger = get_logger(__name__)
# endregion imports

HEF_PATH = "/usr/local/hailo/resources/models/hailo10h/hand_landmark_lite.hef"


class GStreamerHandLandmarkTestApp(GStreamerApp):
    def __init__(self, app_callback, user_data, parser=None):
        if parser is None:
            parser = get_pipeline_parser()

        hailo_logger.info("Initializing Hand Landmark Test App...")
        super().__init__(parser, user_data)

        self.post_process_so = get_resource_path(
            pipeline_name=None,
            resource_type=RESOURCES_SO_DIR_NAME,
            arch=self.arch,
            model=HAND_LANDMARK_POSTPROCESS_SO_FILENAME,
        )

        if self.post_process_so is None or not Path(self.post_process_so).exists():
            hailo_logger.error("Post-process .so missing: %s", self.post_process_so)

        hailo_logger.info("HEF: %s", HEF_PATH)
        hailo_logger.info("Post-process SO: %s", self.post_process_so)

        self.app_callback = app_callback
        setproctitle.setproctitle("hand_landmark_test")
        self.create_pipeline()
        hailo_logger.info("Pipeline created successfully.")

    def get_pipeline_string(self):
        source_pipeline = SOURCE_PIPELINE(
            video_source=self.video_source,
            video_width=self.video_width,
            video_height=self.video_height,
            frame_rate=self.frame_rate,
            sync=self.sync,
        )

        inference = INFERENCE_PIPELINE(
            hef_path=HEF_PATH,
            post_process_so=self.post_process_so,
            post_function_name="filter",
            batch_size=1,
        )
        inference_wrapper = INFERENCE_PIPELINE_WRAPPER(inference)

        user_callback_pipeline = USER_CALLBACK_PIPELINE()
        display_pipeline = DISPLAY_PIPELINE(
            video_sink=self.video_sink, sync=self.sync, show_fps=self.show_fps
        )

        pipeline_string = (
            f"{source_pipeline} ! "
            f"{inference_wrapper} ! "
            f"{user_callback_pipeline} ! "
            f"{display_pipeline}"
        )
        hailo_logger.debug("Pipeline string: %s", pipeline_string)
        return pipeline_string


def main():
    hailo_logger.info("Starting Hand Landmark Test Pipeline (standalone, no cropper)")
    user_data = app_callback_class()
    app = GStreamerHandLandmarkTestApp(dummy_callback, user_data)
    app.run()


if __name__ == "__main__":
    main()
