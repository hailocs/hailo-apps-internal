# YOLO World Community App — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a zero-shot object detection community app using YOLO World v2s on Hailo-10H with on-the-fly prompt updates.

**Architecture:** GStreamer handles video capture and display (SOURCE → USER_CALLBACK → DISPLAY with fakesink). Inference runs via HailoRT standalone API in the callback, supporting the dual-input HEF (image + text embeddings). Text embeddings are generated at startup using HuggingFace CLIP on CPU, cached to disk, and can be updated at runtime by modifying a prompts file.

**Tech Stack:** GStreamer (video I/O), HailoRT Python API (inference), HuggingFace transformers (text encoder), OpenCV (display overlay), numpy (tensor ops)

**Key Architectural Decision:** The `hailonet` GStreamer element does NOT support multi-input HEFs. YOLO World requires two inputs (image 640x640x3 + text embeddings 1x80x512). We use HailoRT's `InferModel` API directly — the same pattern used by the Whisper decoder (`whisper_pipeline.py:92-185`) which also has two input layers. The GStreamer pipeline provides video capture and display, while inference happens via HailoRT in the callback thread.

**Reference files:**
- Whisper multi-input pattern: `hailo_apps/python/standalone_apps/speech_recognition/whisper_pipeline.py`
- CLIP text encoding: `hailo_apps/python/pipeline_apps/clip/clip_text_utils.py`
- Detection pipeline template: `community/apps/pipeline_apps/line_crossing_counter/`
- HailoInfer wrapper: `hailo_apps/python/core/common/hailo_inference.py`
- HEF utils: `hailo_apps/python/core/common/hef_utils.py`

---

## File Structure

```
community/apps/pipeline_apps/yolo_world/
├── __init__.py                    # Empty
├── yolo_world.py                  # Entry point + app_callback + OpenCV overlay
├── yolo_world_pipeline.py         # GStreamerApp subclass (SOURCE → CALLBACK → DISPLAY)
├── yolo_world_inference.py        # HailoRT inference engine (dual-input, async)
├── text_embedding_manager.py      # CLIP text encoder + caching + file watcher
├── postprocess.py                 # YOLO World NMS + box decoding (numpy)
├── default_prompts.json           # COCO-80 class names
├── README.md                      # User documentation
└── CLAUDE.md                      # Developer notes
```

**Why `yolo_world_inference.py` is separate from the pipeline:** The inference engine manages VDevice, InferModel, bindings, and async jobs — a distinct responsibility from GStreamer pipeline construction. This mirrors how `whisper_pipeline.py` separates inference logic.

**Why `postprocess.py` exists:** Since we're NOT using `hailofilter` + NMS `.so` (that requires hailonet), we need Python-based postprocessing. The model zoo's `yolo_world.py` postprocess provides the reference. The postprocess is lightweight: reshape outputs, grid-decode boxes, run NMS — all numpy ops.

---

### Task 1: Project scaffold + default_prompts.json

**Files:**
- Create: `community/apps/pipeline_apps/yolo_world/__init__.py`
- Create: `community/apps/pipeline_apps/yolo_world/default_prompts.json`

- [ ] **Step 1: Create the directory and __init__.py**

```bash
mkdir -p community/apps/pipeline_apps/yolo_world
touch community/apps/pipeline_apps/yolo_world/__init__.py
```

- [ ] **Step 2: Create default_prompts.json with COCO-80 class names**

Write `community/apps/pipeline_apps/yolo_world/default_prompts.json`:
```json
[
    "person", "bicycle", "car", "motorcycle", "airplane",
    "bus", "train", "truck", "boat", "traffic light",
    "fire hydrant", "stop sign", "parking meter", "bench", "bird",
    "cat", "dog", "horse", "sheep", "cow",
    "elephant", "bear", "zebra", "giraffe", "backpack",
    "umbrella", "handbag", "tie", "suitcase", "frisbee",
    "skis", "snowboard", "sports ball", "kite", "baseball bat",
    "baseball glove", "skateboard", "surfboard", "tennis racket", "bottle",
    "wine glass", "cup", "fork", "knife", "spoon",
    "bowl", "banana", "apple", "sandwich", "orange",
    "broccoli", "carrot", "hot dog", "pizza", "donut",
    "cake", "chair", "couch", "potted plant", "bed",
    "dining table", "toilet", "tv", "laptop", "mouse",
    "remote", "keyboard", "cell phone", "microwave", "oven",
    "toaster", "sink", "refrigerator", "book", "clock",
    "vase", "scissors", "teddy bear", "hair drier", "toothbrush"
]
```

- [ ] **Step 3: Commit**

```bash
git add community/apps/pipeline_apps/yolo_world/__init__.py \
      community/apps/pipeline_apps/yolo_world/default_prompts.json
git commit -m "feat(yolo_world): scaffold project with COCO-80 default prompts"
```

---

### Task 2: Text Embedding Manager

**Files:**
- Create: `community/apps/pipeline_apps/yolo_world/text_embedding_manager.py`

This component generates CLIP text embeddings from class name prompts using HuggingFace `CLIPTextModelWithProjection`. It caches embeddings to JSON for fast reload, and supports runtime updates.

**Reference:** The Hailo model zoo (`create_coco_tfrecord_with_text_embeddings.py`) uses `CLIPTextModelWithProjection` from `openai/clip-vit-base-patch32`, tokenizes bare class names, and L2-normalizes the output `text_embeds`. We replicate this exactly.

- [ ] **Step 1: Write text_embedding_manager.py**

Write `community/apps/pipeline_apps/yolo_world/text_embedding_manager.py`:

