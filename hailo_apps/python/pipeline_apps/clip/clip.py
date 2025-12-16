# region imports
# Third-party imports
import gi
gi.require_version('Gst', '1.0')
from gi.repository import Gst

# Local application-specific imports
from hailo_apps.python.core.common.hailo_logger import get_logger
from hailo_apps.python.core.gstreamer.gstreamer_app import app_callback_class
from hailo_apps.python.pipeline_apps.clip.clip_pipeline import GStreamerClipApp

hailo_logger = get_logger(__name__)
# endregion imports


def app_callback(element, buffer, user_data):
    return


def main():
    hailo_logger.info("Starting CLIP App.")
    user_data = app_callback_class()
    app = GStreamerClipApp(app_callback, user_data)
    app.run()


if __name__ == "__main__":
    main()
