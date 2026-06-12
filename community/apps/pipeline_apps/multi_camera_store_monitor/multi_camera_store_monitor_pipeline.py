# region imports
# Standard library imports
import setproctitle
import os
os.environ["GST_PLUGIN_FEATURE_RANK"] = "vaapidecodebin:NONE"

# Third-party imports
import gi
gi.require_version('Gst', '1.0')
from gi.repository import Gst

# Local application-specific imports
import hailo
from hailo_apps.python.core.common.core import get_pipeline_parser, get_resource_path, handle_list_models_flag, resolve_hef_path
from hailo_apps.python.core.common.defines import (
    TAPPAS_STREAM_ID_TOOL_SO_FILENAME,
    MULTI_SOURCE_APP_TITLE,
    SIMPLE_DETECTION_PIPELINE,
    DETECTION_PIPELINE,
    RESOURCES_SO_DIR_NAME,
    DETECTION_POSTPROCESS_SO_FILENAME,
    DETECTION_POSTPROCESS_FUNCTION,
    TAPPAS_POSTPROC_PATH_KEY,
)
from hailo_apps.python.core.gstreamer.gstreamer_helper_pipelines import (
    get_source_type,
    USER_CALLBACK_PIPELINE,
    TRACKER_PIPELINE,
    QUEUE,
    SOURCE_PIPELINE,
    INFERENCE_PIPELINE,
    DISPLAY_PIPELINE,
)
from hailo_apps.python.core.gstreamer.gstreamer_app import GStreamerApp, app_callback_class, dummy_callback
from hailo_apps.python.core.common.hailo_logger import get_logger

hailo_logger = get_logger(__name__)
# endregion imports

# Camera name mapping for display
CAMERA_NAMES = {
    "src_0": "Entrance",
    "src_1": "Checkout",
    "src_2": "Stockroom",
}

NUM_STORE_CAMERAS = 3