```python
import json
import os
import threading
import time
from pathlib import Path

import numpy as np

from hailo_apps.python.core.common.hailo_logger import get_logger

logger = get_logger(__name__)

MAX_CLASSES = 80
EMBEDDING_DIM = 512
CLIP_MODEL_NAME = "openai/clip-vit-base-patch32"


class TextEmbeddingManager:
    """Manages CLIP text embeddings for YOLO World zero-shot detection.

    Generates embeddings from text prompts using HuggingFace CLIPTextModelWithProjection,
    caches them to disk, and supports runtime updates via file watching.
    """

    def __init__(self, prompts=None, prompts_file=None, embeddings_file=None,
                 watch=False, default_prompts_path=None):
        self._lock = threading.Lock()
        self._embeddings = None  # shape: (1, 80, 512) float32
        self._labels = []
        self._watch = watch
        self._watch_thread = None
        self._stop_event = threading.Event()
        self._prompts_file = prompts_file

        if default_prompts_path is None:
            default_prompts_path = str(Path(__file__).parent / "default_prompts.json")
        self._default_prompts_path = default_prompts_path

        if embeddings_file is None:
            embeddings_file = str(Path(__file__).parent / "embeddings.json")
        self._embeddings_file = embeddings_file

        # Resolve prompts and generate/load embeddings
        self._initialize(prompts, prompts_file)

        # Start file watcher if requested
        if watch and prompts_file:
            self._start_watcher()

    def _initialize(self, prompts, prompts_file):
        """Determine prompt source and load/generate embeddings."""
        if prompts:
            # CLI --prompts "cat,dog,person"
            prompt_list = [p.strip() for p in prompts.split(",")]
            logger.info("Using CLI prompts: %s", prompt_list)
            self._encode_and_cache(prompt_list)
        elif prompts_file:
            # --prompts-file my_classes.json
            prompt_list = self._load_prompts_file(prompts_file)
            logger.info("Using prompts from file: %s (%d classes)", prompts_file, len(prompt_list))
            self._encode_and_cache(prompt_list)
        elif os.path.isfile(self._embeddings_file):
            # Cached embeddings exist
            logger.info("Loading cached embeddings from %s", self._embeddings_file)
            self._load_cached()
        else:
            # Default COCO-80
            prompt_list = self._load_prompts_file(self._default_prompts_path)
            logger.info("Using default COCO-80 prompts (%d classes)", len(prompt_list))
            self._encode_and_cache(prompt_list)

    def _load_prompts_file(self, path):
        """Load a JSON array of class name strings."""
        with open(path, "r") as f:
            prompts = json.load(f)
        if not isinstance(prompts, list) or not all(isinstance(p, str) for p in prompts):
            raise ValueError(f"Prompts file must be a JSON array of strings: {path}")
        if len(prompts) > MAX_CLASSES:
            logger.warning("Truncating prompts to %d (max for YOLO World HEF)", MAX_CLASSES)
            prompts = prompts[:MAX_CLASSES]
        return prompts

    def _encode_and_cache(self, prompt_list):
        """Generate CLIP embeddings for prompts and cache to disk."""
        embeddings = self._generate_embeddings(prompt_list)
        self._set_embeddings(embeddings, prompt_list)
        self._save_cached(prompt_list, embeddings)

    @staticmethod
    def _generate_embeddings(prompt_list):
        """Run CLIP text encoder on CPU to produce L2-normalized embeddings.

        Returns ndarray of shape (N, 512) where N = len(prompt_list).
        """
        try:
            import torch
            from transformers import AutoTokenizer, CLIPTextModelWithProjection
        except ImportError:
            raise ImportError(
                "Text encoding requires 'transformers' and 'torch' packages. "
                "Install with: pip install transformers torch\n"
                "Alternatively, provide pre-cached embeddings via --embeddings-file"
            )

        logger.info("Loading CLIP text encoder: %s", CLIP_MODEL_NAME)
        tokenizer = AutoTokenizer.from_pretrained(CLIP_MODEL_NAME)
        model = CLIPTextModelWithProjection.from_pretrained(CLIP_MODEL_NAME)
        model.eval()

        logger.info("Encoding %d prompts...", len(prompt_list))
        with torch.no_grad():
            inputs = tokenizer(prompt_list, return_tensors="pt", padding=True)
            outputs = model(**inputs)
            text_embeds = outputs.text_embeds  # (N, 512)
            # L2 normalize — matches model zoo reference
            text_embeds = text_embeds / text_embeds.norm(p=2, dim=-1, keepdim=True)

        embeddings = text_embeds.cpu().numpy().astype(np.float32)
        logger.info("Generated embeddings shape: %s", embeddings.shape)
        return embeddings

    def _set_embeddings(self, embeddings, labels):
        """Assemble into (1, 80, 512) tensor and set atomically."""
        n = embeddings.shape[0]
        padded = np.zeros((1, MAX_CLASSES, EMBEDDING_DIM), dtype=np.float32)
        padded[0, :n, :] = embeddings
        with self._lock:
            self._embeddings = padded
            self._labels = list(labels)

    def _save_cached(self, labels, embeddings):
        """Cache embeddings + labels to JSON file."""
        data = {
            "labels": labels,
            "embeddings": embeddings.tolist(),
        }
        with open(self._embeddings_file, "w") as f:
            json.dump(data, f)
        logger.info("Cached embeddings to %s", self._embeddings_file)

    def _load_cached(self):
        """Load embeddings + labels from cached JSON file."""
        with open(self._embeddings_file, "r") as f:
            data = json.load(f)
        labels = data["labels"]
        embeddings = np.array(data["embeddings"], dtype=np.float32)
        self._set_embeddings(embeddings, labels)
        logger.info("Loaded %d cached embeddings", len(labels))

    def get_embeddings(self):
        """Return current (1, 80, 512) embedding tensor. Thread-safe."""
        return self._embeddings

    def get_labels(self):
        """Return current label list. Thread-safe."""
        with self._lock:
            return list(self._labels)

    def get_num_classes(self):
        """Return number of active classes (not padded)."""
        with self._lock:
            return len(self._labels)

    def update_prompts(self, prompt_list):
        """Re-encode prompts and swap embeddings atomically."""
        if len(prompt_list) > MAX_CLASSES:
            logger.warning("Truncating to %d classes", MAX_CLASSES)
            prompt_list = prompt_list[:MAX_CLASSES]
        logger.info("Updating prompts: %s", prompt_list)
        embeddings = self._generate_embeddings(prompt_list)
        self._set_embeddings(embeddings, prompt_list)
        self._save_cached(prompt_list, embeddings)
        logger.info("Prompts updated successfully")

    def _start_watcher(self):
        """Watch prompts file for modifications and reload."""
        self._watch_thread = threading.Thread(target=self._watch_loop, daemon=True)
        self._watch_thread.start()
        logger.info("Watching %s for changes", self._prompts_file)

    def _watch_loop(self):
        """Poll prompts file mtime every 2 seconds."""
        last_mtime = os.path.getmtime(self._prompts_file)
        while not self._stop_event.is_set():
            self._stop_event.wait(2.0)
            try:
                current_mtime = os.path.getmtime(self._prompts_file)
                if current_mtime != last_mtime:
                    last_mtime = current_mtime
                    logger.info("Prompts file changed, reloading...")
                    prompt_list = self._load_prompts_file(self._prompts_file)
                    self.update_prompts(prompt_list)
            except Exception as e:
                logger.error("Error watching prompts file: %s", e)

    def stop(self):
        """Stop the file watcher thread."""
        self._stop_event.set()
        if self._watch_thread:
            self._watch_thread.join(timeout=5)
```

