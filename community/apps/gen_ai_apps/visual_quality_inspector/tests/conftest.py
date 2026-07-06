"""Headless test setup for the visual_quality_inspector gen-ai app.

This app's source imports native / device-only modules at import time:
  - ``cv2``                 (OpenCV: image ops + GUI windows)
  - ``hailo_platform``      (HailoRT: ``VDevice``)
  - ``hailo_platform.genai``(``VLM`` inference)
  - ``picamera2``           (RPi camera, imported lazily inside ``_init_camera``)

To run the suite as a PURE-PYTHON unit test in its own headless process -- with
no device, no VLM inference, no camera, and no GUI window -- we install
lightweight stand-ins in ``sys.modules`` *before* the app modules are imported.

The ``cv2`` stub is not a bare MagicMock: ``Backend.convert_resize_image`` calls
``cv2.cvtColor`` and ``cv2.resize`` and the tests assert on the resulting channel
order and shape. So the stub implements those two functions with real numpy so
the colour-order ("RPI colour fix") and crop assertions are meaningful, while
everything else (windowing, ``VideoCapture``, ``waitKey`` ...) is a no-op mock.
"""

import sys
from unittest.mock import MagicMock

import numpy as np


# --------------------------------------------------------------------------- #
# cv2 stub with a *real* cvtColor / resize so colour-order asserts are real.
# --------------------------------------------------------------------------- #
def _install_cv2_stub():
    cv2 = MagicMock(name="cv2_stub")

    # Colour-conversion codes used by the app. The exact integer values do not
    # matter -- only that BGR<->RGB swaps the channel axis -- so we give them
    # distinct sentinel ints and branch on them in cvtColor.
    cv2.COLOR_BGR2RGB = 4
    cv2.COLOR_RGB2BGR = 4  # symmetric channel reversal
    cv2.INTER_LINEAR = 1

    def _cvt_color(img, code):
        img = np.asarray(img)
        # BGR2RGB / RGB2BGR are both a reversal of the last (channel) axis.
        if img.ndim == 3 and img.shape[2] == 3:
            return img[:, :, ::-1].copy()
        return img.copy()

    def _resize(img, size, interpolation=None):
        # size is (width, height) per OpenCV convention.
        img = np.asarray(img)
        new_w, new_h = size
        h, w = img.shape[:2]
        # Nearest-neighbour index maps -- enough for shape-correct tests.
        ys = (np.linspace(0, h - 1, new_h)).astype(int)
        xs = (np.linspace(0, w - 1, new_w)).astype(int)
        out = img[np.ix_(ys, xs)] if img.ndim == 2 else img[np.ix_(ys, xs)]
        return out.copy()

    cv2.cvtColor = _cvt_color
    cv2.resize = _resize
    sys.modules["cv2"] = cv2
    return cv2


# --------------------------------------------------------------------------- #
# hailo_platform / genai / picamera2 -- pure no-op mocks (never invoked by the
# pure-python unit tests, but must import cleanly).
# --------------------------------------------------------------------------- #
def _install_device_stubs():
    if "hailo_platform" not in sys.modules or not hasattr(
        sys.modules["hailo_platform"], "_is_vqi_stub"
    ):
        hp = MagicMock(name="hailo_platform_stub")
        hp._is_vqi_stub = True
        sys.modules["hailo_platform"] = hp

        genai = MagicMock(name="hailo_platform.genai_stub")
        genai._is_vqi_stub = True
        sys.modules["hailo_platform.genai"] = genai

    # picamera2 is imported lazily; stub so any accidental import is harmless.
    if "picamera2" not in sys.modules:
        sys.modules["picamera2"] = MagicMock(name="picamera2_stub")


# Install stubs at import time so they are present before any test module's
# top-level `from community.apps...` import runs.
_install_cv2_stub()
_install_device_stubs()
