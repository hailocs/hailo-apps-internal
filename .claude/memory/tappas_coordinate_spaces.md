# TAPPAS Coordinate Spaces & scaling_bbox

## The Problem
When using `INFERENCE_PIPELINE_WRAPPER`, the wrapper's `hailoaggregator` sets a
`scaling_bbox` on the ROI to record the letterbox/scale transform used for inference.
This scaling_bbox is **non-identity** for non-square frames (e.g., 16:9 → square model).

### Example: 1280x720 frame → 192x192 palm model (letterbox)
```
scaling_bbox: xmin=0.0, ymin=-0.3889, w=1.0, h=1.7778
```
- h = 16/9 = 1.7778 (Y stretch factor)
- ymin = -(16/9 - 1)/2 = -0.3889 (Y offset for letterbox centering)

## HailoROI scaling_bbox API
- `set_scaling_bbox(bbox)` — **ACCUMULATES** (composes with existing), NOT a simple setter!
  - `new_xmin = old_xmin * bbox.width + bbox.xmin`
  - `new_ymin = old_ymin * bbox.height + bbox.ymin`
  - Calling with identity (0,0,1,1) is a no-op
- `clear_scaling_bbox()` — resets to identity (0,0,1,1)
- `get_scaling_bbox()` — returns current scaling_bbox
- Multiple INFERENCE_PIPELINE_WRAPPERs in series compound their scaling_bboxes

## hailooverlay Rendering Asymmetry (BUG/FEATURE)
**Detection bbox** rendering in `get_rect()`:
```cpp
HailoBBox roi_bbox = create_flattened_bbox(roi->get_bbox(), roi->get_scaling_bbox());
screen_x = (det.xmin * roi_bbox.width + roi_bbox.xmin) * frame_w;
screen_y = (det.ymin * roi_bbox.height + roi_bbox.ymin) * frame_h;
```
→ Detection bbox IS transformed through scaling_bbox

**Landmark** rendering in `draw_landmarks()`:
```cpp
HailoBBox bbox = roi->get_bbox();  // roi = parent detection, NO scaling_bbox
screen_x = (pt.x * bbox.width + bbox.xmin) * frame_w;
screen_y = (pt.y * bbox.height + bbox.ymin) * frame_h;
```
→ Landmarks are NOT transformed through scaling_bbox

**Result**: If detections are in letterbox-model space with a non-identity scaling_bbox,
the bbox renders correctly but landmarks render incorrectly (or vice versa, depending
on what coordinate space they're in).

## Fix: Clear scaling_bbox When Changing Coordinate Spaces
If a hailofilter creates new detections in **frame-absolute** normalized coords
(not in the model's letterbox space), it must clear the scaling_bbox:
```cpp
roi->clear_scaling_bbox();
```
This was done in `gesture_classification.cpp` after removing palm detections (which
are in letterbox space) and creating tight hand detections (in frame-absolute space).

## How hailocropper Uses scaling_bbox
The hailocropper **does** use the scaling_bbox to map detection bbox coords to actual
pixel positions when extracting crops. So detections in letterbox-model space with
the correct scaling_bbox will produce correctly-positioned crops.

## Implications for Multi-Wrapper Pipelines
In `pose_hand_detection.py`, two wrappers (pose + palm) compound their scaling_bboxes.
If both use square models on 16:9 input, the composed scaling_bbox has h ≈ 3.16.
When creating hand detections in frame-absolute coords downstream, must account for
or clear this accumulated scaling.

## Detection Coordinate Spaces Summary
| Stage | Coord Space | scaling_bbox |
|---|---|---|
| After INFERENCE_PIPELINE_WRAPPER | model letterbox space | non-identity (letterbox transform) |
| After hailocropper + palm_croppers | hand det: frame-absolute* | inherited from wrapper |
| After gesture_classification | hand det: frame-absolute | cleared to identity |

*palm_croppers computes in pixel space from `image->width()/height()` and normalizes
back to frame dimensions. The palm detection inputs it reads are in letterbox space,
but the pixel coords derived from `frame_w/h` effectively create frame-absolute outputs.