- [ ] **Step 2: Verify the file is syntactically correct**

Run: `python -c "import ast; ast.parse(open('community/apps/pipeline_apps/yolo_world/text_embedding_manager.py').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add community/apps/pipeline_apps/yolo_world/text_embedding_manager.py
git commit -m "feat(yolo_world): add TextEmbeddingManager with CLIP encoding and file watcher"
```

---

### Task 3: YOLO World Postprocessing (numpy)

**Files:**
- Create: `community/apps/pipeline_apps/yolo_world/postprocess.py`

Since we bypass `hailofilter` / NMS `.so` (those require `hailonet`), we implement postprocessing in Python with numpy. Reference: `hailo_model_zoo/core/postprocessing/detection/yolo_world.py`.

**Key facts from model zoo research:**
- 6 output tensors: 3 cls (HxWx80) + 3 reg (HxWx4) at strides [8, 16, 32]
- Sigmoid is ON-DEVICE (already applied to cls outputs)
- Box regression outputs are 4 decoded distance values (DFL decoding is on-device)
- Grid-based box decoding: `center = (grid_idx + 0.5) * stride`, `box = center ± distance * stride`
- NMS: IoU=0.7, score_threshold configurable (default 0.3 for display)

- [ ] **Step 1: Write postprocess.py**

Write `community/apps/pipeline_apps/yolo_world/postprocess.py`:

```python
import numpy as np

from hailo_apps.python.core.common.hailo_logger import get_logger

logger = get_logger(__name__)

STRIDES = [8, 16, 32]
IMAGE_SIZE = 640


def postprocess(output_tensors, score_threshold=0.3, iou_threshold=0.7, num_classes=80):
    """Post-process YOLO World output tensors into detections.

    Args:
        output_tensors: dict mapping layer name to numpy array.
            Expected: 3 cls tensors (HxWx80) + 3 reg tensors (HxWx4).
            Cls outputs have sigmoid already applied on-device.
            Reg outputs are decoded distances (DFL done on-device).
        score_threshold: minimum confidence for a detection.
        iou_threshold: NMS IoU threshold.
        num_classes: number of active classes (for slicing padded outputs).

    Returns:
        list of dicts: [{"bbox": [x1,y1,x2,y2], "class_id": int, "score": float}, ...]
        Bounding boxes are normalized to [0, 1].
    """
    # Separate cls and reg tensors by shape
    cls_tensors = []
    reg_tensors = []
    for name in sorted(output_tensors.keys()):
        tensor = output_tensors[name]
        if len(tensor.shape) == 3:
            h, w, c = tensor.shape
        elif len(tensor.shape) == 4:
            # batch dim
            tensor = tensor[0]
            h, w, c = tensor.shape
        else:
            logger.warning("Unexpected tensor shape %s for %s", tensor.shape, name)
            continue

        if c == 80:
            cls_tensors.append(tensor)
        elif c == 4:
            reg_tensors.append(tensor)
        else:
            logger.warning("Unexpected channel count %d for %s", c, name)

    if len(cls_tensors) != 3 or len(reg_tensors) != 3:
        logger.error("Expected 3 cls + 3 reg tensors, got %d + %d", len(cls_tensors), len(reg_tensors))
        return []

    # Sort by spatial size (largest first = stride 8, then 16, then 32)
    cls_tensors.sort(key=lambda t: t.shape[0] * t.shape[1], reverse=True)
    reg_tensors.sort(key=lambda t: t.shape[0] * t.shape[1], reverse=True)

    all_boxes = []
    all_scores = []
    all_class_ids = []

    for scale_idx, (cls_map, reg_map, stride) in enumerate(zip(cls_tensors, reg_tensors, STRIDES)):
        h, w, _ = cls_map.shape

        # Create grid of center coordinates
        grid_y, grid_x = np.meshgrid(np.arange(h), np.arange(w), indexing="ij")
        center_x = (grid_x.astype(np.float32) + 0.5) * stride
        center_y = (grid_y.astype(np.float32) + 0.5) * stride

        # Decode boxes: reg_map contains [dist_left, dist_top, dist_right, dist_bottom]
        dist_left = reg_map[:, :, 0] * stride
        dist_top = reg_map[:, :, 1] * stride
        dist_right = reg_map[:, :, 2] * stride
        dist_bottom = reg_map[:, :, 3] * stride

        x1 = (center_x - dist_left) / IMAGE_SIZE
        y1 = (center_y - dist_top) / IMAGE_SIZE
        x2 = (center_x + dist_right) / IMAGE_SIZE
        y2 = (center_y + dist_bottom) / IMAGE_SIZE

        # Clip to [0, 1]
        x1 = np.clip(x1, 0.0, 1.0)
        y1 = np.clip(y1, 0.0, 1.0)
        x2 = np.clip(x2, 0.0, 1.0)
        y2 = np.clip(y2, 0.0, 1.0)

        # Flatten spatial dims
        boxes = np.stack([x1, y1, x2, y2], axis=-1).reshape(-1, 4)  # (H*W, 4)
        scores = cls_map[:, :, :num_classes].reshape(-1, num_classes)  # (H*W, num_classes)

        # Sigmoid already applied on-device — scores are probabilities

        # Find detections above threshold
        max_scores = scores.max(axis=1)
        mask = max_scores > score_threshold
        if not mask.any():
            continue

        filtered_boxes = boxes[mask]
        filtered_scores = scores[mask]
        filtered_class_ids = filtered_scores.argmax(axis=1)
        filtered_max_scores = filtered_scores.max(axis=1)

        all_boxes.append(filtered_boxes)
        all_scores.append(filtered_max_scores)
        all_class_ids.append(filtered_class_ids)

    if not all_boxes:
        return []

    all_boxes = np.concatenate(all_boxes, axis=0)
    all_scores = np.concatenate(all_scores, axis=0)
    all_class_ids = np.concatenate(all_class_ids, axis=0)

    # Per-class NMS
    detections = []
    for cls_id in np.unique(all_class_ids):
        cls_mask = all_class_ids == cls_id
        cls_boxes = all_boxes[cls_mask]
        cls_scores = all_scores[cls_mask]

        keep = _nms(cls_boxes, cls_scores, iou_threshold)
        for idx in keep:
            detections.append({
                "bbox": cls_boxes[idx].tolist(),
                "class_id": int(cls_id),
                "score": float(cls_scores[idx]),
            })

    # Sort by score descending
    detections.sort(key=lambda d: d["score"], reverse=True)
    return detections


def _nms(boxes, scores, iou_threshold):
    """Standard greedy NMS. Returns indices to keep."""
    if len(boxes) == 0:
        return []

    order = scores.argsort()[::-1]
    keep = []

    x1 = boxes[:, 0]
    y1 = boxes[:, 1]
    x2 = boxes[:, 2]
    y2 = boxes[:, 3]
    areas = (x2 - x1) * (y2 - y1)

    while len(order) > 0:
        i = order[0]
        keep.append(i)

        if len(order) == 1:
            break

        xx1 = np.maximum(x1[i], x1[order[1:]])
        yy1 = np.maximum(y1[i], y1[order[1:]])
        xx2 = np.minimum(x2[i], x2[order[1:]])
        yy2 = np.minimum(y2[i], y2[order[1:]])

        inter = np.maximum(0.0, xx2 - xx1) * np.maximum(0.0, yy2 - yy1)
        iou = inter / (areas[i] + areas[order[1:]] - inter + 1e-6)

        remaining = np.where(iou <= iou_threshold)[0]
        order = order[remaining + 1]

    return keep
```

