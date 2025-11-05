import threading
import signal
import os
import cv2
import sys
import concurrent.futures
import select
from pathlib import Path
os.environ["QT_QPA_PLATFORM"] = 'xcb'
from backend import Backend
from hailo_apps.python.core.common.core import get_default_parser, get_resource_path
from hailo_apps.python.core.common.camera_utils import get_usb_video_devices, get_rpi_camera
from hailo_apps.python.core.common.defines import (
    VLM_MODEL_NAME_H10, 
    RESOURCES_MODELS_DIR_NAME, 
    BASIC_PIPELINES_VIDEO_EXAMPLE_NAME, 
    RESOURCES_ROOT_PATH_DEFAULT, 
    RESOURCES_VIDEOS_DIR_NAME, 
    RPI_NAME_I, 
    USB_CAMERA
)

class App:
    def __init__(self, camera, camera_type):
        self.camera = camera
        self.camera_type = camera_type
        self.running = True
        self.executor = concurrent.futures.ThreadPoolExecutor()
        self.backend = Backend(hef_path=get_resource_path(resource_type=RESOURCES_MODELS_DIR_NAME, model=VLM_MODEL_NAME_H10))
        signal.signal(signal.SIGINT, self.signal_handler)
        self.frozen_frame = None
        self.waiting_for_question = True
        self.waiting_for_continue = False
        self.user_question = ''

    def signal_handler(self, sig, frame):
        print('')
        self.running = False
        if self.backend:
            self.backend.close()
        self.executor.shutdown(wait=True)

    def check_keyboard_input(self):
        if select.select([sys.stdin], [], [], 0) == ([sys.stdin], [], []):
            input_line = sys.stdin.readline().strip()
            return input_line
        return None

    def get_user_input_nonblocking(self):
        if select.select([sys.stdin], [], [], 0) == ([sys.stdin], [], []):
            return sys.stdin.readline().strip()
        return None

    def show_video(self):
        if self.camera_type == RPI_NAME_I:
            cap = cv2.VideoCapture(0, cv2.CAP_V4L2)
        else:
            cap = cv2.VideoCapture(self.camera)

        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        cap.set(cv2.CAP_PROP_FPS, 30)
        print("\n" + "="*80)
        print("  🎥  CAMERA STARTED  |  Ask a question about the image")
        print("="*80 + "\n")
        print("Type a question about the image (or press Enter for 'Describe the image'): ", end="", flush=True)
        vlm_future = None
        while cap.isOpened() and self.running:
            ret, frame = cap.read()
            if not ret:
                print("Error: Failed to read frame from camera")
                break

            cv2.imshow('Video', frame)

            key = cv2.waitKey(25) & 0xFF
            if key == ord('q'):
                self.stop()
                break

            # Handle keyboard input
            user_input = self.check_keyboard_input()

            # Waiting for user question
            if self.waiting_for_question and user_input is not None:
                self.user_question = user_input
                self.waiting_for_question = False
                self.frozen_frame = frame.copy()

                # Use default prompt if user just hits Enter without typing
                if not self.user_question.strip():
                    self.user_question = "Describe the image"
                    print(f"Using default prompt: '{self.user_question}'")

                print("Processing your question...")
                vlm_future = self.executor.submit(self.backend.vlm_inference, self.frozen_frame.copy(), self.user_question)

            # Waiting for continue after VLM response
            elif self.waiting_for_continue and user_input is not None:
                if user_input == "":  # Enter key pressed
                    # Reset to waiting for next question
                    self.waiting_for_continue = False
                    self.waiting_for_question = True
                    print("\n" + "="*80)
                    print("  🎥  READY FOR NEXT QUESTION")
                    print("="*80 + "\n")
                    print("Type a question about the image (or press Enter for 'Describe the image'): ", end="", flush=True)

            # Handle VLM response when ready
            if vlm_future and vlm_future.done() and not self.waiting_for_continue:
                vlm_future = None
                self.waiting_for_continue = True
                print("\nPress Enter to ask another question...")

        cap.release()
        cv2.destroyAllWindows()

    def run(self):
        self.video_thread = threading.Thread(target=self.show_video)
        self.video_thread.start()
        try:
            self.video_thread.join()
        except KeyboardInterrupt:
            self.stop()
            self.video_thread.join()
    
if __name__ == "__main__":
    parser = get_default_parser()
    options_menu = parser.parse_args()
    if options_menu.input is None:
        video_source = str(Path(RESOURCES_ROOT_PATH_DEFAULT) / RESOURCES_VIDEOS_DIR_NAME / BASIC_PIPELINES_VIDEO_EXAMPLE_NAME)
    elif options_menu.input == USB_CAMERA:
        video_source = get_usb_video_devices()
        if video_source:
            video_source = video_source[0]
    elif options_menu.input == RPI_NAME_I:
        video_source = get_rpi_camera()
    if not video_source:
        print(f'Provided argument "--input" is set to {options_menu.input}, however no available cameras found. Please connect a camera or specifiy different input method.')
        exit(1)
    app = App(camera=video_source, cmaera_type=options_menu.input)
    app.run()
    sys.exit(0)