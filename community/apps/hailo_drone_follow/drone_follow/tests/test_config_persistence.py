"""Tests for ControllerConfig save / live-load round-trip.

Covers:
- save_json → from_json preserves every serialisable field.
- load_from_file mutates the target ControllerConfig in place (callers hold
  the reference) and reports which fields changed.
- load_from_file raises on validation failure and rolls back cleanly.
- Missing file raises FileNotFoundError.
- DEFAULT_CONFIG_PATH points inside the repo root (not /usr, not the schema).
"""

import json
import os
import tempfile

import pytest

from drone_follow.follow_api.config import ControllerConfig, DEFAULT_CONFIG_PATH


def test_default_config_path_in_repo_root():
    """Default save path lives at <repo_root>/df_config.json, not under /usr."""
    assert DEFAULT_CONFIG_PATH.endswith("/df_config.json")
    assert "/usr/" not in DEFAULT_CONFIG_PATH
    # Parent must be the repo root — where df_params.json also lives.
    parent = os.path.dirname(DEFAULT_CONFIG_PATH)
    assert os.path.isfile(os.path.join(parent, "df_params.json")), \
        f"df_params.json not found next to df_config.json at {parent}"


def test_save_roundtrip_preserves_all_fields(tmp_path):
    """save_json + from_json restores every field identically."""
    cfg = ControllerConfig(
        kp_yaw=7.5, kp_forward=2.3, max_forward=1.8,
        target_bbox_height=0.42, auto_select=False, max_forward_accel=0.9,
        yaw_only=False,
    )
    path = str(tmp_path / "df_config.json")
    cfg.save_json(path)

    loaded = ControllerConfig.from_json(path)
    assert loaded.kp_yaw == 7.5
    assert loaded.kp_forward == 2.3
    assert loaded.max_forward == 1.8
    assert loaded.target_bbox_height == 0.42
    assert loaded.auto_select is False
    assert loaded.max_forward_accel == 0.9
    assert loaded.yaw_only is False


def test_load_from_file_mutates_in_place(tmp_path):
    """load_from_file updates the same object; callers keep their reference valid."""
    cfg = ControllerConfig(kp_yaw=1.0, max_forward_accel=1.5)
    original_id = id(cfg)

    path = str(tmp_path / "df_config.json")
    snapshot = ControllerConfig(kp_yaw=9.9, max_forward_accel=2.7)
    snapshot.save_json(path)

    changed = cfg.load_from_file(path)
    assert id(cfg) == original_id, "reference must not change"
    assert cfg.kp_yaw == 9.9
    assert cfg.max_forward_accel == 2.7
    assert set(changed) >= {"kp_yaw", "max_forward_accel"}


def test_load_from_file_reports_only_changed(tmp_path):
    """Fields identical between memory and file are not in the returned list."""
    cfg = ControllerConfig(kp_yaw=5.0, kp_forward=1.5)
    path = str(tmp_path / "df_config.json")
    # Only kp_yaw differs on disk
    disk = ControllerConfig(kp_yaw=7.0, kp_forward=1.5)
    disk.save_json(path)

    changed = cfg.load_from_file(path)
    assert "kp_yaw" in changed
    assert "kp_forward" not in changed


def test_load_from_file_rolls_back_on_validation_error(tmp_path):
    """If the loaded values fail validate(), previous values are restored."""
    cfg = ControllerConfig(min_altitude=2.0, max_altitude=20.0)
    path = str(tmp_path / "df_config.json")
    # Write an invalid combo directly — min >= max trips validate()
    with open(path, "w") as f:
        json.dump({"min_altitude": 15.0, "max_altitude": 5.0}, f)

    with pytest.raises(ValueError):
        cfg.load_from_file(path)
    # Roll-back: values unchanged
    assert cfg.min_altitude == 2.0
    assert cfg.max_altitude == 20.0


def test_load_from_file_missing():
    cfg = ControllerConfig()
    with pytest.raises(FileNotFoundError):
        cfg.load_from_file("/nonexistent/path/df_config.json")


def test_load_from_file_ignores_unknown_keys(tmp_path):
    """Unknown keys in the file are silently ignored (no AttributeError)."""
    cfg = ControllerConfig(kp_yaw=1.0)
    path = str(tmp_path / "df_config.json")
    with open(path, "w") as f:
        json.dump({"kp_yaw": 4.0, "not_a_real_field": 99}, f)
    changed = cfg.load_from_file(path)
    assert cfg.kp_yaw == 4.0
    assert "not_a_real_field" not in changed
    assert not hasattr(cfg, "not_a_real_field")
