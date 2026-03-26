# region imports
# Standard library imports
import os
import shutil
import json
import sys
import time
import threading
import queue
import uuid
import setproctitle
from pathlib import Path
os.environ["GST_PLUGIN_FEATURE_RANK"] = "vaapidecodebin:NONE"

# Third-party imports
import gi
gi.require_version('Gst', '1.0')
from gi.repository import Gst
import numpy as np
from PIL import Image

# Local application-specific imports
import hailo
from hailo import HailoTracker
from hailo_apps.python.core.common.db_handler import DatabaseHandler, Record
from hailo_apps.python.core.common.core import (
    get_pipeline_parser,
    get_resource_path,
    handle_list_models_flag,
    configure_multi_model_hef_path,
    resolve_hef_paths,
)
from hailo_apps.python.core.common.buffer_utils import get_numpy_from_buffer_efficient, get_caps_from_pad
from hailo_apps.python.core.gstreamer.gstreamer_app import GStreamerApp
from hailo_apps.python.core.common.defines import (
    RESOURCES_SO_DIR_NAME,
    FACE_RECOGNITION_PIPELINE,
    FACE_DETECTION_POSTPROCESS_SO_FILENAME,
    FACE_RECOGNITION_POSTPROCESS_SO_FILENAME,
    FACE_ALIGN_POSTPROCESS_SO_FILENAME,
    FACE_CROP_POSTPROCESS_SO_FILENAME,
    RESOURCES_VIDEOS_DIR_NAME,
    FACE_RECOGNITION_VIDEO_NAME,
    FACE_RECON_TRAIN_DIR_NAME,
    FACE_RECON_SAMPLES_DIR_NAME,
    RESOURCES_JSON_DIR_NAME,
    FACE_DETECTION_JSON_NAME,
    DEFAULT_LOCAL_RESOURCES_PATH,
    FACE_RECON_DATABASE_DIR_NAME,
    FACE_RECON_LOCAL_SAMPLES_DIR_NAME,
    BASIC_PIPELINES_VIDEO_EXAMPLE_NAME,
    SCRFD_10G_POSTPROCESS_FUNCTION,
    SCRFD_2_5G_POSTPROCESS_FUNCTION,
    HAILO8_ARCH,
    HAILO10H_ARCH,
    HAILO8L_ARCH,
)
from hailo_apps.python.core.gstreamer.gstreamer_helper_pipelines import (
    QUEUE,
    SOURCE_PIPELINE,
    INFERENCE_PIPELINE,
    INFERENCE_PIPELINE_WRAPPER,
    TRACKER_PIPELINE,
    USER_CALLBACK_PIPELINE,
    DISPLAY_PIPELINE,
    CROPPER_PIPELINE,
)
from hailo_apps.python.core.common.hailo_logger import get_logger

hailo_logger = get_logger(__name__)
# endregion imports

# App title shown in process list
ROOM_SECURITY_MONITOR_APP_TITLE = "hailo-room-security-monitor"


