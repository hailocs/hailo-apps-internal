# region imports
# Standard library imports
import os
import urllib.request
from pathlib import Path

os.environ["GST_PLUGIN_FEATURE_RANK"] = "vaapidecodebin:NONE"

# Third-party imports
import gi
import setproctitle

gi.require_version("Gst", "1.0")

# Local application-specific imports
from hailo_apps.python.core.common.core import (
    get_pipeline_parser,
)
from hailo_apps.python.core.common.installation_utils import detect_hailo_arch
from hailo_apps.python.core.common.defines import (
    HAILO_ARCH_KEY,
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
    SOURCE_PIPELINE,
    USER_CALLBACK_PIPELINE,
)

hailo_logger = get_logger(__name__)

# endregion imports

APP_TITLE = "Hailo Depth Anything"
DEFAULT_MODEL_VERSION = "v2"

# Post-process .so built from postprocess/depth_anything_postprocess.cpp
POSTPROCESS_SO = str(
    Path(__file__).parent / "postprocess" / "build.release" / "libdepth_anything_postprocess.so"
)
POSTPROCESS_FUNCTION = "filter_depth_anything"

# HEF download URLs from Hailo Model Zoo
MODEL_URLS = {
    ("v1", "hailo8"): "https://hailo-model-zoo.s3.eu-west-2.amazonaws.com/ModelZoo/Compiled/v2.18.0/hailo8/depth_anything_vits.hef",
    ("v1", "hailo8l"): "https://hailo-model-zoo.s3.eu-west-2.amazonaws.com/ModelZoo/Compiled/v2.18.0/hailo8l/depth_anything_vits.hef",
    ("v1", "hailo10h"): "https://hailo-model-zoo.s3.eu-west-2.amazonaws.com/ModelZoo/Compiled/v5.2.0/hailo10h/depth_anything_vits.hef",
    ("v2", "hailo8"): "https://hailo-model-zoo.s3.eu-west-2.amazonaws.com/ModelZoo/Compiled/v2.18.0/hailo8/depth_anything_v2_vits.hef",
    ("v2", "hailo8l"): "https://hailo-model-zoo.s3.eu-west-2.amazonaws.com/ModelZoo/Compiled/v2.18.0/hailo8l/depth_anything_v2_vits.hef",
    ("v2", "hailo10h"): "https://hailo-model-zoo.s3.eu-west-2.amazonaws.com/ModelZoo/Compiled/v5.2.0/hailo10h/depth_anything_v2_vits.hef",
}

MODEL_NAMES = {
    "v1": "depth_anything_vits",
    "v2": "depth_anything_v2_vits",
}


def get_hef_path(model_version, arch, user_hef_path=None):
    """Resolve HEF path: use user-provided path, or download from Model Zoo if needed."""
    if user_hef_path and Path(user_hef_path).exists():
        hailo_logger.info("Using user-provided HEF: %s", user_hef_path)
        return user_hef_path

    model_name = MODEL_NAMES[model_version]
    # Store HEFs in a resources dir next to this file
    resources_dir = Path(__file__).parent / "resources"
    resources_dir.mkdir(exist_ok=True)
    hef_path = resources_dir / f"{model_name}.hef"

    if hef_path.exists():
        hailo_logger.info("Found local HEF: %s", hef_path)
        return str(hef_path)

    url_key = (model_version, arch)
    if url_key not in MODEL_URLS:
        raise RuntimeError(
            f"No HEF URL for model version '{model_version}' on architecture '{arch}'. "
            f"Available: {list(MODEL_URLS.keys())}"
        )

    url = MODEL_URLS[url_key]
    hailo_logger.info("Downloading HEF from %s ...", url)
    print(f"Downloading {model_name}.hef for {arch}...")
    try:
        urllib.request.urlretrieve(url, str(hef_path))
        hailo_logger.info("Downloaded HEF to %s", hef_path)
        print(f"Downloaded to {hef_path}")
    except Exception as e:
        raise RuntimeError(
            f"Failed to download HEF from {url}: {e}\n"
            f"Please download manually and pass via --hef-path"
        ) from e

    return str(hef_path)


