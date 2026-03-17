"""
Download MediaPipe Blaze HEF models for Hailo-8 gesture detection.

Downloads from AlbertaBeef's blaze_tutorial release:
  https://github.com/AlbertaBeef/blaze_tutorial/releases/download/hailo8_version_2/blaze_hailo8_models.zip

Extracts palm_detection_lite.hef and hand_landmark_lite.hef to the models directory.
"""

import io
import os
import sys
import zipfile
import urllib.request

MODELS_URL = (
    "https://github.com/AlbertaBeef/blaze_tutorial/releases/download/"
    "hailo8_version_2/blaze_hailo8_models.zip"
)

REQUIRED_MODELS = [
    "palm_detection_lite.hef",
    "hand_landmark_lite.hef",
]

MODELS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models")


def download_models(output_dir=None):
    """Download and extract blaze HEF models.

    Args:
        output_dir: Directory to extract models into. Defaults to ./models/.
    """
    if output_dir is None:
        output_dir = MODELS_DIR

    os.makedirs(output_dir, exist_ok=True)

    # Check if models already exist
    missing = [m for m in REQUIRED_MODELS if not os.path.exists(os.path.join(output_dir, m))]
    if not missing:
        print(f"All models already present in {output_dir}")
        return

    print(f"Downloading blaze models from:\n  {MODELS_URL}")
    response = urllib.request.urlopen(MODELS_URL)
    zip_data = response.read()
    print(f"Downloaded {len(zip_data) / 1024 / 1024:.1f} MB")

    with zipfile.ZipFile(io.BytesIO(zip_data)) as zf:
        for model_name in REQUIRED_MODELS:
            # Find the file in the zip (may be in a subdirectory)
            matching = [n for n in zf.namelist() if n.endswith(model_name)]
            if not matching:
                print(f"Warning: {model_name} not found in archive")
                continue

            # Extract to output dir with flat name
            src = matching[0]
            dst = os.path.join(output_dir, model_name)
            with zf.open(src) as src_f, open(dst, "wb") as dst_f:
                dst_f.write(src_f.read())
            size_mb = os.path.getsize(dst) / 1024 / 1024
            print(f"  Extracted: {model_name} ({size_mb:.1f} MB)")

    print(f"Models saved to {output_dir}")


if __name__ == "__main__":
    output = sys.argv[1] if len(sys.argv) > 1 else None
    download_models(output)
