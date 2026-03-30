# Toolset: YOLO COCO Classes Reference

> Standard 80-class COCO label set used by all YOLO models in the Hailo Model Zoo.
> This is the default label mapping for YOLOv5, YOLOv8, YOLOv10, YOLOv11, and YOLOX models.

## Class List (80 classes, 0-indexed)

| ID | Class | ID | Class | ID | Class | ID | Class |
|---|---|---|---|---|---|---|---|
| 0 | person | 20 | elephant | 40 | wine glass | 60 | dining table |
| 1 | bicycle | 21 | bear | 41 | cup | 61 | toilet |
| 2 | car | 22 | zebra | 42 | fork | 62 | tv |
| 3 | motorcycle | 23 | giraffe | 43 | knife | 63 | laptop |
| 4 | airplane | 24 | backpack | 44 | spoon | 64 | mouse |
| 5 | bus | 25 | umbrella | 45 | bowl | 65 | remote |
| 6 | train | 26 | handbag | 46 | banana | 66 | keyboard |
| 7 | truck | 27 | tie | 47 | apple | 67 | cell phone |
| 8 | boat | 28 | suitcase | 48 | sandwich | 68 | microwave |
| 9 | traffic light | 29 | frisbee | 49 | orange | 69 | oven |
| 10 | fire hydrant | 30 | skis | 50 | broccoli | 70 | toaster |
| 11 | stop sign | 31 | snowboard | 51 | carrot | 71 | sink |
| 12 | parking meter | 32 | sports ball | 52 | hot dog | 72 | refrigerator |
| 13 | bench | 33 | kite | 53 | pizza | 73 | book |
| 14 | bird | 34 | baseball bat | 54 | donut | 74 | clock |
| 15 | cat | 35 | baseball glove | 55 | cake | 75 | vase |
| 16 | dog | 36 | skateboard | 56 | chair | 76 | scissors |
| 17 | horse | 37 | surfboard | 57 | couch | 77 | teddy bear |
| 18 | sheep | 38 | tennis racket | 58 | potted plant | 78 | hair drier |
| 19 | cow | 39 | bottle | 59 | bed | 79 | toothbrush |

## Label File Location

The label file is at `local_resources/coco.txt` — one class name per line, 80 lines total.

## Usage in Pipeline Apps

When building detection pipelines with YOLO models, the postprocess uses COCO labels:

```python
# Loading labels
COCO_LABELS_PATH = os.path.join(os.path.dirname(__file__), "../../../../local_resources/coco.txt")
with open(COCO_LABELS_PATH, "r") as f:
    labels = [line.strip() for line in f.readlines()]

# Accessing by detection class ID
class_id = detection.get_class_id()
label = labels[class_id]  # e.g., "person", "car", "dog"
```

## Filtering by Class

Common pattern — filter detections by class name:

```python
# Filter for people only
PERSON_CLASS_ID = 0
people = [d for d in detections if d.get_class_id() == PERSON_CLASS_ID]

# Filter for vehicles
VEHICLE_IDS = {1, 2, 3, 5, 6, 7}  # bicycle, car, motorcycle, bus, train, truck
vehicles = [d for d in detections if d.get_class_id() in VEHICLE_IDS]

# Filter for animals
ANIMAL_IDS = {14, 15, 16, 17, 18, 19, 20, 21, 22, 23}  # bird through giraffe
animals = [d for d in detections if d.get_class_id() in ANIMAL_IDS]
```

## Common Class Groupings

| Group | Class IDs | Classes |
|-------|-----------|---------|
| People | 0 | person |
| Vehicles | 1-8 | bicycle, car, motorcycle, airplane, bus, train, truck, boat |
| Animals | 14-23 | bird, cat, dog, horse, sheep, cow, elephant, bear, zebra, giraffe |
| Food | 46-55 | banana, apple, sandwich, orange, broccoli, carrot, hot dog, pizza, donut, cake |
| Furniture | 56-60 | chair, couch, potted plant, bed, dining table |
| Electronics | 62-67 | tv, laptop, mouse, remote, keyboard, cell phone |
| Kitchen | 39-45, 68-72 | bottle, wine glass, cup, fork, knife, spoon, bowl, microwave, oven, toaster, sink, refrigerator |

## Models Using COCO Labels

All default YOLO models in the Hailo Model Zoo use this exact 80-class COCO set:
- `yolov5m_wo_spp` / `yolov5s`
- `yolov8s` / `yolov8m` / `yolov8n`
- `yolov10b` / `yolov10s`
- `yolov11s` / `yolov11n`
- `yolox_s_leaky`

**Exception**: Custom-trained models (e.g., `hailo_yolov8n_4_classes_vga`) use different label sets — check the model's documentation.
