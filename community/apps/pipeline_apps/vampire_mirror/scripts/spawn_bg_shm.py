"""Manual test helper: starts a BackgroundService and prints its shm names.

Used to verify the C++ hailovampire_overlay element can open and read
the shared-memory background buffer.

Usage:
    python community/apps/pipeline_apps/vampire_mirror/scripts/spawn_bg_shm.py
Then in another terminal:
    gst-launch-1.0 videotestsrc num-buffers=10 ! \
        video/x-raw,format=RGB,width=320,height=240 ! \
        hailovampire_overlay \
            bg-shm-a-name=<prefix>bg_a \
            bg-shm-b-name=<prefix>bg_b \
            bg-idx-shm-name=<prefix>idx \
            bg-width=320 bg-height=240 ! \
        fakesink
"""
import os
import sys
import time

# Ensure repo root is on sys.path for community.* imports.
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import numpy as np

from community.apps.pipeline_apps.vampire_mirror.bg_service import BackgroundService


def main() -> None:
    svc = BackgroundService(width=320, height=240, channels=3,
                            capture_frames=1, alpha=0.1)
    svc.start()
    try:
        svc.submit_frame(np.full((240, 320, 3), 128, np.uint8), person_mask=None)
        # Allow the subprocess to consume the frame and complete the capture.
        for _ in range(50):
            if svc.is_ready():
                break
            time.sleep(0.02)
        print(f"prefix:    {svc.shm_prefix}")
        print(f"bg_a:      {svc.shm_prefix}bg_a")
        print(f"bg_b:      {svc.shm_prefix}bg_b")
        print(f"idx:       {svc.shm_prefix}idx")
        print()
        print("Service is running. Press Enter to stop and unlink shm.")
        try:
            input()
        except EOFError:
            pass
    finally:
        svc.stop()


if __name__ == "__main__":
    main()
