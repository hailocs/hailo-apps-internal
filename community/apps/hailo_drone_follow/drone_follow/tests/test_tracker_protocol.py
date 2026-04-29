"""Tracker protocol contract tests — every adapter has the same `update` signature."""

import inspect

import pytest

from drone_follow.pipeline_adapter.byte_tracker import ByteTrackerAdapter
from drone_follow.pipeline_adapter.fast_tracker import FastTrackerAdapter
from drone_follow.pipeline_adapter.tracker import MetricsTracker


@pytest.mark.parametrize("cls", [ByteTrackerAdapter, FastTrackerAdapter, MetricsTracker])
def test_update_takes_only_detections(cls):
    """update() takes (self, detections) — no embeddings parameter.

    Embeddings was a vestige of an aborted ReID-feed-the-tracker experiment;
    nothing produces them and no inner tracker accepts them. The wrapper-level
    parameter was dead and is being dropped here. This test locks the
    post-cleanup signature so we don't grow it back accidentally.
    """
    params = list(inspect.signature(cls.update).parameters)
    # First param is `self`. Everything else must be only `detections`.
    assert params == ["self", "detections"], (
        f"{cls.__name__}.update has unexpected params {params}; "
        f"expected ['self', 'detections']"
    )
