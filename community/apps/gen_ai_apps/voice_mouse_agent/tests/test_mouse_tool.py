"""Unit tests for voice_mouse_agent mouse_control tool dispatch.

Patches pyautogui to avoid real mouse moves and to make assertions on calls.
"""

import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

# Stub pyautogui before importing the tool module
_fake_pyautogui = MagicMock()
_fake_pyautogui.PAUSE = 0
_fake_pyautogui.FAILSAFE = True
_fake_pyautogui.FailSafeException = type("FailSafeException", (Exception,), {})
_fake_pyautogui.position.return_value = SimpleNamespace(x=100, y=100)
_fake_pyautogui.size.return_value = (1920, 1080)
sys.modules["pyautogui"] = _fake_pyautogui

from community.apps.gen_ai_apps.voice_mouse_agent.tools.mouse_control import (
    tool as mouse_tool,
)


@pytest.fixture(autouse=True)
def reset_pyautogui_mock():
    _fake_pyautogui.reset_mock()
    _fake_pyautogui.position.return_value = SimpleNamespace(x=100, y=100)
    _fake_pyautogui.size.return_value = (1920, 1080)
    yield


# ============================================================
# Action dispatch
# ============================================================


class TestActionDispatch:
    def test_unknown_action(self):
        result = mouse_tool.run({"action": "fly"})
        assert result["ok"] is False
        assert "unknown action" in result["error"].lower()

    def test_missing_action(self):
        result = mouse_tool.run({})
        assert result["ok"] is False
        assert "missing" in result["error"].lower()

    def test_empty_action_string(self):
        result = mouse_tool.run({"action": ""})
        assert result["ok"] is False


class TestMove:
    def test_move_up_negative_dy(self):
        result = mouse_tool.run({"action": "move", "direction": "up", "pixels": 50})
        assert result["ok"] is True
        _fake_pyautogui.moveRel.assert_called_once()
        dx, dy = _fake_pyautogui.moveRel.call_args[0][:2]
        assert dx == 0
        assert dy == -50

    def test_move_down_positive_dy(self):
        mouse_tool.run({"action": "move", "direction": "down", "pixels": 200})
        dx, dy = _fake_pyautogui.moveRel.call_args[0][:2]
        assert (dx, dy) == (0, 200)

    def test_move_left_negative_dx(self):
        mouse_tool.run({"action": "move", "direction": "left", "pixels": 75})
        dx, dy = _fake_pyautogui.moveRel.call_args[0][:2]
        assert (dx, dy) == (-75, 0)

    def test_move_right_positive_dx(self):
        mouse_tool.run({"action": "move", "direction": "right", "pixels": 150})
        dx, dy = _fake_pyautogui.moveRel.call_args[0][:2]
        assert (dx, dy) == (150, 0)

    def test_move_invalid_direction(self):
        result = mouse_tool.run({"action": "move", "direction": "northeast", "pixels": 10})
        assert result["ok"] is False
        _fake_pyautogui.moveRel.assert_not_called()

    def test_move_default_pixels(self):
        mouse_tool.run({"action": "move", "direction": "up"})
        dx, dy = _fake_pyautogui.moveRel.call_args[0][:2]
        # Default is 100 per the schema description
        assert (dx, dy) == (0, -100)


class TestMoveTo:
    def test_move_to_valid(self):
        result = mouse_tool.run({"action": "move_to", "x": 500, "y": 300})
        assert result["ok"] is True
        x, y = _fake_pyautogui.moveTo.call_args[0][:2]
        assert (x, y) == (500, 300)

    def test_move_to_clamped_to_screen(self):
        # Screen is 1920x1080; values beyond bounds clamp.
        mouse_tool.run({"action": "move_to", "x": 9999, "y": -50})
        x, y = _fake_pyautogui.moveTo.call_args[0][:2]
        assert x == 1919   # screen_w - 1
        assert y == 0      # clamped to 0

    def test_move_to_missing_coords(self):
        result = mouse_tool.run({"action": "move_to", "x": 100})
        assert result["ok"] is False
        _fake_pyautogui.moveTo.assert_not_called()


