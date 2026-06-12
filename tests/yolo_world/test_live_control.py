"""Unit tests for the live-prompt command parser (replace / add / remove)."""

from hailo_apps.python.pipeline_apps.yolo_world.live_control import parse_command


class TestReplace:
    def test_comma_list_replaces_all(self):
        new, msg = parse_command("cat, dog, laptop", ["person"])
        assert new == ["cat", "dog", "laptop"]
        assert "replaced" in msg.lower()

    def test_single_word_replaces(self):
        new, msg = parse_command("bottle", ["person", "cat"])
        assert new == ["bottle"]

    def test_empty_is_noop(self):
        new, msg = parse_command("   ", ["person"])
        assert new is None


class TestAdd:
    def test_add_appends(self):
        new, msg = parse_command("+bottle", ["person", "cat"])
        assert new == ["person", "cat", "bottle"]
        assert "added" in msg.lower()

    def test_add_existing_is_noop(self):
        new, msg = parse_command("+cat", ["person", "cat"])
        assert new is None
        assert "already" in msg.lower()

    def test_add_empty_is_noop(self):
        new, msg = parse_command("+   ", ["person"])
        assert new is None


class TestRemove:
    def test_remove_drops_class(self):
        new, msg = parse_command("-dog", ["cat", "dog", "person"])
        assert new == ["cat", "person"]
        assert "removed" in msg.lower()

    def test_remove_absent_is_noop(self):
        new, msg = parse_command("-zebra", ["cat", "dog"])
        assert new is None
        assert "not active" in msg.lower()

    def test_cannot_remove_last_class(self):
        new, msg = parse_command("-cat", ["cat"])
        assert new is None
        assert "last class" in msg.lower()