- [ ] **Step 2: Verify syntax**

Run: `python -c "import ast; ast.parse(open('community/apps/pipeline_apps/yolo_world/postprocess.py').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add community/apps/pipeline_apps/yolo_world/postprocess.py
git commit -m "feat(yolo_world): add numpy-based YOLO World postprocessing with NMS"
```

---

### Task 4: HailoRT Inference Engine (dual-input)

**Files:**
- Create: `community/apps/pipeline_apps/yolo_world/yolo_world_inference.py`

This is the core component that runs the YOLO World HEF with two inputs. It follows the Whisper decoder pattern (`whisper_pipeline.py:92-185`) for multi-input HailoRT inference.

**Key pattern from Whisper:**
```python
# Set format types for each input by name
model.input(f"{name}/input_layer1").set_format_type(FormatType.FLOAT32)
model.input(f"{name}/input_layer2").set_format_type(FormatType.FLOAT32)
# Create bindings, set buffers for each input
bindings.input(f"{name}/input_layer1").set_buffer(image_data)
bindings.input(f"{name}/input_layer2").set_buffer(text_embeddings)
```

- [ ] **Step 1: Write yolo_world_inference.py**

Write `community/apps/pipeline_apps/yolo_world/yolo_world_inference.py`:

```python
import numpy as np
from hailo_platform import HEF, VDevice, FormatType, HailoSchedulingAlgorithm

from hailo_apps.python.core.common.defines import SHARED_VDEVICE_GROUP_ID
from hailo_apps.python.core.common.hailo_logger import get_logger

logger = get_logger(__name__)


class YoloWorldInference:
    """Runs YOLO World v2s inference on Hailo using the dual-input HEF.

    The HEF has two inputs:
      - input_layer1: image (1, 640, 640, 3) uint8
      - input_layer2: text embeddings (1, 80, 512) float32

    And 6 outputs:
      - 3 classification maps (HxWx80) at strides 8, 16, 32
      - 3 regression maps (HxWx4) at strides 8, 16, 32
    """

    def __init__(self, hef_path, text_embeddings):
        """Initialize inference engine.

        Args:
            hef_path: path to yolo_world_v2s.hef
            text_embeddings: numpy array (1, 80, 512) float32, L2-normalized
        """
        self._hef_path = hef_path
        self._text_embeddings = np.ascontiguousarray(text_embeddings, dtype=np.float32)

        # Introspect HEF to get layer names
        hef = HEF(hef_path)
        self._network_name = hef.get_network_group_names()[0]
        input_infos = hef.get_input_vstream_infos()
        output_infos = hef.get_output_vstream_infos()

        logger.info("HEF network: %s", self._network_name)
        logger.info("Inputs: %s", [(info.name, info.shape) for info in input_infos])
        logger.info("Outputs: %s", [(info.name, info.shape) for info in output_infos])

        # Identify input layers by shape
        self._image_input_name = None
        self._text_input_name = None
        for info in input_infos:
            shape = tuple(info.shape)
            if len(shape) == 4 and shape[-1] == 3:
                self._image_input_name = info.name
            elif len(shape) == 3 and shape[-1] == 512:
                self._text_input_name = info.name

        if not self._image_input_name or not self._text_input_name:
            raise ValueError(
                f"Could not identify input layers. Found: "
                f"{[(info.name, info.shape) for info in input_infos]}"
            )

        logger.info("Image input: %s", self._image_input_name)
        logger.info("Text input: %s", self._text_input_name)

        # Store output names and shapes
        self._output_names = [info.name for info in output_infos]
        self._output_shapes = {info.name: tuple(info.shape) for info in output_infos}

        # Create VDevice and configure model
        params = VDevice.create_params()
        params.group_id = SHARED_VDEVICE_GROUP_ID
        self._vdevice = VDevice(params)

        self._infer_model = self._vdevice.create_infer_model(hef_path)

        # Set format types for inputs
        self._infer_model.input(self._image_input_name).set_format_type(FormatType.UINT8)
        self._infer_model.input(self._text_input_name).set_format_type(FormatType.FLOAT32)

        # Set format type for all outputs to float32
        for name in self._output_names:
            self._infer_model.output(name).set_format_type(FormatType.FLOAT32)

        # Configure (enter context)
        self._config_ctx = self._infer_model.configure()
        self._configured_model = self._config_ctx.__enter__()

        # Pre-allocate output buffers
        self._output_buffers = {
            name: np.empty(self._infer_model.output(name).shape, dtype=np.float32)
            for name in self._output_names
        }

        logger.info("YOLO World inference engine initialized")

    def run(self, image):
        """Run inference on a single image frame.

        Args:
            image: numpy array (640, 640, 3) uint8 RGB

        Returns:
            dict mapping output layer name to numpy array
        """
        bindings = self._configured_model.create_bindings()

        # Set image input
        image_input = np.ascontiguousarray(image, dtype=np.uint8)
        if len(image_input.shape) == 3:
            image_input = np.expand_dims(image_input, axis=0)
        bindings.input(self._image_input_name).set_buffer(image_input)

        # Set text embeddings input
        bindings.input(self._text_input_name).set_buffer(self._text_embeddings)

        # Set output buffers
        for name, buf in self._output_buffers.items():
            bindings.output(name).set_buffer(buf)

        # Run synchronous inference
        self._configured_model.run([bindings], timeout_ms=10000)

        # Collect outputs
        outputs = {}
        for name in self._output_names:
            outputs[name] = bindings.output(name).get_buffer().copy()

        return outputs

    def update_text_embeddings(self, text_embeddings):
        """Update the text embeddings tensor for zero-shot class changes.

        Args:
            text_embeddings: numpy array (1, 80, 512) float32, L2-normalized
        """
        self._text_embeddings = np.ascontiguousarray(text_embeddings, dtype=np.float32)
        logger.info("Text embeddings updated")

    def close(self):
        """Release HailoRT resources."""
        if self._config_ctx:
            self._config_ctx.__exit__(None, None, None)
        logger.info("Inference engine closed")
```

