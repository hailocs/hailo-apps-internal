# region imports
# Standard library imports
import multiprocessing
import os
import pickle

os.environ["GST_PLUGIN_FEATURE_RANK"] = "vaapidecodebin:NONE"

# Third-party imports
import gi

gi.require_version("Gst", "1.0")

import cv2
import hailo
import numpy as np

from community.apps.pipeline_apps.depth_anything.depth_anything_pipeline import (
    GStreamerDepthAnythingApp,
)
from hailo_apps.python.core.common.buffer_utils import (
    get_caps_from_pad,
    get_numpy_from_buffer,
)
from hailo_apps.python.core.common.hailo_logger import get_logger
from hailo_apps.python.core.gstreamer.gstreamer_app import app_callback_class

hailo_logger = get_logger(__name__)

# endregion imports

# Map colormap names to OpenCV constants
COLORMAP_MAP = {
    "inferno": cv2.COLORMAP_INFERNO,
    "spectral": cv2.COLORMAP_RAINBOW,
    "magma": cv2.COLORMAP_MAGMA,
    "turbo": cv2.COLORMAP_TURBO,
}

DEPTH_WINDOW_NAME = "Depth Anything"


class DepthAnythingCallback(app_callback_class):
    """Callback class for Depth Anything depth estimation visualization.

    Reads HailoDepthMask objects produced by the C++ post-process
    (libdepth_anything_postprocess.so), applies colormap, and renders
    via a custom display with mouse-based depth readout.
    """

    def __init__(self, display_mode="depth", colormap_name="inferno", alpha=0.5):
        super().__init__()
        self.display_mode = display_mode
        self.colormap_cv2 = COLORMAP_MAP.get(colormap_name, cv2.COLORMAP_INFERNO)
        self.alpha = alpha


def app_callback(element, buffer, user_data):
    """Per-frame callback: read HailoDepthMask, colorize, and enqueue for display."""
    if buffer is None:
        return

    if not user_data.use_frame:
        return

    roi = hailo.get_roi_from_buffer(buffer)
    depth_masks = roi.get_objects_typed(hailo.HAILO_DEPTH_MASK)

    if len(depth_masks) == 0:
        return

    # Get depth data from the HailoDepthMask created by our C++ post-process
    depth_data = depth_masks[0].get_data()
    mask_width = depth_masks[0].get_width()
    mask_height = depth_masks[0].get_height()
    depth = np.array(depth_data).reshape(mask_height, mask_width)

    # Depth Anything outputs inverse depth (close=high, far=low). Invert so
    # the values read intuitively: close=small, far=large.
    depth = 1.0 / (depth + 1e-6)

    # Normalize to 0-255 for colormap
    d_min = depth.min()
    d_max = depth.max()
    depth_norm = ((depth - d_min) / (d_max - d_min + 1e-6) * 255).astype(np.uint8)

    # Apply colormap (produces BGR, which cv2.imshow expects)
    depth_color = cv2.applyColorMap(depth_norm, user_data.colormap_cv2)

    pad = element.get_static_pad("src")
    fmt, width, height = get_caps_from_pad(pad)
    if not (fmt and width and height):
        return

    # Resize depth colormap to frame dimensions
    depth_color_resized = cv2.resize(depth_color, (width, height), interpolation=cv2.INTER_LINEAR)

    if user_data.display_mode == "depth":
        output = depth_color_resized

    elif user_data.display_mode == "side-by-side":
        # GStreamer buffer is RGB; convert to BGR for cv2.imshow
        frame = get_numpy_from_buffer(buffer, fmt, width, height)
        frame_bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
        half_w = width // 2
        left = cv2.resize(frame_bgr, (half_w, height))
        right = cv2.resize(depth_color_resized, (half_w, height))
        output = np.hstack([left, right])

    elif user_data.display_mode == "overlay":
        frame = get_numpy_from_buffer(buffer, fmt, width, height)
        frame_bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
        output = cv2.addWeighted(frame_bgr, 1 - user_data.alpha, depth_color_resized, user_data.alpha, 0)

    else:
        output = depth_color_resized

    # Resize depth float map to display frame dimensions for cursor readout.
    # For side-by-side mode, the depth map covers only the right half.
    display_h, display_w = output.shape[:2]
    depth_resized = cv2.resize(depth, (display_w, display_h), interpolation=cv2.INTER_LINEAR).astype(np.float32)

    # Send both display frame and depth map through the queue.
    # We pickle-serialize to avoid issues with multiprocessing Queue and numpy arrays.
    user_data.set_frame(pickle.dumps((output, depth_resized)))

    # Print depth stats periodically
    frame_count = user_data.get_count()
    if frame_count % 30 == 0:
        hailo_logger.info(
            "Frame %d | Depth min=%.3f max=%.3f mean=%.3f",
            frame_count, d_min, d_max, depth.mean(),
        )


