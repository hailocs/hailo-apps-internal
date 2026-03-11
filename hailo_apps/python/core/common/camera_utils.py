import os
import signal
import subprocess
import time
import platform
import cv2
import sys
from enum import Enum
from typing import Optional
import subprocess
from .defines import UDEV_CMD, CAMERA_RESOLUTION_MAP
from .hailo_logger import get_logger

hailo_logger = get_logger(__name__)

# if udevadm is not installed, install it using the following command:
# sudo apt-get install udev

class CapProcessingMode(str, Enum):
    """
    Capture processing modes.

    Defines how frames are read from the source and fed into the pipeline,
    based on source type and user options (saving output, target FPS, etc.).
    """

    CAMERA_NORMAL = "camera_normal"
    CAMERA_FRAME_DROP = "camera_frame_drop"
    VIDEO_NORMAL = "video_normal"
    VIDEO_PACE = "video_pace"

class PiCamera2CaptureAdapter:
    """
    Adapter that makes Picamera2 behave like cv2.VideoCapture.

    Goals:
    - Provide read(), isOpened(), get(), release() APIs compatible with OpenCV code
    - Avoid deadlocks when release() is called while another thread is reading
    - Ensure stop()/close() never race with capture_array()
    """

    def __init__(self, picam2):
        self.picam2 = picam2
        self._opened = True
        self._io_lock = threading.Lock()

    def isOpened(self):
        return self._opened

    def read(self):
        if not self._opened:
            return False, None

        # prevent stop/close while capturing
        with self._io_lock:
            if not self._opened: # re-check after taking lock
                return False, None
            frame = self.picam2.capture_array()

        if frame is None:
            return False, None
        return True, frame

    def get(self, prop_id: int) -> float:
        if prop_id in (cv2.CAP_PROP_FRAME_WIDTH, cv2.CAP_PROP_FRAME_HEIGHT):
            try:
                cfg = self.picam2.camera_configuration()
                size = cfg.get("main", {}).get("size", None)
                if size and len(size) == 2:
                    w, h = int(size[0]), int(size[1])
                    return float(w if prop_id == cv2.CAP_PROP_FRAME_WIDTH else h)
            except Exception:
                pass
            return 0.0
        if prop_id == cv2.CAP_PROP_FPS:
            return 30.0
        return None

    def release(self):
        # stop new reads ASAP
        self._opened = False

        # wait if a read() is currently inside capture_array()
        with self._io_lock:
            try:
                self.picam2.stop()
            except Exception:
                pass
            try:
                self.picam2.close()
            except Exception:
                pass

def select_cap_processing_mode(input_type: str,
                           save_output: bool,
                           frame_rate: float | None) -> CapProcessingMode:
    """
    Decide capture processing behavior.

    Modes:
        CAMERA_NORMAL       - realtime camera
        CAMERA_FRAME_DROP   - camera frame dropping to target FPS
        VIDEO_NORMAL        - fastest video processing
        VIDEO_PACE          - realtime pacing (used when saving output)
    """

    is_camera = input_type in ("usb", "rpi", "stream")
    is_video  = input_type == "video"

    has_target_fps = frame_rate is not None and frame_rate > 0

    # CAMERA
    if is_camera:
        return (
            CapProcessingMode.CAMERA_FRAME_DROP
            if has_target_fps
            else CapProcessingMode.CAMERA_NORMAL
        )

    # VIDEO
    if is_video:
        return (
            CapProcessingMode.VIDEO_PACE
            if save_output
            else CapProcessingMode.VIDEO_NORMAL
        )

    # images / fallback
    return None


