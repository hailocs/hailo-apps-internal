# region imports
# Standard library imports
import setproctitle

# Third-party imports
import gi
gi.require_version('Gst', '1.0')
from gi.repository import Gst

# Local application-specific imports
import hailo
from hailo_apps.hailo_app_python.core.common.installation_utils import detect_hailo_arch
from hailo_apps.hailo_app_python.core.common.core import get_default_parser, get_resource_path
from hailo_apps.hailo_app_python.core.common.defines import (
    TILING_APP_TITLE, 
    TILING_POSTPROCESS_SO_FILENAME, 
    TILING_POSTPROCESS_FUNCTION,
    RESOURCES_SO_DIR_NAME,
)
from hailo_apps.hailo_app_python.core.gstreamer.gstreamer_helper_pipelines import SOURCE_PIPELINE, INFERENCE_PIPELINE, USER_CALLBACK_PIPELINE, DISPLAY_PIPELINE, TILE_CROPPER_PIPELINE
from hailo_apps.hailo_app_python.core.gstreamer.gstreamer_app import GStreamerApp, app_callback_class, dummy_callback
# endregion imports

# -----------------------------------------------------------------------------------------------
# User Gstreamer Application
# -----------------------------------------------------------------------------------------------

# This class inherits from the hailo_rpi_common.GStreamerApp class
class GStreamerTilingApp(GStreamerApp):
    def __init__(self, app_callback, user_data, parser=None):
        if parser == None:
            parser = get_default_parser()
        parser.add_argument("--tiles_along_x_axis", default=4, help="Set number of tiles along x axis (columns). Default is 4")
        parser.add_argument("--tiles_along_y_axis", default=3, help="Set number of tiles along y axis (rows). Default is 3")
        parser.add_argument("--overlap_x_axis", default=0.1, help="Set overlap in percentage between tiles along x axis (columns). Default is 0.1")
        parser.add_argument("--overlap_y_axis", default=0.08, help="Set overlap in percentage between tiles along y axis (rows). Default is 0.08")
        parser.add_argument("--iou_threshold", default=0.3, help="Set iou threshold for NMS. Default is 0.3")
        parser.add_argument("--border_threshold", default=0.1, help="Set border threshold to Remove tile's exceeded objects. Relevant only for multi scaling. Default is 0.1")
        parser.add_argument("--single_scaling", action="store_true", help="Whether use single scaling or multi scaling. Default is multi scaling.")
        parser.add_argument("--scale_level", default=2, help="set scales (layers of tiles) in addition to the main layer [1,2,3] 1: {(1 X 1)} 2: {(1 X 1), (2 X 2)} 3: {(1 X 1), (2 X 2), (3 X 3)}. Default is 2. For singlescaling must be 0.")
        
        # Call the parent class constructor
        super().__init__(parser, user_data)
        
        if self.options_menu.single_scaling:
            self.options_menu.scale_level = 0
            self.options_menu.border_threshold = 0

        # Determine the architecture if not specified
        if self.options_menu.arch is None:
            detected_arch = detect_hailo_arch()
            if detected_arch is None:
                raise ValueError("Could not auto-detect Hailo architecture. Please specify --arch manually.")
            self.arch = detected_arch
            print(f"Auto-detected Hailo architecture: {self.arch}")
        else:
            self.arch = self.options_menu.arch

        self.hef_path = '/home/hailo/Desktop/hailo-apps-infra/resources/tiling/ssd_mobilenet_v1.hef'
        self.post_process_so = get_resource_path(pipeline_name=None, resource_type=RESOURCES_SO_DIR_NAME, model=TILING_POSTPROCESS_SO_FILENAME)
        self.post_function = TILING_POSTPROCESS_FUNCTION

        self.app_callback = app_callback
        setproctitle.setproctitle(TILING_APP_TITLE)
        self.create_pipeline()

    def get_pipeline_string(self):
        source_pipeline = SOURCE_PIPELINE(
            video_source=self.video_source,
            video_width=self.video_width, video_height=self.video_height,
            frame_rate=self.frame_rate, sync=self.sync,
            no_webcam_compression=True)
        
        detection_pipeline = INFERENCE_PIPELINE(
            hef_path=self.hef_path,
            post_process_so=self.post_process_so,
            post_function_name=self.post_function,
            batch_size=self.batch_size)
        
        tile_cropper_pipeline = TILE_CROPPER_PIPELINE(
            detection_pipeline,
            name='tile_cropper_wrapper',
            internal_offset=True,
            scale_level=self.options_menu.scale_level,
            tiling_mode=0 if self.options_menu.single_scaling else 1,
            tiles_along_x_axis=self.options_menu.tiles_along_x_axis,
            tiles_along_y_axis=self.options_menu.tiles_along_y_axis,
            overlap_x_axis=self.options_menu.overlap_x_axis,
            overlap_y_axis=self.options_menu.overlap_y_axis,
            iou_threshold=self.options_menu.iou_threshold,
            border_threshold=0 if self.options_menu.single_scaling else self.options_menu.border_threshold
        )

        user_callback_pipeline = USER_CALLBACK_PIPELINE()

        display_pipeline = DISPLAY_PIPELINE(video_sink=self.video_sink, sync=self.sync, show_fps=self.show_fps)

        pipeline_string = (
            f'{source_pipeline} ! '
            f'{tile_cropper_pipeline} ! '
            f'{user_callback_pipeline} ! '
            f'{display_pipeline}'
        )

        print(pipeline_string)
        return pipeline_string
    
def app_callback(pad, info, user_data):
    buffer = info.get_buffer()
    if buffer is None:
        return Gst.PadProbeReturn.OK
    roi = hailo.get_roi_from_buffer(buffer)
    detections = roi.get_objects_typed(hailo.HAILO_DETECTION)
    for detection in detections:
        track_id = detection.get_objects_typed(hailo.HAILO_UNIQUE_ID)[0].get_id()
        print(f'Unified callback, {roi.get_stream_id()}_{detection.get_label()}_{track_id}')
    return Gst.PadProbeReturn.OK

def main():
    # Create an instance of the user app callback class
    user_data = app_callback_class()
    app_callback = dummy_callback
    app = GStreamerTilingApp(app_callback, user_data)
    app.run()

if __name__ == "__main__":
    print("Starting Hailo Tiling App...")
    main()
