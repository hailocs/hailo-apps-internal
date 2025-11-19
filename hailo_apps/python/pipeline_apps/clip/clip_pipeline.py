# region imports
# Standard library imports
import os
import shutil
import json
import time
import threading
import queue
import uuid
import setproctitle
from pathlib import Path
import argparse
import logging
import sys
import signal
import importlib.util
from functools import partial

# Third-party imports
import gi
gi.require_version('Gtk', '3.0')
gi.require_version('Gst', '1.0')
from gi.repository import Gtk

# Local application-specific imports
from hailo_apps.python.core.gstreamer.gstreamer_app import GStreamerApp, app_callback_class, dummy_callback
from hailo_apps.python.core.common.core import get_default_parser, detect_hailo_arch, get_resource_path
from hailo_apps.python.core.common.buffer_utils import get_numpy_from_buffer_efficient, get_caps_from_pad
from hailo_apps.python.pipeline_apps.clip import text_image_matcher, gui
from hailo_apps.python.core.gstreamer.gstreamer_helper_pipelines import QUEUE, SOURCE_PIPELINE, INFERENCE_PIPELINE, INFERENCE_PIPELINE_WRAPPER, TRACKER_PIPELINE, USER_CALLBACK_PIPELINE, DISPLAY_PIPELINE, CROPPER_PIPELINE
from hailo_apps.python.core.common.defines import (
    RESOURCES_SO_DIR_NAME, 
    RESOURCES_MODELS_DIR_NAME, 
    RESOURCES_VIDEOS_DIR_NAME,
    RESOURCES_JSON_DIR_NAME,
    DEFAULT_LOCAL_RESOURCES_PATH,
    BASIC_PIPELINES_VIDEO_EXAMPLE_NAME,
    HAILO8_ARCH,
    HAILO10H_ARCH,
    HAILO8L_ARCH,
    CLIP_APP_TITLE,
    CLIP_VIDEO_NAME,
    CLIP_PIPELINE,
    CLIP_DETECTION_PIPELINE,
    CLIP_DETECTION_JSON_NAME,
    CLIP_DETECTION_POSTPROCESS_SO_FILENAME,
    CLIP_POSTPROCESS_SO_FILENAME,
    CLIP_CROPPER_POSTPROCESS_SO_FILENAME,
)
# endregion

