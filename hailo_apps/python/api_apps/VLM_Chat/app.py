import threading
import signal
import os
import cv2
import sys
import concurrent.futures
import select
os.environ["QT_QPA_PLATFORM"] = 'xcb'
from backend import Backend
from hailo_apps.python.core.common.core import get_default_parser, get_resource_path
from hailo_apps.python.core.common.camera_utils import get_usb_video_devices
from hailo_apps.python.core.common.defines import (
    VLM_MODEL_NAME_H10, 
    RESOURCES_MODELS_DIR_NAME,
    RPI_NAME_I, 
    USB_CAMERA
)

class App:
    def __init__(self, camera, camera_type):
        self.camera = camera
        self.camera_type = camera_type
        self.running = True
        self.executor = concurrent.futures.ThreadPoolExecutor()
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
        # Initialize camera based on type
        if self.camera_type == RPI_NAME_I:
            try:
                from picamera2 import Picamera2
                picam2 = Picamera2()
                config = picam2.create_preview_configuration(main={"size": (640, 480), "format": "RGB888"})
                picam2.configure(config)
                picam2.start()
                get_frame = lambda: picam2.capture_array()
                cleanup = lambda: picam2.stop()
                camera_name = "RPI"
            except (ImportError, Exception) as e:
                print(f"Error initializing RPI camera: {e}")
                return
        else:
            cap = cv2.VideoCapture(self.camera)
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            cap.set(cv2.CAP_PROP_FPS, 30)
            get_frame = lambda: (lambda r: r[1] if r[0] else None)(cap.read())
            cleanup = lambda: cap.release()
            camera_name = "USB"
        
        print("\n" + "="*80)
        print(f"  🎥  {camera_name} CAMERA STARTED  |  Ask a question about the image")
        print("="*80 + "\n")
        print("Type a question about the image (or press Enter for 'Describe the image'): ", end="", flush=True)
        
        # Initialize Backend after video already started
        self.backend = Backend(hef_path=str(get_resource_path(pipeline_name=None, resource_type=RESOURCES_MODELS_DIR_NAME, model=VLM_MODEL_NAME_H10)))
        
        vlm_future = None
        try:
            while self.running:
                frame = get_frame()
                if frame is None:
                    print("Error: Failed to read frame from camera")
                    break
                
                cv2.imshow('Video', frame)
                
                if cv2.waitKey(25) & 0xFF == ord('q'):
                    self.stop()
                    break
                
                user_input = self.check_keyboard_input()
                
                # Waiting for user question
                if self.waiting_for_question and user_input is not None:
                    self.user_question = user_input.strip() or "Describe the image"
                    if not user_input.strip():
                        print(f"Using default prompt: '{self.user_question}'")
                    
                    self.waiting_for_question = False
                    self.frozen_frame = frame.copy()
                    print("Processing your question...")
                    vlm_future = self.executor.submit(self.backend.vlm_inference, self.frozen_frame.copy(), self.user_question)
                
                # Waiting for continue after VLM response
                elif self.waiting_for_continue and user_input == "":
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
        finally:
            cleanup()
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
    
    video_source = None
    
    if options_menu.input is None:
        print('Please provide an input source using the "--input" argument: "usb" for USB camera or "rpi" for Raspberry Pi camera.')
        exit(1)
    elif options_menu.input == USB_CAMERA:
        video_source = get_usb_video_devices()
        video_source = video_source[0] if video_source else None
    elif options_menu.input == RPI_NAME_I:
        video_source = RPI_NAME_I
    
    if not video_source:
        print(f'Provided argument "--input" is set to {options_menu.input}, however no available cameras found. Please connect a camera or specify different input method.')
        exit(1)
    
    app = App(camera=video_source, camera_type=options_menu.input)
    app.run()
    sys.exit(0)