# region imports
# Standard library imports
import os
import sys
import time
import uuid
import setproctitle
from pathlib import Path
os.environ["GST_PLUGIN_FEATURE_RANK"] = "vaapidecodebin:NONE"

# Third-party imports
import gi
gi.require_version('Gst', '1.0')
from gi.repository import Gst
import numpy as np

# Local application-specific imports
import hailo
from hailo import HailoTracker
from hailo_apps.python.core.common.core import (
    get_pipeline_parser,
    get_resource_path,
    handle_list_models_flag,
    configure_multi_model_hef_path,
    resolve_hef_paths,
)
from hailo_apps.python.core.common.db_handler import DatabaseHandler, Record
from hailo_apps.python.core.common.installation_utils import detect_host_arch
from hailo_apps.python.core.common.defines import (
    ALL_DETECTIONS_CROPPER_POSTPROCESS_SO_FILENAME,
    ARCFACE_MOBILEFACENET_POSTPROCESS_FUNCTION,
    DETECTION_POSTPROCESS_SO_FILENAME,
    FACE_ALIGN_POSTPROCESS_SO_FILENAME,
    FACE_CROP_POSTPROCESS_SO_FILENAME,
    FACE_DETECTION_JSON_NAME,
    FACE_DETECTION_POSTPROCESS_SO_FILENAME,
    FACE_RECOGNITION_POSTPROCESS_SO_FILENAME,
    FACE_RECOGNITION_VIDEO_NAME,
    REID_CLASSIFICATION_TYPE,
    REID_CROPPER_POSTPROCESS_FUNCTION,
    REID_POSTPROCESS_FUNCTION,
    REID_POSTPROCESS_SO_FILENAME,
    RESOURCES_JSON_DIR_NAME,
    RESOURCES_SO_DIR_NAME,
    RESOURCES_VIDEOS_DIR_NAME,
    SCRFD_10G_POSTPROCESS_FUNCTION,
    SCRFD_2_5G_POSTPROCESS_FUNCTION,
    TAPPAS_POSTPROC_PATH_KEY,
    TAPPAS_STREAM_ID_TOOL_SO_FILENAME,
    VMS_CROPPER_POSTPROCESS_FUNCTION,
    RPI_NAME_I,
    HAILO8_ARCH,
    HAILO10H_ARCH,
    HAILO8L_ARCH,
    REID_MULTISOURCE_PIPELINE,
)
from hailo_apps.python.core.gstreamer.gstreamer_helper_pipelines import (
    CROPPER_PIPELINE,
    DISPLAY_PIPELINE,
    INFERENCE_PIPELINE,
    INFERENCE_PIPELINE_WRAPPER,
    QUEUE,
    SOURCE_PIPELINE,
    TRACKER_PIPELINE,
    USER_CALLBACK_PIPELINE,
    get_source_type
)
from hailo_apps.python.core.gstreamer.gstreamer_app import GStreamerApp, app_callback_class, dummy_callback
from hailo_apps.python.core.common.hailo_logger import get_logger

hailo_logger = get_logger(__name__)
# endregion imports


