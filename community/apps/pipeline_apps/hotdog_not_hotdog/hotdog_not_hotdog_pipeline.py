# region imports
import os
import setproctitle

import numpy as np

import hailo
from hailo_apps.python.core.common.hailo_logger import get_logger
from hailo_apps.python.core.common.defines import (
    BASIC_PIPELINES_VIDEO_EXAMPLE_NAME,
    CLIP_PIPELINE,
    CLIP_POSTPROCESS_SO_FILENAME,
    CLIP_POSTPROCESS_FUNCTION_NAME,
    RESOURCES_SO_DIR_NAME,
    RESOURCES_VIDEOS_DIR_NAME,
    CLIP_VIDEO_NAME,
    HAILO8_ARCH,
    HAILO8L_ARCH,
)
from hailo_apps.python.core.common.core import (
    configure_multi_model_hef_path,
    get_pipeline_parser,
    get_resource_path,
    handle_list_models_flag,
    resolve_hef_paths,
)
from hailo_apps.python.core.gstreamer.gstreamer_app import (
    GStreamerApp,
    app_callback_class,
    dummy_callback,
)
from hailo_apps.python.core.gstreamer.gstreamer_helper_pipelines import (
    DISPLAY_PIPELINE,
    INFERENCE_PIPELINE,
    QUEUE,
    SOURCE_PIPELINE,
    USER_CALLBACK_PIPELINE,
)
from hailo_apps.python.pipeline_apps.clip.text_image_matcher import text_image_matcher
# endregion

hailo_logger = get_logger(__name__)


