# region imports
# Standard library imports
import os
import signal
import setproctitle

# Third-party imports
import numpy as np

# Local application-specific imports
import hailo
from hailo_apps.python.core.common.hailo_logger import get_logger
from hailo_apps.python.core.common.defines import (
    BASIC_PIPELINES_VIDEO_EXAMPLE_NAME,
    CLIP_CROPPER_PERSON_POSTPROCESS_FUNCTION_NAME,
    CLIP_CROPPER_POSTPROCESS_SO_FILENAME,
    CLIP_DETECTION_POSTPROCESS_FUNCTION_NAME,
    CLIP_PIPELINE,
    CLIP_POSTPROCESS_SO_FILENAME,
    CLIP_VIDEO_NAME,
    DETECTION_POSTPROCESS_SO_FILENAME,
    RESOURCES_SO_DIR_NAME,
    RESOURCES_VIDEOS_DIR_NAME,
    HAILO8_ARCH,
    HAILO8L_ARCH,
    CLIP_POSTPROCESS_FUNCTION_NAME,
)
from hailo_apps.python.core.common.core import (
    configure_multi_model_hef_path,
    get_pipeline_parser,
    get_resource_path,
    handle_list_models_flag,
    resolve_hef_paths,
)
from hailo_apps.python.core.common.hef_utils import get_hef_labels_json
from hailo_apps.python.core.gstreamer.gstreamer_app import (
    GStreamerApp,
    app_callback_class,
    dummy_callback,
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
)
from hailo_apps.python.pipeline_apps.clip.text_image_matcher import text_image_matcher
# endregion

hailo_logger = get_logger(__name__)

# PPE compliance status constants
PPE_STATUS_SAFE = "SAFE"
PPE_STATUS_VIOLATION = "VIOLATION"
PPE_STATUS_UNKNOWN = "UNKNOWN"

# Default PPE text prompts for CLIP zero-shot classification
DEFAULT_PPE_PROMPTS = [
    "a person wearing a hard hat and safety vest",
    "a person wearing a safety helmet",
    "a person wearing a high visibility vest",
    "a person without safety equipment",
    "a person without a helmet",
    "a person without a safety vest",
]

# Indices into DEFAULT_PPE_PROMPTS that indicate safe (compliant) status
SAFE_PROMPT_INDICES = {0, 1, 2}
# Indices that indicate violation (non-compliant) status
VIOLATION_PROMPT_INDICES = {3, 4, 5}


class PPESafetyCallback(app_callback_class):
    """Extended callback class for PPE safety checking state."""

    def __init__(self):
        super().__init__()
        self.violation_count = 0
        self.safe_count = 0
        self.total_checks = 0