def display_depth_frame(user_data):
    """Custom display process with mouse callback for depth readout.

    Replaces the framework's display_user_data_frame. Reads (frame, depth_map)
    tuples from the queue, tracks mouse position, and overlays the depth value
    at the cursor location.
    """
    mouse_pos = [0, 0]  # [x, y] — mutable list for closure access

    def on_mouse(event, x, y, flags, param):
        mouse_pos[0] = x
        mouse_pos[1] = y

    cv2.namedWindow(DEPTH_WINDOW_NAME, cv2.WINDOW_AUTOSIZE)
    cv2.setMouseCallback(DEPTH_WINDOW_NAME, on_mouse)

    while user_data.running:
        raw = user_data.get_frame()
        if raw is not None:
            frame, depth_map = pickle.loads(raw)
            h, w = frame.shape[:2]
            mx, my = mouse_pos

            # Clamp mouse position to frame bounds
            mx = max(0, min(mx, w - 1))
            my = max(0, min(my, h - 1))

            depth_val = depth_map[my, mx]
            label = f"Depth: {depth_val:.3f}"

            # Draw text with background for readability
            font = cv2.FONT_HERSHEY_SIMPLEX
            font_scale = 0.7
            thickness = 2
            (tw, th), baseline = cv2.getTextSize(label, font, font_scale, thickness)

            # Position the label near the cursor, but keep it within frame bounds
            tx = mx + 15
            ty = my - 10
            if tx + tw > w:
                tx = mx - tw - 15
            if ty - th < 0:
                ty = my + th + 15

            # Background rectangle
            cv2.rectangle(frame, (tx - 2, ty - th - 2), (tx + tw + 2, ty + baseline + 2), (0, 0, 0), -1)
            cv2.putText(frame, label, (tx, ty), font, font_scale, (255, 255, 255), thickness)

            # Small crosshair at cursor
            cv2.drawMarker(frame, (mx, my), (0, 255, 0), cv2.MARKER_CROSS, 15, 1)

            cv2.imshow(DEPTH_WINDOW_NAME, frame)
        cv2.waitKey(1)

    cv2.destroyAllWindows()


def main():
    hailo_logger.info("Starting Depth Anything App.")

    from hailo_apps.python.core.common.core import get_pipeline_parser

    parser = get_pipeline_parser()
    parser.add_argument(
        "--model-version",
        type=str,
        choices=["v1", "v2"],
        default="v2",
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

    # Pre-parse to get custom args for callback setup
    args, _ = parser.parse_known_args()

    user_data = DepthAnythingCallback(
        display_mode=args.display_mode,
        colormap_name=args.colormap,
        alpha=args.alpha,
    )
    app = GStreamerDepthAnythingApp(app_callback, user_data, parser=parser)

    # Enable frame processing in the callback regardless of --use-frame CLI flag.
    # We manage our own display process instead of the framework's default one.
    user_data.use_frame = True

    # The framework's run() will only start its display process if
    # options_menu.use_frame is True. We force it False so we can use our own
    # custom display with mouse tracking.
    app.options_menu.use_frame = False

    # Start our custom display process
    display_process = multiprocessing.Process(
        target=display_depth_frame, args=(user_data,)
    )
    display_process.start()

    try:
        app.run()
    finally:
        user_data.running = False
        display_process.terminate()
        display_process.join()


if __name__ == "__main__":
    main()
