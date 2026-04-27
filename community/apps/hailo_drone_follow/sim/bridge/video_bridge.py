#!/usr/bin/env python3
"""Gazebo camera -> UDP H.264 RTP bridge.

Subscribes to a Gazebo gz-transport camera topic, encodes each frame as H.264,
wraps it in RTP, and sends via UDP.  The drone-follow app consumes this via
``--input udp://0.0.0.0:5600``.

Usage:
    sim/bridge/video_bridge.py                 # defaults
    sim/bridge/video_bridge.py --discover      # list available gz topics
    sim/bridge/video_bridge.py --port 5600 --bitrate 2000
"""

import os
# Must be set BEFORE importing gz.msgs (protobuf version mismatch workaround)
os.environ.setdefault("PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION", "python")

import argparse
import signal
import sys
import time

import cv2
import numpy as np
from gz.msgs10.image_pb2 import Image
from gz.transport13 import Node

import gi
gi.require_version('Gst', '1.0')
from gi.repository import Gst


def parse_args():
    p = argparse.ArgumentParser(description="Gazebo camera -> UDP H.264 RTP bridge")
    p.add_argument(
        "--topic",
        default="/camera",
        help="Gazebo gz-transport image topic (default: /camera)",
    )
    p.add_argument("--host", default="127.0.0.1", help="UDP destination host (default: 127.0.0.1)")
    p.add_argument("--port", type=int, default=5600, help="UDP destination port (default: 5600)")
    p.add_argument("--bitrate", type=int, default=2000, help="H.264 bitrate in kbps (default: 2000)")
    p.add_argument("--fps", type=int, default=30, help="Target FPS (default: 30)")
    p.add_argument("--discover", action="store_true", help="List available gz topics and exit")
    return p.parse_args()


# Pixel format enum values from gz.msgs.PixelFormatType
_RGB_INT8 = 3
_BGR_INT8 = 13


def main():
    args = parse_args()
    node = Node()

    if args.discover:
        print("Discovering gz-transport topics (waiting 2s)...")
        time.sleep(2)
        topics = node.topic_list()
        for t in topics:
            print(f"  {t}")
        if not topics:
            print("  (none found — is Gazebo running?)")
        return

    Gst.init(None)

    # Pipeline is created lazily on the first frame (need to know resolution).
    pipeline = [None]
    appsrc = [None]
    frame_count = [0]

    def create_pipeline(width, height):
        pipeline_str = (
            f"appsrc name=src is-live=true format=time "
            f"caps=video/x-raw,format=BGR,width={width},height={height},framerate={args.fps}/1 ! "
            f"queue max-size-buffers=3 leaky=downstream ! "
            f"videoconvert ! "
            f"x264enc tune=zerolatency speed-preset=ultrafast bitrate={args.bitrate} "
            f"key-int-max={args.fps} ! "
            f"video/x-h264,profile=baseline ! "
            f"rtph264pay config-interval=1 pt=96 ! "
            f"udpsink host={args.host} port={args.port} sync=false async=false"
        )
        pipe = Gst.parse_launch(pipeline_str)
        src = pipe.get_by_name("src")
        pipe.set_state(Gst.State.PLAYING)
        return pipe, src

    def on_image(msg: Image):
        try:
            w, h = msg.width, msg.height
            fmt = msg.pixel_format_type
            data = msg.data

            channels = 3
            frame = np.frombuffer(data, dtype=np.uint8).reshape(h, w, channels)

            if fmt == _RGB_INT8:
                frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)

            # Create pipeline on first frame when resolution is known.
            if pipeline[0] is None:
                pipeline[0], appsrc[0] = create_pipeline(w, h)
                print(f"[bridge] Created H.264 pipeline ({w}x{h} @ {args.fps}fps)")

            buf = Gst.Buffer.new_wrapped(frame.tobytes())
            buf.pts = frame_count[0] * Gst.SECOND // args.fps
            buf.duration = Gst.SECOND // args.fps
            appsrc[0].emit("push-buffer", buf)

            frame_count[0] += 1
            if frame_count[0] % 300 == 0:
                print(f"[bridge] Sent {frame_count[0]} frames ({w}x{h})")

        except Exception as e:
            print(f"[bridge] Error: {e}", file=sys.stderr)

    print(f"[bridge] Subscribing to: {args.topic}")
    print(f"[bridge] Sending H.264 RTP to udp://{args.host}:{args.port} (bitrate={args.bitrate}kbps)")

    subscribed = node.subscribe(Image, args.topic, on_image)
    if not subscribed:
        print(f"[bridge] ERROR: Failed to subscribe to {args.topic}", file=sys.stderr)
        print("[bridge] Run with --discover to list available topics.", file=sys.stderr)
        sys.exit(1)

    print("[bridge] Waiting for frames... (Ctrl+C to stop)")

    def shutdown(*_):
        if pipeline[0]:
            appsrc[0].emit("end-of-stream")
            pipeline[0].set_state(Gst.State.NULL)
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)
    try:
        signal.pause()
    except AttributeError:
        while True:
            time.sleep(1)


if __name__ == "__main__":
    main()