class GStreamerDepthAnythingApp(GStreamerApp):
    """GStreamer pipeline app for Depth Anything V1/V2 depth estimation.

    Uses hailonet for inference, hailofilter with a custom C++ post-process
    (.so) that creates HailoDepthMask, and hailooverlay for depth rendering.
    """

    def __init__(self, app_callback, user_data, parser=None):
        if parser is None:
            parser = get_pipeline_parser()
            parser.add_argument(
                "--model-version",
                type=str,
                choices=["v1", "v2"],
                default=DEFAULT_MODEL_VERSION,
                help="Depth Anything model version (default: v2)",
            )
            parser.add_argument(
                "--display-mode",
                type=str,
                choices=["depth", "side-by-side", "overlay"],
                default="depth",
                help="Display mode (default: depth)",
            )
            parser.add_argument(
                "--colormap",
                type=str,
                choices=["inferno", "spectral", "magma", "turbo"],
                default="inferno",
                help="Colormap for depth visualization (default: inferno)",
            )
            parser.add_argument(
                "--alpha",
                type=float,
                default=0.5,
                help="Blend alpha for overlay mode (0.0-1.0, default: 0.5)",
            )

        hailo_logger.info("Initializing Depth Anything App...")

        super().__init__(parser, user_data)

        self.model_version = self.options_menu.model_version
        self.display_mode = self.options_menu.display_mode
        self.colormap_name = self.options_menu.colormap
        self.alpha = self.options_menu.alpha

        hailo_logger.debug(
            "Options: arch=%s, model_version=%s, display_mode=%s, colormap=%s, alpha=%s",
            self.arch, self.model_version, self.display_mode, self.colormap_name, self.alpha,
        )

        self.app_callback = app_callback
        setproctitle.setproctitle(APP_TITLE)

        # Resolve HEF path with auto-download
        self.hef_path = get_hef_path(
            self.model_version,
            self.arch,
            user_hef_path=self.hef_path,
        )

        # Resolve post-process .so
        self.post_process_so = POSTPROCESS_SO
        self.post_function_name = POSTPROCESS_FUNCTION

        if self.hef_path is None or not Path(self.hef_path).exists():
            hailo_logger.error("HEF path is invalid or missing: %s", self.hef_path)
        if not Path(self.post_process_so).exists():
            hailo_logger.error(
                "Post-process .so not found: %s — run 'meson setup build.release && ninja -C build.release' "
                "in postprocess/ directory",
                self.post_process_so,
            )

        hailo_logger.info(
            "Resources resolved | hef=%s | model=%s | post_so=%s | post_fn=%s",
            self.hef_path, MODEL_NAMES[self.model_version],
            self.post_process_so, self.post_function_name,
        )

        self.create_pipeline()
        hailo_logger.debug("Pipeline created")

    def get_pipeline_string(self):
        source_pipeline = SOURCE_PIPELINE(
            video_source=self.video_source,
            video_width=self.video_width,
            video_height=self.video_height,
            frame_rate=self.frame_rate,
            sync=self.sync,
        )

        # Center-crop the frame to a square before inference.
        # Depth Anything expects 224x224 (square). Letterbox padding adds black
        # bars that produce garbage depth. Stretching distorts the image.
        # Center crop preserves aspect ratio and gives the model real content.
        w = self.video_width or 1280
        h = self.video_height or 720
        if w > h:
            # Landscape: crop sides
            crop_left = (w - h) // 2
            crop_right = w - h - crop_left
            center_crop = f"videocrop left={crop_left} right={crop_right} "
        elif h > w:
            # Portrait: crop top/bottom
            crop_top = (h - w) // 2
            crop_bottom = h - w - crop_top
            center_crop = f"videocrop top={crop_top} bottom={crop_bottom} "
        else:
            center_crop = ""

        depth_pipeline = INFERENCE_PIPELINE(
            hef_path=self.hef_path,
            post_process_so=self.post_process_so,
            post_function_name=self.post_function_name,
            name="depth_inference",
        )
        user_callback_pipeline = USER_CALLBACK_PIPELINE()
        display_pipeline = DISPLAY_PIPELINE(
            video_sink=self.video_sink, sync=self.sync, show_fps=self.show_fps
        )

        parts = [source_pipeline]
        if center_crop:
            parts.append(center_crop)
        parts.extend([depth_pipeline, user_callback_pipeline, display_pipeline])
        pipeline_str = " ! ".join(parts)
        hailo_logger.debug("Pipeline string: %s", pipeline_str)
        return pipeline_str


def main():
    # Canonical entry point is depth_anything.py (with visualization callback).
    # This main() runs the pipeline with a dummy callback (hailooverlay renders depth).
    user_data = app_callback_class()
    app_callback = dummy_callback
    app = GStreamerDepthAnythingApp(app_callback, user_data)
    app.run()


if __name__ == "__main__":
    print("Starting Hailo Depth Anything App...")
    main()
