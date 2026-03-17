# Aerial Object Counter

Count and classify objects in aerial/drone images using oriented (rotated) bounding boxes. Built on the YOLO11s-OBB model, this app detects objects at arbitrary angles and produces both annotated images and a JSON count summary per class per image.

## Prerequisites

- Hailo-8 accelerator (also works on Hailo-8L and Hailo-10H)
- YOLO11s-OBB model HEF (downloaded via `hailo-download-resources`)
- DOTA labels file (included in `local_resources/dota.txt`)

## How to Run

```bash
# Process a directory of aerial images
python community/apps/standalone_apps/aerial_object_counter/aerial_object_counter.py \
    --input /path/to/drone/images/ \
    --no-display

# With custom score threshold and JSON output path
python community/apps/standalone_apps/aerial_object_counter/aerial_object_counter.py \
    --input /path/to/drone/images/ \
    --score-threshold 0.4 \
    --json-output results/counts.json \
    --no-display

# With display (for debugging)
python community/apps/standalone_apps/aerial_object_counter/aerial_object_counter.py \
    --input /path/to/drone/images/
```

## Output

1. **Annotated images** in the output directory with:
   - Rotated bounding boxes colored by class
   - Class labels and confidence scores
   - Count summary overlay in the top-left corner

2. **JSON summary** (`count_summary.json`) with:
   - Total images processed
   - Global object count and per-class counts
   - Per-image breakdown

Example JSON output:
```json
{
  "total_images": 10,
  "total_objects": 147,
  "global_counts_per_class": {
    "vehicle": 89,
    "ship": 32,
    "plane": 26
  },
  "per_image": [
    {
      "image": "image_0001.jpg",
      "total_objects": 15,
      "counts_per_class": {"vehicle": 12, "ship": 3}
    }
  ]
}
```

## Architecture

```
Input Images --> Letterbox Preprocess --> YOLO11s-OBB (Hailo) --> OBB Postprocess --> Count & Annotate --> Output
     |                                                                                      |
     |                                                                                      v
     |                                                                              JSON Summary
     v
  3-Thread Pipeline: [Preprocess] -> [Async Inference] -> [Counting Visualizer]
```

## DOTA Labels (15 classes)

plane, ship, storage-tank, baseball-diamond, tennis-court, basketball-court,
ground-track-field, harbor, bridge, large-vehicle, small-vehicle,
helicopter, roundabout, soccer-ball-field, swimming-pool

## Customization

- **Custom labels:** Use `--labels <path>` for non-DOTA datasets
- **Score threshold:** Use `--score-threshold <float>` to adjust sensitivity
- **Batch size:** Use `--batch-size <int>` for throughput tuning
- **Custom model:** Provide `--hef-path <path>` for a different OBB model (requires matching config)