- [ ] **Step 2: Verify syntax**

Run: `python -c "import ast; ast.parse(open('community/apps/pipeline_apps/yolo_world/yolo_world_inference.py').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add community/apps/pipeline_apps/yolo_world/yolo_world_inference.py
git commit -m "feat(yolo_world): add HailoRT dual-input inference engine"
```

---

### Task 5: GStreamer Pipeline

**Files:**
- Create: `community/apps/pipeline_apps/yolo_world/yolo_world_pipeline.py`

The pipeline is simple: SOURCE → USER_CALLBACK → DISPLAY (fakesink). All inference happens via HailoRT in the callback, not via `hailonet`. This is because `hailonet` cannot handle the dual-input HEF.

- [ ] **Step 1: Write yolo_world_pipeline.py**

Write `community/apps/pipeline_apps/yolo_world/yolo_world_pipeline.py`:

```python
from pathlib import Path

import setproctitle

from hailo_apps.python.core.common.core import (
    get_pipeline_parser,
    resolve_hef_path,
)
from hailo_apps.python.core.common.hailo_logger import get_logger
from hailo_apps.python.core.gstreamer.gstreamer_app import (
    GStreamerApp,
    app_callback_class,
    dummy_callback,
)
from hailo_apps.python.core.gstreamer.gstreamer_helper_pipelines import (
    DISPLAY_PIPELINE,
    SOURCE_PIPELINE,
    USER_CALLBACK_PIPELINE,
)

logger = get_logger(__name__)

APP_TITLE = "hailo-yolo-world"
YOLO_WORLD_PIPELINE = "yolo_world"


class GStreamerYoloWorldApp(GStreamerApp):
    def __init__(self, app_callback, user_data, parser=None):
        if parser is None:
            parser = get_pipeline_parser()

        parser.add_argument(
            "--prompts",
            type=str,
            default=None,
            help='Comma-separated class names for detection, e.g. "cat,dog,person"',
        )
        parser.add_argument(
            "--prompts-file",
            type=str,
            default=None,
            help="Path to JSON file with class name list",
        )
        parser.add_argument(
            "--embeddings-file",
            type=str,
            default=None,
            help="Path to cached embeddings JSON (default: embeddings.json in app dir)",
        )
        parser.add_argument(
            "--confidence-threshold",
            type=float,
            default=0.3,
            help="Detection confidence threshold (default: 0.3)",
        )
        parser.add_argument(
            "--watch-prompts",
            action="store_true",
            default=False,
            help="Watch prompts-file for changes and reload at runtime",
        )

        # Default to use_frame=True since we render detections via OpenCV
        parser.set_defaults(use_frame=True)

        logger.info("Initializing GStreamer YOLO World App...")

        super().__init__(parser, user_data)

        # Use fakesink — all visualization via OpenCV in callback
        self.video_sink = "fakesink"

        # Resolve HEF path
        self.hef_path = resolve_hef_path(
            self.hef_path,
            app_name=YOLO_WORLD_PIPELINE,
            arch=self.arch,
        )
        if self.hef_path is None or not Path(self.hef_path).exists():
            logger.error("HEF path is invalid or missing: %s", self.hef_path)

        logger.info("HEF path: %s", self.hef_path)

        self.app_callback = app_callback

        setproctitle.setproctitle(APP_TITLE)

        self.create_pipeline()
        logger.debug("Pipeline created")

    def get_pipeline_string(self):
        source_pipeline = SOURCE_PIPELINE(
            video_source=self.video_source,
            video_width=self.video_width,
            video_height=self.video_height,
            frame_rate=self.frame_rate,
            sync=self.sync,
        )
        user_callback_pipeline = USER_CALLBACK_PIPELINE()
        display_pipeline = DISPLAY_PIPELINE(
            video_sink=self.video_sink, sync=self.sync, show_fps=self.show_fps
        )

        pipeline_string = (
            f"{source_pipeline} ! "
            f"videoscale ! video/x-raw,width=640,height=640 ! "
            f"{user_callback_pipeline} ! "
            f"{display_pipeline}"
        )
        logger.debug("Pipeline string: %s", pipeline_string)
        return pipeline_string


def main():
    logger.info("Starting YOLO World App...")
    user_data = app_callback_class()
    app = GStreamerYoloWorldApp(dummy_callback, user_data)
    app.run()


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Verify syntax**

Run: `python -c "import ast; ast.parse(open('community/apps/pipeline_apps/yolo_world/yolo_world_pipeline.py').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add community/apps/pipeline_apps/yolo_world/yolo_world_pipeline.py
git commit -m "feat(yolo_world): add GStreamer pipeline with video scaling to 640x640"
```

---

### Task 6: Main App Entry Point + Callback

**Files:**
- Create: `community/apps/pipeline_apps/yolo_world/yolo_world.py`

This wires everything together: TextEmbeddingManager + YoloWorldInference + postprocess, running in the GStreamer callback.

- [ ] **Step 1: Write yolo_world.py**

Write `community/apps/pipeline_apps/yolo_world/yolo_world.py`:

```python
import os
os.environ["GST_PLUGIN_FEATURE_RANK"] = "vaapidecodebin:NONE"

