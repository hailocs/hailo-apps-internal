"""Tier-1 install smoke tests for the community/drone-follow port.

These tests do NOT require a Hailo device, a flight controller, or a camera.
They verify that:
  1. The drone_follow package imports cleanly.
  2. The drone-follow console script's --help runs and exits 0.
  3. The follow_api submodules load (controller config, types).
"""
import subprocess
import sys
from importlib import import_module


def test_drone_follow_package_imports():
    mod = import_module("drone_follow")
    assert mod is not None


def test_drone_follow_follow_api_imports():
    for name in (
        "drone_follow.follow_api.types",
        "drone_follow.follow_api.config",
        "drone_follow.follow_api.controller",
        "drone_follow.follow_api.state",
    ):
        m = import_module(name)
        assert m is not None, name


def test_drone_follow_help_exits_zero():
    proc = subprocess.run(
        [sys.executable, "-m", "drone_follow.drone_follow_app", "--help"],
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert proc.returncode == 0, (
        f"--help exited {proc.returncode}\nstdout:\n{proc.stdout.decode(errors='replace')}\n"
        f"stderr:\n{proc.stderr.decode(errors='replace')}"
    )
    assert b"--input" in proc.stdout or b"--input" in proc.stderr
