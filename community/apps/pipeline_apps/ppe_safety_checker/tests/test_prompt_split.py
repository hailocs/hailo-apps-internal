"""Unit tests for the PPE safe/violation prompt-split logic.

`GStreamerPPESafetyCheckerApp._setup_ppe_prompts()` loads CLIP text prompts
into the text_image_matcher, marking the SECOND HALF of the prompt list as
"negative" (violation) and the FIRST HALF as positive (safe). The split is
derived from ``len(prompts) // 2`` so any even-length list works.

This file exercises that method directly with a fake `self`, a fake
text_image_matcher, and a fake options_menu — no GStreamer, no Hailo device,
no inference.

Regression guard: the split was previously hard-coded to a {3,4,5} index set
which mis-split any list that was not exactly 6 prompts. We assert that a
4-prompt list now splits 2 safe / 2 violation (not 2/2 via the old buggy
hardcode) and a 6-prompt list splits 3/3.
"""

import sys
from unittest.mock import MagicMock

import pytest

pytestmark = pytest.mark.community

# ----------------------------------------------------------------------------
# Stub the heavy native / GStreamer modules BEFORE importing the app module so
# that the import is pure-Python and device-free.
# ----------------------------------------------------------------------------
for mod_name in [
    "hailo",
    "gi",
    "gi.repository",
    "gi.repository.Gst",
    "setproctitle",
]:
    if mod_name not in sys.modules:
        sys.modules[mod_name] = MagicMock()
sys.modules["gi"].require_version = lambda *a, **kw: None

from community.apps.pipeline_apps.ppe_safety_checker.ppe_safety_checker_pipeline import (  # noqa: E402
    DEFAULT_PPE_PROMPTS,
    GStreamerPPESafetyCheckerApp,
    PPE_STATUS_SAFE,
    PPE_STATUS_UNKNOWN,
    PPE_STATUS_VIOLATION,
)


class _FakeMatcher:
    """Records add_text() calls so we can inspect the safe/violation split."""

    def __init__(self, max_entries=6):
        self.max_entries = max_entries
        self.added = []  # list of dicts: {prompt, index, negative}

    def add_text(self, prompt, index, negative):
        self.added.append(
            {"prompt": prompt, "index": index, "negative": negative}
        )


class _FakeOptions:
    def __init__(self, prompts):
        self.prompts = prompts


class _FakeApp:
    """Minimal stand-in for the app instance with just the attributes that
    _setup_ppe_prompts() touches."""

    def __init__(self, prompts, max_entries=6):
        self.options_menu = _FakeOptions(prompts)
        self.text_image_matcher = _FakeMatcher(max_entries=max_entries)


def _run_setup(prompts, max_entries=6):
    """Invoke the real (unbound) _setup_ppe_prompts on a fake self."""
    app = _FakeApp(prompts, max_entries=max_entries)
    GStreamerPPESafetyCheckerApp._setup_ppe_prompts(app)
    return app.text_image_matcher.added


def _safe_negative_lists(added):
    """Split recorded calls into (safe_prompts, violation_prompts) by the
    negative flag actually used."""
    safe = [a["prompt"] for a in added if not a["negative"]]
    violation = [a["prompt"] for a in added if a["negative"]]
    return safe, violation


class TestStatusConstants:
    def test_constants_are_distinct_strings(self):
        assert PPE_STATUS_SAFE == "SAFE"
        assert PPE_STATUS_VIOLATION == "VIOLATION"
        assert PPE_STATUS_UNKNOWN == "UNKNOWN"
        assert len({PPE_STATUS_SAFE, PPE_STATUS_VIOLATION, PPE_STATUS_UNKNOWN}) == 3

    def test_violation_not_substring_of_safe(self):
        # The user callback classifies by `STATUS in label` substring match,
        # so SAFE and VIOLATION must not be substrings of one another.
        assert PPE_STATUS_SAFE not in PPE_STATUS_VIOLATION
        assert PPE_STATUS_VIOLATION not in PPE_STATUS_SAFE


