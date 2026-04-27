"""Tier-1 install smoke tests for the community/drone-follow port.

These tests do NOT require a Hailo device, a flight controller, or a camera.
They verify that:
  1. The drone_follow package imports cleanly.
  2. The follow_api submodules load (controller config, types).
  3. The drone-follow console script is on PATH and `--help` exits 0.

The console-script test uses shutil.which to find the entry point installed
by `pip install -e .`. We don't use `sys.executable -m drone_follow...` because
pytest may be invoked under a different interpreter than the venv that owns
drone-follow (e.g. a user-local pytest in ~/.local/bin running under system
python while the venv was activated only for PATH resolution).
"""
import os
import shutil
import subprocess
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
    drone_follow_bin = shutil.which("drone-follow")
    assert drone_follow_bin, (
        "drone-follow console script not on PATH. Activate the parent venv "
        "(`source <hailo-apps-infra>/setup_env.sh`) and re-run."
    )
    proc = subprocess.run(
        [drone_follow_bin, "--help"],
        capture_output=True,
        timeout=30,
        check=False,
        env={**os.environ},
    )
    assert proc.returncode == 0, (
        f"`{drone_follow_bin} --help` exited {proc.returncode}\n"
        f"stdout:\n{proc.stdout.decode(errors='replace')}\n"
        f"stderr:\n{proc.stderr.decode(errors='replace')}"
    )
    assert b"--input" in proc.stdout or b"--input" in proc.stderr
