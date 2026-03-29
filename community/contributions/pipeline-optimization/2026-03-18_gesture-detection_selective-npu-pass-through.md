---
title: "Selective NPU stage toggling via hailonet pass-through for multi-model pipelines"
category: pipeline-optimization
source_agent: interactive
contributor: "Gilad Nahor"
date: "2026-03-18"
hailo_arch: hailo8l
app: gesture_detection
tags: [pass-through, hailonet, hailofilter, multi-model, on-demand-inference, npu-load]
reproducibility: observed
---

## Summary

In multi-model GStreamer pipelines (e.g., person detection → palm detection → hand landmarks), you can selectively enable/disable individual NPU inference stages at runtime using the `pass-through` property on `hailonet` and `hailofilter` elements. This avoids rebuilding the pipeline while dramatically reducing NPU load when downstream stages aren't needed.

## Context

The gesture detection pipeline chains three NPU models: YOLOv8n (person/face tiling) → palm_detection_lite → hand_landmark_lite. Hand landmark inference is the most expensive downstream stage, running on every detected palm in every frame — even when no one is actively controlling the drone. On Hailo-8L, this unnecessary inference competes for NPU scheduling time with the upstream detection models.

## Finding

GStreamer `hailonet` elements support a `pass-through` property that, when set to `True`, causes the element to forward buffers without running NPU inference. Similarly, `hailofilter` elements (used for C++ postprocess) support the same property. By toggling these at runtime from Python, you can create a state machine where expensive downstream stages only run when their output is actually needed.

Key detail: when disabling a model stage, you must also disable any downstream `hailofilter` postprocess that would clean up intermediate metadata. For example, the `gesture_classification` filter removes raw palm detections — if hand landmarks are off but gesture classification is still active, the palm bounding boxes needed for tracking get removed before reaching the Python callback.

## Solution

Define groups of pipeline elements that must be toggled together:

```python
# In your GStreamerApp subclass:

def enable_hand_landmarks(self):
    """Enable hand landmark inference (after lock-on)."""
    for name in ("hand_landmark_hailonet", "gesture_classification"):
        el = self.pipeline.get_by_name(name)
        if el is not None:
            el.set_property("pass-through", False)

def disable_hand_landmarks(self):
    """Disable hand landmark inference (saves NPU compute)."""
    for name in ("hand_landmark_hailonet", "gesture_classification"):
        el = self.pipeline.get_by_name(name)
        if el is not None:
            el.set_property("pass-through", True)
```

Use a state machine to control when stages are active:

| State | Upstream (palm detection) | Downstream (hand landmarks + postprocess) |
|-------|--------------------------|-------------------------------------------|
| Idle / follow mode | pass-through | pass-through |
| Gesture mode, waiting for wave | **active** | pass-through |
| Gesture mode, palm locked | **active** | **active** |

Important constraints:
- Only toggle pass-through after the pipeline reaches PLAYING state — toggling during preroll can cause deadlocks
- The `hailocropper` and `hailoaggregator` elements (crop/merge stages) still run in all states — they're lightweight and don't need toggling
- When a `hailonet` is in pass-through, buffers flow through unchanged — any metadata from upstream stages survives

## Results

| Metric | Before (always-on) | After (on-demand) | Change |
|--------|--------------------|--------------------|--------|
| Hand landmark inference | Every frame, every palm | Only when locked on one palm | Eliminated when not needed |
| NPU scheduling contention | 3 models competing | 2 models (idle) or 3 (active) | Reduced in idle/waiting states |
| Palm tracking | Not possible (metadata cleaned) | Works via raw palm bboxes | Enabled by disabling postprocess filter |

## Applicability

This pattern applies to any multi-model Hailo pipeline where:
- Downstream models are conditionally needed (e.g., only after a trigger event)
- You want to reduce NPU load without rebuilding the GStreamer pipeline
- Intermediate metadata from upstream stages is useful on its own (e.g., palm bboxes for tracking without full hand landmarks)

Look for pipelines with chained `hailonet` elements where the downstream model's output isn't always consumed. Common examples: detection → classification, detection → landmark, detection → re-identification.