def open_usb_camera(input_src: str, resolution: Optional[str]):
    """
    USB camera open .

    Behavior:
    - "usb":
        * Linux  -> Detect REAL USB cameras via v4l2-ctl
        * Windows -> Probe camera indices via OpenCV (DirectShow)
        * If CAMERA_INDEX env var exists -> use it
        * Else -> auto-pick FIRST available USB camera
    - "/dev/videoX":
        * Linux explicit camera device
    - "0"/"1"/...:
        * Windows explicit camera index
    - Apply resolution if requested
    - Ensure camera actually streams frames
    
    """
    system = platform.system()
    # -----------------------------
    # Helper: apply resolution + validate
    # -----------------------------
    def _apply_and_validate(cap):
        if resolution in CAMERA_RESOLUTION_MAP:
            w, h = CAMERA_RESOLUTION_MAP[resolution]
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, w)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, h)
            logger.debug(f"Camera resolution forced to {w}x{h}")

        ok, frame = cap.read()
        if not ok or frame is None:
            cap.release()
            logger.error("Camera opened but produced no frames.")
            sys.exit(1)
        return cap

    # =========================================================
    # 1) Explicit Linux device path: /dev/videoX
    # =========================================================
    if str(input_src).startswith("/dev/video"):
        if system == "Windows":
            logger.error("On Windows, '/dev/videoX' is not supported. Use '-i 0' or '-i usb'.")
            sys.exit(1)

        cap = cv2.VideoCapture(str(input_src))
        if not cap.isOpened():
            logger.error(f"Failed to open Linux camera device: {input_src}")

            # Only check available cameras AFTER failure
            available_cameras = get_usb_video_devices()
            if available_cameras:
                logger.error(f"Available USB camera indices: {available_cameras}")
            else:
                logger.error("No USB cameras detected.")

            sys.exit(1)

        logger.info(f"Using USB camera device: {input_src}")
        return _apply_and_validate(cap)


    # =========================================================
    # 2) Explicit Windows numeric index: 0/1/2...
    # =========================================================
    if str(input_src).isdigit():
        if system == "Linux":
            logger.error("On Linux, numeric camera index is not supported. Use '-i /dev/videoX' or '-i usb'.")
            sys.exit(1)

        cam_index = int(str(input_src))
        cap = cv2.VideoCapture(cam_index)

        if not cap.isOpened():
            hailo_logger.error(f"Failed to open Windows camera index: {cam_index}")

            # Only scan cameras AFTER failure
            available_cameras = get_usb_video_devices()
            if available_cameras:
                hailo_logger.error(f"Available camera indices detected: {available_cameras}")
            else:
                hailo_logger.error("No cameras detected on Windows.")

            sys.exit(1)

        hailo_logger.info(f"Using USB camera index: {cam_index}")
        return _apply_and_validate(cap)

    # =========================================================
    # 3) Auto USB selection: "usb"
    # =========================================================
    if input_src != "usb":
        hailo_logger.error(f"open_usb_camera received invalid camera input: '{input_src}'")
        sys.exit(1)

    # ---------------------------------------------------------
    # 3.1 Windows: select first available camera index
    # ---------------------------------------------------------
    if system == "Windows":
        available_cameras = get_usb_video_devices()
        if available_cameras is None:
            hailo_logger.error("USB mode requested, but no cameras detected on Windows.")
            sys.exit(1)

        cam_index = available_cameras[0]
        cap = cv2.VideoCapture(cam_index)
        if not cap.isOpened():
            hailo_logger.error(f"Failed to open USB camera index {cam_index} on Windows.")
            sys.exit(1)

        hailo_logger.info(f"Using USB camera index: {cam_index}")
        return _apply_and_validate(cap)

    # ---------------------------------------------------------
    # 3.2 Linux: select first USB /dev/videoX (v4l2-ctl)
    # ---------------------------------------------------------
    available_cameras = get_usb_video_devices()
    if available_cameras is None:
        hailo_logger.error("USB mode requested, but no USB cameras detected on Linux.")
        sys.exit(1)

    cam_index = available_cameras[0]
    cap = cv2.VideoCapture(cam_index)
    if not cap.isOpened():
        hailo_logger.error(f"Failed to open USB camera index {cam_index} on Linux.")
        sys.exit(1)

    hailo_logger.info(f"Using USB camera index: {cam_index}")
    return _apply_and_validate(cap)


def open_rpi_camera():
    try:
        from picamera2 import Picamera2
    except Exception as e:
        hailo_logger.error(f"Picamera2 not available: {e}")
        return None

    try:
        picam2 = Picamera2()
        main = {"size": (800, 600), "format": "RGB888"}
        config = picam2.create_video_configuration(main=main, controls={"FrameRate": 30})

        picam2.configure(config)
        picam2.start()
        return PiCamera2CaptureAdapter(picam2)

    except Exception as e:
        hailo_logger.error(f"Failed to open RPi camera: {e}")
        try:
            picam2.stop()
        except Exception:
            pass
        try:
            picam2.close()
        except Exception:
            pass
        return None


def is_stream_url(input_arg: str) -> bool:
    return input_arg.startswith(("http://", "https://", "rtsp://"))