class GStreamerRoomSecurityMonitorApp(GStreamerApp):
    """Room security monitor pipeline: SCRFD face detection + ArcFace recognition.

    Supports three modes:
    - run: Real-time monitoring with alarm on unknown faces.
    - train: Enroll authorized personnel from images.
    - delete: Clear the face database.
    """

    def __init__(self, app_callback, user_data, parser=None):
        if parser is None:
            parser = get_pipeline_parser()
        parser.add_argument(
            "--mode", default='run',
            choices=['run', 'train', 'delete'],
            help="Application mode: run (monitor), train (enroll faces), delete (clear DB)"
        )
        parser.add_argument(
            "--ui", action='store_true', default=False,
            help="Launch graphical enrollment panel (kid-friendly UI for adding faces)"
        )

        # Configure --hef-path for multi-model support (face detection + face recognition)
        configure_multi_model_hef_path(parser)

        # Handle --list-models flag before full initialization
        handle_list_models_flag(parser, FACE_RECOGNITION_PIPELINE)

        super().__init__(parser, user_data)
        setproctitle.setproctitle(ROOM_SECURITY_MONITOR_APP_TITLE)

        # Load algorithm parameters
        json_file_path = os.path.join(os.path.dirname(__file__), "security_algo_params.json")
        with open(json_file_path, "r") as json_file:
            self.algo_params = json.load(json_file)

        self.skip_frames = self.algo_params['skip_frames']
        self.lance_db_vector_search_classificaiton_confidence_threshold = (
            self.algo_params['lance_db_vector_search_classificaiton_confidence_threshold']
        )
        self.batch_size = self.algo_params['batch_size']

        # Initialize directories
        current_dir = Path(__file__).parent
        self.train_images_dir = current_dir / FACE_RECON_TRAIN_DIR_NAME
        self.samples_dir = current_dir / FACE_RECON_SAMPLES_DIR_NAME
        self.database_dir = current_dir / FACE_RECON_DATABASE_DIR_NAME
        os.makedirs(self.train_images_dir, exist_ok=True)
        os.makedirs(self.samples_dir, exist_ok=True)

        # Initialize the database and table
        self.db_handler = DatabaseHandler(
            db_name='persons.db',
            table_name='persons',
            schema=Record,
            threshold=self.lance_db_vector_search_classificaiton_confidence_threshold,
            database_dir=self.database_dir,
            samples_dir=self.samples_dir,
        )

        # Replace default video source with face recognition video if using the basic example
        if BASIC_PIPELINES_VIDEO_EXAMPLE_NAME in self.video_source:
            self.video_source = get_resource_path(
                pipeline_name=None,
                resource_type=RESOURCES_VIDEOS_DIR_NAME,
                arch=self.arch,
                model=FACE_RECOGNITION_VIDEO_NAME,
            )

        self.current_file = None  # for train mode
        self.processed_names = set()
        self.processed_files = set()

        # Resolve HEF paths for multi-model app (face detection + face recognition)
        models = resolve_hef_paths(
            hef_paths=self.options_menu.hef_path,
            app_name=FACE_RECOGNITION_PIPELINE,
            arch=self.arch,
        )
        self.hef_path_detection = models[0].path
        self.hef_path_recognition = models[1].path

        # Select architecture-specific postprocess function
        if self.arch in (HAILO8_ARCH, HAILO10H_ARCH):
            self.detection_func = SCRFD_10G_POSTPROCESS_FUNCTION
        elif self.arch == HAILO8L_ARCH:
            self.detection_func = SCRFD_2_5G_POSTPROCESS_FUNCTION
        else:
            hailo_logger.error("Unsupported Hailo architecture: %s", self.arch)
            print(
                f"ERROR: Unsupported Hailo architecture: {self.arch}. "
                "Supported architectures are: hailo8, hailo8l, hailo10h.",
                file=sys.stderr,
            )
            sys.exit(1)

        self.recognition_func = "filter"
        self.cropper_func = "face_recognition"

        # Set the post-processing shared object files
        self.post_process_so_scrfd = get_resource_path(
            pipeline_name=None, resource_type=RESOURCES_SO_DIR_NAME,
            arch=self.arch, model=FACE_DETECTION_POSTPROCESS_SO_FILENAME,
        )
        self.post_process_so_face_recognition = get_resource_path(
            pipeline_name=None, resource_type=RESOURCES_SO_DIR_NAME,
            arch=self.arch, model=FACE_RECOGNITION_POSTPROCESS_SO_FILENAME,
        )
        self.post_process_so_face_align = get_resource_path(
            pipeline_name=None, resource_type=RESOURCES_SO_DIR_NAME,
            arch=self.arch, model=FACE_ALIGN_POSTPROCESS_SO_FILENAME,
        )
        self.post_process_so_cropper = get_resource_path(
            pipeline_name=None, resource_type=RESOURCES_SO_DIR_NAME,
            arch=self.arch, model=FACE_CROP_POSTPROCESS_SO_FILENAME,
        )

        # Callbacks: bindings between the C++ & Python code
        self.app_callback = app_callback
        self.vector_db_callback_name = "vector_db_callback"
        self.train_vector_db_callback_name = "train_vector_db_callback"
        self.create_pipeline()
        if self.options_menu.mode == 'run':
            self.connect_vector_db_callback()
        else:  # train
            self.connect_train_vector_db_callback()

        self.track_id_frame_count = {}
        self.tracker = HailoTracker.get_instance()

        # region worker queue threads for saving images
        self.task_queue = queue.Queue()

        def worker():
            while True:
                task = self.task_queue.get()
                if task is None:
                    break
                if task['type'] == 'save_image':
                    frame, image_path = task['frame'], task['image_path']
                    self.save_image_file(frame, image_path)
                self.task_queue.task_done()

        self.num_worker_threads = 1
        self.threads = []
        for _ in range(self.num_worker_threads):
            t = threading.Thread(target=worker)
            t.daemon = True
            t.start()
            self.threads.append(t)
        # endregion

    def get_pipeline_string(self):
        """Build the GStreamer pipeline string for room security monitoring."""
        source_pipeline = SOURCE_PIPELINE(
            self.video_source, self.video_width, self.video_height,
            frame_rate=self.frame_rate, sync=self.sync,
        )
        detection_pipeline = INFERENCE_PIPELINE(
            hef_path=self.hef_path_detection,
            post_process_so=self.post_process_so_scrfd,
            post_function_name=self.detection_func,
            batch_size=self.batch_size,
            config_json=get_resource_path(
                pipeline_name=None, resource_type=RESOURCES_JSON_DIR_NAME,
                arch=self.arch, model=FACE_DETECTION_JSON_NAME,
            ),
        )
        detection_pipeline_wrapper = INFERENCE_PIPELINE_WRAPPER(detection_pipeline)
        tracker_pipeline = TRACKER_PIPELINE(
            class_id=-1, kalman_dist_thr=0.7, iou_thr=0.8,
            init_iou_thr=0.9, keep_new_frames=2, keep_tracked_frames=6,
            keep_lost_frames=8, keep_past_metadata=True,
            name='hailo_face_tracker',
        )
        mobile_facenet_pipeline = INFERENCE_PIPELINE(
            hef_path=self.hef_path_recognition,
            post_process_so=self.post_process_so_face_recognition,
            post_function_name=self.recognition_func,
            batch_size=self.batch_size,
            config_json=None,
            name='face_recognition_inference',
        )
        cropper_pipeline = CROPPER_PIPELINE(
            inner_pipeline=(
                f'hailofilter so-path={self.post_process_so_face_align} '
                f'name=face_align_hailofilter use-gst-buffer=true qos=false ! '
                f'{QUEUE(name="detector_pos_face_align_q")} ! '
                f'{mobile_facenet_pipeline}'
            ),
            so_path=self.post_process_so_cropper,
            function_name=self.cropper_func,
            internal_offset=True,
        )
        vector_db_callback_pipeline = USER_CALLBACK_PIPELINE(name=self.vector_db_callback_name)
        user_callback_pipeline = USER_CALLBACK_PIPELINE()
        display_pipeline = DISPLAY_PIPELINE(
            video_sink=self.video_sink, sync=self.sync, show_fps=self.show_fps,
        )

        if self.options_menu.mode == 'train':
            source_pipeline = (
                f"multifilesrc location={self.current_file} loop=true num-buffers=30 ! "
                f"decodebin ! videoconvert n-threads=4 qos=false ! "
                f"video/x-raw, format=RGB, pixel-aspect-ratio=1/1 "
            )
            vector_db_callback_pipeline = USER_CALLBACK_PIPELINE(
                name=self.train_vector_db_callback_name,
            )
            display_pipeline = DISPLAY_PIPELINE(
                video_sink=self.video_sink, sync=self.sync, show_fps=self.show_fps,
            )

        return (
            f'{source_pipeline} ! '
            f'{detection_pipeline_wrapper} ! '
            f'{tracker_pipeline} ! '
            f'{cropper_pipeline} ! '
            f'{vector_db_callback_pipeline} ! '
            f'{user_callback_pipeline} ! '
            f'{display_pipeline}'
        )

    def run(self):
        if self.options_menu.mode == 'run':
            super().run()
        else:  # train
            self.run_training()

    def run_training(self):
        """Iterate over training folder, generate embeddings, store in database.

        Training folder structure:
            train/
                person_name_1/
                    image1.jpg
                    image2.jpg
                person_name_2/
                    image1.jpg
        """
        # Copy default samples if training dir is empty
        if not os.listdir(self.train_images_dir):
            print(f"Training directory {self.train_images_dir} is empty. "
                  "Copying default training images from local resources.")
            source_dir = get_resource_path(
                pipeline_name=None, resource_type=DEFAULT_LOCAL_RESOURCES_PATH,
                arch=self.arch, model=FACE_RECON_LOCAL_SAMPLES_DIR_NAME,
            )
            for item in os.listdir(source_dir):
                source_path = os.path.join(source_dir, item)
                destination_path = os.path.join(self.train_images_dir, item)
                if os.path.isdir(source_path):
                    shutil.copytree(source_path, destination_path)
                else:
                    shutil.copy2(source_path, destination_path)

        print(f"Training on images from {self.train_images_dir}")
        for person_name in os.listdir(self.train_images_dir):
            person_folder = os.path.join(self.train_images_dir, person_name)
            if self.db_handler.get_record_by_label(label=person_name):
                continue
            if not os.path.isdir(person_folder):
                continue
            print(f"Processing person: {person_name}")
            for image_file in os.listdir(person_folder):
                print(f"Processing image: {image_file}")
                self.current_file = os.path.join(person_folder, image_file)
                self.create_pipeline()
                self.connect_train_vector_db_callback()
                try:
                    self.pipeline.set_state(Gst.State.PLAYING)
                    time.sleep(2)
                except Exception as e:
                    print(f"Error processing image {image_file}: {e}")
                finally:
                    if self.pipeline:
                        self.pipeline.set_state(Gst.State.NULL)
        print("Training completed. Authorized personnel enrolled.")

    def connect_vector_db_callback(self):
        identity = self.pipeline.get_by_name(self.vector_db_callback_name)
        if identity:
            identity_pad = identity.get_static_pad("src")
            identity_pad.add_probe(
                Gst.PadProbeType.BUFFER, self.vector_db_callback, self.user_data,
            )

    def connect_train_vector_db_callback(self):
        identity = self.pipeline.get_by_name(self.train_vector_db_callback_name)
        if identity:
            identity_pad = identity.get_static_pad("src")
            identity_pad.add_probe(
                Gst.PadProbeType.BUFFER, self.train_vector_db_callback, self.user_data,
            )

    def save_image_file(self, frame, image_path):
        image = Image.fromarray(frame)
        image.save(image_path, format="JPEG", quality=85)

    def crop_frame(self, frame, bbox, width, height):
        """Crop a frame around a detection bbox with 15% padding."""
        x_min = max(0, min(bbox.xmin() - 0.15, 1))
        y_min = max(0, min(bbox.ymin() - 0.15, 1))
        x_max = max(0, min(bbox.xmax() + 0.15, 1))
        y_max = max(0, min(bbox.ymax() + 0.15, 1))

        x_min = int(x_min * width)
        y_min = int(y_min * height)
        x_max = int(x_max * width)
        y_max = int(y_max * height)

        return frame[y_min:y_max, x_min:x_max]

    def add_task(self, task_type, **kwargs):
        task = {'type': task_type, **kwargs}
        self.task_queue.put(task)

    def get_processed_names_by_name(self, key):
        for k, v in self.processed_names:
            if k == key:
                return v
        return None

    def is_name_processed(self, key):
        for k, _ in self.processed_names:
            if k == key:
                return True
        return False

    def force_reclassify(self, track_id):
        """Force a track to be re-classified on the next frame.

        Called after enrollment so the overlay immediately shows the new name
        instead of staying "Unknown".
        """
        if track_id is not None:
            # Reset frame count so the next callback triggers a DB lookup
            self.track_id_frame_count[track_id] = self.skip_frames
            # Remove stale classification from the tracker
            try:
                tracker_name = self.tracker.get_trackers_list()[0]
                self.tracker.remove_classifications_from_track(
                    tracker_name, track_id, 'face_recon',
                )
            except Exception:
                pass  # Tracker may not have this track anymore

    def vector_db_callback(self, pad, info, user_data):
        """Run mode callback: search vector DB for face embeddings, classify.

        Also stores face data (embedding + crop) in user_data for real-time enrollment.
        """
        tracker_name = self.tracker.get_trackers_list()[0]
        buffer = info.get_buffer()
        if buffer is None:
            return Gst.PadProbeReturn.OK
        format, width, height = get_caps_from_pad(pad)
        roi = hailo.get_roi_from_buffer(buffer)

        for detection in (
            d for d in roi.get_objects_typed(hailo.HAILO_DETECTION)
            if d.get_label() == 'face'
        ):
            track_id = (
                detection.get_objects_typed(hailo.HAILO_UNIQUE_ID)[0].get_id()
                if detection.get_objects_typed(hailo.HAILO_UNIQUE_ID)
                else None
            )

            # Skip initial frames (often blurry as person enters frame)
            if self.track_id_frame_count.get(track_id, 0) < self.skip_frames:
                self.track_id_frame_count[track_id] = (
                    self.track_id_frame_count.get(track_id, 0) + 1
                )
                continue

            frame = get_numpy_from_buffer_efficient(buffer, format, width, height)
            embedding = detection.get_objects_typed(hailo.HAILO_MATRIX)
            if len(embedding) == 0:
                continue
            if len(embedding) > 1:
                print(f"Warning: Multiple embeddings found for track ID {track_id}.")
                detection.remove_object(embedding[0])
                continue

            embedding_vector = np.array(embedding[0].get_data())
            person = self.db_handler.search_record(embedding=embedding_vector)
            new_confidence = 1 - person['_distance']

            classification = detection.get_objects_typed(hailo.HAILO_CLASSIFICATION)
            if not classification or classification[0].get_confidence() < new_confidence:
                if classification:
                    detection.remove_object(classification[0])
                new_classification = hailo.HailoClassification(
                    type='face_recon',
                    label=person['label'],
                    confidence=new_confidence,
                )
                detection.add_object(new_classification)
                self.tracker.remove_classifications_from_track(
                    tracker_name, track_id, 'face_recon',
                )
                self.tracker.add_object_to_track(
                    tracker_name, track_id, new_classification,
                )

            # Store face data for real-time enrollment
            if hasattr(user_data, 'store_enrollable_face'):
                try:
                    cropped = self.crop_frame(frame, detection.get_bbox(), width, height)
                    if cropped.size > 0:
                        user_data.store_enrollable_face(
                            track_id, embedding_vector, cropped, label=person['label'],
                        )
                except Exception:
                    pass  # Non-critical — don't break the pipeline

            # Re-process after skip_frames * 3 for periodic re-verification
            self.track_id_frame_count[track_id] = -3 * self.skip_frames

        return Gst.PadProbeReturn.OK

    def train_vector_db_callback(self, pad, info, user_data):
        """Train mode callback: extract embeddings and store in vector DB."""
        if self.current_file in self.processed_files:
            return Gst.PadProbeReturn.OK
        buffer = info.get_buffer()
        if buffer is None:
            return Gst.PadProbeReturn.OK
        format, width, height = get_caps_from_pad(pad)
        frame = get_numpy_from_buffer_efficient(buffer, format, width, height)
        roi = hailo.get_roi_from_buffer(buffer)

        if len(roi.get_objects_typed(hailo.HAILO_DETECTION)) == 0:
            print("No face detections found in the current frame.")

        for detection in (
            d for d in roi.get_objects_typed(hailo.HAILO_DETECTION)
            if d.get_label() == "face"
        ):
            embedding = detection.get_objects_typed(hailo.HAILO_MATRIX)
            if len(embedding) != 1:
                continue
            detection.remove_object(embedding[0])
            cropped_frame = self.crop_frame(frame, detection.get_bbox(), width, height)
            embedding_vector = np.array(embedding[0].get_data())
            image_path = os.path.join(self.samples_dir, f"{uuid.uuid4()}.jpeg")
            self.add_task('save_image', frame=cropped_frame, image_path=image_path)
            name = os.path.basename(os.path.dirname(self.current_file))
            if self.is_name_processed(name):
                self.db_handler.insert_new_sample(
                    record=self.db_handler.get_record_by_id(
                        self.get_processed_names_by_name(name)
                    ),
                    embedding=embedding_vector,
                    sample=image_path,
                    timestamp=int(time.time()),
                )
                print(f"Adding face to: {name}")
            else:
                person = self.db_handler.create_record(
                    embedding=embedding_vector,
                    sample=image_path,
                    timestamp=int(time.time()),
                    label=name,
                )
                print(f"New person added with ID: {person['global_id']}")
                self.processed_names.add((name, person['global_id']))
            self.processed_files.add(self.current_file)
            return Gst.PadProbeReturn.OK
        return Gst.PadProbeReturn.OK
