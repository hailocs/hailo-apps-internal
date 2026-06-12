"""
Download MediaPipe Blaze HEF models for Hailo gesture detection.

Downloads architecture-specific models from AlbertaBeef's blaze_tutorial releases:
  - Hailo-8:  hailo8_version_2/blaze_hailo8_models.zip
  - Hailo-8L: hailo8_version_2/blaze_hailo8l_models.zip
  - Hailo-10H: uses the Hailo-8 models (compatible)

Extracts palm_detection_lite.hef and hand_landmark_lite.hef to models/<arch>/.
"""

import io
import os
import sys
import zipfile
import urllib.request

from hailo_apps.python.core.common.defines import (
    HAILO8_ARCH,
    HAILO8L_ARCH,
    HAILO10H_ARCH,
)

_RELEASE_BASE = (
    "https://github.com/AlbertaBeef/blaze_tutorial/releases/download/hailo8_version_2"
)

# Map each arch to its download URL.
# Hailo-10H uses the Hailo-8 models (binary-compatible).
ARCH_MODEL_URLS = {
    HAILO8_ARCH: f"{_RELEASE_BASE}/blaze_hailo8_models.zip",
    HAILO8L_ARCH: f"{_RELEASE_BASE}/blaze_hailo8l_models.zip",
    HAILO10H_ARCH: f"{_RELEASE_BASE}/blaze_hailo8_models.zip",
}

REQUIRED_MODELS = [
    "palm_detection_lite.hef",
    "hand_landmark_lite.hef",
]

MODELS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models")


def get_models_dir(arch):
    """Return the arch-specific models directory, e.g. models/hailo8/."""
    return os.path.join(MODELS_DIR, arch)


def download_models(arch, output_dir=None):
    """Download and extract blaze HEF models for the given architecture.

    Args:
        arch: Target architecture ("hailo8", "hailo8l", or "hailo10h").
        output_dir: Directory to extract models into. Defaults to models/<arch>/.
    """
    if arch not in ARCH_MODEL_URLS:
        print(f"ERROR: Unsupported architecture '{arch}' for gesture detection. "
              f"Supported: {', '.join(ARCH_MODEL_URLS.keys())}")
        sys.exit(1)

    if output_dir is None:
        output_dir = get_models_dir(arch)

    os.makedirs(output_dir, exist_ok=True)

    # Check if models already exist
    missing = [m for m in REQUIRED_MODELS if not os.path.exists(os.path.join(output_dir, m))]
    if not missing:
        print(f"All models already present in {output_dir}")
        return

    url = ARCH_MODEL_URLS[arch]
    print(f"Downloading blaze models for {arch} from:\n  {url}")
    response = urllib.request.urlopen(url)
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


def ensure_models(arch):
    """Ensure models are downloaded for the given arch, downloading if needed."""
    output_dir = get_models_dir(arch)
    missing = [m for m in REQUIRED_MODELS if not os.path.exists(os.path.join(output_dir, m))]
    if missing:
        print(f"Models not found for {arch}. Downloading...")
        download_models(arch, output_dir)
    return output_dir


if __name__ == "__main__":
    from hailo_apps.python.core.common.installation_utils import detect_hailo_arch

    arch = sys.argv[1] if len(sys.argv) > 1 else detect_hailo_arch()
    if not arch:
        print("ERROR: Could not detect Hailo architecture. "
              "Pass architecture as argument: python download_models.py hailo8")
        sys.exit(1)
    print(f"Detected architecture: {arch}")
    download_models(arch)