class TestClicks:
    def test_left_click_calls_click(self):
        result = mouse_tool.run({"action": "left_click"})
        assert result["ok"] is True
        _fake_pyautogui.click.assert_called_once()

    def test_right_click(self):
        result = mouse_tool.run({"action": "right_click"})
        assert result["ok"] is True
        _fake_pyautogui.rightClick.assert_called_once()

    def test_double_click(self):
        result = mouse_tool.run({"action": "double_click"})
        assert result["ok"] is True
        _fake_pyautogui.doubleClick.assert_called_once()


class TestScroll:
    def test_scroll_up_positive_amount(self):
        result = mouse_tool.run({"action": "scroll", "direction": "up", "amount": 5})
        assert result["ok"] is True
        _fake_pyautogui.scroll.assert_called_with(5)

    def test_scroll_down_negative_amount(self):
        result = mouse_tool.run({"action": "scroll", "direction": "down", "amount": 3})
        assert result["ok"] is True
        _fake_pyautogui.scroll.assert_called_with(-3)

    def test_scroll_invalid_direction(self):
        result = mouse_tool.run({"action": "scroll", "direction": "sideways", "amount": 3})
        assert result["ok"] is False

    def test_scroll_default_amount(self):
        mouse_tool.run({"action": "scroll", "direction": "up"})
        # Default amount is 3
        _fake_pyautogui.scroll.assert_called_with(3)


class TestDrag:
    def test_drag_right(self):
        result = mouse_tool.run({"action": "drag", "direction": "right", "pixels": 300})
        assert result["ok"] is True
        dx, dy = _fake_pyautogui.dragRel.call_args[0][:2]
        assert (dx, dy) == (300, 0)

    def test_drag_invalid_direction(self):
        result = mouse_tool.run({"action": "drag", "direction": "diagonal", "pixels": 100})
        assert result["ok"] is False
        _fake_pyautogui.dragRel.assert_not_called()


class TestFailsafe:
    def test_failsafe_caught(self):
        _fake_pyautogui.click.side_effect = _fake_pyautogui.FailSafeException("triggered")
        result = mouse_tool.run({"action": "left_click"})
        assert result["ok"] is False
        assert "failsafe" in result["error"].lower()

    def test_generic_error_caught(self):
        _fake_pyautogui.click.side_effect = RuntimeError("boom")
        result = mouse_tool.run({"action": "left_click"})
        assert result["ok"] is False
        assert "failed" in result["error"].lower() or "boom" in result["error"]


# ============================================================
# Module metadata
# ============================================================


class TestModuleMetadata:
    def test_tool_name(self):
        assert mouse_tool.name == "mouse_control"

    def test_tools_schema_has_one_function(self):
        assert len(mouse_tool.TOOLS_SCHEMA) == 1
        fn = mouse_tool.TOOLS_SCHEMA[0]
        assert fn["type"] == "function"
        assert fn["function"]["name"] == "mouse_control"

    def test_action_enum_complete(self):
        enum = mouse_tool.schema["properties"]["action"]["enum"]
        assert set(enum) == {
            "move", "move_to", "left_click", "right_click",
            "double_click", "scroll", "drag",
        }

    def test_required_includes_action(self):
        assert "action" in mouse_tool.schema["required"]


# ============================================================
# YAML config few-shot examples — make sure each example maps to a real action
# ============================================================


class TestFewShotConsistency:
    """The YAML config gives few-shot examples; each must reference a valid action."""

    def test_all_examples_use_known_actions(self):
        import yaml
        from pathlib import Path
        config_path = Path(__file__).resolve().parents[1] / "tools" / "config.yaml"
        if not config_path.exists():
            pytest.skip(f"missing {config_path}")
        try:
            cfg = yaml.safe_load(config_path.read_text())
        except Exception as e:
            pytest.skip(f"yaml parse failed: {e}")

        examples = cfg.get("few_shot_examples", [])
        valid_actions = set(mouse_tool.schema["properties"]["action"]["enum"])

        for ex in examples:
            args = ex["tool_call"]["arguments"]
            assert args["action"] in valid_actions, (
                f"few-shot example uses unknown action '{args['action']}'"
            )