class GStreamerPPESafetyCheckerApp(GStreamerApp):
    """
    PPE Safety Checker pipeline app using CLIP zero-shot classification.

    Detects people using YOLOv8, then classifies each person crop with CLIP
    to determine if they are wearing required PPE (helmet, safety vest).
    Color-coded bounding boxes indicate compliance status:
    - Green: Worker is wearing required PPE (safe)
    - Red: Worker is missing required PPE (violation)
    """

    def __init__(self, app_callback, user_data, parser=None):
        setproctitle.setproctitle("ppe_safety_checker")
        if parser is None:
            parser = get_pipeline_parser()
        parser.add_argument(
            "--detection-threshold",
            type=float,
            default=0.5,
            help="Detection confidence threshold for person detection.",
        )
        parser.add_argument(
            "--clip-threshold",
            type=float,
            default=0.3,
            help="CLIP matching threshold for PPE classification.",
        )
        parser.add_argument(
            "--labels-json",
            type=str,
            default=None,
            help="Path to custom labels JSON file for detection model.",
        )
        parser.add_argument(
            "--prompts",
            type=str,
            nargs="+",
            default=None,
            help="Custom CLIP text prompts (overrides defaults). "
            "First half are 'safe' prompts, second half are 'violation' prompts.",
        )
        configure_multi_model_hef_path(parser)
        handle_list_models_flag(parser, CLIP_PIPELINE)
        super().__init__(parser, user_data)

        self.app_callback = app_callback
        self.text_image_matcher = text_image_matcher
        self.text_image_matcher.set_threshold(self.options_menu.clip_threshold)
        self.detection_batch_size = 8
        self.clip_batch_size = 8

        if BASIC_PIPELINES_VIDEO_EXAMPLE_NAME in self.video_source:
            self.video_source = get_resource_path(
                pipeline_name=None,
                resource_type=RESOURCES_VIDEOS_DIR_NAME,
                model=CLIP_VIDEO_NAME,
            )

        # Resolve HEF paths for multi-model app (detection + clip)
        models = resolve_hef_paths(
            hef_paths=self.options_menu.hef_path,
            app_name=CLIP_PIPELINE,
            arch=self.arch,
        )

        # order as in hailo_apps/config/resources_config.yaml
        self.hef_path_clip = models[0].path
        self.hef_path_detection = models[1].path
        self.text_image_matcher.set_hef_path(models[2].path)

        # User-defined label JSON file for detection model
        self.labels_json = self.options_menu.labels_json
        if self.labels_json is None:
            self.labels_json = get_hef_labels_json(self.hef_path_detection)
            if self.labels_json is not None:
                hailo_logger.info("Auto detected Labels JSON: %s", self.labels_json)

        self.post_process_so_detection = get_resource_path(
            pipeline_name=None,
            resource_type=RESOURCES_SO_DIR_NAME,
            model=DETECTION_POSTPROCESS_SO_FILENAME,
        )
        self.post_process_so_clip = get_resource_path(
            pipeline_name=None,
            resource_type=RESOURCES_SO_DIR_NAME,
            model=CLIP_POSTPROCESS_SO_FILENAME,
        )
        self.post_process_so_cropper = get_resource_path(
            pipeline_name=None,
            resource_type=RESOURCES_SO_DIR_NAME,
            model=CLIP_CROPPER_POSTPROCESS_SO_FILENAME,
        )

        self.clip_post_process_function_name = CLIP_POSTPROCESS_FUNCTION_NAME
        self.detection_post_process_function_name = CLIP_DETECTION_POSTPROCESS_FUNCTION_NAME
        # Always use person detector for PPE
        self.class_id = 1
        self.cropper_post_process_function_name = CLIP_CROPPER_PERSON_POSTPROCESS_FUNCTION_NAME

        self.matching_callback_name = "ppe_matching_callback"

        # Initialize PPE prompts in the text_image_matcher
        self._setup_ppe_prompts()

        self.create_pipeline()
        self._connect_matching_callback()

    def _setup_ppe_prompts(self):
        """Load default PPE prompts into the text_image_matcher."""
        prompts = self.options_menu.prompts or DEFAULT_PPE_PROMPTS
        for i, prompt in enumerate(prompts):
            if i >= self.text_image_matcher.max_entries:
                hailo_logger.warning(
                    "Too many prompts (%d). Max supported: %d. Truncating.",
                    len(prompts),
                    self.text_image_matcher.max_entries,
                )
                break
            # Mark violation prompts as negative
            is_negative = i in VIOLATION_PROMPT_INDICES
            self.text_image_matcher.add_text(prompt, index=i, negative=is_negative)

    def _connect_matching_callback(self):
        """Connect the matching identity callback to the pipeline."""
        identity = self.pipeline.get_by_name(self.matching_callback_name)
        if identity:
            identity.set_property("signal-handoffs", True)
            identity.connect("handoff", self.matching_identity_callback, self.user_data)

    def _on_pipeline_rebuilt(self):
        """Reconnect custom callbacks after pipeline rebuild."""
        self._connect_matching_callback()

    def get_pipeline_string(self):
        source_pipeline = SOURCE_PIPELINE(
            self.video_source,
            self.video_width,
            self.video_height,
            frame_rate=self.frame_rate,
            sync=self.sync,
        )

        multi_process_service_value = (
            "true"
            if getattr(self, "arch", None) in [HAILO8_ARCH, HAILO8L_ARCH]
            else None
        )

        detection_pipeline = INFERENCE_PIPELINE(
            hef_path=self.hef_path_detection,
            post_process_so=self.post_process_so_detection,
            post_function_name=self.detection_post_process_function_name,
            batch_size=self.detection_batch_size,
            scheduler_priority=31,
            scheduler_timeout_ms=100,
            name="detection_inference",
            multi_process_service=multi_process_service_value,
        )

        detection_pipeline_wrapper = INFERENCE_PIPELINE_WRAPPER(detection_pipeline)

        clip_pipeline = INFERENCE_PIPELINE(
            hef_path=self.hef_path_clip,
            post_process_so=self.post_process_so_clip,
            post_function_name=self.clip_post_process_function_name,
            batch_size=self.clip_batch_size,
            scheduler_priority=16,
            scheduler_timeout_ms=1000,
            name="clip_inference",
            multi_process_service=multi_process_service_value,
        )

        tracker_pipeline = TRACKER_PIPELINE(
            class_id=self.class_id, keep_past_metadata=True
        )

        clip_cropper_pipeline = CROPPER_PIPELINE(
            inner_pipeline=clip_pipeline,
            so_path=self.post_process_so_cropper,
            function_name=self.cropper_post_process_function_name,
            name="clip_cropper",
        )

        display_pipeline = DISPLAY_PIPELINE(
            video_sink=self.video_sink, sync=self.sync, show_fps="True"
        )

        matching_callback_pipeline = USER_CALLBACK_PIPELINE(
            name=self.matching_callback_name
        )

        user_callback_pipeline = USER_CALLBACK_PIPELINE()

        return (
            f"{source_pipeline} ! "
            f"{detection_pipeline_wrapper} ! "
            f"{tracker_pipeline} ! "
            f"{clip_cropper_pipeline} ! "
            f"{matching_callback_pipeline} ! "
            f"{user_callback_pipeline} ! "
            f"{display_pipeline}"
        )

    def matching_identity_callback(self, element, buffer, user_data):
        """
        CLIP matching callback: classifies each detected person as safe or violation.

        Extracts CLIP embeddings from each detected person and matches them against
        PPE text prompts. Adds classification metadata with compliance status.
        """
        if buffer is None:
            return
        roi = hailo.get_roi_from_buffer(buffer)
        if roi is None:
            return

        detections = roi.get_objects_typed(hailo.HAILO_DETECTION)
        embeddings_np = None
        used_detection = []

        for detection in detections:
            results = detection.get_objects_typed(hailo.HAILO_MATRIX)
            if len(results) == 0:
                continue
            detection_embeddings = np.array(results[0].get_data())
            used_detection.append(detection)
            if embeddings_np is None:
                embeddings_np = detection_embeddings[np.newaxis, :]
            else:
                embeddings_np = np.vstack((embeddings_np, detection_embeddings))

        if embeddings_np is not None:
            matches = self.text_image_matcher.match(
                embeddings_np, report_all=True
            )
            for match in matches:
                detection = used_detection[match.row_idx]

                # Remove old classifications before adding new
                old_classifications = detection.get_objects_typed(
                    hailo.HAILO_CLASSIFICATION
                )

                # Determine PPE compliance status
                if match.passed_threshold and not match.negative:
                    status = PPE_STATUS_SAFE
                    label = f"{status}: {match.text}"
                elif match.passed_threshold and match.negative:
                    status = PPE_STATUS_VIOLATION
                    label = f"{status}: {match.text}"
                else:
                    status = PPE_STATUS_UNKNOWN
                    label = status

                classification = hailo.HailoClassification(
                    "ppe_status", label, match.similarity
                )
                detection.add_object(classification)

                for old in old_classifications:
                    detection.remove_object(old)


if __name__ == "__main__":
    user_data = PPESafetyCallback()
    app = GStreamerPPESafetyCheckerApp(dummy_callback, user_data)
    app.run()