class GStreamerStoreMonitorApp(GStreamerApp):
    """Multi-camera store monitoring pipeline.

    Processes 3 camera feeds (entrance, checkout, stockroom) through a single
    shared YOLOv8 detection pipeline using round-robin scheduling. Each source
    gets its own display window with detection overlays and per-camera person
    counts accessible in the callback.
    """

    def __init__(self, app_callback, user_data, parser=None):
        if parser is None:
            parser = get_pipeline_parser()
        parser.add_argument(
            "--sources",
            default="",
            help=(
                "Comma-separated list of video sources for the 3 store cameras. "
                "e.g., /dev/video0,/dev/video2,/dev/video4 or "
                "entrance.mp4,checkout.mp4,stockroom.mp4"
            ),
        )
        parser.add_argument(
            "--person-threshold",
            type=float,
            default=0.5,
            help="Confidence threshold for person detections (default: 0.5)",
        )

        # Handle --list-models flag - uses detection models
        handle_list_models_flag(parser, DETECTION_PIPELINE)

        super().__init__(parser, user_data)
        setproctitle.setproctitle("Hailo Store Monitor")

        # Resolve HEF path with smart lookup and auto-download (uses detection models)
        self.hef_path = resolve_hef_path(
            self.hef_path,
            app_name=DETECTION_PIPELINE,
            arch=self.arch,
        )
        self.post_process_so = get_resource_path(
            SIMPLE_DETECTION_PIPELINE,
            RESOURCES_SO_DIR_NAME,
            self.arch,
            DETECTION_POSTPROCESS_SO_FILENAME,
        )
        self.post_function_name = DETECTION_POSTPROCESS_FUNCTION

        # Parse sources: default to 3 copies of the default video if not specified
        if self.options_menu.sources:
            source_list = self.options_menu.sources.split(",")
        else:
            source_list = [self.video_source] * NUM_STORE_CAMERAS

        if len(source_list) != NUM_STORE_CAMERAS:
            hailo_logger.warning(
                "Expected %d sources but got %d. Adjusting.",
                NUM_STORE_CAMERAS,
                len(source_list),
            )
            # Pad or truncate to NUM_STORE_CAMERAS
            while len(source_list) < NUM_STORE_CAMERAS:
                source_list.append(source_list[-1])
            source_list = source_list[:NUM_STORE_CAMERAS]

        self.video_sources_types = [
            (src.strip(), get_source_type(src.strip())) for src in source_list
        ]
        self.num_sources = len(self.video_sources_types)

        # Store person threshold for use in callback
        self.person_threshold = self.options_menu.person_threshold

        self.app_callback = app_callback
        self.create_pipeline()

    def get_pipeline_string(self):
        """Build the multi-source round-robin detection pipeline.

        Pipeline layout:
            SOURCE_0 -> set_stream_id(src_0) -> robin.sink_0
            SOURCE_1 -> set_stream_id(src_1) -> robin.sink_1
            SOURCE_2 -> set_stream_id(src_2) -> robin.sink_2

            hailoroundrobin(mode=1) -> INFERENCE -> TRACKER -> CALLBACK
                -> hailostreamrouter
                    router.src_0 -> per-source callback -> DISPLAY_0
                    router.src_1 -> per-source callback -> DISPLAY_1
                    router.src_2 -> per-source callback -> DISPLAY_2
        """
        sources_string = ""
        router_string = ""

        tappas_post_process_dir = os.environ.get(TAPPAS_POSTPROC_PATH_KEY, "")
        set_stream_id_so = os.path.join(
            tappas_post_process_dir, TAPPAS_STREAM_ID_TOOL_SO_FILENAME
        )

        for idx in range(self.num_sources):
            camera_name = CAMERA_NAMES.get(f"src_{idx}", f"Camera_{idx}")
            sources_string += SOURCE_PIPELINE(
                video_source=self.video_sources_types[idx][0],
                frame_rate=self.frame_rate,
                sync=self.sync,
                name=f"source_{idx}",
                no_webcam_compression=False,
            )
            sources_string += (
                f"! hailofilter name=set_src_{idx} so-path={set_stream_id_so} "
                f"config-path=src_{idx} "
            )
            sources_string += (
                f"! {QUEUE(name=f'src_q_{idx}', max_size_buffers=30)} "
                f"! robin.sink_{idx} "
            )

            router_string += (
                f"router.src_{idx} "
                f"! {USER_CALLBACK_PIPELINE(name=f'src_{idx}_callback')} "
                f"! {QUEUE(name=f'callback_q_{idx}', max_size_buffers=30)} "
                f"! {DISPLAY_PIPELINE(video_sink=self.video_sink, sync=self.sync, show_fps=self.show_fps, name=f'hailo_display_{idx}')} "
            )

        self.thresholds_str = (
            "nms-score-threshold=0.3 "
            "nms-iou-threshold=0.45 "
            "output-format-type=HAILO_FORMAT_TYPE_FLOAT32"
        )

        # Shared detection pipeline for all sources
        detection_pipeline = INFERENCE_PIPELINE(
            hef_path=self.hef_path,
            post_process_so=self.post_process_so,
            post_function_name=self.post_function_name,
            batch_size=self.batch_size,
            additional_params=self.thresholds_str,
        )

        inference_string = (
            f"hailoroundrobin mode=1 name=robin "
            f"! {detection_pipeline} "
            f"! {TRACKER_PIPELINE(class_id=-1)} "
            f"! {USER_CALLBACK_PIPELINE()} "
            f"! {QUEUE(name='call_q', max_size_buffers=30)} "
            f"! hailostreamrouter name=router "
        )
        for idx in range(self.num_sources):
            inference_string += f'src_{idx}::input-streams="<sink_{idx}>" '

        pipeline_string = sources_string + inference_string + router_string
        hailo_logger.info("Pipeline string:\n%s", pipeline_string)
        return pipeline_string


def main():
    # Create an instance of the user app callback class
    user_data = app_callback_class()
    app_callback_fn = dummy_callback
    app = GStreamerStoreMonitorApp(app_callback_fn, user_data)
    app.run()


if __name__ == "__main__":
    print("Starting Hailo Multi-Camera Store Monitor...")
    main()