class GStreamerClipApp(GStreamerApp):
    def __init__(self, user_data, app_callback):
        setproctitle.setproctitle(CLIP_APP_TITLE)
        if parser == None:
            parser = get_default_parser()
        parser.add_argument("--detector", "-d", type=str, choices=["person", "face", "none"], default="none", help="Which detection pipeline to use.")
        parser.add_argument("--json-path", type=str, default=None, help="Path to JSON file to load and save embeddings. If not set, embeddings.json will be used.")
        parser.add_argument("--detection-threshold", type=float, default=0.5, help="Detection threshold.")
        parser.add_argument("--disable-runtime-prompts", action="store_true", help="When set, app will not support runtime prompts. Default is False.")
        super().__init__(parser, user_data)
        if self.options_menu.input is None:
            self.json_file = os.path.join(self.current_path, "example_embeddings.json") if self.options_menu.json_path is None else self.options_menu.json_path
        else:
            self.json_file = os.path.join(self.current_path, "embeddings.json") if self.options_menu.json_path is None else self.options_menu.json_path
        self.app_callback = app_callback
        self.detector = self.options_menu.detector
        self.text_image_matcher = text_image_matcher
        self.text_image_matcher.set_threshold(self.options_menu.detection_threshold)
        self.win = AppWindow(self.args, self.user_data, self.app_callback)
        self.batch_size = 8

        if self.options_menu.arch is None:
            detected_arch = detect_hailo_arch()
            if detected_arch is None:
                raise ValueError("Could not auto-detect Hailo architecture. Please specify --arch manually.")
            self.arch = detected_arch
        else:
            self.arch = self.options_menu.arch

        if BASIC_PIPELINES_VIDEO_EXAMPLE_NAME in self.video_source:
            self.video_source = get_resource_path(pipeline_name=None, resource_type=RESOURCES_VIDEOS_DIR_NAME, model=CLIP_VIDEO_NAME)

        self.hef_path_detection = get_resource_path(pipeline_name=CLIP_DETECTION_PIPELINE, resource_type=RESOURCES_MODELS_DIR_NAME)
        self.hef_path_clip = get_resource_path(pipeline_name=CLIP_PIPELINE, resource_type=RESOURCES_MODELS_DIR_NAME)

        self.detection_config_json_path = get_resource_path(pipeline_name=None, resource_type=RESOURCES_JSON_DIR_NAME, model=CLIP_DETECTION_JSON_NAME)

        self.post_process_so_detection = get_resource_path(pipeline_name=None, resource_type=RESOURCES_SO_DIR_NAME, model=CLIP_DETECTION_POSTPROCESS_SO_FILENAME)
        self.post_process_so_clip = get_resource_path(pipeline_name=None, resource_type=RESOURCES_SO_DIR_NAME, model=CLIP_POSTPROCESS_SO_FILENAME)
        self.post_process_so_cropper = get_resource_path(pipeline_name=None, resource_type=RESOURCES_SO_DIR_NAME, model=CLIP_CROPPER_POSTPROCESS_SO_FILENAME)

        self.detection_post_process_function_name = 'yolov5_personface_letterbox'
        self.clip_post_process_function_name = 'filter'
        if self.options_menu.detector == 'person':
            self.class_id = 1
            self.cropper_post_process_function_name = 'person_cropper'
        elif self.options_menu.detector == 'face':
            self.class_id = 2
            self.cropper_post_process_function_name = 'face_cropper'
        else: # fast_sam
            self.class_id = 0
            self.cropper_post_process_function_name = 'object_cropper'
    
        self.create_pipeline()

    def run(self):
        self.win.connect("destroy", self.on_destroy)
        self.win.show_all()
        signal.signal(signal.SIGINT, signal.SIG_DFL)
        Gtk.main()
        super().run()
        
    def on_destroy(self, window):
        window.quit_button_clicked(None)

    def get_pipeline_string(self):
        source_pipeline = SOURCE_PIPELINE(self.video_source, self.video_width, self.video_height, frame_rate=self.frame_rate, sync=self.sync)

        detection_pipeline = INFERENCE_PIPELINE(
                hef_path=hef_path,
                post_process_so=YOLO5_POSTPROCESS_SO,
                batch_size=batch_size,
                config_json=YOLO5_CONFIG_PATH,
                post_function_name=YOLO5_NETWORK_NAME,
                scheduler_priority=31,
                scheduler_timeout_ms=100,
                name='detection_inference'
            )

        if self.options_menu.detector == "none":
            detection_pipeline_wrapper = ""
        else:
            detection_pipeline_wrapper = INFERENCE_PIPELINE_WRAPPER(detection_pipeline)


        clip_pipeline = INFERENCE_PIPELINE(
                hef_path=clip_hef_path,
                post_process_so=clip_postprocess_so,
                batch_size=batch_size,
                name='clip_inference',
                scheduler_timeout_ms=1000,
                scheduler_priority=16,
            )
    
        tracker_pipeline = TRACKER_PIPELINE(class_id=class_id, keep_past_metadata=True)

        clip_cropper_pipeline = CROPPER_PIPELINE(
            inner_pipeline=clip_pipeline,
            so_path=DEFAULT_CROP_SO,
            function_name=crop_function_name,
            name='clip_cropper'
        )

        # Clip pipeline with muxer integration (no cropper)
        clip_pipeline_wrapper = f'tee name=clip_t hailomuxer name=clip_hmux \
            clip_t. ! {QUEUE(name="clip_bypass_q", max_size_buffers=20)} ! clip_hmux.sink_0 \
            clip_t. ! {QUEUE(name="clip_muxer_queue")} ! videoscale n-threads=4 qos=false ! {clip_pipeline} ! clip_hmux.sink_1 \
            clip_hmux. ! {QUEUE(name="clip_hmux_queue")} '

        # TBD aggregator does not support ROI classification
        # clip_pipeline_wrapper = INFERENCE_PIPELINE_WRAPPER(clip_pipeline, name='clip')

        display_pipeline = DISPLAY_PIPELINE(sync=self.sync, show_fps=self.show_fps)

        # Text to image matcher
        CLIP_PYTHON_MATCHER = f'hailopython name=pyproc module={hailopython_path} qos=false '
        CLIP_CPP_MATCHER = f'hailofilter so-path={clip_matcher_so} qos=false config-path={clip_matcher_config} '

        clip_postprocess_pipeline = f' {CLIP_PYTHON_MATCHER} ! \
            {QUEUE(name="clip_postprocess_queue")} ! \
            identity name=identity_callback '

        # PIPELINE
        if self.detector == "none":
            PIPELINE = f'{source_pipeline} ! \
            {clip_pipeline_wrapper} ! \
            {clip_postprocess_pipeline} ! \
            {display_pipeline}'
        else:
            PIPELINE = f'{source_pipeline} ! \
            {detection_pipeline_wrapper} ! \
            {tracker_pipeline} ! \
            {clip_cropper_pipeline} ! \
            {clip_postprocess_pipeline} ! \
            {display_pipeline}'

class AppWindow(Gtk.Window):
    # Add GUI functions to the AppWindow class
    build_ui = gui.build_ui
    add_text_boxes = gui.add_text_boxes
    update_text_boxes = gui.update_text_boxes
    update_text_prefix = gui.update_text_prefix
    quit_button_clicked = gui.quit_button_clicked
    on_text_box_updated = gui.on_text_box_updated
    on_slider_value_changed = gui.on_slider_value_changed
    on_negative_check_button_toggled = gui.on_negative_check_button_toggled
    on_ensemble_check_button_toggled = gui.on_ensemble_check_button_toggled
    on_load_button_clicked = gui.on_load_button_clicked
    on_save_button_clicked = gui.on_save_button_clicked
    update_progress_bars = gui.update_progress_bars
    on_track_id_update = gui.on_track_id_update
    disable_text_boxes = gui.disable_text_boxes

    def __init__(self):
        Gtk.Window.__init__(self, title="Clip App")
        self.set_border_width(10)
        self.set_default_size(1, 1)
        self.fullscreen_mode = False
        self.max_entries = 6
        self.build_ui(self.options_menu)
        if self.options_menu.disable_runtime_prompts:
            self.disable_text_boxes()
            self.on_load_button_clicked(None)
        else:
            self.text_image_matcher.init_clip()
        if self.text_image_matcher.model_runtime is not None:
            self.on_load_button_clicked(None)
        self.update_text_boxes()

if __name__ == "__main__":
    user_data = app_callback_class()
    app = GStreamerClipApp(user_data, dummy_callback)
    app.run()