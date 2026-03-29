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
from community.apps.pipeline_apps.depth_anything.metric_depth import MetricDepthConverter, render_scale_bar
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

    def __init__(self, display_mode="depth", colormap_name="inferno", alpha=0.5,
                 depth_mode="relative", scene_type="indoor", max_depth=None,
                 calibrate_ref=None, export_depth=None, temporal_alpha=0.4,
                 max_clip=10.0):
        super().__init__()
        self.display_mode = display_mode
        self.colormap_cv2 = COLORMAP_MAP.get(colormap_name, cv2.COLORMAP_INFERNO)
        self.alpha = alpha
        self.depth_mode = depth_mode
        self.export_depth = export_depth
        self.max_clip = max_clip if max_clip and max_clip > 0 else None

        # Temporal smoothing state
        self.temporal_alpha = temporal_alpha
        self._prev_depth = None
        self._smooth_min = None
        self._smooth_max = None

        # Metric depth converter
        self.metric_converter = None
        if depth_mode == "metric":
            self.metric_converter = MetricDepthConverter(
                scene_type=scene_type, max_depth=max_depth
            )
            # Apply pre-run calibration if provided
            if calibrate_ref:
                rel_str, met_str = calibrate_ref.split(":")
                self.metric_converter.calibrate_from_reference(
                    relative_values=np.array([float(rel_str)]),
                    metric_values=np.array([float(met_str)]),
                )

        # Export directory
        if export_depth:
            os.makedirs(export_depth, exist_ok=True)


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
    depth = np.clip(depth, 0, 1000.0)  # Cap extreme values from near-zero raw pixels

    # --- Clip far-end depth outliers ---
    # Cap at the 95th percentile to remove noise spikes that stretch the
    # colormap and flatten near-field contrast.
    if user_data.max_clip is not None:
        clip_val = np.percentile(depth, 95)
        depth = np.clip(depth, depth.min(), clip_val)

    # --- Temporal smoothing ---
    # EMA on depth values reduces frame-to-frame jitter.
    # Spatial blur reduces per-pixel noise.
    t_alpha = user_data.temporal_alpha
    if t_alpha > 0:
        # Spatial denoising (light bilateral filter preserves edges better than Gaussian)
        depth_f32 = depth.astype(np.float32)
        depth = cv2.bilateralFilter(depth_f32, d=5, sigmaColor=0.5, sigmaSpace=5)

        # Temporal EMA on depth map
        if user_data._prev_depth is not None and user_data._prev_depth.shape == depth.shape:
            depth = t_alpha * user_data._prev_depth + (1 - t_alpha) * depth
        user_data._prev_depth = depth.copy()

    # --- Metric depth conversion ---
    metric_depth_m = None
    if user_data.depth_mode == "metric" and user_data.metric_converter is not None:
        metric_depth_m = user_data.metric_converter.convert(depth)

    # Normalize to 0-255 for colormap — use EMA-smoothed min/max to prevent scale jumping
    d_min = float(depth.min())
    d_max = float(depth.max())
    if t_alpha > 0:
        if user_data._smooth_min is not None:
            user_data._smooth_min = t_alpha * user_data._smooth_min + (1 - t_alpha) * d_min
            user_data._smooth_max = t_alpha * user_data._smooth_max + (1 - t_alpha) * d_max
        else:
            user_data._smooth_min = d_min
            user_data._smooth_max = d_max
        d_min = user_data._smooth_min
        d_max = user_data._smooth_max

    depth_norm = (255 - ((depth - d_min) / (d_max - d_min + 1e-6) * 255)).astype(np.uint8)

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

    elif user_data.display_mode == "metric":
        if metric_depth_m is not None:
            # Colorize the metric depth (normalize to [0, max_depth] → [0, 255])
            max_d = user_data.metric_converter.max_depth
            depth_clamped = np.clip(metric_depth_m, 0, max_d)
            depth_vis = (255 - (depth_clamped / max_d * 255)).astype(np.uint8)
            depth_color = cv2.applyColorMap(depth_vis, user_data.colormap_cv2)
            output = cv2.resize(depth_color, (width, height), interpolation=cv2.INTER_LINEAR)

            # Draw scale bar
            min_m = float(metric_depth_m.min())
            max_m = float(metric_depth_m.max())
            render_scale_bar(output, min_m, max_m, user_data.colormap_cv2)

            # Draw center distance readout
            cy, cx = metric_depth_m.shape[0] // 2, metric_depth_m.shape[1] // 2
            center_depth = metric_depth_m[cy, cx]
            # Scale center coords to output resolution
            out_cx = width // 2
            out_cy = height // 2
            cv2.drawMarker(output, (out_cx, out_cy), (0, 255, 0), cv2.MARKER_CROSS, 20, 2)
            cv2.putText(output, f"{center_depth:.2f}m", (out_cx + 15, out_cy - 5),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)

            # Show raw relative value at center (for calibration reference)
            cy_raw, cx_raw = depth.shape[0] // 2, depth.shape[1] // 2
            raw_center = depth[cy_raw, cx_raw]
            cv2.putText(output, f"raw: {raw_center:.2f}", (out_cx + 15, out_cy + 20),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)

            # Draw stats bar at top
            mean_m = float(metric_depth_m.mean())
            stats_text = f"Min: {min_m:.2f}m | Max: {max_m:.2f}m | Mean: {mean_m:.2f}m"
            cv2.putText(output, stats_text, (10, 25),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        else:
            output = depth_color_resized  # Fallback to regular depth

    else:
        output = depth_color_resized

    # If metric mode is on but display_mode is NOT "metric", still show metric stats
    if user_data.depth_mode == "metric" and user_data.display_mode != "metric" and metric_depth_m is not None:
        min_m = float(metric_depth_m.min())
        max_m = float(metric_depth_m.max())
        mean_m = float(metric_depth_m.mean())
        stats_text = f"Depth: {min_m:.1f}-{max_m:.1f}m (avg {mean_m:.1f}m)"
        cv2.putText(output, stats_text, (10, height - 15),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

    # Resize depth float map to display frame dimensions for cursor readout.
    # For side-by-side mode, the depth map covers only the right half.
    display_h, display_w = output.shape[:2]
    depth_resized = cv2.resize(depth, (display_w, display_h), interpolation=cv2.INTER_LINEAR).astype(np.float32)

    # Send both display frame and depth map through the queue.
    # We pickle-serialize to avoid issues with multiprocessing Queue and numpy arrays.
    frame_count = user_data.get_count()
    user_data.set_frame(pickle.dumps((output, depth_resized)))

    # Export depth data (uses frame_count already assigned above)
    if user_data.export_depth:
        if metric_depth_m is not None:
            export_data = metric_depth_m
            suffix = "metric"
        else:
            export_data = depth
            suffix = "relative"
        np.save(
            os.path.join(user_data.export_depth, f"depth_{suffix}_{frame_count:06d}.npy"),
            export_data,
        )

    # Print depth stats periodically
    if frame_count % 30 == 0:
        if metric_depth_m is not None:
            hailo_logger.info(
                "Frame %d | Metric depth min=%.2fm max=%.2fm mean=%.2fm",
                frame_count, metric_depth_m.min(), metric_depth_m.max(), metric_depth_m.mean(),
            )
        else:
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
        choices=["depth", "raw", "side-by-side", "overlay", "metric"],
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
    parser.add_argument(
        "--depth-mode",
        type=str,
        choices=["relative", "metric"],
        default="relative",
        help="Depth output mode: relative (unitless) or metric (meters) (default: relative)",
    )
    parser.add_argument(
        "--scene-type",
        type=str,
        choices=["indoor", "outdoor"],
        default="indoor",
        help="Scene type for metric depth estimation (default: indoor)",
    )
    parser.add_argument(
        "--max-depth",
        type=float,
        default=None,
        help="Maximum depth in meters (overrides scene-type default). Indoor=20m, outdoor=80m.",
    )
    parser.add_argument(
        "--calibrate-ref",
        type=str,
        default=None,
        help="Calibrate with known reference: 'RELATIVE_DEPTH:REAL_METERS' (e.g., '15.3:2.5')",
    )
    parser.add_argument(
        "--export-depth",
        type=str,
        default=None,
        help="Directory to export metric depth frames as .npy files",
    )
    parser.add_argument(
        "--temporal-alpha",
        type=float,
        default=0.4,
        help="Temporal smoothing factor (0.0=off, 0.9=very smooth, default: 0.4)",
    )
    parser.add_argument(
        "--max-clip",
        type=float,
        default=10.0,
        help="Clip depth values beyond this distance in meters (removes far-end outliers, default: 10.0). Set to 0 to disable.",
    )

    # Pre-parse to get custom args for callback setup
    args, _ = parser.parse_known_args()

    user_data = DepthAnythingCallback(
        display_mode=args.display_mode,
        colormap_name=args.colormap,
        alpha=args.alpha,
        depth_mode=args.depth_mode,
        scene_type=args.scene_type,
        max_depth=args.max_depth,
        calibrate_ref=args.calibrate_ref,
        export_depth=args.export_depth,
        temporal_alpha=args.temporal_alpha,
        max_clip=args.max_clip,
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
        display_process.join(timeout=2)
        if display_process.is_alive():
            display_process.terminate()
            display_process.join()


if __name__ == "__main__":
    main()