# Checks if a Raspberry Pi camera is connected and responsive.
def is_rpi_camera_available():
    """Returns True if the RPi camera is connected."""
    hailo_logger.debug("Checking if Raspberry Pi camera is available...")
    try:
        process = subprocess.Popen(
            ["rpicam-hello", "-t", "0"], stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        hailo_logger.debug("Started rpicam-hello process.")
        time.sleep(5)
        process.send_signal(signal.SIGTERM)
        hailo_logger.debug("Sent SIGTERM to rpicam-hello process.")
        process.wait(timeout=2)
        stdout, stderr = process.communicate()
        stderr_str = stderr.decode().lower()
        hailo_logger.debug(f"rpicam-hello stderr: {stderr_str}")
        if "no cameras available" in stderr_str:
            hailo_logger.info("No Raspberry Pi cameras detected.")
            return False
        hailo_logger.info("Raspberry Pi camera is available.")
        return True
    except Exception as e:
        hailo_logger.error(f"Error checking Raspberry Pi camera: {e}")
        return False


def get_usb_video_devices():
    """
    Return a list of available USB video devices for the current platform.

    Returns:
        list[str | int]:
            - On Linux: list of device paths such as ['/dev/video0', '/dev/video2']
            - On Windows: list of OpenCV-compatible camera indices such as [0, 1]

    Notes:
        - Linux detection is based on `udevadm` and filters devices that:
          1. are connected via USB
          2. expose capture capability
        - Windows detection relies on DirectShow device enumeration via `pygrabber`.
          The returned indices follow the enumeration order and are intended for use
          with OpenCV / DirectShow.
    """
    system = platform.system()
    hailo_logger.debug(f"Detecting USB video devices on {system}...")

    if system == "Linux":
        return _get_usb_video_devices_linux()

    if system == "Windows":
        return _get_usb_video_devices_windows()

    hailo_logger.warning(f"Unsupported platform: {system}")
    return []

# Checks if a USB camera is connected and responsive.
def _get_usb_video_devices_linux():
    """Detect USB video capture devices on Linux."""
    hailo_logger.debug("Scanning /dev for video devices...")
    video_devices = [
        f"/dev/{device}" for device in os.listdir("/dev") if device.startswith("video")
    ]
    usb_video_devices = []
    hailo_logger.debug(f"Found video devices: {video_devices}")

    for device in video_devices:
        try:
            hailo_logger.debug(f"Checking device: {device}")
            # Use udevadm to get detailed information about the device
            udevadm_cmd = [UDEV_CMD, "info", "--query=all", "--name=" + device]
            hailo_logger.debug(f"Running command: {' '.join(udevadm_cmd)}")
            result = subprocess.run(udevadm_cmd, check=False, capture_output=True)
            output = result.stdout.decode("utf-8")
            hailo_logger.debug(f"udevadm output for {device}: {output}")

            # Check if the device is connected via USB and has video capture capabilities
            if "ID_BUS=usb" in output and ":capture:" in output:
                hailo_logger.info(f"USB camera detected: {device}")
                usb_video_devices.append(device)
        except Exception as e:
            hailo_logger.error(f"Error checking device {device}: {e}")

    hailo_logger.debug(f"USB video devices found on Linux: {usb_video_devices}")
    return usb_video_devices

def _get_usb_video_devices_windows():
    """
    Detect USB video devices on Windows using DirectShow enumeration.

    Returns:
        list[int]: Camera indices compatible with OpenCV / DirectShow.
    """
    usb_video_devices = []

    try:
        from pygrabber.dshow_graph import FilterGraph
    except ImportError:
        hailo_logger.error(
            "pygrabber is not installed. Please install it with: pip install pygrabber"
        )
        return []

    try:
        hailo_logger.debug("Enumerating DirectShow input devices...")
        graph = FilterGraph()
        devices = graph.get_input_devices()
        hailo_logger.debug(f"Found DirectShow devices: {devices}")

        for index, name in enumerate(devices):
            hailo_logger.info(f"USB camera detected: index={index}, name='{name}'")
            usb_video_devices.append(index)

    except Exception as e:
        hailo_logger.error(f"Failed to enumerate Windows video devices: {e}")
        return []

    hailo_logger.debug(f"USB video devices found on Windows: {usb_video_devices}")
    return usb_video_devices

def main():
    hailo_logger.debug("Running main() to check for USB cameras.")
    usb_video_devices = get_usb_video_devices()

    if usb_video_devices:
        hailo_logger.info(f"USB cameras found on: {', '.join(usb_video_devices)}")
        print(f"USB cameras found on: {', '.join(usb_video_devices)}")
    else:
        hailo_logger.info("No available USB cameras found.")
        print("No available USB cameras found.")


if __name__ == "__main__":
    main()
