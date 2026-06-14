"""Tests for the vampire_mirror hailovampire_overlay GStreamer element.

The element is app-specific and lives with this app under postprocess/ (it was
moved out of the shared/official postprocess). These tests verify the build is
self-contained and, when the toolchain/element is available, that it compiles
and registers as a GStreamer plugin. Build/inspect tests skip gracefully when
the dev toolchain or installed element is absent (e.g. CI without tappas-core).
"""
import os
import shutil
import subprocess

import pytest

POSTPROCESS_DIR = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "postprocess")
)
SOURCES = [
    "gsthailovampire_overlay.cpp",
    "gsthailovampire_overlay.hpp",
    "vampire_draw.cpp",
    "vampire_draw.hpp",
    "bg_shm_reader.hpp",
    "meson.build",
    "build.sh",
]


def test_postprocess_is_self_contained():
    """All sources + build files live with the app, not in shared postprocess."""
    for f in SOURCES:
        assert os.path.isfile(os.path.join(POSTPROCESS_DIR, f)), f"missing {f}"


def test_not_in_shared_postprocess():
    """The element must no longer live in the official/shared postprocess tree."""
    repo_root = os.path.normpath(os.path.join(POSTPROCESS_DIR, "..", "..", "..", "..", ".."))
    stale = os.path.join(repo_root, "hailo_apps", "postprocess", "cpp", "vampire_overlay")
    assert not os.path.isdir(stale), f"vampire_overlay still present at {stale}"


def test_meson_declares_element_and_install_dir():
    with open(os.path.join(POSTPROCESS_DIR, "meson.build")) as fh:
        meson = fh.read()
    assert "gsthailovampire_overlay" in meson
    assert '-DPACKAGE="hailovampire_overlay"' in meson
    assert "pluginsdir" in meson  # installs into the GStreamer plugin dir


@pytest.mark.skipif(
    shutil.which("meson") is None or shutil.which("pkg-config") is None,
    reason="meson/pkg-config not available",
)
def test_builds_with_meson(tmp_path):
    """The element compiles standalone (no shared-postprocess dependency)."""
    have_tappas = subprocess.run(
        ["pkg-config", "--exists", "hailo-tappas-core"]
    ).returncode == 0 or subprocess.run(
        ["pkg-config", "--exists", "hailo_tappas"]
    ).returncode == 0
    if not have_tappas:
        pytest.skip("tappas-core dev package not installed")
    build_dir = tmp_path / "build"
    setup = subprocess.run(
        ["meson", "setup", str(build_dir), POSTPROCESS_DIR],
        capture_output=True, text=True,
    )
    assert setup.returncode == 0, setup.stderr
    compile_ = subprocess.run(
        ["meson", "compile", "-C", str(build_dir)],
        capture_output=True, text=True,
    )
    assert compile_.returncode == 0, compile_.stderr
    assert (build_dir / "libgsthailovampire_overlay.so").exists()


@pytest.mark.skipif(
    shutil.which("gst-inspect-1.0") is None,
    reason="gst-inspect-1.0 not available",
)
def test_element_registers_if_installed():
    """If the element is installed, gst-inspect must recognize it."""
    res = subprocess.run(
        ["gst-inspect-1.0", "hailovampire_overlay"],
        capture_output=True, text=True,
    )
    if res.returncode != 0:
        pytest.skip("hailovampire_overlay not installed in this environment")
    assert "hailovampire_overlay" in res.stdout