class MultiEntranceTrackerApp(GStreamerApp):
    """Multi-entrance face re-identification tracker.

    Combines SCRFD face detection with ArcFace embedding extraction across
    multiple camera streams, using a LanceDB vector database to track identities
    across entrances. Each entrance camera gets its own display panel with
    cross-camera identity matches highlighted.
    """

    def __init__(self, app_callback, user_data, parser=None):

        if parser is None:
            parser = get_pipeline_parser()
        parser.add_argument(
            "--sources", default='',
            help="Comma-separated list of sources (e.g., /dev/video0,/dev/video1 or video1.mp4,video2.mp4)"
        )
        parser.add_argument(
            "--match-threshold", type=float, default=0.1,
            help="Vector similarity threshold for cross-camera identity matching (lower = stricter, default: 0.1)"
        )
        # Set default resolution for this app
        parser.set_defaults(width=640, height=640)

        # Configure --hef-path for multi-model support (face detection + face recognition)
        configure_multi_model_hef_path(parser)

        # Handle --list-models flag before full initialization
        handle_list_models_flag(parser, REID_MULTISOURCE_PIPELINE)

        super().__init__(parser, user_data)

        setproctitle.setproctitle("multi_entrance_tracker")

        # Resolve HEF paths for multi-model app (face detection + face recognition)
        models = resolve_hef_paths(
            hef_paths=self.options_menu.hef_path,
            app_name=REID_MULTISOURCE_PIPELINE,
            arch=self.arch,
        )
        self.hef_path_scrfd_detection = models[0].path
        self.hef_path_arcface_recognition = models[1].path

        # Postprocess .so paths
        self.post_process_so_yolo_detection = get_resource_path(
            pipeline_name=None, resource_type=RESOURCES_SO_DIR_NAME,
            arch=self.arch, model=DETECTION_POSTPROCESS_SO_FILENAME
        )
        self.post_process_so_repvgg_reid = get_resource_path(
            pipeline_name=None, resource_type=RESOURCES_SO_DIR_NAME,
            arch=self.arch, model=REID_POSTPROCESS_SO_FILENAME
        )
        self.post_process_so_cropper = get_resource_path(
            pipeline_name=None, resource_type=RESOURCES_SO_DIR_NAME,
            arch=self.arch, model=ALL_DETECTIONS_CROPPER_POSTPROCESS_SO_FILENAME
        )
        self.post_process_so_scrfd_detection = get_resource_path(
            pipeline_name=None, resource_type=RESOURCES_SO_DIR_NAME,
            arch=self.arch, model=FACE_DETECTION_POSTPROCESS_SO_FILENAME
        )
        self.post_process_so_arcface_recognition = get_resource_path(
            pipeline_name=None, resource_type=RESOURCES_SO_DIR_NAME,
            arch=self.arch, model=FACE_RECOGNITION_POSTPROCESS_SO_FILENAME
        )
        self.post_process_so_face_align = get_resource_path(
            pipeline_name=None, resource_type=RESOURCES_SO_DIR_NAME,
            arch=self.arch, model=FACE_ALIGN_POSTPROCESS_SO_FILENAME
        )
        self.post_process_so_vms_cropper = get_resource_path(
            pipeline_name=None, resource_type=RESOURCES_SO_DIR_NAME,
            arch=self.arch, model=FACE_CROP_POSTPROCESS_SO_FILENAME
        )

        # Postprocess function names (arch-dependent for SCRFD)
        if self.arch in (HAILO8_ARCH, HAILO10H_ARCH):
            self.post_function_scrfd_detection = SCRFD_10G_POSTPROCESS_FUNCTION
        elif self.arch == HAILO8L_ARCH:
            self.post_function_scrfd_detection = SCRFD_2_5G_POSTPROCESS_FUNCTION
        else:
            hailo_logger.error("Unsupported Hailo architecture: %s", self.arch)
            print(
                f"ERROR: Unsupported Hailo architecture: {self.arch}. "
                "Supported architectures are: hailo8, hailo8l, hailo10h.",
                file=sys.stderr
            )
            sys.exit(1)

        self.post_function_arcface_recognition = ARCFACE_MOBILEFACENET_POSTPROCESS_FUNCTION
        self.post_function_vms_cropper = VMS_CROPPER_POSTPROCESS_FUNCTION
        self.post_function_repvgg_reid = REID_POSTPROCESS_FUNCTION
        self.post_function_cropper = REID_CROPPER_POSTPROCESS_FUNCTION

        # Use face recognition video as default input
        if self.options_menu.input is None:
            self.video_source = get_resource_path(
                pipeline_name=None, resource_type=RESOURCES_VIDEOS_DIR_NAME,
                arch=self.arch, model=FACE_RECOGNITION_VIDEO_NAME
            )

        # Parse video sources
        self.video_sources_types = [
            (video_source, get_source_type(video_source))
            for video_source in (
                self.options_menu.sources.split(',')
                if self.options_menu.sources
                else [self.video_source, self.video_source]
            )
        ]
        self.num_sources = len(self.video_sources_types)
        self.match_threshold = self.options_menu.match_threshold
        self.video_height = self.options_menu.height
        self.video_width = self.options_menu.width
        self.host_arch = detect_host_arch()

        if self.host_arch == RPI_NAME_I:
            self.frame_rate = 12
        else:
            self.frame_rate = 15

        self.tracker = HailoTracker.get_instance()

        # Entry/exit log: list of dicts with timestamp, person_id, entrance_id, event_type
        self.entry_exit_log = []
        # Track which entrance each person was last seen at
        self.person_last_entrance = {}

        self.app_callback = app_callback
        self.generate_callbacks()
        self.create_pipeline()
        self.connect_src_callbacks()

        # Initialize database directory
        current_dir = Path(__file__).parent
        self.database_dir = current_dir / "database"
        os.makedirs(self.database_dir, exist_ok=True)

        # Initialize the LanceDB vector database for cross-camera identity tracking
        self.db_handler = DatabaseHandler(
            db_name='entrance_tracker.db',
            table_name='cross_tracked',
            schema=Record,
            threshold=self.match_threshold,
            database_dir=self.database_dir,
            samples_dir=None
        )

    def get_pipeline_string(self):
        """Build the GStreamer pipeline string for multi-entrance tracking.

        Pipeline structure:
        N sources -> hailoroundrobin -> SCRFD face detection (wrapped) ->
        tracker -> cropper(face_align + ArcFace recognition) ->
        unified callback -> hailostreamrouter -> N per-source ReID callbacks -> N displays
        """
        sources_string = ''
        router_string = ''

        tappas_post_process_dir = os.environ.get(TAPPAS_POSTPROC_PATH_KEY, '')
        set_stream_id_so = os.path.join(tappas_post_process_dir, TAPPAS_STREAM_ID_TOOL_SO_FILENAME)

        for id in range(self.num_sources):
            sources_string += SOURCE_PIPELINE(
                video_source=self.video_sources_types[id][0],
                video_width=self.video_width, video_height=self.video_height,
                frame_rate=self.frame_rate, sync=self.sync,
                name=f"source_{id}", no_webcam_compression=True
            )
            sources_string += f"! hailofilter name=set_src_{id} so-path={set_stream_id_so} config-path='src_{id}' "
            sources_string += f"! robin.sink_{id} "
            router_string += (
                f"router.src_{id} ! "
                f"{USER_CALLBACK_PIPELINE(name=f'src_{id}_callback')} ! "
                f"{QUEUE(name=f'callback_q_{id}')} ! "
                f"{DISPLAY_PIPELINE(video_sink=self.video_sink, sync=self.sync, show_fps=self.show_fps, name=f'hailo_display_{id}')} "
            )

        # Face detection (SCRFD) with inference wrapper for resolution preservation
        detection_pipeline = INFERENCE_PIPELINE(
            hef_path=self.hef_path_scrfd_detection,
            post_process_so=self.post_process_so_scrfd_detection,
            post_function_name=self.post_function_scrfd_detection,
            batch_size=self.batch_size,
            config_json=get_resource_path(
                pipeline_name=None, resource_type=RESOURCES_JSON_DIR_NAME,
                arch=self.arch, model=FACE_DETECTION_JSON_NAME
            )
        )
        tracker_pipeline = TRACKER_PIPELINE(class_id=-1, name='hailo_face_tracker')

        # Face recognition (ArcFace) pipeline inside the cropper
        id_pipeline = INFERENCE_PIPELINE(
            hef_path=self.hef_path_arcface_recognition,
            post_process_so=self.post_process_so_arcface_recognition,
            post_function_name=self.post_function_arcface_recognition,
            batch_size=self.batch_size,
            config_json=None,
            name='id_inference'
        )

        # Cropper: face alignment + ArcFace recognition on each detected face
        cropper_pipeline = CROPPER_PIPELINE(
            inner_pipeline=(
                f'hailofilter so-path={self.post_process_so_face_align} '
                f'name=face_align_hailofilter use-gst-buffer=true qos=false ! '
                f'{QUEUE(name="detector_pos_face_align_q")} ! '
                f'{id_pipeline}'
            ),
            so_path=self.post_process_so_vms_cropper,
            function_name=self.post_function_vms_cropper,
            internal_offset=True
        )

        detection_pipeline_wrapper = INFERENCE_PIPELINE_WRAPPER(detection_pipeline)
        user_callback_pipeline = USER_CALLBACK_PIPELINE()

        main_pipeline = (
            f'{detection_pipeline_wrapper} ! '
            f'{tracker_pipeline} ! '
            f'{cropper_pipeline} ! '
            f'{user_callback_pipeline} ! '
        )

        inference_string = f"hailoroundrobin mode=1 name=robin ! {main_pipeline} {QUEUE(name='call_q')} ! hailostreamrouter name=router "
        for id in range(self.num_sources):
            inference_string += f"src_{id}::input-streams=\"<sink_{id}>\" "

        pipeline_string = sources_string + inference_string + router_string
        return pipeline_string

    def generate_callbacks(self):
        """Dynamically generate per-source ReID callback functions.

        Each callback:
        1. Extracts face embeddings from detections
        2. Searches the vector database for known identities
        3. Creates new identity records for unknown faces
        4. Updates tracker with cross-camera identity classifications
        5. Logs entry/exit events when a person appears at a new entrance
        """
        for id in range(self.num_sources):
            def callback_function(element, buffer, user_data, id=id):
                try:
                    if buffer is None:
                        return

                    tracker_names = self.tracker.get_trackers_list()
                    roi = hailo.get_roi_from_buffer(buffer)
                    detections = roi.get_objects_typed(hailo.HAILO_DETECTION)

                    for detection in detections:
                        embedding = detection.get_objects_typed(hailo.HAILO_MATRIX)
                        if len(embedding) == 0:
                            continue

                        embedding_vector = np.array(embedding[0].get_data())
                        res = self.db_handler.search_record(embedding=embedding_vector)
                        s_id = roi.get_stream_id().replace("'", "")

                        # Remove old classifications
                        classifications = detection.get_objects_typed(hailo.HAILO_CLASSIFICATION)
                        for classification in classifications:
                            detection.remove_object(classification)

                        ids = detection.get_objects_typed(hailo.HAILO_UNIQUE_ID)
                        if not ids:
                            continue
                        track_id = ids[0].get_id()

                        new_classification = None
                        if res['label'] == 'Unknown':
                            # New person: create a record in the database
                            person_label = f"person_{str(uuid.uuid4())[-6:]}"
                            res = self.db_handler.create_record(
                                embedding=embedding_vector,
                                sample=None,
                                timestamp=int(time.time()),
                                label=f"entrance_{id}_{person_label}"
                            )
                            new_classification = hailo.HailoClassification(
                                type=REID_CLASSIFICATION_TYPE,
                                label=f'{s_id}, entrance_{id}_{person_label}',
                                confidence=0
                            )
                            # Log entry event
                            self._log_event(person_label, id, 'entry')
                        else:
                            if res['_distance'] < 0:
                                res['_distance'] = 0
                            confidence = 1 - res['_distance']
                            new_classification = hailo.HailoClassification(
                                type=REID_CLASSIFICATION_TYPE,
                                label=f"{s_id}," + res['label'],
                                confidence=confidence
                            )
                            # Check if person moved to a different entrance
                            person_label = res['label']
                            self._log_entrance_change(person_label, id)

                        detection.add_object(new_classification)
                        for tracker_name in tracker_names:
                            self.tracker.remove_classifications_from_track(
                                tracker_name, track_id, REID_CLASSIFICATION_TYPE
                            )
                            self.tracker.add_object_to_track(
                                tracker_name, track_id, new_classification
                            )

                except Exception as e:
                    hailo_logger.error("Error in entrance %d callback: %s", id, e)
                return

            setattr(self, f'src_{id}_callback', callback_function)

    def connect_src_callbacks(self):
        """Connect per-source callback functions to their identity elements in the pipeline."""
        for id in range(self.num_sources):
            identity = self.pipeline.get_by_name(f'src_{id}_callback')
            if identity:
                identity.set_property("signal-handoffs", True)
                callback_function = getattr(self, f'src_{id}_callback', None)
                identity.connect("handoff", callback_function, self.user_data)

    def _log_event(self, person_label, entrance_id, event_type):
        """Log an entry or exit event for a person at an entrance."""
        event = {
            'timestamp': time.time(),
            'person_id': person_label,
            'entrance_id': entrance_id,
            'event_type': event_type,
        }
        self.entry_exit_log.append(event)
        hailo_logger.info(
            "Event: %s | Person: %s | Entrance: %d",
            event_type, person_label, entrance_id
        )

    def _log_entrance_change(self, person_label, current_entrance_id):
        """Log when a person is seen at a different entrance (cross-camera match)."""
        last_entrance = self.person_last_entrance.get(person_label)
        if last_entrance is not None and last_entrance != current_entrance_id:
            self._log_event(person_label, last_entrance, 'exit')
            self._log_event(person_label, current_entrance_id, 'entry')
        self.person_last_entrance[person_label] = current_entrance_id


def main():
    user_data = app_callback_class()
    app_callback = dummy_callback
    app = MultiEntranceTrackerApp(app_callback, user_data)
    app.run()


if __name__ == "__main__":
    print("Starting Multi-Entrance Tracker...")
    main()
