# Community Apps

Example applications built with the `/hl-build-app` skill and community contributors. These live separately from the core framework (`hailo-apps/hailo_apps/`) to ease maintenance and merging.

## Structure

```
community/apps/
├── pipeline_apps/       # GStreamer real-time video apps
├── standalone_apps/     # Lightweight HailoRT-only batch apps
└── gen_ai_apps/         # Hailo-10H GenAI apps
```

## Running

All apps use the same framework as main apps. Run from the repo root:

```bash
# Pipeline app
python community/apps/pipeline_apps/<app_name>/<app_name>.py --input usb

# Standalone app
python community/apps/standalone_apps/<app_name>/<app_name>.py --input path/to/video.mp4

# GenAI app (Hailo-10H only)
python community/apps/gen_ai_apps/<app_name>/<app_name>.py
```

## Apps

### Pipeline Apps (14)
| App | Description | Template |
|-----|-------------|----------|
| crowd_counting | Count people crossing a virtual line | detection |
| cat_food_monitor | Identify cats at food bowl with training | face_recognition |
| semaphore_translator | Translate semaphore flag signals from pose | pose_estimation |
| room_security_monitor | Face recognition door access with alarm | face_recognition |
| parking_lot_occupancy | Zone-based vehicle counting | detection |
| baby_sleep_monitor | Infant sleep position safety alerts | pose_estimation |
| retail_shelf_analyzer | Tiled small-object counting on shelves | tiling |
| workout_rep_counter | Exercise rep counting via joint angles | pose_estimation |
| ppe_safety_checker | Zero-shot PPE compliance via CLIP | clip |
| multi_entrance_tracker | Cross-camera face re-ID | reid_multisource |
| depth_proximity_alert | Depth-based closeness warning | depth |
| multi_camera_store_monitor | 3-camera retail surveillance | multisource |
| license_plate_reader | Detect plates + OCR text | paddle_ocr |
| gesture_mouse | Hand gesture mouse control | gesture_detection |

### Standalone Apps (5)
| App | Description | Template |
|-----|-------------|----------|
| traffic_light_detector | Classify traffic light state from video | object_detection |
| document_text_extractor | Batch OCR from document images | paddle_ocr |
| aerial_object_counter | Rotated bbox counting for drone images | oriented_object_detection |
| photo_enhancer | Batch 2x upscale with Real-ESRGAN | super_resolution |
| lane_departure_warning | Lane departure alerts from dashcam | lane_detection |

### GenAI Apps (2)
| App | Description | Template |
|-----|-------------|----------|
| visual_quality_inspector | VLM defect description for manufacturing | vlm_chat |
| voice_controlled_camera | Voice commands to detect and describe | voice_assistant |

## Building New Apps

Use `/hl-build-app` to create new apps with AI assistance, or follow the skill docs in `.hailo/skills/hl-build-app.md`. New apps are scaffolded in this directory automatically.