import cv2
import numpy as np

import gi
gi.require_version("Gst", "1.0")
from gi.repository import Gst

from community.apps.pipeline_apps.yolo_world.yolo_world_pipeline import (
    GStreamerYoloWorldApp,
)
from community.apps.pipeline_apps.yolo_world.yolo_world_inference import (
    YoloWorldInference,
)
from community.apps.pipeline_apps.yolo_world.text_embedding_manager import (
    TextEmbeddingManager,
)
from community.apps.pipeline_apps.yolo_world.postprocess import postprocess
from hailo_apps.python.core.common.buffer_utils import (
    get_caps_from_pad,
    get_numpy_from_buffer,
)
from hailo_apps.python.core.common.hailo_logger import get_logger
from hailo_apps.python.core.gstreamer.gstreamer_app import app_callback_class

logger = get_logger(__name__)

# Colors for drawing bounding boxes (BGR for OpenCV)
COLORS = [
    (255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0),
    (255, 0, 255), (0, 255, 255), (128, 0, 0), (0, 128, 0),
    (0, 0, 128), (128, 128, 0), (128, 0, 128), (0, 128, 128),
]


class YoloWorldCallbackData(app_callback_class):
    def __init__(self):
        super().__init__()
        self.inference_engine = None
        self.embedding_manager = None
        self.confidence_threshold = 0.3
        self._last_embeddings_id = None


def app_callback(element, buffer, user_data):
    if buffer is None:
        return

    pad = element.get_static_pad("src")
    fmt, width, height = get_caps_from_pad(pad)

    if fmt is None or width is None or height is None:
        return

    frame = get_numpy_from_buffer(buffer, fmt, width, height)
    if frame is None:
        return

    engine = user_data.inference_engine
    manager = user_data.embedding_manager

    # Check if embeddings have been updated
    current_embeddings = manager.get_embeddings()
    if current_embeddings is not user_data._last_embeddings_id:
        engine.update_text_embeddings(current_embeddings)
        user_data._last_embeddings_id = current_embeddings
        logger.info("Inference engine updated with new embeddings")

    # Run inference — frame should already be 640x640 from pipeline videoscale
    outputs = engine.run(frame)

    # Postprocess
    labels = manager.get_labels()
    num_classes = manager.get_num_classes()
    detections = postprocess(
        outputs,
        score_threshold=user_data.confidence_threshold,
        iou_threshold=0.7,
        num_classes=num_classes,
    )

    # Draw detections on frame
    if user_data.use_frame:
        for det in detections:
            x1, y1, x2, y2 = det["bbox"]
            cls_id = det["class_id"]
            score = det["score"]
            label = labels[cls_id] if cls_id < len(labels) else f"class_{cls_id}"
            color = COLORS[cls_id % len(COLORS)]

            # Convert normalized coords to pixels
            px1 = int(x1 * width)
            py1 = int(y1 * height)
            px2 = int(x2 * width)
            py2 = int(y2 * height)

            cv2.rectangle(frame, (px1, py1), (px2, py2), color, 2)
            text = f"{label}: {score:.2f}"
            cv2.putText(
                frame, text, (px1, max(15, py1 - 8)),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1,
            )

        # Show active classes at top
        active_text = f"Classes: {', '.join(labels[:5])}"
        if len(labels) > 5:
            active_text += f" +{len(labels) - 5} more"
        cv2.putText(
            frame, active_text, (10, 25),
            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1,
        )

        frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
        user_data.set_frame(frame)

    # Log periodically
    frame_idx = user_data.get_count()
    if frame_idx % 30 == 0 and detections:
        det_summary = ", ".join(
            f"{labels[d['class_id']]}: {d['score']:.2f}" for d in detections[:5]
        )
        logger.debug("Frame %d: %d detections — %s", frame_idx, len(detections), det_summary)