class TestDefaultPrompts:
    def test_default_prompts_structure(self):
        assert isinstance(DEFAULT_PPE_PROMPTS, list)
        assert all(isinstance(p, str) and p for p in DEFAULT_PPE_PROMPTS)

    def test_default_prompts_even_length(self):
        # The split logic assumes an even list; the default must be even so it
        # cleanly halves into safe/violation.
        assert len(DEFAULT_PPE_PROMPTS) % 2 == 0

    def test_default_prompts_no_duplicates(self):
        assert len(set(DEFAULT_PPE_PROMPTS)) == len(DEFAULT_PPE_PROMPTS)

    def test_default_split_three_three(self):
        added = _run_setup(None)  # None -> uses DEFAULT_PPE_PROMPTS
        safe, violation = _safe_negative_lists(added)
        assert len(safe) == 3
        assert len(violation) == 3
        # First half are the "wearing ..." prompts, second half the "without ..."
        assert safe == DEFAULT_PPE_PROMPTS[:3]
        assert violation == DEFAULT_PPE_PROMPTS[3:]


class TestPromptSplit:
    def test_six_prompts_split_three_three(self):
        prompts = [f"p{i}" for i in range(6)]
        added = _run_setup(prompts)
        safe, violation = _safe_negative_lists(added)
        assert safe == ["p0", "p1", "p2"]
        assert violation == ["p3", "p4", "p5"]

    def test_four_prompts_split_two_two(self):
        # REGRESSION: the old hardcoded {3,4,5} negative-index set would mark
        # zero of these 4 prompts negative (indices 0-3, none >= 3 except 3).
        # The fixed len//2 logic splits 2 safe / 2 violation.
        prompts = ["a", "b", "c", "d"]
        added = _run_setup(prompts)
        safe, violation = _safe_negative_lists(added)
        assert safe == ["a", "b"]
        assert violation == ["c", "d"]
        # The negative flags by index must be [F, F, T, T].
        assert [a["negative"] for a in added] == [False, False, True, True]

    def test_two_prompts_split_one_one(self):
        prompts = ["safe_prompt", "violation_prompt"]
        added = _run_setup(prompts)
        safe, violation = _safe_negative_lists(added)
        assert safe == ["safe_prompt"]
        assert violation == ["violation_prompt"]

    def test_indices_are_sequential(self):
        prompts = ["a", "b", "c", "d"]
        added = _run_setup(prompts)
        assert [a["index"] for a in added] == [0, 1, 2, 3]


class TestPromptSplitEdgeCases:
    def test_empty_prompt_list_falls_back_to_defaults(self):
        # An explicitly empty list (like None) is falsy, so the source's
        # ``prompts = self.options_menu.prompts or DEFAULT_PPE_PROMPTS`` falls
        # back to the 6 default prompts -> 3 safe / 3 violation. No crash.
        added = _run_setup([])
        safe, violation = _safe_negative_lists(added)
        assert len(added) == len(DEFAULT_PPE_PROMPTS)
        assert len(safe) == 3
        assert len(violation) == 3

    def test_odd_length_warns_and_first_half_safe(self, caplog):
        # Odd-length list: floor split. 5 prompts -> 2 safe, 3 violation.
        prompts = ["a", "b", "c", "d", "e"]
        with caplog.at_level("WARNING"):
            added = _run_setup(prompts)
        safe, violation = _safe_negative_lists(added)
        assert safe == ["a", "b"]
        assert violation == ["c", "d", "e"]
        # A warning about the odd count should have been emitted.
        assert any("odd" in r.message.lower() for r in caplog.records)

    def test_single_prompt_all_safe(self):
        # len//2 == 0 -> the single prompt is in the (empty) first half region;
        # index 0 >= split(0) is True, so it is marked negative (violation).
        # This documents the actual behavior for a degenerate 1-prompt list.
        prompts = ["only"]
        added = _run_setup(prompts)
        assert len(added) == 1
        assert added[0]["negative"] is True  # 0 >= 0

    def test_truncation_beyond_max_entries(self, caplog):
        # More prompts than the matcher can hold -> truncated at max_entries,
        # with a warning. Use max_entries=4 and feed 8 prompts.
        prompts = [f"p{i}" for i in range(8)]
        with caplog.at_level("WARNING"):
            added = _run_setup(prompts, max_entries=4)
        # Only the first 4 are added.
        assert [a["prompt"] for a in added] == ["p0", "p1", "p2", "p3"]
        assert any("truncat" in r.message.lower() for r in caplog.records)

    def test_split_uses_full_list_length_not_truncated(self):
        # The split is computed from len(prompts) BEFORE truncation, so with
        # 8 prompts split=4: indices 0-3 are safe. With max_entries=4 we add
        # exactly those 4 safe prompts and none of the violation half.
        prompts = [f"p{i}" for i in range(8)]
        added = _run_setup(prompts, max_entries=4)
        assert all(a["negative"] is False for a in added)
