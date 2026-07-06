"""Build/config-integrity checks for the depth_anything_cpp standalone app.

This app is implemented entirely in C++ (depth_anything.cpp + CMakeLists.txt +
build.sh + README.md). There is NO Python runtime logic to unit-test, so instead
of behavioral tests this suite validates that the build/config scaffolding is
intact and free of machine-specific paths. The checks are pure-Python and require
no C++ compiler, no HailoRT, and no Hailo device:

  - the expected source/build files exist;
  - CMakeLists.txt wires up HailoRT + OpenCV and defines the executable target;
  - build.sh parses as valid bash and runs the documented cmake/make build;
  - depth_anything.cpp references the expected HailoRT/inference symbols and the
    depth-output handling, and carries no hardcoded /home/<user> dev paths;
  - README documents the build + run steps and only points at the public
    download host.
"""

import re
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.community

APP_DIR = Path(__file__).resolve().parent.parent

CPP_SRC = APP_DIR / "depth_anything.cpp"
CMAKELISTS = APP_DIR / "CMakeLists.txt"
BUILD_SH = APP_DIR / "build.sh"
README = APP_DIR / "README.md"


# --------------------------------------------------------------------------- #
# File presence
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "rel_name",
    ["depth_anything.cpp", "CMakeLists.txt", "build.sh", "README.md"],
)
def test_expected_files_exist(rel_name):
    path = APP_DIR / rel_name
    assert path.is_file(), f"Missing expected app file: {rel_name}"
    assert path.stat().st_size > 0, f"App file is empty: {rel_name}"


# --------------------------------------------------------------------------- #
# CMakeLists.txt
# --------------------------------------------------------------------------- #
def test_cmakelists_requires_hailort():
    text = CMAKELISTS.read_text()
    assert re.search(r"find_package\(\s*HailoRT\b", text), (
        "CMakeLists.txt must require HailoRT via find_package(HailoRT ...)"
    )
    assert "HailoRT::libhailort" in text, (
        "CMakeLists.txt must link the HailoRT::libhailort target"
    )


def test_cmakelists_uses_opencv():
    text = CMAKELISTS.read_text()
    assert re.search(r"find_package\(\s*OpenCV\b", text), (
        "CMakeLists.txt must require OpenCV via find_package(OpenCV ...)"
    )
    assert "${OpenCV_LIBS}" in text, "CMakeLists.txt must link ${OpenCV_LIBS}"


def test_cmakelists_defines_executable_target():
    text = CMAKELISTS.read_text()
    assert "add_executable(" in text, "CMakeLists.txt must define an executable target"
    # The executable is built from the project's own .cpp source.
    assert "${PROJECT_NAME}.cpp" in text, (
        "CMakeLists.txt should build the executable from ${PROJECT_NAME}.cpp"
    )


# --------------------------------------------------------------------------- #
# build.sh
# --------------------------------------------------------------------------- #
def test_build_sh_parses_as_valid_bash():
    result = subprocess.run(
        ["bash", "-n", str(BUILD_SH)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"build.sh failed bash syntax check:\n{result.stderr}"
    )


def test_build_sh_runs_documented_build_steps():
    text = BUILD_SH.read_text()
    assert "cmake" in text, "build.sh must invoke cmake"
    # build.sh uses `cmake --build`; accept either that or a direct make call.
    assert ("cmake --build" in text) or ("make" in text), (
        "build.sh must build via `cmake --build` or `make`"
    )


# --------------------------------------------------------------------------- #
# depth_anything.cpp
# --------------------------------------------------------------------------- #
def test_cpp_has_main_entrypoint():
    text = CPP_SRC.read_text()
    assert re.search(r"int\s+main\s*\(", text), "depth_anything.cpp must define main()"


def test_cpp_references_hailort_inference_symbols():
    text = CPP_SRC.read_text()
    assert '#include "hailo/hailort.hpp"' in text, (
        "depth_anything.cpp must include the HailoRT C++ header"
    )
    # The app drives inference through the hailo-apps common HailoInfer wrapper.
    assert "HailoInfer" in text, "depth_anything.cpp must use HailoInfer"
    assert "run_inference_async" in text, (
        "depth_anything.cpp must launch async inference"
    )


def test_cpp_handles_depth_output():
    text = CPP_SRC.read_text()
    # The postprocess callback consumes the model output and produces a depth map.
    assert "postprocess_callback" in text, (
        "depth_anything.cpp must define a postprocess callback for the depth output"
    )
    assert "hailo_vstream_info_t" in text, (
        "depth_anything.cpp must read output vstream info"
    )
    # Single-channel depth feature handling + normalization to a viewable map.
    assert "shape.features" in text, (
        "depth_anything.cpp must inspect the output feature shape"
    )
    assert "applyColorMap" in text, (
        "depth_anything.cpp must colorize the normalized depth map"
    )


def test_cpp_has_no_hardcoded_user_home_paths():
    text = CPP_SRC.read_text()
    matches = re.findall(r"/home/[A-Za-z0-9._-]+", text)
    assert not matches, f"depth_anything.cpp contains hardcoded user-home paths: {matches}"


# --------------------------------------------------------------------------- #
# README.md
# --------------------------------------------------------------------------- #
def test_readme_documents_build_and_run():
    text = README.read_text().lower()
    assert "## build" in text, "README must document a Build section"
    assert "build.sh" in text, "README build steps must reference build.sh"
    assert ("## usage" in text) or ("## run" in text), (
        "README must document how to run the app"
    )
    # Run examples invoke the built binary with the -n/--net HEF argument.
    assert "depth_anything -n" in README.read_text(), (
        "README run examples must show invoking the binary with -n <hef>"
    )


def test_readme_uses_only_public_download_host():
    text = README.read_text()
    # If the README links any Hailo download host, it must be the public one.
    hailo_hosts = re.findall(r"https?://[^\s)\"']*hailo[^\s)\"']*", text, re.IGNORECASE)
    forbidden = [
        h
        for h in hailo_hosts
        if "dev-public.hailo.ai" not in h and "hailo.ai/developer-zone" not in h
    ]
    # Internal hosts (freenas, jenkins, internal IPs, *.hailo.local, dev-private) must never appear.
    assert "dev-public.hailo.ai" in text or not hailo_hosts, (
        f"README references non-public Hailo download hosts: {forbidden or hailo_hosts}"
    )
    assert not re.search(r"freenas|jenkins|dev-private|10\.\d+\.\d+\.\d+", text, re.IGNORECASE), (
        "README must not reference internal hosts/IPs"
    )
