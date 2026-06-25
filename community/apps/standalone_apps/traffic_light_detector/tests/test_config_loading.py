"""Pure-Python tests for traffic_light_detector config.json.

Verifies the config that ships next to the app module: it must be discoverable
relative to the package directory (the loader uses Path(__file__).parent), it
must carry the expected visualization keys, and the stale `tracker` / `color_map`
blocks that were removed must stay gone.
"""

import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.community

import community.apps.standalone_apps.traffic_light_detector as app_pkg

APP_DIR = Path(app_pkg.__file__).resolve().parent
CONFIG_PATH = APP_DIR / "config.json"


@pytest.fixture(scope="module")
def config():
    # Mirrors how traffic_light_detector.run_inference_pipeline resolves the
    # config: relative to the module directory, not the CWD.
    assert CONFIG_PATH.is_file(), f"config.json missing next to module: {CONFIG_PATH}"
    with open(CONFIG_PATH) as f:
        return json.load(f)


class TestConfigLocation:
    def test_config_sits_next_to_module(self):
        # Loader uses Path(__file__).resolve().parent / "config.json".
        assert CONFIG_PATH.parent == APP_DIR

    def test_config_is_valid_json_object(self, config):
        assert isinstance(config, dict)


class TestConfigKeys:
    def test_has_visualization_params(self, config):
        assert "visualization_params" in config
        assert isinstance(config["visualization_params"], dict)

    def test_expected_keys_present(self, config):
        vp = config["visualization_params"]
        for key in ("score_thres", "max_boxes_to_draw", "traffic_light_class_id"):
            assert key in vp, f"missing key: {key}"

    def test_score_thres_is_sensible_float(self, config):
        score = config["visualization_params"]["score_thres"]
        assert isinstance(score, (int, float))
        assert 0.0 <= score <= 1.0

    def test_traffic_light_class_id_is_coco_9(self, config):
        assert config["visualization_params"]["traffic_light_class_id"] == 9

    def test_max_boxes_positive_int(self, config):
        max_boxes = config["visualization_params"]["max_boxes_to_draw"]
        assert isinstance(max_boxes, int)
        assert max_boxes > 0


class TestRemovedBlocks:
    def test_no_tracker_block(self, config):
        assert "tracker" not in config
        assert "tracker" not in config.get("visualization_params", {})

    def test_no_color_map_block(self, config):
        assert "color_map" not in config
        assert "color_map" not in config.get("visualization_params", {})