def main():
    logger.info("Starting YOLO World App.")
    user_data = YoloWorldCallbackData()
    user_data.window_title = "YOLO World — Zero-Shot Detection"

    app = GStreamerYoloWorldApp(app_callback, user_data)

    opts = app.options_menu
    user_data.confidence_threshold = opts.confidence_threshold

    # Initialize text embedding manager
    user_data.embedding_manager = TextEmbeddingManager(
        prompts=opts.prompts,
        prompts_file=opts.prompts_file,
        embeddings_file=opts.embeddings_file,
        watch=opts.watch_prompts,
    )

    # Initialize inference engine
    user_data.inference_engine = YoloWorldInference(
        hef_path=app.hef_path,
        text_embeddings=user_data.embedding_manager.get_embeddings(),
    )
    user_data._last_embeddings_id = user_data.embedding_manager.get_embeddings()

    try:
        app.run()
    finally:
        user_data.inference_engine.close()
        user_data.embedding_manager.stop()


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Verify syntax**

Run: `python -c "import ast; ast.parse(open('community/apps/pipeline_apps/yolo_world/yolo_world.py').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add community/apps/pipeline_apps/yolo_world/yolo_world.py
git commit -m "feat(yolo_world): add main entry point with callback and OpenCV overlay"
```

---

### Task 7: README.md and CLAUDE.md

**Files:**
- Create: `community/apps/pipeline_apps/yolo_world/README.md`
- Create: `community/apps/pipeline_apps/yolo_world/CLAUDE.md`

- [ ] **Step 1: Write README.md**

Write `community/apps/pipeline_apps/yolo_world/README.md`:

```markdown
# YOLO World — Zero-Shot Object Detection

Detect **any object** by describing it in text. No retraining required.

This app uses [YOLO World v2s](https://github.com/AILab-CVC/YOLO-World) on Hailo-10H for real-time zero-shot object detection. You provide text class names (e.g., "cat", "dog", "coffee mug"), and the model detects them in the video stream using CLIP text-image similarity computed on-device.

## How It Works

1. **Text Encoding** (startup): CLIP text encoder (`openai/clip-vit-base-patch32`) converts your class names into 512-dim embeddings on CPU
2. **Detection** (real-time): YOLO World HEF on Hailo-10H takes the video frame + text embeddings and outputs bounding boxes with class scores
3. **Display**: OpenCV draws detections on each frame

The text-image contrastive matching runs entirely on the Hailo accelerator. Changing detected classes only requires swapping the text embeddings — no model recompilation needed.

## Prerequisites

- **Hardware**: Hailo-10H
- **Model**: `yolo_world_v2s` HEF (auto-downloaded on first run)
- **Python packages**: `transformers`, `torch` (for text encoding; not needed if using cached embeddings)

Install text encoder dependencies:
```bash
pip install transformers torch
```

## Usage

```bash
# Activate environment first
source setup_env.sh

# Default COCO-80 classes
python community/apps/pipeline_apps/yolo_world/yolo_world.py --input usb

# Custom classes via CLI
python community/apps/pipeline_apps/yolo_world/yolo_world.py --input usb \
    --prompts "cat,dog,person,car"

# Custom classes via file
python community/apps/pipeline_apps/yolo_world/yolo_world.py --input usb \
    --prompts-file my_classes.json

# Live prompt updates (edit the file while running)
python community/apps/pipeline_apps/yolo_world/yolo_world.py --input usb \
    --prompts-file my_classes.json --watch-prompts

# Pre-cached embeddings (no torch/transformers needed)
python community/apps/pipeline_apps/yolo_world/yolo_world.py --input usb \
    --embeddings-file embeddings.json
```

### Prompts File Format

A simple JSON array of class names:
```json
["cat", "dog", "person", "car", "bicycle"]
```

Maximum 80 classes. Use bare class names (not "a photo of a cat").

## CLI Arguments

| Argument | Type | Default | Description |
|---|---|---|---|
| `--input` | str | required | Video source: `usb`, file path, or RTSP URL |
| `--prompts` | str | None | Comma-separated class names |
| `--prompts-file` | str | None | Path to JSON prompts file |
| `--embeddings-file` | str | `embeddings.json` | Path to cached embeddings |
| `--confidence-threshold` | float | 0.3 | Detection confidence filter |
| `--watch-prompts` | flag | False | Watch prompts file for live updates |
| `--show-fps` | flag | False | Display FPS counter |

## Architecture

```
┌─────────────────────────────────────────────┐
│ GStreamer Pipeline                           │
│ USB Camera → videoscale(640x640) → callback  │
│                                    ↓         │
│              ┌─────────────────────┤         │
│              │ Python Callback     │         │
│              │  ┌────────────┐     │         │
│              │  │ HailoRT    │     │         │
│              │  │ VDevice    │     │         │
│              │  │            │     │         │
│              │  │ image ─────┤     │         │
│              │  │ text_emb ──┤→ HEF│         │
│              │  │            │     │         │
│              │  └──────┬─────┘     │         │
│              │         ↓           │         │
│              │  postprocess (NMS)  │         │
│              │         ↓           │         │
│              │  OpenCV overlay     │         │
│              └─────────────────────┤         │
│                                    ↓         │
│ fakesink ← ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ┘         │
│ OpenCV window ← frame display               │
└─────────────────────────────────────────────┘

Text Embedding Manager (background):
  CLIP encoder (CPU) → embeddings.json → HailoRT input_layer2
  File watcher → re-encode on prompts change
```

## Performance

| Metric | Value |
|---|---|
| Model | YOLO World v2s (640x640) |
| FPS | ~45 (batch=1) |
| mAP (COCO) | 31.6 (quantized) |
| Max classes | 80 |

## Customization

- **Different classes**: Use `--prompts` or `--prompts-file`
- **Sensitivity**: Adjust `--confidence-threshold` (lower = more detections)
- **Live updates**: Use `--watch-prompts` with a prompts file, edit while running
- **Offline mode**: Generate embeddings once, then use `--embeddings-file` without torch
```

- [ ] **Step 2: Write CLAUDE.md**

Write `community/apps/pipeline_apps/yolo_world/CLAUDE.md`:

```markdown
# YOLO World — Zero-Shot Detection

## What This App Does
Real-time zero-shot object detection using YOLO World v2s on Hailo-10H. Users provide text prompts, and the model detects those objects using CLIP text-image similarity computed on-device.

## Architecture
- **Type:** Pipeline (GStreamer) + Standalone inference (HailoRT)
- **Pattern:** Source → videoscale(640x640) → UserCallback(HailoRT inference + postprocess) → Display(fakesink)
- **Models:** yolo_world_v2s (dual-input: image 640x640x3 + text embeddings 1x80x512)
- **Hardware:** hailo10h (hailo15h should also work)
- **Postprocess:** Python numpy (not hailofilter .so — hailonet can't handle dual-input HEFs)

## Key Files
| File | Purpose |
|------|---------|
| `yolo_world.py` | Entry point, app_callback, OpenCV overlay |
| `yolo_world_pipeline.py` | GStreamerApp subclass (SOURCE → CALLBACK → DISPLAY) |
| `yolo_world_inference.py` | HailoRT dual-input inference engine |
| `text_embedding_manager.py` | CLIP text encoder + embedding cache + file watcher |
| `postprocess.py` | YOLO World NMS + box decoding (numpy) |
| `default_prompts.json` | COCO-80 class names |

## Why HailoRT Standalone Instead of hailonet
The `hailonet` GStreamer element only supports single-input HEFs. YOLO World requires two inputs (image + text embeddings). We use HailoRT's `InferModel` API directly in the callback, following the same pattern as the Whisper decoder in `hailo_apps/python/standalone_apps/speech_recognition/whisper_pipeline.py`.

## HEF Details
- **Inputs:** input_layer1 (1,640,640,3 uint8), input_layer2 (1,80,512 float32)
- **Outputs:** 6 tensors — 3 cls (80x80x80, 40x40x80, 20x20x80) + 3 reg (80x80x4, 40x40x4, 20x20x4)
- **On-device:** image normalization, sigmoid on cls, DFL box decoding
- **Software:** grid-based box coord decoding, NMS

## Text Embeddings
- Generated by `openai/clip-vit-base-patch32` (HuggingFace CLIPTextModelWithProjection)
- Bare class names, NO prompt templates
- L2-normalized, shape (1, 80, 512), zero-padded if <80 classes
- Cached to embeddings.json for reuse

## How to Extend
- Add new classes: edit prompts file or use --prompts CLI arg
- Adjust sensitivity: --confidence-threshold flag
- Add tracking: integrate TRACKER_PIPELINE (would need to add hailo metadata to detections)
- Support other archs: add model name mappings when HEFs become available
```

- [ ] **Step 3: Commit**

```bash
git add community/apps/pipeline_apps/yolo_world/README.md \
      community/apps/pipeline_apps/yolo_world/CLAUDE.md
git commit -m "docs(yolo_world): add README and CLAUDE.md"
```

---

### Task 8: Smoke Test on Device

This task verifies the full pipeline works end-to-end on a Hailo-10H device.

**Files:** None (testing only)

- [ ] **Step 1: Activate environment**

```bash
source setup_env.sh
```

- [ ] **Step 2: Install text encoder dependencies**

```bash
pip install transformers torch
```

- [ ] **Step 3: Run with default COCO-80 classes on USB camera**

```bash
python community/apps/pipeline_apps/yolo_world/yolo_world.py --input usb --show-fps
```

Expected: OpenCV window opens showing video with bounding boxes around detected objects. Labels should match COCO classes (person, car, etc.). FPS should be ~30-45.

- [ ] **Step 4: Test custom prompts**

```bash
python community/apps/pipeline_apps/yolo_world/yolo_world.py \
    --input usb --prompts "person,chair,laptop,phone"
```

Expected: Only detects person, chair, laptop, phone — not other COCO classes.

- [ ] **Step 5: Test prompts file with watch**

Create test prompts file:
```bash
echo '["person", "cat", "dog"]' > /tmp/test_prompts.json
```

Run with watch:
```bash
python community/apps/pipeline_apps/yolo_world/yolo_world.py \
    --input usb --prompts-file /tmp/test_prompts.json --watch-prompts
```

While running, edit the file:
```bash
echo '["car", "bus", "truck"]' > /tmp/test_prompts.json
```

Expected: After ~2 seconds, detections switch from person/cat/dog to car/bus/truck without app restart.

- [ ] **Step 6: Test cached embeddings (no torch)**

Verify `embeddings.json` was created in the app directory from a previous run. Then test:
```bash
python community/apps/pipeline_apps/yolo_world/yolo_world.py \
    --input usb --embeddings-file community/apps/pipeline_apps/yolo_world/embeddings.json
```

Expected: App starts without loading torch/transformers (check logs), uses cached embeddings.

- [ ] **Step 7: Debug and fix any issues**

If any test fails:
1. Check logs with `--log-level DEBUG`
2. Verify HEF input/output layer names match what `hef_utils.py` reports
3. Verify postprocess output tensor sorting (cls vs reg identification)
4. Check frame dimensions — ensure videoscale produces 640x640

---

### Task 9: Update Design Spec with Architectural Changes

**Files:**
- Modify: `docs/superpowers/specs/2026-03-28-yolo-world-community-app-design.md`

The implementation revealed that `hailonet` cannot handle dual-input HEFs, so we use HailoRT standalone inference instead. The design spec should be updated to reflect this.

- [ ] **Step 1: Update the spec**

Add a section documenting the architectural change:
- Pipeline uses `USER_CALLBACK` with HailoRT standalone inference, not `INFERENCE_PIPELINE` with `hailonet`
- Postprocessing is numpy-based, not via `hailofilter` `.so`
- Reference the Whisper decoder as the multi-input pattern

- [ ] **Step 2: Commit**

```bash
git add docs/superpowers/specs/2026-03-28-yolo-world-community-app-design.md
git commit -m "docs(yolo_world): update spec with HailoRT standalone architecture"
```
