# region imports
# Standard library imports


# Third-party imports
import numpy as np
import gi
gi.require_version('Gst', '1.0')
from gi.repository import Gst

# Local application-specific imports
import hailo
from hailo_apps.python.core.common.buffer_utils import get_numpy_from_buffer_efficient, get_caps_from_pad
from hailo_apps.python.core.gstreamer.gstreamer_app import app_callback_class
from hailo_apps.python.pipeline_apps.clip.clip_pipeline import GStreamerClipApp
from hailo_apps.python.pipeline_apps.clip import text_image_matcher
# endregion

def app_callback(self, pad, info, user_data):
    buffer = info.get_buffer()
    if buffer is None:
        return Gst.PadProbeReturn.OK
    format, width, height = get_caps_from_pad(pad)
    video_frame = get_numpy_from_buffer_efficient(buffer, format, width, height)
    top_level_matrix = video_frame.roi.get_objects_typed(hailo.HAILO_MATRIX)
    if len(top_level_matrix) == 0:
        detections = video_frame.roi.get_objects_typed(hailo.HAILO_DETECTION)
    else:
        detections = [video_frame.roi] # Use the ROI as the detection
    embeddings_np = None
    used_detection = []
    track_id_focus = text_image_matcher.track_id_focus # Used to focus on a specific track_id
    update_tracked_probability = None
    for detection in detections:
        results = detection.get_objects_typed(hailo.HAILO_MATRIX)
        if len(results) == 0:
            continue
        detection_embeddings = np.array(results[0].get_data())  # Convert the matrix to a NumPy array
        used_detection.append(detection)
        if embeddings_np is None:
            embeddings_np = detection_embeddings[np.newaxis, :]
        else:
            embeddings_np = np.vstack((embeddings_np, detection_embeddings))
        if track_id_focus is not None:
            track = detection.get_objects_typed(hailo.HAILO_UNIQUE_ID)
            if len(track) == 1:
                track_id = track[0].get_id()
                # If we have a track_id_focus, update only the tracked_probability of the focused track
                if track_id == track_id_focus:
                    update_tracked_probability = len(used_detection) - 1
    if embeddings_np is not None:
        matches = text_image_matcher.match(embeddings_np, report_all=True, update_tracked_probability=update_tracked_probability)
        for match in matches:
            # (row_idx, label, confidence, entry_index) = match
            detection = used_detection[match.row_idx]
            old_classification = detection.get_objects_typed(hailo.HAILO_CLASSIFICATION)
            if (match.passed_threshold and not match.negative):
                # Add label as classification metadata
                classification = hailo.HailoClassification('clip', match.text, match.similarity)
                detection.add_object(classification)
            # remove old classification
            for old in old_classification:
                detection.remove_object(old)
    return Gst.FlowReturn.OK

def main():
    user_data = app_callback_class()
    app = GStreamerClipApp(user_data, app_callback)
    app.run()
    
if __name__ == "__main__":
    main()