class GStreamerHotdogApp(GStreamerApp):
    def __init__(self, app_callback, user_data, parser=None):
        setproctitle.setproctitle("hotdog_not_hotdog")
        if parser is None:
            parser = get_pipeline_parser()
        parser.add_argument(
            "--threshold", type=float, default=0.5,
            help="Classification confidence threshold (default: 0.5).",
        )
        parser.add_argument(
            "--regenerate-embeddings", action="store_true",
            help="Re-encode text prompts and overwrite the saved embeddings JSON.",
        )
        configure_multi_model_hef_path(parser)
        handle_list_models_flag(parser, CLIP_PIPELINE)
        super().__init__(parser, user_data)

        self.app_callback = app_callback
        self.clip_batch_size = 8
        self.text_image_matcher = text_image_matcher
        self.text_image_matcher.set_threshold(self.options_menu.threshold)

        if BASIC_PIPELINES_VIDEO_EXAMPLE_NAME in self.video_source:
            self.video_source = get_resource_path(
                pipeline_name=None,
                resource_type=RESOURCES_VIDEOS_DIR_NAME,
                model=CLIP_VIDEO_NAME,
            )

        # Resolve CLIP model HEF paths
        models = resolve_hef_paths(
            hef_paths=self.options_menu.hef_path,
            app_name=CLIP_PIPELINE,
            arch=self.arch,
        )
        # CLIP pipeline has 3 models: clip_image_encoder, detection, text_encoder
        self.hef_path_clip = models[0].path
        # models[1] is detection (unused — we run full-frame CLIP)
        self.text_image_matcher.set_hef_path(models[2].path)

        self.post_process_so_clip = get_resource_path(
            pipeline_name=None,
            resource_type=RESOURCES_SO_DIR_NAME,
            model=CLIP_POSTPROCESS_SO_FILENAME,
        )

        # Load or generate text embeddings: "hotdog" + background classes.
        # CLIP doesn't handle negation well ("not hotdog" still encodes hotdog features),
        # so we use diverse background classes and classify as "not hotdog" when any wins.
        self.embeddings_json = os.path.join(os.path.dirname(os.path.abspath(__file__)), "embeddings.json")
        self._load_or_generate_embeddings()

        self.matching_callback_name = "matching_identity_callback"

        self.create_pipeline()
        self._connect_matching_callback()

    def _load_or_generate_embeddings(self):
        """Load pre-computed embeddings from JSON, or generate and save them."""
        prompts = ["hotdog", "food", "person", "animal", "object", "room"]

        if not self.options_menu.regenerate_embeddings and os.path.isfile(self.embeddings_json):
            hailo_logger.info("Loading pre-computed text embeddings from %s", self.embeddings_json)
            self.text_image_matcher.load_embeddings(self.embeddings_json)
            # Verify the loaded embeddings match our expected prompts
            loaded_texts = [e for e in self.text_image_matcher.get_texts() if e]
            if loaded_texts == prompts:
                hailo_logger.info("Text embeddings loaded from cache.")
                return
            hailo_logger.warning("Cached embeddings don't match expected prompts, regenerating...")

        hailo_logger.info("Encoding text prompts (one-time): %s", prompts)
        for i, prompt in enumerate(prompts):
            self.text_image_matcher.add_text(prompt, index=i, ensemble=True)
        self.text_image_matcher.save_embeddings(self.embeddings_json)
        hailo_logger.info("Text embeddings saved to %s", self.embeddings_json)

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
            self.video_source, self.video_width, self.video_height,
            frame_rate=self.frame_rate, sync=self.sync,
        )

        multi_process_service_value = (
            "true" if getattr(self, "arch", None) in [HAILO8_ARCH, HAILO8L_ARCH] else None
        )
        clip_pipeline = INFERENCE_PIPELINE(
            hef_path=self.hef_path_clip,
            post_process_so=self.post_process_so_clip,
            post_function_name=CLIP_POSTPROCESS_FUNCTION_NAME,
            batch_size=self.clip_batch_size,
            scheduler_priority=16,
            scheduler_timeout_ms=1000,
            name="clip_inference",
            multi_process_service=multi_process_service_value,
        )

        # Full-frame CLIP: tee → bypass + clip inference → muxer
        clip_pipeline_wrapper = (
            f"tee name=clip_t hailomuxer name=clip_hmux "
            f"clip_t. ! {QUEUE(name='clip_bypass_q', max_size_buffers=20)} ! clip_hmux.sink_0 "
            f"clip_t. ! {QUEUE(name='clip_muxer_queue')} ! videoscale qos=false ! {clip_pipeline} ! clip_hmux.sink_1 "
            f"clip_hmux. ! {QUEUE(name='clip_hmux_queue')} "
        )

        matching_callback_pipeline = USER_CALLBACK_PIPELINE(name=self.matching_callback_name)
        user_callback_pipeline = USER_CALLBACK_PIPELINE()
        display_pipeline = DISPLAY_PIPELINE(
            video_sink=self.video_sink, sync=self.sync, show_fps="True",
        )

        return (
            f"{source_pipeline} ! "
            f"{clip_pipeline_wrapper} ! "
            f"{matching_callback_pipeline} ! "
            f"{user_callback_pipeline} ! "
            f"{display_pipeline}"
        )

    def matching_identity_callback(self, element, buffer, user_data):
        """Match CLIP image embeddings against 'hotdog' / 'not hotdog' text embeddings."""
        if buffer is None:
            return
        roi = hailo.get_roi_from_buffer(buffer)
        if roi is None:
            return

        # Full-frame mode: embeddings are on the ROI itself
        top_level_matrix = roi.get_objects_typed(hailo.HAILO_MATRIX)
        if len(top_level_matrix) == 0:
            return

        embeddings_np = np.array(top_level_matrix[0].get_data())[np.newaxis, :]
        matches = self.text_image_matcher.match(embeddings_np, report_all=True)

        for match in matches:
            old_classifications = roi.get_objects_typed(hailo.HAILO_CLASSIFICATION)
            if match.passed_threshold and not match.negative:
                classification = hailo.HailoClassification("clip", match.text, match.similarity)
                roi.add_object(classification)
                for old in old_classifications:
                    roi.remove_object(old)
