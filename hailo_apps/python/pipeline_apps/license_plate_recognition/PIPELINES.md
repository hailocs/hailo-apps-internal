# LPR Pipeline Variants

Generated on: Tue Dec 30 05:24:21 PM IST 2025

This document contains all GStreamer pipeline variants for the License Plate Recognition application.

---

## Pipeline: `simple`

```
================================================================================
PIPELINE VARIANT: simple
================================================================================

--- GStreamer CLI Command ---

gst-launch-1.0 filesrc location="/usr/local/hailo/resources/videos/lpr_video.mp4" name=source ! queue name=source_queue_decode leaky=no max-size-buffers=10 max-size-bytes=0 max-size-time=0 ! decodebin name=source_decodebin caps=video/x-raw ! queue name=source_scale_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! videoscale name=source_videoscale n-threads=2 ! queue name=source_convert_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! videoconvert n-threads=3 name=source_convert qos=false ! video/x-raw, pixel-aspect-ratio=1/1, format=RGB, width=1280, height=720 ! videorate name=source_videorate ! capsfilter name=source_fps_caps caps="video/x-raw, framerate=30/1" ! queue name=inference_wrapper_input_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! hailocropper name=inference_wrapper_crop so-path=/usr/lib/x86_64-linux-gnu/hailo/tappas/post_processes/cropping_algorithms/libwhole_buffer.so function-name=create_crops use-letterbox=true resize-method=inter-area internal-offset=true hailoaggregator name=inference_wrapper_agg inference_wrapper_crop. ! queue name=inference_wrapper_bypass_q leaky=no max-size-buffers=20 max-size-bytes=0 max-size-time=0 ! inference_wrapper_agg.sink_0 inference_wrapper_crop. ! queue name=vehicle_detection_scale_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! videoscale name=vehicle_detection_videoscale n-threads=2 qos=false ! queue name=vehicle_detection_convert_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! video/x-raw, pixel-aspect-ratio=1/1 ! videoconvert name=vehicle_detection_videoconvert n-threads=2 ! queue name=vehicle_detection_hailonet_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! hailonet name=vehicle_detection_hailonet hef-path=/usr/local/hailo/resources/models/hailo8/yolov5m_vehicles.hef batch-size=2 vdevice-group-id=SHARED nms-score-threshold=0.3 nms-iou-threshold=0.45 output-format-type=HAILO_FORMAT_TYPE_FLOAT32 force-writable=true ! queue name=vehicle_detection_hailofilter_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! hailofilter name=vehicle_detection_hailofilter so-path=/usr/local/hailo/resources/so/libyolo_hailortpp_postprocess.so config-path=/home/omria/hailo/dev/lpr/hailo-apps-infra/hailo_apps/python/pipeline_apps/license_plate_recognition/configs/yolov5m_vehicles.json function-name=yolov5m_vehicles qos=false ! queue name=vehicle_detection_output_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! inference_wrapper_agg.sink_1 inference_wrapper_agg. ! queue name=inference_wrapper_output_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! hailotracker name=hailo_tracker class-id=-1 kalman-dist-thr=0.5 iou-thr=0.6 init-iou-thr=0.7 keep-new-frames=2 keep-tracked-frames=2 keep-lost-frames=2 keep-past-metadata=True qos=False ! queue name=hailo_tracker_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! tee name=context_tee context_tee. ! queue name=vehicle_cropper_input_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! hailocropper name=vehicle_cropper_cropper so-path=/usr/local/hailo/resources/so/liblpr_croppers.so function-name=vehicles_without_ocr use-letterbox=true no-scaling-bbox=true internal-offset=true resize-method=bilinear hailoaggregator name=vehicle_cropper_agg vehicle_cropper_cropper. ! queue name=vehicle_cropper_bypass_q leaky=no max-size-buffers=20 max-size-bytes=0 max-size-time=0 ! vehicle_cropper_agg.sink_0 vehicle_cropper_cropper. ! queue name=plate_detection_scale_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! videoscale name=plate_detection_videoscale n-threads=2 qos=false ! queue name=plate_detection_convert_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! video/x-raw, pixel-aspect-ratio=1/1 ! videoconvert name=plate_detection_videoconvert n-threads=2 ! queue name=plate_detection_hailonet_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! hailonet name=plate_detection_hailonet hef-path=/usr/local/hailo/resources/models/hailo8/yolov8n_relu6_global_lp_det.hef batch-size=1 vdevice-group-id=SHARED nms-score-threshold=0.3 nms-iou-threshold=0.45 output-format-type=HAILO_FORMAT_TYPE_FLOAT32 force-writable=true ! queue name=plate_detection_hailofilter_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! hailofilter name=plate_detection_hailofilter so-path=/usr/local/hailo/resources/so/libyolo_hailortpp_postprocess.so config-path=/home/omria/hailo/dev/lpr/hailo-apps-infra/hailo_apps/python/pipeline_apps/license_plate_recognition/configs/yolov8n_relu6_global_lp_det.json function-name=yolov8n_relu6_license_plate qos=false ! queue name=plate_detection_output_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! vehicle_cropper_agg.sink_1 vehicle_cropper_agg. ! queue name=vehicle_cropper_output_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! tee name=vehicle_cropper_tee hailoaggregator name=agg2 vehicle_cropper_tee. ! queue ! agg2.sink_0 vehicle_cropper_tee. ! queue ! queue name=lp_cropper_input_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! hailocropper name=lp_cropper_cropper so-path=/usr/local/hailo/resources/so/liblpr_croppers.so function-name=license_plate_no_quality use-letterbox=true no-scaling-bbox=true internal-offset=true resize-method=bilinear hailoaggregator name=lp_cropper_agg lp_cropper_cropper. ! queue name=lp_cropper_bypass_q leaky=no max-size-buffers=20 max-size-bytes=0 max-size-time=0 ! lp_cropper_agg.sink_0 lp_cropper_cropper. ! queue name=ocr_detection_scale_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! videoscale name=ocr_detection_videoscale n-threads=2 qos=false ! queue name=ocr_detection_convert_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! video/x-raw, pixel-aspect-ratio=1/1 ! videoconvert name=ocr_detection_videoconvert n-threads=2 ! queue name=ocr_detection_hailonet_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! hailonet name=ocr_detection_hailonet hef-path=/usr/local/hailo/resources/models/hailo8/ocr.hef batch-size=1 vdevice-group-id=SHARED force-writable=true ! queue name=ocr_detection_hailofilter_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! hailofilter name=ocr_detection_hailofilter so-path=/usr/local/hailo/resources/so/libocr_postprocess.so function-name=paddleocr_recognize qos=false ! queue name=ocr_detection_output_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! lp_cropper_agg.sink_1 lp_cropper_agg. ! queue name=lp_cropper_output_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! queue ! agg2.sink_1 agg2. ! queue ! tee name=postproc_tee postproc_tee. ! queue ! hailoaggregator name=display_agg context_tee. ! queue ! display_agg.sink_1 display_agg. ! queue ! queue name=hailo_display_overlay_q leaky=downstream max-size-buffers=10 max-size-bytes=0 max-size-time=0 ! hailooverlay name=hailo_display_overlay ! queue name=hailo_display_videoconvert_q leaky=downstream max-size-buffers=10 max-size-bytes=0 max-size-time=0 ! videoconvert name=hailo_display_videoconvert n-threads=2 qos=false ! queue name=hailo_display_q leaky=downstream max-size-buffers=10 max-size-bytes=0 max-size-time=0 ! fpsdisplaysink name=hailo_display video-sink=autovideosink sync=false text-overlay=False signal-fps-measurements=true postproc_tee. ! queue ! identity name=identity_callback ! hailofilter use-gst-buffer=true so-path=/usr/local/hailo/resources/so/liblpr_ocrsink.so qos=false ! fakesink sync=false async=false

--- Pipeline String (formatted) ---

gst-launch-1.0 \
    filesrc location="/usr/local/hailo/resources/videos/lpr_video.mp4" name=source ! \
    queue name=source_queue_decode leaky=no max-size-buffers=10 max-size-bytes=0 max-size-time=0  ! \
    decodebin name=source_decodebin caps=video/x-raw ! \
     queue name=source_scale_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0  ! \
    videoscale name=source_videoscale n-threads=2 ! \
    queue name=source_convert_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0  ! \
    videoconvert n-threads=3 name=source_convert qos=false ! \
    video/x-raw, pixel-aspect-ratio=1/1, format=RGB, width=1280, height=720 ! \
    videorate name=source_videorate ! \
    capsfilter name=source_fps_caps caps="video/x-raw, framerate=30/1"  ! \
    queue name=inference_wrapper_input_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0  ! \
    hailocropper name=inference_wrapper_crop so-path=/usr/lib/x86_64-linux-gnu/hailo/tappas/post_processes/cropping_algorithms/libwhole_buffer.so function-name=create_crops use-letterbox=true resize-method=inter-area internal-offset=true hailoaggregator name=inference_wrapper_agg inference_wrapper_crop. ! \
    queue name=inference_wrapper_bypass_q leaky=no max-size-buffers=20 max-size-bytes=0 max-size-time=0  ! \
    inference_wrapper_agg.sink_0 inference_wrapper_crop. ! \
    queue name=vehicle_detection_scale_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0  ! \
    videoscale name=vehicle_detection_videoscale n-threads=2 qos=false ! \
    queue name=vehicle_detection_convert_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0  ! \
    video/x-raw, pixel-aspect-ratio=1/1 ! \
    videoconvert name=vehicle_detection_videoconvert n-threads=2 ! \
    queue name=vehicle_detection_hailonet_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0  ! \
    hailonet name=vehicle_detection_hailonet hef-path=/usr/local/hailo/resources/models/hailo8/yolov5m_vehicles.hef batch-size=2  vdevice-group-id=SHARED nms-score-threshold=0.3 nms-iou-threshold=0.45 output-format-type=HAILO_FORMAT_TYPE_FLOAT32 force-writable=true  ! \
    queue name=vehicle_detection_hailofilter_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0  ! \
    hailofilter name=vehicle_detection_hailofilter so-path=/usr/local/hailo/resources/so/libyolo_hailortpp_postprocess.so  config-path=/home/omria/hailo/dev/lpr/hailo-apps-infra/hailo_apps/python/pipeline_apps/license_plate_recognition/configs/yolov5m_vehicles.json   function-name=yolov5m_vehicles  qos=false ! \
    queue name=vehicle_detection_output_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0   ! \
    inference_wrapper_agg.sink_1 inference_wrapper_agg. ! \
    queue name=inference_wrapper_output_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0   ! \
    hailotracker name=hailo_tracker class-id=-1 kalman-dist-thr=0.5 iou-thr=0.6 init-iou-thr=0.7 keep-new-frames=2 keep-tracked-frames=2 keep-lost-frames=2 keep-past-metadata=True qos=False ! \
    queue name=hailo_tracker_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0   ! \
    tee name=context_tee context_tee. ! \
    queue name=vehicle_cropper_input_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0  ! \
    hailocropper name=vehicle_cropper_cropper so-path=/usr/local/hailo/resources/so/liblpr_croppers.so function-name=vehicles_without_ocr use-letterbox=true no-scaling-bbox=true internal-offset=true resize-method=bilinear hailoaggregator name=vehicle_cropper_agg vehicle_cropper_cropper. ! \
    queue name=vehicle_cropper_bypass_q leaky=no max-size-buffers=20 max-size-bytes=0 max-size-time=0  ! \
    vehicle_cropper_agg.sink_0 vehicle_cropper_cropper. ! \
    queue name=plate_detection_scale_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0  ! \
    videoscale name=plate_detection_videoscale n-threads=2 qos=false ! \
    queue name=plate_detection_convert_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0  ! \
    video/x-raw, pixel-aspect-ratio=1/1 ! \
    videoconvert name=plate_detection_videoconvert n-threads=2 ! \
    queue name=plate_detection_hailonet_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0  ! \
    hailonet name=plate_detection_hailonet hef-path=/usr/local/hailo/resources/models/hailo8/yolov8n_relu6_global_lp_det.hef batch-size=1  vdevice-group-id=SHARED nms-score-threshold=0.3 nms-iou-threshold=0.45 output-format-type=HAILO_FORMAT_TYPE_FLOAT32 force-writable=true  ! \
    queue name=plate_detection_hailofilter_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0  ! \
    hailofilter name=plate_detection_hailofilter so-path=/usr/local/hailo/resources/so/libyolo_hailortpp_postprocess.so  config-path=/home/omria/hailo/dev/lpr/hailo-apps-infra/hailo_apps/python/pipeline_apps/license_plate_recognition/configs/yolov8n_relu6_global_lp_det.json   function-name=yolov8n_relu6_license_plate  qos=false ! \
    queue name=plate_detection_output_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0   ! \
    vehicle_cropper_agg.sink_1 vehicle_cropper_agg. ! \
    queue name=vehicle_cropper_output_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0   ! \
    tee name=vehicle_cropper_tee hailoaggregator name=agg2 vehicle_cropper_tee. ! \
    queue ! \
    agg2.sink_0 vehicle_cropper_tee. ! \
    queue ! \
    queue name=lp_cropper_input_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0  ! \
    hailocropper name=lp_cropper_cropper so-path=/usr/local/hailo/resources/so/liblpr_croppers.so function-name=license_plate_no_quality use-letterbox=true no-scaling-bbox=true internal-offset=true resize-method=bilinear hailoaggregator name=lp_cropper_agg lp_cropper_cropper. ! \
    queue name=lp_cropper_bypass_q leaky=no max-size-buffers=20 max-size-bytes=0 max-size-time=0  ! \
    lp_cropper_agg.sink_0 lp_cropper_cropper. ! \
    queue name=ocr_detection_scale_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0  ! \
    videoscale name=ocr_detection_videoscale n-threads=2 qos=false ! \
    queue name=ocr_detection_convert_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0  ! \
    video/x-raw, pixel-aspect-ratio=1/1 ! \
    videoconvert name=ocr_detection_videoconvert n-threads=2 ! \
    queue name=ocr_detection_hailonet_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0  ! \
    hailonet name=ocr_detection_hailonet hef-path=/usr/local/hailo/resources/models/hailo8/ocr.hef batch-size=1  vdevice-group-id=SHARED  force-writable=true  ! \
    queue name=ocr_detection_hailofilter_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0  ! \
    hailofilter name=ocr_detection_hailofilter so-path=/usr/local/hailo/resources/so/libocr_postprocess.so   function-name=paddleocr_recognize  qos=false ! \
    queue name=ocr_detection_output_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0   ! \
    lp_cropper_agg.sink_1 lp_cropper_agg. ! \
    queue name=lp_cropper_output_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0   ! \
    queue ! \
    agg2.sink_1 agg2. ! \
    queue ! \
    tee name=postproc_tee postproc_tee. ! \
    queue ! \
    hailoaggregator name=display_agg context_tee. ! \
    queue ! \
    display_agg.sink_1 display_agg. ! \
    queue ! \
    queue name=hailo_display_overlay_q leaky=downstream max-size-buffers=10 max-size-bytes=0 max-size-time=0  ! \
    hailooverlay name=hailo_display_overlay  ! \
    queue name=hailo_display_videoconvert_q leaky=downstream max-size-buffers=10 max-size-bytes=0 max-size-time=0  ! \
    videoconvert name=hailo_display_videoconvert n-threads=2 qos=false ! \
    queue name=hailo_display_q leaky=downstream max-size-buffers=10 max-size-bytes=0 max-size-time=0  ! \
    fpsdisplaysink name=hailo_display video-sink=autovideosink sync=false text-overlay=False signal-fps-measurements=true  postproc_tee. ! \
    queue ! \
    identity name=identity_callback ! \
    hailofilter use-gst-buffer=true so-path=/usr/local/hailo/resources/so/liblpr_ocrsink.so qos=false ! \
    fakesink sync=false async=false

--- Available Pipeline Variants ---

  --pipeline simple               : Full LPR: Vehicle → Tracker → LP → OCR with display aggregators <-- CURRENT
  --pipeline complex              : Full LPR: Explicit low-level GStreamer elements
  --pipeline optimized            : Full LPR: Parallel display/processing with quality filter
  --pipeline optimized_direct     : Full LPR: Parallel display/processing, no quality filter
  --pipeline candidate            : Full LPR: Hardcoded paths (debugging)
  --pipeline vehicle_and_lp       : Vehicle + LP detection only (no OCR)
  --pipeline vehicle_only         : Vehicle detection only
  --pipeline lp_only              : LP detection on full frame only
  --pipeline lp_only_crops        : LP detection + crop saving (no display)
  --pipeline lp_and_ocr           : Full-frame LP + OCR (no vehicle detection)
  --pipeline lp_and_ocr_direct    : Full-frame LP + OCR with explicit elements
```

---

## Pipeline: `complex`

```
================================================================================
PIPELINE VARIANT: complex
================================================================================

--- GStreamer CLI Command ---

gst-launch-1.0 filesrc location="/usr/local/hailo/resources/videos/lpr_video.mp4" name=source ! queue name=source_queue_decode leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! decodebin name=source_decodebin ! queue name=source_scale_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! videoscale name=source_videoscale n-threads=2 ! queue name=source_convert_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! videoconvert n-threads=3 name=source_convert qos=false ! video/x-raw, pixel-aspect-ratio=1/1, format=RGB, width=1280, height=720 ! videorate name=source_videorate ! capsfilter name=source_fps_caps caps="video/x-raw, framerate=30/1" ! queue name=vehicle_pre_scale_q leaky=no max-size-buffers=30 max-size-bytes=0 max-size-time=0 ! videoscale name=vehicle_videoscale n-threads=2 qos=false ! queue name=vehicle_pre_convert_q leaky=no max-size-buffers=30 max-size-bytes=0 max-size-time=0 ! video/x-raw, pixel-aspect-ratio=1/1 ! videoconvert name=vehicle_videoconvert n-threads=2 ! queue name=vehicle_pre_hailonet_q leaky=no max-size-buffers=30 max-size-bytes=0 max-size-time=0 ! hailonet name=vehicle_hailonet hef-path=/usr/local/hailo/resources/models/hailo8/yolov5m_vehicles.hef vdevice-group-id=1 scheduling-algorithm=1 scheduler-threshold=1 scheduler-timeout-ms=100 nms-score-threshold=0.3 nms-iou-threshold=0.45 output-format-type=HAILO_FORMAT_TYPE_FLOAT32 force-writable=true ! queue name=vehicle_post_hailonet_q leaky=no max-size-buffers=30 max-size-bytes=0 max-size-time=0 ! hailofilter name=vehicle_hailofilter so-path=/usr/local/hailo/resources/so/libyolo_hailortpp_postprocess.so function-name=yolov5m_vehicles config-path=/home/omria/hailo/dev/lpr/hailo-apps-infra/hailo_apps/python/pipeline_apps/license_plate_recognition/configs/yolov5m_vehicles.json qos=false ! queue name=vehicle_post_filter_q leaky=no max-size-buffers=30 max-size-bytes=0 max-size-time=0 ! hailotracker name=hailo_tracker keep-past-metadata=true kalman-dist-thr=0.5 iou-thr=0.6 keep-tracked-frames=2 keep-lost-frames=2 ! queue name=tracker_post_q leaky=no max-size-buffers=30 max-size-bytes=0 max-size-time=0 ! tee name=context_tee context_tee. ! queue name=processing_branch_q leaky=no max-size-buffers=30 max-size-bytes=0 max-size-time=0 ! hailocropper so-path=/usr/local/hailo/resources/so/liblpr_croppers.so function-name=vehicles_without_ocr internal-offset=true drop-uncropped-buffers=false name=cropper1 hailoaggregator name=agg1 cropper1. ! queue name=cropper1_bypass_q leaky=no max-size-buffers=50 max-size-bytes=0 max-size-time=0 ! agg1.sink_0 cropper1. ! queue name=cropper1_process_q leaky=no max-size-buffers=30 max-size-bytes=0 max-size-time=0 ! hailonet name=plate_hailonet hef-path=/usr/local/hailo/resources/models/hailo8/yolov8n_relu6_global_lp_det.hef vdevice-group-id=1 scheduling-algorithm=1 scheduler-threshold=5 scheduler-timeout-ms=100 ! queue name=plate_post_hailonet_q leaky=no max-size-buffers=30 max-size-bytes=0 max-size-time=0 ! hailofilter name=plate_hailofilter so-path=/usr/local/hailo/resources/so/libyolo_hailortpp_postprocess.so config-path=/home/omria/hailo/dev/lpr/hailo-apps-infra/hailo_apps/python/pipeline_apps/license_plate_recognition/configs/yolov8n_relu6_global_lp_det.json function-name=yolov8n_relu6_license_plate qos=false ! queue name=plate_post_filter_q leaky=no max-size-buffers=30 max-size-bytes=0 max-size-time=0 ! agg1.sink_1 agg1. ! queue name=agg1_output_q leaky=no max-size-buffers=30 max-size-bytes=0 max-size-time=0 ! hailocropper so-path=/usr/local/hailo/resources/so/liblpr_croppers.so function-name=license_plate_no_quality internal-offset=true drop-uncropped-buffers=false name=cropper2 hailoaggregator name=agg2 cropper2. ! queue name=cropper2_bypass_q leaky=no max-size-buffers=50 max-size-bytes=0 max-size-time=0 ! agg2.sink_0 cropper2. ! queue name=cropper2_process_q leaky=no max-size-buffers=30 max-size-bytes=0 max-size-time=0 ! hailonet name=ocr_hailonet hef-path=/usr/local/hailo/resources/models/hailo8/ocr.hef vdevice-group-id=1 scheduling-algorithm=1 scheduler-threshold=1 scheduler-timeout-ms=100 ! queue name=ocr_post_hailonet_q leaky=no max-size-buffers=30 max-size-bytes=0 max-size-time=0 ! hailofilter name=ocr_hailofilter so-path=/usr/local/hailo/resources/so/libocr_postprocess.so function-name=paddleocr_recognize qos=false ! queue name=ocr_post_filter_q leaky=no max-size-buffers=30 max-size-bytes=0 max-size-time=0 ! agg2.sink_1 agg2. ! queue name=agg2_output_q leaky=no max-size-buffers=30 max-size-bytes=0 max-size-time=0 ! tee name=postproc_tee postproc_tee. ! queue name=display_meta_q leaky=no max-size-buffers=30 max-size-bytes=0 max-size-time=0 ! hailoaggregator name=display_agg context_tee. ! queue name=display_bypass_q leaky=no max-size-buffers=30 max-size-bytes=0 max-size-time=0 ! display_agg.sink_1 display_agg. ! queue name=display_branch_q leaky=no max-size-buffers=30 max-size-bytes=0 max-size-time=0 ! videobox top=1 bottom=1 ! queue name=display_videobox_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! hailooverlay line-thickness=3 font-thickness=1 qos=false ! hailofilter use-gst-buffer=true so-path=/usr/local/hailo/resources/so/liblpr_overlay.so qos=false ! videoconvert ! fpsdisplaysink name=hailo_display video-sink=autovideosink sync=false text-overlay=False signal-fps-measurements=true postproc_tee. ! queue name=final_sink_q leaky=no max-size-buffers=30 max-size-bytes=0 max-size-time=0 ! identity name=identity_callback ! hailofilter use-gst-buffer=true so-path=/usr/local/hailo/resources/so/liblpr_ocrsink.so qos=false ! fakesink sync=false async=false

--- Pipeline String (formatted) ---

gst-launch-1.0 \
    filesrc location="/usr/local/hailo/resources/videos/lpr_video.mp4" name=source ! \
    queue name=source_queue_decode leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0  ! \
    decodebin name=source_decodebin ! \
     queue name=source_scale_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0  ! \
    videoscale name=source_videoscale n-threads=2 ! \
    queue name=source_convert_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0  ! \
    videoconvert n-threads=3 name=source_convert qos=false ! \
    video/x-raw, pixel-aspect-ratio=1/1, format=RGB, width=1280, height=720 ! \
    videorate name=source_videorate ! \
    capsfilter name=source_fps_caps caps="video/x-raw, framerate=30/1"  ! \
    queue name=vehicle_pre_scale_q leaky=no max-size-buffers=30 max-size-bytes=0 max-size-time=0  ! \
    videoscale name=vehicle_videoscale n-threads=2 qos=false ! \
    queue name=vehicle_pre_convert_q leaky=no max-size-buffers=30 max-size-bytes=0 max-size-time=0  ! \
    video/x-raw, pixel-aspect-ratio=1/1 ! \
    videoconvert name=vehicle_videoconvert n-threads=2 ! \
    queue name=vehicle_pre_hailonet_q leaky=no max-size-buffers=30 max-size-bytes=0 max-size-time=0  ! \
    hailonet name=vehicle_hailonet hef-path=/usr/local/hailo/resources/models/hailo8/yolov5m_vehicles.hef vdevice-group-id=1 scheduling-algorithm=1 scheduler-threshold=1 scheduler-timeout-ms=100 nms-score-threshold=0.3 nms-iou-threshold=0.45 output-format-type=HAILO_FORMAT_TYPE_FLOAT32 force-writable=true ! \
    queue name=vehicle_post_hailonet_q leaky=no max-size-buffers=30 max-size-bytes=0 max-size-time=0  ! \
    hailofilter name=vehicle_hailofilter so-path=/usr/local/hailo/resources/so/libyolo_hailortpp_postprocess.so function-name=yolov5m_vehicles config-path=/home/omria/hailo/dev/lpr/hailo-apps-infra/hailo_apps/python/pipeline_apps/license_plate_recognition/configs/yolov5m_vehicles.json qos=false ! \
    queue name=vehicle_post_filter_q leaky=no max-size-buffers=30 max-size-bytes=0 max-size-time=0   ! \
    hailotracker name=hailo_tracker keep-past-metadata=true kalman-dist-thr=0.5 iou-thr=0.6 keep-tracked-frames=2 keep-lost-frames=2 ! \
    queue name=tracker_post_q leaky=no max-size-buffers=30 max-size-bytes=0 max-size-time=0   ! \
    tee name=context_tee context_tee. ! \
    queue name=processing_branch_q leaky=no max-size-buffers=30 max-size-bytes=0 max-size-time=0  ! \
    hailocropper so-path=/usr/local/hailo/resources/so/liblpr_croppers.so function-name=vehicles_without_ocr internal-offset=true drop-uncropped-buffers=false name=cropper1 hailoaggregator name=agg1 cropper1. ! \
    queue name=cropper1_bypass_q leaky=no max-size-buffers=50 max-size-bytes=0 max-size-time=0  ! \
    agg1.sink_0 cropper1. ! \
    queue name=cropper1_process_q leaky=no max-size-buffers=30 max-size-bytes=0 max-size-time=0  ! \
    hailonet name=plate_hailonet hef-path=/usr/local/hailo/resources/models/hailo8/yolov8n_relu6_global_lp_det.hef vdevice-group-id=1 scheduling-algorithm=1 scheduler-threshold=5 scheduler-timeout-ms=100 ! \
    queue name=plate_post_hailonet_q leaky=no max-size-buffers=30 max-size-bytes=0 max-size-time=0  ! \
    hailofilter name=plate_hailofilter so-path=/usr/local/hailo/resources/so/libyolo_hailortpp_postprocess.so config-path=/home/omria/hailo/dev/lpr/hailo-apps-infra/hailo_apps/python/pipeline_apps/license_plate_recognition/configs/yolov8n_relu6_global_lp_det.json function-name=yolov8n_relu6_license_plate qos=false ! \
    queue name=plate_post_filter_q leaky=no max-size-buffers=30 max-size-bytes=0 max-size-time=0   ! \
    agg1.sink_1 agg1. ! \
    queue name=agg1_output_q leaky=no max-size-buffers=30 max-size-bytes=0 max-size-time=0  ! \
    hailocropper so-path=/usr/local/hailo/resources/so/liblpr_croppers.so function-name=license_plate_no_quality internal-offset=true drop-uncropped-buffers=false name=cropper2 hailoaggregator name=agg2 cropper2. ! \
    queue name=cropper2_bypass_q leaky=no max-size-buffers=50 max-size-bytes=0 max-size-time=0  ! \
    agg2.sink_0 cropper2. ! \
    queue name=cropper2_process_q leaky=no max-size-buffers=30 max-size-bytes=0 max-size-time=0  ! \
    hailonet name=ocr_hailonet hef-path=/usr/local/hailo/resources/models/hailo8/ocr.hef vdevice-group-id=1 scheduling-algorithm=1 scheduler-threshold=1 scheduler-timeout-ms=100 ! \
    queue name=ocr_post_hailonet_q leaky=no max-size-buffers=30 max-size-bytes=0 max-size-time=0  ! \
    hailofilter name=ocr_hailofilter so-path=/usr/local/hailo/resources/so/libocr_postprocess.so function-name=paddleocr_recognize qos=false ! \
    queue name=ocr_post_filter_q leaky=no max-size-buffers=30 max-size-bytes=0 max-size-time=0   ! \
    agg2.sink_1 agg2. ! \
    queue name=agg2_output_q leaky=no max-size-buffers=30 max-size-bytes=0 max-size-time=0  ! \
    tee name=postproc_tee postproc_tee. ! \
    queue name=display_meta_q leaky=no max-size-buffers=30 max-size-bytes=0 max-size-time=0  ! \
    hailoaggregator name=display_agg context_tee. ! \
    queue name=display_bypass_q leaky=no max-size-buffers=30 max-size-bytes=0 max-size-time=0  ! \
    display_agg.sink_1 display_agg. ! \
    queue name=display_branch_q leaky=no max-size-buffers=30 max-size-bytes=0 max-size-time=0  ! \
    videobox top=1 bottom=1 ! \
    queue name=display_videobox_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0  ! \
    hailooverlay line-thickness=3 font-thickness=1 qos=false ! \
    hailofilter use-gst-buffer=true so-path=/usr/local/hailo/resources/so/liblpr_overlay.so qos=false ! \
    videoconvert ! \
    fpsdisplaysink name=hailo_display video-sink=autovideosink sync=false text-overlay=False signal-fps-measurements=true postproc_tee. ! \
    queue name=final_sink_q leaky=no max-size-buffers=30 max-size-bytes=0 max-size-time=0  ! \
    identity name=identity_callback ! \
    hailofilter use-gst-buffer=true so-path=/usr/local/hailo/resources/so/liblpr_ocrsink.so qos=false ! \
    fakesink sync=false async=false

--- Available Pipeline Variants ---

  --pipeline simple               : Full LPR: Vehicle → Tracker → LP → OCR with display aggregators
  --pipeline complex              : Full LPR: Explicit low-level GStreamer elements <-- CURRENT
  --pipeline optimized            : Full LPR: Parallel display/processing with quality filter
  --pipeline optimized_direct     : Full LPR: Parallel display/processing, no quality filter
  --pipeline candidate            : Full LPR: Hardcoded paths (debugging)
  --pipeline vehicle_and_lp       : Vehicle + LP detection only (no OCR)
  --pipeline vehicle_only         : Vehicle detection only
  --pipeline lp_only              : LP detection on full frame only
  --pipeline lp_only_crops        : LP detection + crop saving (no display)
  --pipeline lp_and_ocr           : Full-frame LP + OCR (no vehicle detection)
  --pipeline lp_and_ocr_direct    : Full-frame LP + OCR with explicit elements
```

---

## Pipeline: `optimized`

```
================================================================================
PIPELINE VARIANT: optimized
================================================================================

--- GStreamer CLI Command ---

gst-launch-1.0 filesrc location="/usr/local/hailo/resources/videos/lpr_video.mp4" name=source ! queue name=source_queue_decode leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! decodebin name=source_decodebin ! queue name=source_scale_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! videoscale name=source_videoscale n-threads=2 ! queue name=source_convert_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! videoconvert n-threads=3 name=source_convert qos=false ! video/x-raw, pixel-aspect-ratio=1/1, format=RGB, width=1280, height=720 ! videorate name=source_videorate ! capsfilter name=source_fps_caps caps="video/x-raw, framerate=30/1" ! queue name=vehicle_wrapper_input_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! hailocropper name=vehicle_wrapper_crop so-path=/usr/lib/x86_64-linux-gnu/hailo/tappas/post_processes/cropping_algorithms/libwhole_buffer.so function-name=create_crops use-letterbox=true resize-method=inter-area internal-offset=true hailoaggregator name=vehicle_wrapper_agg vehicle_wrapper_crop. ! queue name=vehicle_wrapper_bypass_q leaky=no max-size-buffers=30 max-size-bytes=0 max-size-time=0 ! vehicle_wrapper_agg.sink_0 vehicle_wrapper_crop. ! queue name=vehicle_detection_scale_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! videoscale name=vehicle_detection_videoscale n-threads=2 qos=false ! queue name=vehicle_detection_convert_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! video/x-raw, pixel-aspect-ratio=1/1 ! videoconvert name=vehicle_detection_videoconvert n-threads=2 ! queue name=vehicle_detection_hailonet_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! hailonet name=vehicle_detection_hailonet hef-path=/usr/local/hailo/resources/models/hailo8/yolov5m_vehicles.hef batch-size=2 vdevice-group-id=SHARED scheduler-timeout-ms=100 nms-score-threshold=0.3 nms-iou-threshold=0.45 output-format-type=HAILO_FORMAT_TYPE_FLOAT32 force-writable=true ! queue name=vehicle_detection_hailofilter_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! hailofilter name=vehicle_detection_hailofilter so-path=/usr/local/hailo/resources/so/libyolo_hailortpp_postprocess.so config-path=/home/omria/hailo/dev/lpr/hailo-apps-infra/hailo_apps/python/pipeline_apps/license_plate_recognition/configs/yolov5m_vehicles.json function-name=yolov5m_vehicles qos=false ! queue name=vehicle_detection_output_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! vehicle_wrapper_agg.sink_1 vehicle_wrapper_agg. ! queue name=vehicle_wrapper_output_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! hailotracker name=vehicle_tracker class-id=-1 kalman-dist-thr=0.5 iou-thr=0.6 init-iou-thr=0.7 keep-new-frames=2 keep-tracked-frames=5 keep-lost-frames=3 keep-past-metadata=True qos=False ! queue name=vehicle_tracker_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! tee name=main_tee main_tee. ! queue name=display_q leaky=downstream max-size-buffers=10 max-size-bytes=0 max-size-time=0 ! queue name=hailo_display_overlay_q leaky=downstream max-size-buffers=10 max-size-bytes=0 max-size-time=0 ! hailooverlay name=hailo_display_overlay ! queue name=hailo_display_videoconvert_q leaky=downstream max-size-buffers=10 max-size-bytes=0 max-size-time=0 ! videoconvert name=hailo_display_videoconvert n-threads=2 qos=false ! queue name=hailo_display_q leaky=downstream max-size-buffers=10 max-size-bytes=0 max-size-time=0 ! fpsdisplaysink name=hailo_display video-sink=autovideosink sync=false text-overlay=False signal-fps-measurements=true main_tee. ! queue name=processing_q leaky=no max-size-buffers=10 max-size-bytes=0 max-size-time=0 ! queue name=vehicle_cropper_input_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! hailocropper name=vehicle_cropper_cropper so-path=/usr/local/hailo/resources/so/liblpr_croppers.so function-name=vehicles_without_ocr use-letterbox=true no-scaling-bbox=true internal-offset=true resize-method=bilinear hailoaggregator name=vehicle_cropper_agg vehicle_cropper_cropper. ! queue name=vehicle_cropper_bypass_q leaky=downstream max-size-buffers=30 max-size-bytes=0 max-size-time=0 ! vehicle_cropper_agg.sink_0 vehicle_cropper_cropper. ! queue name=plate_detection_scale_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! videoscale name=plate_detection_videoscale n-threads=2 qos=false ! queue name=plate_detection_convert_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! video/x-raw, pixel-aspect-ratio=1/1 ! videoconvert name=plate_detection_videoconvert n-threads=2 ! queue name=plate_detection_hailonet_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! hailonet name=plate_detection_hailonet hef-path=/usr/local/hailo/resources/models/hailo8/yolov8n_relu6_global_lp_det.hef batch-size=4 vdevice-group-id=SHARED scheduler-timeout-ms=100 nms-score-threshold=0.3 nms-iou-threshold=0.45 output-format-type=HAILO_FORMAT_TYPE_FLOAT32 force-writable=true ! queue name=plate_detection_hailofilter_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! hailofilter name=plate_detection_hailofilter so-path=/usr/local/hailo/resources/so/libyolo_hailortpp_postprocess.so config-path=/home/omria/hailo/dev/lpr/hailo-apps-infra/hailo_apps/python/pipeline_apps/license_plate_recognition/configs/yolov8n_relu6_global_lp_det.json function-name=yolov8n_relu6_license_plate qos=false ! queue name=plate_detection_output_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! vehicle_cropper_agg.sink_1 vehicle_cropper_agg. ! queue name=vehicle_cropper_output_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! queue name=pre_lp_crop_q leaky=no max-size-buffers=10 max-size-bytes=0 max-size-time=0 ! queue name=lp_cropper_input_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! hailocropper name=lp_cropper_cropper so-path=/usr/local/hailo/resources/so/liblpr_croppers.so function-name=license_plate_no_quality use-letterbox=true no-scaling-bbox=true internal-offset=true resize-method=bilinear hailoaggregator name=lp_cropper_agg lp_cropper_cropper. ! queue name=lp_cropper_bypass_q leaky=downstream max-size-buffers=30 max-size-bytes=0 max-size-time=0 ! lp_cropper_agg.sink_0 lp_cropper_cropper. ! queue name=ocr_detection_scale_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! videoscale name=ocr_detection_videoscale n-threads=2 qos=false ! queue name=ocr_detection_convert_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! video/x-raw, pixel-aspect-ratio=1/1 ! videoconvert name=ocr_detection_videoconvert n-threads=2 ! queue name=ocr_detection_hailonet_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! hailonet name=ocr_detection_hailonet hef-path=/usr/local/hailo/resources/models/hailo8/ocr.hef batch-size=8 vdevice-group-id=SHARED scheduler-timeout-ms=100 force-writable=true ! queue name=ocr_detection_hailofilter_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! hailofilter name=ocr_detection_hailofilter so-path=/usr/local/hailo/resources/so/libocr_postprocess.so function-name=paddleocr_recognize qos=false ! queue name=ocr_detection_output_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! lp_cropper_agg.sink_1 lp_cropper_agg. ! queue name=lp_cropper_output_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! queue name=post_ocr_q leaky=no max-size-buffers=5 max-size-bytes=0 max-size-time=0 ! identity name=identity_callback ! hailofilter use-gst-buffer=true so-path=/usr/local/hailo/resources/so/liblpr_ocrsink.so qos=false ! fakesink sync=false async=false

--- Pipeline String (formatted) ---

gst-launch-1.0 \
    filesrc location="/usr/local/hailo/resources/videos/lpr_video.mp4" name=source ! \
    queue name=source_queue_decode leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0  ! \
    decodebin name=source_decodebin ! \
     queue name=source_scale_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0  ! \
    videoscale name=source_videoscale n-threads=2 ! \
    queue name=source_convert_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0  ! \
    videoconvert n-threads=3 name=source_convert qos=false ! \
    video/x-raw, pixel-aspect-ratio=1/1, format=RGB, width=1280, height=720 ! \
    videorate name=source_videorate ! \
    capsfilter name=source_fps_caps caps="video/x-raw, framerate=30/1"  ! \
    queue name=vehicle_wrapper_input_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0  ! \
    hailocropper name=vehicle_wrapper_crop so-path=/usr/lib/x86_64-linux-gnu/hailo/tappas/post_processes/cropping_algorithms/libwhole_buffer.so function-name=create_crops use-letterbox=true resize-method=inter-area internal-offset=true hailoaggregator name=vehicle_wrapper_agg vehicle_wrapper_crop. ! \
    queue name=vehicle_wrapper_bypass_q leaky=no max-size-buffers=30 max-size-bytes=0 max-size-time=0  ! \
    vehicle_wrapper_agg.sink_0 vehicle_wrapper_crop. ! \
    queue name=vehicle_detection_scale_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0  ! \
    videoscale name=vehicle_detection_videoscale n-threads=2 qos=false ! \
    queue name=vehicle_detection_convert_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0  ! \
    video/x-raw, pixel-aspect-ratio=1/1 ! \
    videoconvert name=vehicle_detection_videoconvert n-threads=2 ! \
    queue name=vehicle_detection_hailonet_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0  ! \
    hailonet name=vehicle_detection_hailonet hef-path=/usr/local/hailo/resources/models/hailo8/yolov5m_vehicles.hef batch-size=2  vdevice-group-id=SHARED  scheduler-timeout-ms=100 nms-score-threshold=0.3 nms-iou-threshold=0.45 output-format-type=HAILO_FORMAT_TYPE_FLOAT32 force-writable=true  ! \
    queue name=vehicle_detection_hailofilter_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0  ! \
    hailofilter name=vehicle_detection_hailofilter so-path=/usr/local/hailo/resources/so/libyolo_hailortpp_postprocess.so  config-path=/home/omria/hailo/dev/lpr/hailo-apps-infra/hailo_apps/python/pipeline_apps/license_plate_recognition/configs/yolov5m_vehicles.json   function-name=yolov5m_vehicles  qos=false ! \
    queue name=vehicle_detection_output_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0   ! \
    vehicle_wrapper_agg.sink_1 vehicle_wrapper_agg. ! \
    queue name=vehicle_wrapper_output_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0   ! \
    hailotracker name=vehicle_tracker class-id=-1 kalman-dist-thr=0.5 iou-thr=0.6 init-iou-thr=0.7 keep-new-frames=2 keep-tracked-frames=5 keep-lost-frames=3 keep-past-metadata=True qos=False ! \
    queue name=vehicle_tracker_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0   ! \
    tee name=main_tee main_tee. ! \
    queue name=display_q leaky=downstream max-size-buffers=10 max-size-bytes=0 max-size-time=0  ! \
    queue name=hailo_display_overlay_q leaky=downstream max-size-buffers=10 max-size-bytes=0 max-size-time=0  ! \
    hailooverlay name=hailo_display_overlay  ! \
    queue name=hailo_display_videoconvert_q leaky=downstream max-size-buffers=10 max-size-bytes=0 max-size-time=0  ! \
    videoconvert name=hailo_display_videoconvert n-threads=2 qos=false ! \
    queue name=hailo_display_q leaky=downstream max-size-buffers=10 max-size-bytes=0 max-size-time=0  ! \
    fpsdisplaysink name=hailo_display video-sink=autovideosink sync=false text-overlay=False signal-fps-measurements=true  main_tee. ! \
    queue name=processing_q leaky=no max-size-buffers=10 max-size-bytes=0 max-size-time=0  ! \
    queue name=vehicle_cropper_input_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0  ! \
    hailocropper name=vehicle_cropper_cropper so-path=/usr/local/hailo/resources/so/liblpr_croppers.so function-name=vehicles_without_ocr use-letterbox=true no-scaling-bbox=true internal-offset=true resize-method=bilinear hailoaggregator name=vehicle_cropper_agg vehicle_cropper_cropper. ! \
    queue name=vehicle_cropper_bypass_q leaky=downstream max-size-buffers=30 max-size-bytes=0 max-size-time=0  ! \
    vehicle_cropper_agg.sink_0 vehicle_cropper_cropper. ! \
    queue name=plate_detection_scale_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0  ! \
    videoscale name=plate_detection_videoscale n-threads=2 qos=false ! \
    queue name=plate_detection_convert_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0  ! \
    video/x-raw, pixel-aspect-ratio=1/1 ! \
    videoconvert name=plate_detection_videoconvert n-threads=2 ! \
    queue name=plate_detection_hailonet_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0  ! \
    hailonet name=plate_detection_hailonet hef-path=/usr/local/hailo/resources/models/hailo8/yolov8n_relu6_global_lp_det.hef batch-size=4  vdevice-group-id=SHARED  scheduler-timeout-ms=100 nms-score-threshold=0.3 nms-iou-threshold=0.45 output-format-type=HAILO_FORMAT_TYPE_FLOAT32 force-writable=true  ! \
    queue name=plate_detection_hailofilter_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0  ! \
    hailofilter name=plate_detection_hailofilter so-path=/usr/local/hailo/resources/so/libyolo_hailortpp_postprocess.so  config-path=/home/omria/hailo/dev/lpr/hailo-apps-infra/hailo_apps/python/pipeline_apps/license_plate_recognition/configs/yolov8n_relu6_global_lp_det.json   function-name=yolov8n_relu6_license_plate  qos=false ! \
    queue name=plate_detection_output_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0   ! \
    vehicle_cropper_agg.sink_1 vehicle_cropper_agg. ! \
    queue name=vehicle_cropper_output_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0   ! \
    queue name=pre_lp_crop_q leaky=no max-size-buffers=10 max-size-bytes=0 max-size-time=0  ! \
    queue name=lp_cropper_input_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0  ! \
    hailocropper name=lp_cropper_cropper so-path=/usr/local/hailo/resources/so/liblpr_croppers.so function-name=license_plate_no_quality use-letterbox=true no-scaling-bbox=true internal-offset=true resize-method=bilinear hailoaggregator name=lp_cropper_agg lp_cropper_cropper. ! \
    queue name=lp_cropper_bypass_q leaky=downstream max-size-buffers=30 max-size-bytes=0 max-size-time=0  ! \
    lp_cropper_agg.sink_0 lp_cropper_cropper. ! \
    queue name=ocr_detection_scale_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0  ! \
    videoscale name=ocr_detection_videoscale n-threads=2 qos=false ! \
    queue name=ocr_detection_convert_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0  ! \
    video/x-raw, pixel-aspect-ratio=1/1 ! \
    videoconvert name=ocr_detection_videoconvert n-threads=2 ! \
    queue name=ocr_detection_hailonet_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0  ! \
    hailonet name=ocr_detection_hailonet hef-path=/usr/local/hailo/resources/models/hailo8/ocr.hef batch-size=8  vdevice-group-id=SHARED  scheduler-timeout-ms=100  force-writable=true  ! \
    queue name=ocr_detection_hailofilter_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0  ! \
    hailofilter name=ocr_detection_hailofilter so-path=/usr/local/hailo/resources/so/libocr_postprocess.so   function-name=paddleocr_recognize  qos=false ! \
    queue name=ocr_detection_output_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0   ! \
    lp_cropper_agg.sink_1 lp_cropper_agg. ! \
    queue name=lp_cropper_output_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0   ! \
    queue name=post_ocr_q leaky=no max-size-buffers=5 max-size-bytes=0 max-size-time=0  ! \
    identity name=identity_callback ! \
    hailofilter use-gst-buffer=true so-path=/usr/local/hailo/resources/so/liblpr_ocrsink.so qos=false ! \
    fakesink sync=false async=false

--- Available Pipeline Variants ---

  --pipeline simple               : Full LPR: Vehicle → Tracker → LP → OCR with display aggregators
  --pipeline complex              : Full LPR: Explicit low-level GStreamer elements
  --pipeline optimized            : Full LPR: Parallel display/processing with quality filter <-- CURRENT
  --pipeline optimized_direct     : Full LPR: Parallel display/processing, no quality filter
  --pipeline candidate            : Full LPR: Hardcoded paths (debugging)
  --pipeline vehicle_and_lp       : Vehicle + LP detection only (no OCR)
  --pipeline vehicle_only         : Vehicle detection only
  --pipeline lp_only              : LP detection on full frame only
  --pipeline lp_only_crops        : LP detection + crop saving (no display)
  --pipeline lp_and_ocr           : Full-frame LP + OCR (no vehicle detection)
  --pipeline lp_and_ocr_direct    : Full-frame LP + OCR with explicit elements
```

---

## Pipeline: `optimized_direct`

```
================================================================================
PIPELINE VARIANT: optimized_direct
================================================================================

--- GStreamer CLI Command ---

gst-launch-1.0 filesrc location="/usr/local/hailo/resources/videos/lpr_video.mp4" name=source ! queue name=source_queue_decode leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! decodebin name=source_decodebin ! queue name=source_scale_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! videoscale name=source_videoscale n-threads=2 ! queue name=source_convert_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! videoconvert n-threads=3 name=source_convert qos=false ! video/x-raw, pixel-aspect-ratio=1/1, format=RGB, width=1280, height=720 ! videorate name=source_videorate ! capsfilter name=source_fps_caps caps="video/x-raw, framerate=30/1" ! queue name=vehicle_wrapper_input_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! hailocropper name=vehicle_wrapper_crop so-path=/usr/lib/x86_64-linux-gnu/hailo/tappas/post_processes/cropping_algorithms/libwhole_buffer.so function-name=create_crops use-letterbox=true resize-method=inter-area internal-offset=true hailoaggregator name=vehicle_wrapper_agg vehicle_wrapper_crop. ! queue name=vehicle_wrapper_bypass_q leaky=no max-size-buffers=30 max-size-bytes=0 max-size-time=0 ! vehicle_wrapper_agg.sink_0 vehicle_wrapper_crop. ! queue name=vehicle_detection_scale_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! videoscale name=vehicle_detection_videoscale n-threads=2 qos=false ! queue name=vehicle_detection_convert_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! video/x-raw, pixel-aspect-ratio=1/1 ! videoconvert name=vehicle_detection_videoconvert n-threads=2 ! queue name=vehicle_detection_hailonet_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! hailonet name=vehicle_detection_hailonet hef-path=/usr/local/hailo/resources/models/hailo8/yolov5m_vehicles.hef batch-size=2 vdevice-group-id=SHARED scheduler-timeout-ms=100 nms-score-threshold=0.3 nms-iou-threshold=0.45 output-format-type=HAILO_FORMAT_TYPE_FLOAT32 force-writable=true ! queue name=vehicle_detection_hailofilter_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! hailofilter name=vehicle_detection_hailofilter so-path=/usr/local/hailo/resources/so/libyolo_hailortpp_postprocess.so config-path=/home/omria/hailo/dev/lpr/hailo-apps-infra/hailo_apps/python/pipeline_apps/license_plate_recognition/configs/yolov5m_vehicles.json function-name=yolov5m_vehicles qos=false ! queue name=vehicle_detection_output_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! vehicle_wrapper_agg.sink_1 vehicle_wrapper_agg. ! queue name=vehicle_wrapper_output_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! hailotracker name=vehicle_tracker class-id=-1 kalman-dist-thr=0.5 iou-thr=0.6 init-iou-thr=0.7 keep-new-frames=2 keep-tracked-frames=5 keep-lost-frames=3 keep-past-metadata=True qos=False ! queue name=vehicle_tracker_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! tee name=main_tee main_tee. ! queue name=display_q leaky=downstream max-size-buffers=10 max-size-bytes=0 max-size-time=0 ! queue name=hailo_display_overlay_q leaky=downstream max-size-buffers=10 max-size-bytes=0 max-size-time=0 ! hailooverlay name=hailo_display_overlay ! queue name=hailo_display_videoconvert_q leaky=downstream max-size-buffers=10 max-size-bytes=0 max-size-time=0 ! videoconvert name=hailo_display_videoconvert n-threads=2 qos=false ! queue name=hailo_display_q leaky=downstream max-size-buffers=10 max-size-bytes=0 max-size-time=0 ! fpsdisplaysink name=hailo_display video-sink=autovideosink sync=false text-overlay=False signal-fps-measurements=true main_tee. ! queue name=processing_q leaky=no max-size-buffers=10 max-size-bytes=0 max-size-time=0 ! queue name=vehicle_cropper_input_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! hailocropper name=vehicle_cropper_cropper so-path=/usr/local/hailo/resources/so/liblpr_croppers.so function-name=vehicles_without_ocr use-letterbox=true no-scaling-bbox=true internal-offset=true resize-method=bilinear hailoaggregator name=vehicle_cropper_agg vehicle_cropper_cropper. ! queue name=vehicle_cropper_bypass_q leaky=downstream max-size-buffers=30 max-size-bytes=0 max-size-time=0 ! vehicle_cropper_agg.sink_0 vehicle_cropper_cropper. ! queue name=plate_detection_scale_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! videoscale name=plate_detection_videoscale n-threads=2 qos=false ! queue name=plate_detection_convert_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! video/x-raw, pixel-aspect-ratio=1/1 ! videoconvert name=plate_detection_videoconvert n-threads=2 ! queue name=plate_detection_hailonet_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! hailonet name=plate_detection_hailonet hef-path=/usr/local/hailo/resources/models/hailo8/yolov8n_relu6_global_lp_det.hef batch-size=4 vdevice-group-id=SHARED scheduler-timeout-ms=100 nms-score-threshold=0.3 nms-iou-threshold=0.45 output-format-type=HAILO_FORMAT_TYPE_FLOAT32 force-writable=true ! queue name=plate_detection_hailofilter_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! hailofilter name=plate_detection_hailofilter so-path=/usr/local/hailo/resources/so/libyolo_hailortpp_postprocess.so config-path=/home/omria/hailo/dev/lpr/hailo-apps-infra/hailo_apps/python/pipeline_apps/license_plate_recognition/configs/yolov8n_relu6_global_lp_det.json function-name=yolov8n_relu6_license_plate qos=false ! queue name=plate_detection_output_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! vehicle_cropper_agg.sink_1 vehicle_cropper_agg. ! queue name=vehicle_cropper_output_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! queue name=pre_lp_crop_q leaky=no max-size-buffers=10 max-size-bytes=0 max-size-time=0 ! queue name=lp_cropper_input_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! hailocropper name=lp_cropper_cropper so-path=/usr/local/hailo/resources/so/liblpr_croppers.so function-name=license_plate_no_quality use-letterbox=true no-scaling-bbox=true internal-offset=true resize-method=bilinear hailoaggregator name=lp_cropper_agg lp_cropper_cropper. ! queue name=lp_cropper_bypass_q leaky=downstream max-size-buffers=30 max-size-bytes=0 max-size-time=0 ! lp_cropper_agg.sink_0 lp_cropper_cropper. ! queue name=ocr_detection_scale_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! videoscale name=ocr_detection_videoscale n-threads=2 qos=false ! queue name=ocr_detection_convert_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! video/x-raw, pixel-aspect-ratio=1/1 ! videoconvert name=ocr_detection_videoconvert n-threads=2 ! queue name=ocr_detection_hailonet_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! hailonet name=ocr_detection_hailonet hef-path=/usr/local/hailo/resources/models/hailo8/ocr.hef batch-size=8 vdevice-group-id=SHARED scheduler-timeout-ms=100 force-writable=true ! queue name=ocr_detection_hailofilter_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! hailofilter name=ocr_detection_hailofilter so-path=/usr/local/hailo/resources/so/libocr_postprocess.so function-name=paddleocr_recognize qos=false ! queue name=ocr_detection_output_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! lp_cropper_agg.sink_1 lp_cropper_agg. ! queue name=lp_cropper_output_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! queue name=post_ocr_q leaky=no max-size-buffers=5 max-size-bytes=0 max-size-time=0 ! identity name=identity_callback ! hailofilter use-gst-buffer=true so-path=/usr/local/hailo/resources/so/liblpr_ocrsink.so qos=false ! fakesink sync=false async=false

--- Pipeline String (formatted) ---

gst-launch-1.0 \
    filesrc location="/usr/local/hailo/resources/videos/lpr_video.mp4" name=source ! \
    queue name=source_queue_decode leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0  ! \
    decodebin name=source_decodebin ! \
     queue name=source_scale_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0  ! \
    videoscale name=source_videoscale n-threads=2 ! \
    queue name=source_convert_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0  ! \
    videoconvert n-threads=3 name=source_convert qos=false ! \
    video/x-raw, pixel-aspect-ratio=1/1, format=RGB, width=1280, height=720 ! \
    videorate name=source_videorate ! \
    capsfilter name=source_fps_caps caps="video/x-raw, framerate=30/1"  ! \
    queue name=vehicle_wrapper_input_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0  ! \
    hailocropper name=vehicle_wrapper_crop so-path=/usr/lib/x86_64-linux-gnu/hailo/tappas/post_processes/cropping_algorithms/libwhole_buffer.so function-name=create_crops use-letterbox=true resize-method=inter-area internal-offset=true hailoaggregator name=vehicle_wrapper_agg vehicle_wrapper_crop. ! \
    queue name=vehicle_wrapper_bypass_q leaky=no max-size-buffers=30 max-size-bytes=0 max-size-time=0  ! \
    vehicle_wrapper_agg.sink_0 vehicle_wrapper_crop. ! \
    queue name=vehicle_detection_scale_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0  ! \
    videoscale name=vehicle_detection_videoscale n-threads=2 qos=false ! \
    queue name=vehicle_detection_convert_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0  ! \
    video/x-raw, pixel-aspect-ratio=1/1 ! \
    videoconvert name=vehicle_detection_videoconvert n-threads=2 ! \
    queue name=vehicle_detection_hailonet_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0  ! \
    hailonet name=vehicle_detection_hailonet hef-path=/usr/local/hailo/resources/models/hailo8/yolov5m_vehicles.hef batch-size=2  vdevice-group-id=SHARED  scheduler-timeout-ms=100 nms-score-threshold=0.3 nms-iou-threshold=0.45 output-format-type=HAILO_FORMAT_TYPE_FLOAT32 force-writable=true  ! \
    queue name=vehicle_detection_hailofilter_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0  ! \
    hailofilter name=vehicle_detection_hailofilter so-path=/usr/local/hailo/resources/so/libyolo_hailortpp_postprocess.so  config-path=/home/omria/hailo/dev/lpr/hailo-apps-infra/hailo_apps/python/pipeline_apps/license_plate_recognition/configs/yolov5m_vehicles.json   function-name=yolov5m_vehicles  qos=false ! \
    queue name=vehicle_detection_output_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0   ! \
    vehicle_wrapper_agg.sink_1 vehicle_wrapper_agg. ! \
    queue name=vehicle_wrapper_output_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0   ! \
    hailotracker name=vehicle_tracker class-id=-1 kalman-dist-thr=0.5 iou-thr=0.6 init-iou-thr=0.7 keep-new-frames=2 keep-tracked-frames=5 keep-lost-frames=3 keep-past-metadata=True qos=False ! \
    queue name=vehicle_tracker_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0   ! \
    tee name=main_tee main_tee. ! \
    queue name=display_q leaky=downstream max-size-buffers=10 max-size-bytes=0 max-size-time=0  ! \
    queue name=hailo_display_overlay_q leaky=downstream max-size-buffers=10 max-size-bytes=0 max-size-time=0  ! \
    hailooverlay name=hailo_display_overlay  ! \
    queue name=hailo_display_videoconvert_q leaky=downstream max-size-buffers=10 max-size-bytes=0 max-size-time=0  ! \
    videoconvert name=hailo_display_videoconvert n-threads=2 qos=false ! \
    queue name=hailo_display_q leaky=downstream max-size-buffers=10 max-size-bytes=0 max-size-time=0  ! \
    fpsdisplaysink name=hailo_display video-sink=autovideosink sync=false text-overlay=False signal-fps-measurements=true  main_tee. ! \
    queue name=processing_q leaky=no max-size-buffers=10 max-size-bytes=0 max-size-time=0  ! \
    queue name=vehicle_cropper_input_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0  ! \
    hailocropper name=vehicle_cropper_cropper so-path=/usr/local/hailo/resources/so/liblpr_croppers.so function-name=vehicles_without_ocr use-letterbox=true no-scaling-bbox=true internal-offset=true resize-method=bilinear hailoaggregator name=vehicle_cropper_agg vehicle_cropper_cropper. ! \
    queue name=vehicle_cropper_bypass_q leaky=downstream max-size-buffers=30 max-size-bytes=0 max-size-time=0  ! \
    vehicle_cropper_agg.sink_0 vehicle_cropper_cropper. ! \
    queue name=plate_detection_scale_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0  ! \
    videoscale name=plate_detection_videoscale n-threads=2 qos=false ! \
    queue name=plate_detection_convert_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0  ! \
    video/x-raw, pixel-aspect-ratio=1/1 ! \
    videoconvert name=plate_detection_videoconvert n-threads=2 ! \
    queue name=plate_detection_hailonet_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0  ! \
    hailonet name=plate_detection_hailonet hef-path=/usr/local/hailo/resources/models/hailo8/yolov8n_relu6_global_lp_det.hef batch-size=4  vdevice-group-id=SHARED  scheduler-timeout-ms=100 nms-score-threshold=0.3 nms-iou-threshold=0.45 output-format-type=HAILO_FORMAT_TYPE_FLOAT32 force-writable=true  ! \
    queue name=plate_detection_hailofilter_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0  ! \
    hailofilter name=plate_detection_hailofilter so-path=/usr/local/hailo/resources/so/libyolo_hailortpp_postprocess.so  config-path=/home/omria/hailo/dev/lpr/hailo-apps-infra/hailo_apps/python/pipeline_apps/license_plate_recognition/configs/yolov8n_relu6_global_lp_det.json   function-name=yolov8n_relu6_license_plate  qos=false ! \
    queue name=plate_detection_output_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0   ! \
    vehicle_cropper_agg.sink_1 vehicle_cropper_agg. ! \
    queue name=vehicle_cropper_output_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0   ! \
    queue name=pre_lp_crop_q leaky=no max-size-buffers=10 max-size-bytes=0 max-size-time=0  ! \
    queue name=lp_cropper_input_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0  ! \
    hailocropper name=lp_cropper_cropper so-path=/usr/local/hailo/resources/so/liblpr_croppers.so function-name=license_plate_no_quality use-letterbox=true no-scaling-bbox=true internal-offset=true resize-method=bilinear hailoaggregator name=lp_cropper_agg lp_cropper_cropper. ! \
    queue name=lp_cropper_bypass_q leaky=downstream max-size-buffers=30 max-size-bytes=0 max-size-time=0  ! \
    lp_cropper_agg.sink_0 lp_cropper_cropper. ! \
    queue name=ocr_detection_scale_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0  ! \
    videoscale name=ocr_detection_videoscale n-threads=2 qos=false ! \
    queue name=ocr_detection_convert_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0  ! \
    video/x-raw, pixel-aspect-ratio=1/1 ! \
    videoconvert name=ocr_detection_videoconvert n-threads=2 ! \
    queue name=ocr_detection_hailonet_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0  ! \
    hailonet name=ocr_detection_hailonet hef-path=/usr/local/hailo/resources/models/hailo8/ocr.hef batch-size=8  vdevice-group-id=SHARED  scheduler-timeout-ms=100  force-writable=true  ! \
    queue name=ocr_detection_hailofilter_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0  ! \
    hailofilter name=ocr_detection_hailofilter so-path=/usr/local/hailo/resources/so/libocr_postprocess.so   function-name=paddleocr_recognize  qos=false ! \
    queue name=ocr_detection_output_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0   ! \
    lp_cropper_agg.sink_1 lp_cropper_agg. ! \
    queue name=lp_cropper_output_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0   ! \
    queue name=post_ocr_q leaky=no max-size-buffers=5 max-size-bytes=0 max-size-time=0  ! \
    identity name=identity_callback ! \
    hailofilter use-gst-buffer=true so-path=/usr/local/hailo/resources/so/liblpr_ocrsink.so qos=false ! \
    fakesink sync=false async=false

--- Available Pipeline Variants ---

  --pipeline simple               : Full LPR: Vehicle → Tracker → LP → OCR with display aggregators
  --pipeline complex              : Full LPR: Explicit low-level GStreamer elements
  --pipeline optimized            : Full LPR: Parallel display/processing with quality filter
  --pipeline optimized_direct     : Full LPR: Parallel display/processing, no quality filter <-- CURRENT
  --pipeline candidate            : Full LPR: Hardcoded paths (debugging)
  --pipeline vehicle_and_lp       : Vehicle + LP detection only (no OCR)
  --pipeline vehicle_only         : Vehicle detection only
  --pipeline lp_only              : LP detection on full frame only
  --pipeline lp_only_crops        : LP detection + crop saving (no display)
  --pipeline lp_and_ocr           : Full-frame LP + OCR (no vehicle detection)
  --pipeline lp_and_ocr_direct    : Full-frame LP + OCR with explicit elements
```

---

## Pipeline: `candidate`

```
================================================================================
PIPELINE VARIANT: candidate
================================================================================

--- GStreamer CLI Command ---

gst-launch-1.0 filesrc location="/usr/local/hailo/resources/videos/lpr_video.mp4" name=source ! queue name=source_queue_decode leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! decodebin name=source_decodebin ! queue name=source_scale_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! videoscale name=source_videoscale n-threads=2 ! queue name=source_convert_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! videoconvert n-threads=3 name=source_convert qos=true ! video/x-raw, pixel-aspect-ratio=1/1, format=RGB, width=1280, height=720 ! videorate name=source_videorate ! capsfilter name=source_fps_caps caps="video/x-raw, framerate=15/1" ! queue name=vehicle_wrapper_input_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! hailocropper name=vehicle_wrapper_crop so-path=/usr/lib/x86_64-linux-gnu/hailo/tappas/post_processes/cropping_algorithms/libwhole_buffer.so function-name=create_crops use-letterbox=true resize-method=inter-area internal-offset=true hailoaggregator name=vehicle_wrapper_agg vehicle_wrapper_crop. ! queue name=vehicle_wrapper_bypass_q leaky=no max-size-buffers=30 max-size-bytes=0 max-size-time=0 ! vehicle_wrapper_agg.sink_0 vehicle_wrapper_crop. ! queue name=vehicle_detection_scale_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! videoscale name=vehicle_detection_videoscale n-threads=2 qos=true ! queue name=vehicle_detection_convert_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! video/x-raw, pixel-aspect-ratio=1/1 ! videoconvert name=vehicle_detection_videoconvert n-threads=2 qos=true ! queue name=vehicle_detection_hailonet_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! hailonet name=vehicle_detection_hailonet hef-path=/usr/local/hailo/resources/models/hailo8/yolov5m_vehicles.hef batch-size=1 vdevice-group-id=SHARED scheduler-timeout-ms=66 nms-score-threshold=0.3 nms-iou-threshold=0.45 output-format-type=HAILO_FORMAT_TYPE_FLOAT32 force-writable=true ! queue name=vehicle_detection_hailofilter_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! hailofilter name=vehicle_detection_hailofilter so-path=/usr/local/hailo/resources/so/libyolo_hailortpp_postprocess.so config-path=/home/omria/hailo/hailo-apps-infra/hailo_apps/python/pipeline_apps/license_plate_recognition/configs/yolov5m_vehicles.json function-name=yolov5m_vehicles qos=false ! queue name=vehicle_detection_output_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! vehicle_wrapper_agg.sink_1 vehicle_wrapper_agg. ! queue name=vehicle_wrapper_output_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! hailotracker name=vehicle_tracker class-id=-1 kalman-dist-thr=0.5 iou-thr=0.6 init-iou-thr=0.7 keep-new-frames=2 keep-tracked-frames=5 keep-lost-frames=3 keep-past-metadata=True qos=False ! queue name=vehicle_tracker_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! tee name=main_tee main_tee. ! queue name=lpr_display_q leaky=downstream max-size-buffers=10 max-size-bytes=0 max-size-time=50000000 ! hailooverlay name=lpr_display_overlay line-thickness=3 font-thickness=1 qos=false ! hailofilter use-gst-buffer=true so-path=/usr/local/hailo/resources/so/liblpr_overlay.so qos=false ! queue name=lpr_display_convert_q leaky=downstream max-size-buffers=10 max-size-bytes=0 max-size-time=50000000 ! videoconvert name=lpr_display_videoconvert n-threads=2 qos=true ! queue name=lpr_display_sink_q leaky=downstream max-size-buffers=10 max-size-bytes=0 max-size-time=50000000 ! fpsdisplaysink name=lpr_display video-sink=autovideosink sync=false text-overlay=False signal-fps-measurements=true main_tee. ! queue name=processing_q leaky=downstream max-size-buffers=4 max-size-bytes=0 max-size-time=50000000 ! queue name=vehicle_cropper_input_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! hailocropper name=vehicle_cropper_cropper so-path=/usr/local/hailo/resources/so/liblpr_croppers.so function-name=vehicles_without_ocr use-letterbox=true no-scaling-bbox=true internal-offset=true resize-method=bilinear hailoaggregator name=vehicle_cropper_agg vehicle_cropper_cropper. ! queue name=vehicle_cropper_bypass_q leaky=downstream max-size-buffers=30 max-size-bytes=0 max-size-time=0 ! vehicle_cropper_agg.sink_0 vehicle_cropper_cropper. ! queue name=plate_detection_scale_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! videoscale name=plate_detection_videoscale n-threads=2 qos=true ! queue name=plate_detection_convert_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! video/x-raw, pixel-aspect-ratio=1/1 ! videoconvert name=plate_detection_videoconvert n-threads=2 qos=true ! queue name=plate_detection_hailonet_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! hailonet name=plate_detection_hailonet hef-path=/usr/local/hailo/resources/models/hailo8/yolov8n_relu6_global_lp_det.hef batch-size=2 vdevice-group-id=SHARED scheduler-timeout-ms=66 nms-score-threshold=0.3 nms-iou-threshold=0.45 output-format-type=HAILO_FORMAT_TYPE_FLOAT32 force-writable=true ! queue name=plate_detection_hailofilter_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! hailofilter name=plate_detection_hailofilter so-path=/usr/local/hailo/resources/so/libyolo_hailortpp_postprocess.so config-path=/home/omria/hailo/hailo-apps-infra/hailo_apps/python/pipeline_apps/license_plate_recognition/configs/yolov8n_relu6_global_lp_det.json function-name=yolov8n_relu6_license_plate qos=false ! queue name=plate_detection_output_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! vehicle_cropper_agg.sink_1 vehicle_cropper_agg. ! queue name=vehicle_cropper_output_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! queue name=pre_lp_crop_q leaky=downstream max-size-buffers=4 max-size-bytes=0 max-size-time=50000000 ! queue name=lp_cropper_input_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! hailocropper name=lp_cropper_cropper so-path=/usr/local/hailo/resources/so/liblpr_croppers.so function-name=license_plate_no_quality use-letterbox=true no-scaling-bbox=true internal-offset=true resize-method=bilinear hailoaggregator name=lp_cropper_agg lp_cropper_cropper. ! queue name=lp_cropper_bypass_q leaky=downstream max-size-buffers=30 max-size-bytes=0 max-size-time=0 ! lp_cropper_agg.sink_0 lp_cropper_cropper. ! queue name=ocr_detection_scale_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! videoscale name=ocr_detection_videoscale n-threads=2 qos=true ! queue name=ocr_detection_convert_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! video/x-raw, pixel-aspect-ratio=1/1 ! videoconvert name=ocr_detection_videoconvert n-threads=2 qos=true ! queue name=ocr_detection_hailonet_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! hailonet name=ocr_detection_hailonet hef-path=/usr/local/hailo/resources/models/hailo8/ocr.hef batch-size=2 vdevice-group-id=SHARED scheduler-timeout-ms=66 force-writable=true ! queue name=ocr_detection_hailofilter_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! hailofilter name=ocr_detection_hailofilter so-path=/usr/local/hailo/resources/so/libocr_postprocess.so function-name=paddleocr_recognize qos=false ! queue name=ocr_detection_output_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! lp_cropper_agg.sink_1 lp_cropper_agg. ! queue name=lp_cropper_output_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! queue name=post_ocr_q leaky=downstream max-size-buffers=2 max-size-bytes=0 max-size-time=50000000 ! identity name=identity_callback ! hailofilter use-gst-buffer=true so-path=/usr/local/hailo/resources/so/liblpr_ocrsink.so qos=false ! fakesink sync=false async=false

--- Pipeline String (formatted) ---

gst-launch-1.0 \
    filesrc location="/usr/local/hailo/resources/videos/lpr_video.mp4" name=source ! \
    queue name=source_queue_decode leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! \
    decodebin name=source_decodebin ! \
    queue name=source_scale_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! \
    videoscale name=source_videoscale n-threads=2 ! \
    queue name=source_convert_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! \
    videoconvert n-threads=3 name=source_convert qos=true ! \
    video/x-raw, pixel-aspect-ratio=1/1, format=RGB, width=1280, height=720 ! \
    videorate name=source_videorate ! \
    capsfilter name=source_fps_caps caps="video/x-raw, framerate=15/1" ! \
    queue name=vehicle_wrapper_input_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! \
    hailocropper name=vehicle_wrapper_crop so-path=/usr/lib/x86_64-linux-gnu/hailo/tappas/post_processes/cropping_algorithms/libwhole_buffer.so function-name=create_crops use-letterbox=true resize-method=inter-area internal-offset=true hailoaggregator name=vehicle_wrapper_agg vehicle_wrapper_crop. ! \
    queue name=vehicle_wrapper_bypass_q leaky=no max-size-buffers=30 max-size-bytes=0 max-size-time=0 ! \
    vehicle_wrapper_agg.sink_0 vehicle_wrapper_crop. ! \
    queue name=vehicle_detection_scale_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! \
    videoscale name=vehicle_detection_videoscale n-threads=2 qos=true ! \
    queue name=vehicle_detection_convert_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! \
    video/x-raw, pixel-aspect-ratio=1/1 ! \
    videoconvert name=vehicle_detection_videoconvert n-threads=2 qos=true ! \
    queue name=vehicle_detection_hailonet_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! \
    hailonet name=vehicle_detection_hailonet hef-path=/usr/local/hailo/resources/models/hailo8/yolov5m_vehicles.hef batch-size=1 vdevice-group-id=SHARED scheduler-timeout-ms=66 nms-score-threshold=0.3 nms-iou-threshold=0.45 output-format-type=HAILO_FORMAT_TYPE_FLOAT32 force-writable=true ! \
    queue name=vehicle_detection_hailofilter_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! \
    hailofilter name=vehicle_detection_hailofilter so-path=/usr/local/hailo/resources/so/libyolo_hailortpp_postprocess.so config-path=/home/omria/hailo/hailo-apps-infra/hailo_apps/python/pipeline_apps/license_plate_recognition/configs/yolov5m_vehicles.json function-name=yolov5m_vehicles qos=false ! \
    queue name=vehicle_detection_output_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! \
    vehicle_wrapper_agg.sink_1 vehicle_wrapper_agg. ! \
    queue name=vehicle_wrapper_output_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! \
    hailotracker name=vehicle_tracker class-id=-1 kalman-dist-thr=0.5 iou-thr=0.6 init-iou-thr=0.7 keep-new-frames=2 keep-tracked-frames=5 keep-lost-frames=3 keep-past-metadata=True qos=False ! \
    queue name=vehicle_tracker_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! \
    tee name=main_tee main_tee. ! \
    queue name=lpr_display_q leaky=downstream max-size-buffers=10 max-size-bytes=0 max-size-time=50000000 ! \
    hailooverlay name=lpr_display_overlay line-thickness=3 font-thickness=1 qos=false ! \
    hailofilter use-gst-buffer=true so-path=/usr/local/hailo/resources/so/liblpr_overlay.so qos=false ! \
    queue name=lpr_display_convert_q leaky=downstream max-size-buffers=10 max-size-bytes=0 max-size-time=50000000 ! \
    videoconvert name=lpr_display_videoconvert n-threads=2 qos=true ! \
    queue name=lpr_display_sink_q leaky=downstream max-size-buffers=10 max-size-bytes=0 max-size-time=50000000 ! \
    fpsdisplaysink name=lpr_display video-sink=autovideosink sync=false text-overlay=False signal-fps-measurements=true main_tee. ! \
    queue name=processing_q leaky=downstream max-size-buffers=4 max-size-bytes=0 max-size-time=50000000 ! \
    queue name=vehicle_cropper_input_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! \
    hailocropper name=vehicle_cropper_cropper so-path=/usr/local/hailo/resources/so/liblpr_croppers.so function-name=vehicles_without_ocr use-letterbox=true no-scaling-bbox=true internal-offset=true resize-method=bilinear hailoaggregator name=vehicle_cropper_agg vehicle_cropper_cropper. ! \
    queue name=vehicle_cropper_bypass_q leaky=downstream max-size-buffers=30 max-size-bytes=0 max-size-time=0 ! \
    vehicle_cropper_agg.sink_0 vehicle_cropper_cropper. ! \
    queue name=plate_detection_scale_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! \
    videoscale name=plate_detection_videoscale n-threads=2 qos=true ! \
    queue name=plate_detection_convert_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! \
    video/x-raw, pixel-aspect-ratio=1/1 ! \
    videoconvert name=plate_detection_videoconvert n-threads=2 qos=true ! \
    queue name=plate_detection_hailonet_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! \
    hailonet name=plate_detection_hailonet hef-path=/usr/local/hailo/resources/models/hailo8/yolov8n_relu6_global_lp_det.hef batch-size=2 vdevice-group-id=SHARED scheduler-timeout-ms=66 nms-score-threshold=0.3 nms-iou-threshold=0.45 output-format-type=HAILO_FORMAT_TYPE_FLOAT32 force-writable=true ! \
    queue name=plate_detection_hailofilter_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! \
    hailofilter name=plate_detection_hailofilter so-path=/usr/local/hailo/resources/so/libyolo_hailortpp_postprocess.so config-path=/home/omria/hailo/hailo-apps-infra/hailo_apps/python/pipeline_apps/license_plate_recognition/configs/yolov8n_relu6_global_lp_det.json function-name=yolov8n_relu6_license_plate qos=false ! \
    queue name=plate_detection_output_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! \
    vehicle_cropper_agg.sink_1 vehicle_cropper_agg. ! \
    queue name=vehicle_cropper_output_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! \
    queue name=pre_lp_crop_q leaky=downstream max-size-buffers=4 max-size-bytes=0 max-size-time=50000000 ! \
    queue name=lp_cropper_input_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! \
    hailocropper name=lp_cropper_cropper so-path=/usr/local/hailo/resources/so/liblpr_croppers.so function-name=license_plate_no_quality use-letterbox=true no-scaling-bbox=true internal-offset=true resize-method=bilinear hailoaggregator name=lp_cropper_agg lp_cropper_cropper. ! \
    queue name=lp_cropper_bypass_q leaky=downstream max-size-buffers=30 max-size-bytes=0 max-size-time=0 ! \
    lp_cropper_agg.sink_0 lp_cropper_cropper. ! \
    queue name=ocr_detection_scale_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! \
    videoscale name=ocr_detection_videoscale n-threads=2 qos=true ! \
    queue name=ocr_detection_convert_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! \
    video/x-raw, pixel-aspect-ratio=1/1 ! \
    videoconvert name=ocr_detection_videoconvert n-threads=2 qos=true ! \
    queue name=ocr_detection_hailonet_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! \
    hailonet name=ocr_detection_hailonet hef-path=/usr/local/hailo/resources/models/hailo8/ocr.hef batch-size=2 vdevice-group-id=SHARED scheduler-timeout-ms=66 force-writable=true ! \
    queue name=ocr_detection_hailofilter_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! \
    hailofilter name=ocr_detection_hailofilter so-path=/usr/local/hailo/resources/so/libocr_postprocess.so function-name=paddleocr_recognize qos=false ! \
    queue name=ocr_detection_output_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! \
    lp_cropper_agg.sink_1 lp_cropper_agg. ! \
    queue name=lp_cropper_output_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! \
    queue name=post_ocr_q leaky=downstream max-size-buffers=2 max-size-bytes=0 max-size-time=50000000 ! \
    identity name=identity_callback ! \
    hailofilter use-gst-buffer=true so-path=/usr/local/hailo/resources/so/liblpr_ocrsink.so qos=false ! \
    fakesink sync=false async=false

--- Available Pipeline Variants ---

  --pipeline simple               : Full LPR: Vehicle → Tracker → LP → OCR with display aggregators
  --pipeline complex              : Full LPR: Explicit low-level GStreamer elements
  --pipeline optimized            : Full LPR: Parallel display/processing with quality filter
  --pipeline optimized_direct     : Full LPR: Parallel display/processing, no quality filter
  --pipeline candidate            : Full LPR: Hardcoded paths (debugging) <-- CURRENT
  --pipeline vehicle_and_lp       : Vehicle + LP detection only (no OCR)
  --pipeline vehicle_only         : Vehicle detection only
  --pipeline lp_only              : LP detection on full frame only
  --pipeline lp_only_crops        : LP detection + crop saving (no display)
  --pipeline lp_and_ocr           : Full-frame LP + OCR (no vehicle detection)
  --pipeline lp_and_ocr_direct    : Full-frame LP + OCR with explicit elements
```

---

## Pipeline: `vehicle_and_lp`

```
================================================================================
PIPELINE VARIANT: vehicle_and_lp
================================================================================

--- GStreamer CLI Command ---

gst-launch-1.0 filesrc location="/usr/local/hailo/resources/videos/lpr_video.mp4" name=source ! queue name=source_queue_decode leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! decodebin name=source_decodebin ! queue name=source_scale_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! videoscale name=source_videoscale n-threads=2 ! queue name=source_convert_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! videoconvert n-threads=3 name=source_convert qos=false ! video/x-raw, pixel-aspect-ratio=1/1, format=RGB, width=1280, height=720 ! videorate name=source_videorate ! capsfilter name=source_fps_caps caps="video/x-raw, framerate=30/1" ! queue name=inference_wrapper_input_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! hailocropper name=inference_wrapper_crop so-path=/usr/lib/x86_64-linux-gnu/hailo/tappas/post_processes/cropping_algorithms/libwhole_buffer.so function-name=create_crops use-letterbox=true resize-method=inter-area internal-offset=true hailoaggregator name=inference_wrapper_agg inference_wrapper_crop. ! queue name=inference_wrapper_bypass_q leaky=no max-size-buffers=20 max-size-bytes=0 max-size-time=0 ! inference_wrapper_agg.sink_0 inference_wrapper_crop. ! queue name=vehicle_detection_scale_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! videoscale name=vehicle_detection_videoscale n-threads=2 qos=false ! queue name=vehicle_detection_convert_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! video/x-raw, pixel-aspect-ratio=1/1 ! videoconvert name=vehicle_detection_videoconvert n-threads=2 ! queue name=vehicle_detection_hailonet_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! hailonet name=vehicle_detection_hailonet hef-path=/usr/local/hailo/resources/models/hailo8/yolov5m_vehicles.hef batch-size=2 vdevice-group-id=SHARED nms-score-threshold=0.3 nms-iou-threshold=0.45 output-format-type=HAILO_FORMAT_TYPE_FLOAT32 force-writable=true ! queue name=vehicle_detection_hailofilter_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! hailofilter name=vehicle_detection_hailofilter so-path=/usr/local/hailo/resources/so/libyolo_hailortpp_postprocess.so config-path=/home/omria/hailo/dev/lpr/hailo-apps-infra/hailo_apps/python/pipeline_apps/license_plate_recognition/configs/yolov5m_vehicles.json function-name=yolov5m_vehicles qos=false ! queue name=vehicle_detection_output_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! inference_wrapper_agg.sink_1 inference_wrapper_agg. ! queue name=inference_wrapper_output_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! hailotracker name=vehicle_tracker class-id=-1 kalman-dist-thr=0.5 iou-thr=0.6 init-iou-thr=0.7 keep-new-frames=2 keep-tracked-frames=5 keep-lost-frames=3 keep-past-metadata=True qos=False ! queue name=vehicle_tracker_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! queue name=vehicle_cropper_input_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! hailocropper name=vehicle_cropper_cropper so-path=/usr/local/hailo/resources/so/liblpr_croppers.so function-name=vehicles_without_ocr use-letterbox=true no-scaling-bbox=true internal-offset=true resize-method=bilinear hailoaggregator name=vehicle_cropper_agg vehicle_cropper_cropper. ! queue name=vehicle_cropper_bypass_q leaky=no max-size-buffers=20 max-size-bytes=0 max-size-time=0 ! vehicle_cropper_agg.sink_0 vehicle_cropper_cropper. ! queue name=plate_detection_scale_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! videoscale name=plate_detection_videoscale n-threads=2 qos=false ! queue name=plate_detection_convert_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! video/x-raw, pixel-aspect-ratio=1/1 ! videoconvert name=plate_detection_videoconvert n-threads=2 ! queue name=plate_detection_hailonet_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! hailonet name=plate_detection_hailonet hef-path=/usr/local/hailo/resources/models/hailo8/yolov8n_relu6_global_lp_det.hef batch-size=8 vdevice-group-id=SHARED nms-score-threshold=0.3 nms-iou-threshold=0.45 output-format-type=HAILO_FORMAT_TYPE_FLOAT32 force-writable=true ! queue name=plate_detection_hailofilter_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! hailofilter name=plate_detection_hailofilter so-path=/usr/local/hailo/resources/so/libyolo_hailortpp_postprocess.so config-path=/home/omria/hailo/dev/lpr/hailo-apps-infra/hailo_apps/python/pipeline_apps/license_plate_recognition/configs/yolov8n_relu6_global_lp_det.json function-name=yolov8n_relu6_license_plate qos=false ! queue name=plate_detection_output_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! vehicle_cropper_agg.sink_1 vehicle_cropper_agg. ! queue name=vehicle_cropper_output_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! identity name=identity_callback ! queue name=hailo_display_overlay_q leaky=downstream max-size-buffers=10 max-size-bytes=0 max-size-time=0 ! hailooverlay name=hailo_display_overlay ! queue name=hailo_display_videoconvert_q leaky=downstream max-size-buffers=10 max-size-bytes=0 max-size-time=0 ! videoconvert name=hailo_display_videoconvert n-threads=2 qos=false ! queue name=hailo_display_q leaky=downstream max-size-buffers=10 max-size-bytes=0 max-size-time=0 ! fpsdisplaysink name=hailo_display video-sink=autovideosink sync=false text-overlay=False signal-fps-measurements=true

--- Pipeline String (formatted) ---

gst-launch-1.0 \
    filesrc location="/usr/local/hailo/resources/videos/lpr_video.mp4" name=source ! \
    queue name=source_queue_decode leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0  ! \
    decodebin name=source_decodebin ! \
     queue name=source_scale_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0  ! \
    videoscale name=source_videoscale n-threads=2 ! \
    queue name=source_convert_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0  ! \
    videoconvert n-threads=3 name=source_convert qos=false ! \
    video/x-raw, pixel-aspect-ratio=1/1, format=RGB, width=1280, height=720 ! \
    videorate name=source_videorate ! \
    capsfilter name=source_fps_caps caps="video/x-raw, framerate=30/1"  ! \
    queue name=inference_wrapper_input_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0  ! \
    hailocropper name=inference_wrapper_crop so-path=/usr/lib/x86_64-linux-gnu/hailo/tappas/post_processes/cropping_algorithms/libwhole_buffer.so function-name=create_crops use-letterbox=true resize-method=inter-area internal-offset=true hailoaggregator name=inference_wrapper_agg inference_wrapper_crop. ! \
    queue name=inference_wrapper_bypass_q leaky=no max-size-buffers=20 max-size-bytes=0 max-size-time=0  ! \
    inference_wrapper_agg.sink_0 inference_wrapper_crop. ! \
    queue name=vehicle_detection_scale_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0  ! \
    videoscale name=vehicle_detection_videoscale n-threads=2 qos=false ! \
    queue name=vehicle_detection_convert_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0  ! \
    video/x-raw, pixel-aspect-ratio=1/1 ! \
    videoconvert name=vehicle_detection_videoconvert n-threads=2 ! \
    queue name=vehicle_detection_hailonet_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0  ! \
    hailonet name=vehicle_detection_hailonet hef-path=/usr/local/hailo/resources/models/hailo8/yolov5m_vehicles.hef batch-size=2  vdevice-group-id=SHARED nms-score-threshold=0.3 nms-iou-threshold=0.45 output-format-type=HAILO_FORMAT_TYPE_FLOAT32 force-writable=true  ! \
    queue name=vehicle_detection_hailofilter_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0  ! \
    hailofilter name=vehicle_detection_hailofilter so-path=/usr/local/hailo/resources/so/libyolo_hailortpp_postprocess.so  config-path=/home/omria/hailo/dev/lpr/hailo-apps-infra/hailo_apps/python/pipeline_apps/license_plate_recognition/configs/yolov5m_vehicles.json   function-name=yolov5m_vehicles  qos=false ! \
    queue name=vehicle_detection_output_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0   ! \
    inference_wrapper_agg.sink_1 inference_wrapper_agg. ! \
    queue name=inference_wrapper_output_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0   ! \
    hailotracker name=vehicle_tracker class-id=-1 kalman-dist-thr=0.5 iou-thr=0.6 init-iou-thr=0.7 keep-new-frames=2 keep-tracked-frames=5 keep-lost-frames=3 keep-past-metadata=True qos=False ! \
    queue name=vehicle_tracker_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0   ! \
    queue name=vehicle_cropper_input_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0  ! \
    hailocropper name=vehicle_cropper_cropper so-path=/usr/local/hailo/resources/so/liblpr_croppers.so function-name=vehicles_without_ocr use-letterbox=true no-scaling-bbox=true internal-offset=true resize-method=bilinear hailoaggregator name=vehicle_cropper_agg vehicle_cropper_cropper. ! \
    queue name=vehicle_cropper_bypass_q leaky=no max-size-buffers=20 max-size-bytes=0 max-size-time=0  ! \
    vehicle_cropper_agg.sink_0 vehicle_cropper_cropper. ! \
    queue name=plate_detection_scale_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0  ! \
    videoscale name=plate_detection_videoscale n-threads=2 qos=false ! \
    queue name=plate_detection_convert_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0  ! \
    video/x-raw, pixel-aspect-ratio=1/1 ! \
    videoconvert name=plate_detection_videoconvert n-threads=2 ! \
    queue name=plate_detection_hailonet_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0  ! \
    hailonet name=plate_detection_hailonet hef-path=/usr/local/hailo/resources/models/hailo8/yolov8n_relu6_global_lp_det.hef batch-size=8  vdevice-group-id=SHARED nms-score-threshold=0.3 nms-iou-threshold=0.45 output-format-type=HAILO_FORMAT_TYPE_FLOAT32 force-writable=true  ! \
    queue name=plate_detection_hailofilter_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0  ! \
    hailofilter name=plate_detection_hailofilter so-path=/usr/local/hailo/resources/so/libyolo_hailortpp_postprocess.so  config-path=/home/omria/hailo/dev/lpr/hailo-apps-infra/hailo_apps/python/pipeline_apps/license_plate_recognition/configs/yolov8n_relu6_global_lp_det.json   function-name=yolov8n_relu6_license_plate  qos=false ! \
    queue name=plate_detection_output_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0   ! \
    vehicle_cropper_agg.sink_1 vehicle_cropper_agg. ! \
    queue name=vehicle_cropper_output_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0   ! \
    identity name=identity_callback ! \
    queue name=hailo_display_overlay_q leaky=downstream max-size-buffers=10 max-size-bytes=0 max-size-time=0  ! \
    hailooverlay name=hailo_display_overlay  ! \
    queue name=hailo_display_videoconvert_q leaky=downstream max-size-buffers=10 max-size-bytes=0 max-size-time=0  ! \
    videoconvert name=hailo_display_videoconvert n-threads=2 qos=false ! \
    queue name=hailo_display_q leaky=downstream max-size-buffers=10 max-size-bytes=0 max-size-time=0  ! \
    fpsdisplaysink name=hailo_display video-sink=autovideosink sync=false text-overlay=False signal-fps-measurements=true 

--- Available Pipeline Variants ---

  --pipeline simple               : Full LPR: Vehicle → Tracker → LP → OCR with display aggregators
  --pipeline complex              : Full LPR: Explicit low-level GStreamer elements
  --pipeline optimized            : Full LPR: Parallel display/processing with quality filter
  --pipeline optimized_direct     : Full LPR: Parallel display/processing, no quality filter
  --pipeline candidate            : Full LPR: Hardcoded paths (debugging)
  --pipeline vehicle_and_lp       : Vehicle + LP detection only (no OCR) <-- CURRENT
  --pipeline vehicle_only         : Vehicle detection only
  --pipeline lp_only              : LP detection on full frame only
  --pipeline lp_only_crops        : LP detection + crop saving (no display)
  --pipeline lp_and_ocr           : Full-frame LP + OCR (no vehicle detection)
  --pipeline lp_and_ocr_direct    : Full-frame LP + OCR with explicit elements
```

---

## Pipeline: `vehicle_only`

```
================================================================================
PIPELINE VARIANT: vehicle_only
================================================================================

--- GStreamer CLI Command ---

gst-launch-1.0 filesrc location="/usr/local/hailo/resources/videos/lpr_video.mp4" name=source ! queue name=source_queue_decode leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! decodebin name=source_decodebin ! queue name=source_scale_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! videoscale name=source_videoscale n-threads=2 ! queue name=source_convert_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! videoconvert n-threads=3 name=source_convert qos=false ! video/x-raw, pixel-aspect-ratio=1/1, format=RGB, width=1280, height=720 ! videorate name=source_videorate ! capsfilter name=source_fps_caps caps="video/x-raw, framerate=30/1" ! queue name=inference_wrapper_input_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! hailocropper name=inference_wrapper_crop so-path=/usr/lib/x86_64-linux-gnu/hailo/tappas/post_processes/cropping_algorithms/libwhole_buffer.so function-name=create_crops use-letterbox=true resize-method=inter-area internal-offset=true hailoaggregator name=inference_wrapper_agg inference_wrapper_crop. ! queue name=inference_wrapper_bypass_q leaky=no max-size-buffers=20 max-size-bytes=0 max-size-time=0 ! inference_wrapper_agg.sink_0 inference_wrapper_crop. ! queue name=vehicle_detection_scale_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! videoscale name=vehicle_detection_videoscale n-threads=2 qos=false ! queue name=vehicle_detection_convert_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! video/x-raw, pixel-aspect-ratio=1/1 ! videoconvert name=vehicle_detection_videoconvert n-threads=2 ! queue name=vehicle_detection_hailonet_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! hailonet name=vehicle_detection_hailonet hef-path=/usr/local/hailo/resources/models/hailo8/yolov5m_vehicles.hef batch-size=2 vdevice-group-id=SHARED nms-score-threshold=0.3 nms-iou-threshold=0.45 output-format-type=HAILO_FORMAT_TYPE_FLOAT32 force-writable=true ! queue name=vehicle_detection_hailofilter_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! hailofilter name=vehicle_detection_hailofilter so-path=/usr/local/hailo/resources/so/libyolo_hailortpp_postprocess.so config-path=/home/omria/hailo/dev/lpr/hailo-apps-infra/hailo_apps/python/pipeline_apps/license_plate_recognition/configs/yolov5m_vehicles.json function-name=yolov5m_vehicles qos=false ! queue name=vehicle_detection_output_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! inference_wrapper_agg.sink_1 inference_wrapper_agg. ! queue name=inference_wrapper_output_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! queue name=hailo_display_overlay_q leaky=downstream max-size-buffers=10 max-size-bytes=0 max-size-time=0 ! hailooverlay name=hailo_display_overlay ! queue name=hailo_display_videoconvert_q leaky=downstream max-size-buffers=10 max-size-bytes=0 max-size-time=0 ! videoconvert name=hailo_display_videoconvert n-threads=2 qos=false ! queue name=hailo_display_q leaky=downstream max-size-buffers=10 max-size-bytes=0 max-size-time=0 ! fpsdisplaysink name=hailo_display video-sink=autovideosink sync=false text-overlay=False signal-fps-measurements=true

--- Pipeline String (formatted) ---

gst-launch-1.0 \
    filesrc location="/usr/local/hailo/resources/videos/lpr_video.mp4" name=source ! \
    queue name=source_queue_decode leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0  ! \
    decodebin name=source_decodebin ! \
     queue name=source_scale_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0  ! \
    videoscale name=source_videoscale n-threads=2 ! \
    queue name=source_convert_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0  ! \
    videoconvert n-threads=3 name=source_convert qos=false ! \
    video/x-raw, pixel-aspect-ratio=1/1, format=RGB, width=1280, height=720 ! \
    videorate name=source_videorate ! \
    capsfilter name=source_fps_caps caps="video/x-raw, framerate=30/1"  ! \
    queue name=inference_wrapper_input_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0  ! \
    hailocropper name=inference_wrapper_crop so-path=/usr/lib/x86_64-linux-gnu/hailo/tappas/post_processes/cropping_algorithms/libwhole_buffer.so function-name=create_crops use-letterbox=true resize-method=inter-area internal-offset=true hailoaggregator name=inference_wrapper_agg inference_wrapper_crop. ! \
    queue name=inference_wrapper_bypass_q leaky=no max-size-buffers=20 max-size-bytes=0 max-size-time=0  ! \
    inference_wrapper_agg.sink_0 inference_wrapper_crop. ! \
    queue name=vehicle_detection_scale_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0  ! \
    videoscale name=vehicle_detection_videoscale n-threads=2 qos=false ! \
    queue name=vehicle_detection_convert_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0  ! \
    video/x-raw, pixel-aspect-ratio=1/1 ! \
    videoconvert name=vehicle_detection_videoconvert n-threads=2 ! \
    queue name=vehicle_detection_hailonet_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0  ! \
    hailonet name=vehicle_detection_hailonet hef-path=/usr/local/hailo/resources/models/hailo8/yolov5m_vehicles.hef batch-size=2  vdevice-group-id=SHARED nms-score-threshold=0.3 nms-iou-threshold=0.45 output-format-type=HAILO_FORMAT_TYPE_FLOAT32 force-writable=true  ! \
    queue name=vehicle_detection_hailofilter_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0  ! \
    hailofilter name=vehicle_detection_hailofilter so-path=/usr/local/hailo/resources/so/libyolo_hailortpp_postprocess.so  config-path=/home/omria/hailo/dev/lpr/hailo-apps-infra/hailo_apps/python/pipeline_apps/license_plate_recognition/configs/yolov5m_vehicles.json   function-name=yolov5m_vehicles  qos=false ! \
    queue name=vehicle_detection_output_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0   ! \
    inference_wrapper_agg.sink_1 inference_wrapper_agg. ! \
    queue name=inference_wrapper_output_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0   ! \
    queue name=hailo_display_overlay_q leaky=downstream max-size-buffers=10 max-size-bytes=0 max-size-time=0  ! \
    hailooverlay name=hailo_display_overlay  ! \
    queue name=hailo_display_videoconvert_q leaky=downstream max-size-buffers=10 max-size-bytes=0 max-size-time=0  ! \
    videoconvert name=hailo_display_videoconvert n-threads=2 qos=false ! \
    queue name=hailo_display_q leaky=downstream max-size-buffers=10 max-size-bytes=0 max-size-time=0  ! \
    fpsdisplaysink name=hailo_display video-sink=autovideosink sync=false text-overlay=False signal-fps-measurements=true 

--- Available Pipeline Variants ---

  --pipeline simple               : Full LPR: Vehicle → Tracker → LP → OCR with display aggregators
  --pipeline complex              : Full LPR: Explicit low-level GStreamer elements
  --pipeline optimized            : Full LPR: Parallel display/processing with quality filter
  --pipeline optimized_direct     : Full LPR: Parallel display/processing, no quality filter
  --pipeline candidate            : Full LPR: Hardcoded paths (debugging)
  --pipeline vehicle_and_lp       : Vehicle + LP detection only (no OCR)
  --pipeline vehicle_only         : Vehicle detection only <-- CURRENT
  --pipeline lp_only              : LP detection on full frame only
  --pipeline lp_only_crops        : LP detection + crop saving (no display)
  --pipeline lp_and_ocr           : Full-frame LP + OCR (no vehicle detection)
  --pipeline lp_and_ocr_direct    : Full-frame LP + OCR with explicit elements
```

---

## Pipeline: `lp_only`

```
================================================================================
PIPELINE VARIANT: lp_only
================================================================================

--- GStreamer CLI Command ---

gst-launch-1.0 filesrc location="/usr/local/hailo/resources/videos/lpr_video.mp4" name=source ! queue name=source_queue_decode leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! decodebin name=source_decodebin ! queue name=source_scale_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! videoscale name=source_videoscale n-threads=2 ! queue name=source_convert_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! videoconvert n-threads=3 name=source_convert qos=false ! video/x-raw, pixel-aspect-ratio=1/1, format=RGB, width=1280, height=720 ! videorate name=source_videorate ! capsfilter name=source_fps_caps caps="video/x-raw, framerate=30/1" ! queue name=inference_wrapper_input_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! hailocropper name=inference_wrapper_crop so-path=/usr/lib/x86_64-linux-gnu/hailo/tappas/post_processes/cropping_algorithms/libwhole_buffer.so function-name=create_crops use-letterbox=true resize-method=inter-area internal-offset=true hailoaggregator name=inference_wrapper_agg inference_wrapper_crop. ! queue name=inference_wrapper_bypass_q leaky=no max-size-buffers=20 max-size-bytes=0 max-size-time=0 ! inference_wrapper_agg.sink_0 inference_wrapper_crop. ! queue name=plate_detection_scale_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! videoscale name=plate_detection_videoscale n-threads=2 qos=false ! queue name=plate_detection_convert_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! video/x-raw, pixel-aspect-ratio=1/1 ! videoconvert name=plate_detection_videoconvert n-threads=2 ! queue name=plate_detection_hailonet_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! hailonet name=plate_detection_hailonet hef-path=/usr/local/hailo/resources/models/hailo8/yolov8n_relu6_global_lp_det.hef batch-size=1 vdevice-group-id=SHARED force-writable=true ! queue name=plate_detection_hailofilter_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! hailofilter name=plate_detection_hailofilter so-path=/usr/local/hailo/resources/so/libyolo_hailortpp_postprocess.so config-path=/home/omria/hailo/dev/lpr/hailo-apps-infra/hailo_apps/python/pipeline_apps/license_plate_recognition/configs/yolov8n_relu6_global_lp_det.json function-name=yolov8n_relu6_license_plate qos=false ! queue name=plate_detection_output_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! inference_wrapper_agg.sink_1 inference_wrapper_agg. ! queue name=inference_wrapper_output_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! queue name=hailo_display_overlay_q leaky=downstream max-size-buffers=10 max-size-bytes=0 max-size-time=0 ! hailooverlay name=hailo_display_overlay ! queue name=hailo_display_videoconvert_q leaky=downstream max-size-buffers=10 max-size-bytes=0 max-size-time=0 ! videoconvert name=hailo_display_videoconvert n-threads=2 qos=false ! queue name=hailo_display_q leaky=downstream max-size-buffers=10 max-size-bytes=0 max-size-time=0 ! fpsdisplaysink name=hailo_display video-sink=autovideosink sync=false text-overlay=False signal-fps-measurements=true

--- Pipeline String (formatted) ---

gst-launch-1.0 \
    filesrc location="/usr/local/hailo/resources/videos/lpr_video.mp4" name=source ! \
    queue name=source_queue_decode leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0  ! \
    decodebin name=source_decodebin ! \
     queue name=source_scale_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0  ! \
    videoscale name=source_videoscale n-threads=2 ! \
    queue name=source_convert_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0  ! \
    videoconvert n-threads=3 name=source_convert qos=false ! \
    video/x-raw, pixel-aspect-ratio=1/1, format=RGB, width=1280, height=720 ! \
    videorate name=source_videorate ! \
    capsfilter name=source_fps_caps caps="video/x-raw, framerate=30/1"  ! \
    queue name=inference_wrapper_input_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0  ! \
    hailocropper name=inference_wrapper_crop so-path=/usr/lib/x86_64-linux-gnu/hailo/tappas/post_processes/cropping_algorithms/libwhole_buffer.so function-name=create_crops use-letterbox=true resize-method=inter-area internal-offset=true hailoaggregator name=inference_wrapper_agg inference_wrapper_crop. ! \
    queue name=inference_wrapper_bypass_q leaky=no max-size-buffers=20 max-size-bytes=0 max-size-time=0  ! \
    inference_wrapper_agg.sink_0 inference_wrapper_crop. ! \
    queue name=plate_detection_scale_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0  ! \
    videoscale name=plate_detection_videoscale n-threads=2 qos=false ! \
    queue name=plate_detection_convert_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0  ! \
    video/x-raw, pixel-aspect-ratio=1/1 ! \
    videoconvert name=plate_detection_videoconvert n-threads=2 ! \
    queue name=plate_detection_hailonet_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0  ! \
    hailonet name=plate_detection_hailonet hef-path=/usr/local/hailo/resources/models/hailo8/yolov8n_relu6_global_lp_det.hef batch-size=1  vdevice-group-id=SHARED  force-writable=true  ! \
    queue name=plate_detection_hailofilter_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0  ! \
    hailofilter name=plate_detection_hailofilter so-path=/usr/local/hailo/resources/so/libyolo_hailortpp_postprocess.so  config-path=/home/omria/hailo/dev/lpr/hailo-apps-infra/hailo_apps/python/pipeline_apps/license_plate_recognition/configs/yolov8n_relu6_global_lp_det.json   function-name=yolov8n_relu6_license_plate  qos=false ! \
    queue name=plate_detection_output_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0   ! \
    inference_wrapper_agg.sink_1 inference_wrapper_agg. ! \
    queue name=inference_wrapper_output_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0   ! \
    queue name=hailo_display_overlay_q leaky=downstream max-size-buffers=10 max-size-bytes=0 max-size-time=0  ! \
    hailooverlay name=hailo_display_overlay  ! \
    queue name=hailo_display_videoconvert_q leaky=downstream max-size-buffers=10 max-size-bytes=0 max-size-time=0  ! \
    videoconvert name=hailo_display_videoconvert n-threads=2 qos=false ! \
    queue name=hailo_display_q leaky=downstream max-size-buffers=10 max-size-bytes=0 max-size-time=0  ! \
    fpsdisplaysink name=hailo_display video-sink=autovideosink sync=false text-overlay=False signal-fps-measurements=true 

--- Available Pipeline Variants ---

  --pipeline simple               : Full LPR: Vehicle → Tracker → LP → OCR with display aggregators
  --pipeline complex              : Full LPR: Explicit low-level GStreamer elements
  --pipeline optimized            : Full LPR: Parallel display/processing with quality filter
  --pipeline optimized_direct     : Full LPR: Parallel display/processing, no quality filter
  --pipeline candidate            : Full LPR: Hardcoded paths (debugging)
  --pipeline vehicle_and_lp       : Vehicle + LP detection only (no OCR)
  --pipeline vehicle_only         : Vehicle detection only
  --pipeline lp_only              : LP detection on full frame only <-- CURRENT
  --pipeline lp_only_crops        : LP detection + crop saving (no display)
  --pipeline lp_and_ocr           : Full-frame LP + OCR (no vehicle detection)
  --pipeline lp_and_ocr_direct    : Full-frame LP + OCR with explicit elements
```

---

## Pipeline: `lp_only_crops`

```
================================================================================
PIPELINE VARIANT: lp_only_crops
================================================================================

--- GStreamer CLI Command ---

gst-launch-1.0 filesrc location="/usr/local/hailo/resources/videos/lpr_video.mp4" name=source ! queue name=source_queue_decode leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! decodebin name=source_decodebin ! queue name=source_scale_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! videoscale name=source_videoscale n-threads=2 ! queue name=source_convert_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! videoconvert n-threads=3 name=source_convert qos=false ! video/x-raw, pixel-aspect-ratio=1/1, format=RGB, width=1280, height=720 ! videorate name=source_videorate ! capsfilter name=source_fps_caps caps="video/x-raw, framerate=30/1" ! queue name=plate_wrapper_input_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! hailocropper name=plate_wrapper_crop so-path=/usr/lib/x86_64-linux-gnu/hailo/tappas/post_processes/cropping_algorithms/libwhole_buffer.so function-name=create_crops use-letterbox=true resize-method=inter-area internal-offset=true hailoaggregator name=plate_wrapper_agg plate_wrapper_crop. ! queue name=plate_wrapper_bypass_q leaky=no max-size-buffers=30 max-size-bytes=0 max-size-time=0 ! plate_wrapper_agg.sink_0 plate_wrapper_crop. ! queue name=plate_detection_scale_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! videoscale name=plate_detection_videoscale n-threads=2 qos=false ! queue name=plate_detection_convert_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! video/x-raw, pixel-aspect-ratio=1/1 ! videoconvert name=plate_detection_videoconvert n-threads=2 ! queue name=plate_detection_hailonet_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! hailonet name=plate_detection_hailonet hef-path=/usr/local/hailo/resources/models/hailo8/yolov8n_relu6_global_lp_det.hef batch-size=4 vdevice-group-id=SHARED scheduler-timeout-ms=100 nms-score-threshold=0.3 nms-iou-threshold=0.45 output-format-type=HAILO_FORMAT_TYPE_FLOAT32 force-writable=true ! queue name=plate_detection_hailofilter_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! hailofilter name=plate_detection_hailofilter so-path=/usr/local/hailo/resources/so/libyolo_hailortpp_postprocess.so config-path=/home/omria/hailo/dev/lpr/hailo-apps-infra/hailo_apps/python/pipeline_apps/license_plate_recognition/configs/yolov8n_relu6_global_lp_det.json function-name=yolov8n_relu6_license_plate qos=false ! queue name=plate_detection_output_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! plate_wrapper_agg.sink_1 plate_wrapper_agg. ! queue name=plate_wrapper_output_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! queue name=lp_cropper_input_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! hailocropper name=lp_cropper_cropper so-path=/usr/local/hailo/resources/so/liblpr_croppers.so function-name=license_plate_fullframe use-letterbox=true no-scaling-bbox=true internal-offset=true resize-method=bilinear hailoaggregator name=lp_cropper_agg lp_cropper_cropper. ! queue name=lp_cropper_bypass_q leaky=no max-size-buffers=20 max-size-bytes=0 max-size-time=0 ! lp_cropper_agg.sink_0 lp_cropper_cropper. ! queue name=lp_cropper_passthrough_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! identity name=lp_cropper_passthrough ! lp_cropper_agg.sink_1 lp_cropper_agg. ! queue name=lp_cropper_output_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! queue name=identity_callback_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! identity name=identity_callback ! queue name=hailo_display_overlay_q leaky=downstream max-size-buffers=10 max-size-bytes=0 max-size-time=0 ! hailooverlay name=hailo_display_overlay ! queue name=hailo_display_videoconvert_q leaky=downstream max-size-buffers=10 max-size-bytes=0 max-size-time=0 ! videoconvert name=hailo_display_videoconvert n-threads=2 qos=false ! queue name=hailo_display_q leaky=downstream max-size-buffers=10 max-size-bytes=0 max-size-time=0 ! fpsdisplaysink name=hailo_display video-sink=fakesink sync=False text-overlay=False signal-fps-measurements=true

--- Pipeline String (formatted) ---

gst-launch-1.0 \
    filesrc location="/usr/local/hailo/resources/videos/lpr_video.mp4" name=source ! \
    queue name=source_queue_decode leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0  ! \
    decodebin name=source_decodebin ! \
     queue name=source_scale_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0  ! \
    videoscale name=source_videoscale n-threads=2 ! \
    queue name=source_convert_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0  ! \
    videoconvert n-threads=3 name=source_convert qos=false ! \
    video/x-raw, pixel-aspect-ratio=1/1, format=RGB, width=1280, height=720 ! \
    videorate name=source_videorate ! \
    capsfilter name=source_fps_caps caps="video/x-raw, framerate=30/1"  ! \
    queue name=plate_wrapper_input_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0  ! \
    hailocropper name=plate_wrapper_crop so-path=/usr/lib/x86_64-linux-gnu/hailo/tappas/post_processes/cropping_algorithms/libwhole_buffer.so function-name=create_crops use-letterbox=true resize-method=inter-area internal-offset=true hailoaggregator name=plate_wrapper_agg plate_wrapper_crop. ! \
    queue name=plate_wrapper_bypass_q leaky=no max-size-buffers=30 max-size-bytes=0 max-size-time=0  ! \
    plate_wrapper_agg.sink_0 plate_wrapper_crop. ! \
    queue name=plate_detection_scale_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0  ! \
    videoscale name=plate_detection_videoscale n-threads=2 qos=false ! \
    queue name=plate_detection_convert_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0  ! \
    video/x-raw, pixel-aspect-ratio=1/1 ! \
    videoconvert name=plate_detection_videoconvert n-threads=2 ! \
    queue name=plate_detection_hailonet_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0  ! \
    hailonet name=plate_detection_hailonet hef-path=/usr/local/hailo/resources/models/hailo8/yolov8n_relu6_global_lp_det.hef batch-size=4  vdevice-group-id=SHARED  scheduler-timeout-ms=100 nms-score-threshold=0.3 nms-iou-threshold=0.45 output-format-type=HAILO_FORMAT_TYPE_FLOAT32 force-writable=true  ! \
    queue name=plate_detection_hailofilter_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0  ! \
    hailofilter name=plate_detection_hailofilter so-path=/usr/local/hailo/resources/so/libyolo_hailortpp_postprocess.so  config-path=/home/omria/hailo/dev/lpr/hailo-apps-infra/hailo_apps/python/pipeline_apps/license_plate_recognition/configs/yolov8n_relu6_global_lp_det.json   function-name=yolov8n_relu6_license_plate  qos=false ! \
    queue name=plate_detection_output_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0   ! \
    plate_wrapper_agg.sink_1 plate_wrapper_agg. ! \
    queue name=plate_wrapper_output_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0   ! \
    queue name=lp_cropper_input_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0  ! \
    hailocropper name=lp_cropper_cropper so-path=/usr/local/hailo/resources/so/liblpr_croppers.so function-name=license_plate_fullframe use-letterbox=true no-scaling-bbox=true internal-offset=true resize-method=bilinear hailoaggregator name=lp_cropper_agg lp_cropper_cropper. ! \
    queue name=lp_cropper_bypass_q leaky=no max-size-buffers=20 max-size-bytes=0 max-size-time=0  ! \
    lp_cropper_agg.sink_0 lp_cropper_cropper. ! \
    queue name=lp_cropper_passthrough_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0  ! \
    identity name=lp_cropper_passthrough ! \
    lp_cropper_agg.sink_1 lp_cropper_agg. ! \
    queue name=lp_cropper_output_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0   ! \
    queue name=identity_callback_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0  ! \
    identity name=identity_callback  ! \
    queue name=hailo_display_overlay_q leaky=downstream max-size-buffers=10 max-size-bytes=0 max-size-time=0  ! \
    hailooverlay name=hailo_display_overlay  ! \
    queue name=hailo_display_videoconvert_q leaky=downstream max-size-buffers=10 max-size-bytes=0 max-size-time=0  ! \
    videoconvert name=hailo_display_videoconvert n-threads=2 qos=false ! \
    queue name=hailo_display_q leaky=downstream max-size-buffers=10 max-size-bytes=0 max-size-time=0  ! \
    fpsdisplaysink name=hailo_display video-sink=fakesink sync=False text-overlay=False signal-fps-measurements=true 

--- Available Pipeline Variants ---

  --pipeline simple               : Full LPR: Vehicle → Tracker → LP → OCR with display aggregators
  --pipeline complex              : Full LPR: Explicit low-level GStreamer elements
  --pipeline optimized            : Full LPR: Parallel display/processing with quality filter
  --pipeline optimized_direct     : Full LPR: Parallel display/processing, no quality filter
  --pipeline candidate            : Full LPR: Hardcoded paths (debugging)
  --pipeline vehicle_and_lp       : Vehicle + LP detection only (no OCR)
  --pipeline vehicle_only         : Vehicle detection only
  --pipeline lp_only              : LP detection on full frame only
  --pipeline lp_only_crops        : LP detection + crop saving (no display) <-- CURRENT
  --pipeline lp_and_ocr           : Full-frame LP + OCR (no vehicle detection)
  --pipeline lp_and_ocr_direct    : Full-frame LP + OCR with explicit elements
```

---

## Pipeline: `lp_and_ocr`

```
================================================================================
PIPELINE VARIANT: lp_and_ocr
================================================================================

--- GStreamer CLI Command ---

gst-launch-1.0 filesrc location="/usr/local/hailo/resources/videos/lpr_video.mp4" name=source ! queue name=source_queue_decode leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! decodebin name=source_decodebin ! queue name=source_scale_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! videoscale name=source_videoscale n-threads=2 ! queue name=source_convert_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! videoconvert n-threads=3 name=source_convert qos=false ! video/x-raw, pixel-aspect-ratio=1/1, format=RGB, width=1280, height=720 ! videorate name=source_videorate ! capsfilter name=source_fps_caps caps="video/x-raw, framerate=30/1" ! queue name=plate_wrapper_input_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! hailocropper name=plate_wrapper_crop so-path=/usr/lib/x86_64-linux-gnu/hailo/tappas/post_processes/cropping_algorithms/libwhole_buffer.so function-name=create_crops use-letterbox=true resize-method=inter-area internal-offset=true hailoaggregator name=plate_wrapper_agg plate_wrapper_crop. ! queue name=plate_wrapper_bypass_q leaky=no max-size-buffers=30 max-size-bytes=0 max-size-time=0 ! plate_wrapper_agg.sink_0 plate_wrapper_crop. ! queue name=plate_detection_scale_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! videoscale name=plate_detection_videoscale n-threads=2 qos=false ! queue name=plate_detection_convert_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! video/x-raw, pixel-aspect-ratio=1/1 ! videoconvert name=plate_detection_videoconvert n-threads=2 ! queue name=plate_detection_hailonet_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! hailonet name=plate_detection_hailonet hef-path=/usr/local/hailo/resources/models/hailo8/yolov8n_relu6_global_lp_det.hef batch-size=4 vdevice-group-id=SHARED scheduler-timeout-ms=100 nms-score-threshold=0.3 nms-iou-threshold=0.45 output-format-type=HAILO_FORMAT_TYPE_FLOAT32 force-writable=true ! queue name=plate_detection_hailofilter_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! hailofilter name=plate_detection_hailofilter so-path=/usr/local/hailo/resources/so/libyolo_hailortpp_postprocess.so config-path=/home/omria/hailo/dev/lpr/hailo-apps-infra/hailo_apps/python/pipeline_apps/license_plate_recognition/configs/yolov8n_relu6_global_lp_det.json function-name=yolov8n_relu6_license_plate qos=false ! queue name=plate_detection_output_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! plate_wrapper_agg.sink_1 plate_wrapper_agg. ! queue name=plate_wrapper_output_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! hailotracker name=hailo_tracker class-id=-1 kalman-dist-thr=0.5 iou-thr=0.6 init-iou-thr=0.7 keep-new-frames=2 keep-tracked-frames=2 keep-lost-frames=2 keep-past-metadata=True qos=False ! queue name=hailo_tracker_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! tee name=main_tee main_tee. ! queue name=display_q leaky=downstream max-size-buffers=10 max-size-bytes=0 max-size-time=0 ! queue name=hailo_display_overlay_q leaky=downstream max-size-buffers=10 max-size-bytes=0 max-size-time=0 ! hailooverlay name=hailo_display_overlay ! queue name=hailo_display_videoconvert_q leaky=downstream max-size-buffers=10 max-size-bytes=0 max-size-time=0 ! videoconvert name=hailo_display_videoconvert n-threads=2 qos=false ! queue name=hailo_display_q leaky=downstream max-size-buffers=10 max-size-bytes=0 max-size-time=0 ! fpsdisplaysink name=hailo_display video-sink=autovideosink sync=false text-overlay=False signal-fps-measurements=true main_tee. ! queue name=processing_q leaky=no max-size-buffers=10 max-size-bytes=0 max-size-time=0 ! queue name=lp_cropper_input_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! hailocropper name=lp_cropper_cropper so-path=/usr/local/hailo/resources/so/liblpr_croppers.so function-name=license_plate_fullframe use-letterbox=true no-scaling-bbox=true internal-offset=true resize-method=bilinear hailoaggregator name=lp_cropper_agg lp_cropper_cropper. ! queue name=lp_cropper_bypass_q leaky=no max-size-buffers=20 max-size-bytes=0 max-size-time=0 ! lp_cropper_agg.sink_0 lp_cropper_cropper. ! queue name=ocr_detection_scale_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! videoscale name=ocr_detection_videoscale n-threads=2 qos=false ! queue name=ocr_detection_convert_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! video/x-raw, pixel-aspect-ratio=1/1 ! videoconvert name=ocr_detection_videoconvert n-threads=2 ! queue name=ocr_detection_hailonet_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! hailonet name=ocr_detection_hailonet hef-path=/usr/local/hailo/resources/models/hailo8/ocr.hef batch-size=1 vdevice-group-id=SHARED force-writable=true ! queue name=ocr_detection_hailofilter_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! hailofilter name=ocr_detection_hailofilter so-path=/usr/local/hailo/resources/so/libocr_postprocess.so function-name=paddleocr_recognize qos=false ! queue name=ocr_detection_output_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! lp_cropper_agg.sink_1 lp_cropper_agg. ! queue name=lp_cropper_output_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! queue name=post_ocr_q leaky=no max-size-buffers=5 max-size-bytes=0 max-size-time=0 ! identity name=identity_callback ! hailofilter use-gst-buffer=true so-path=/usr/local/hailo/resources/so/liblpr_ocrsink.so qos=false ! fakesink sync=false async=false

--- Pipeline String (formatted) ---

gst-launch-1.0 \
    filesrc location="/usr/local/hailo/resources/videos/lpr_video.mp4" name=source ! \
    queue name=source_queue_decode leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0  ! \
    decodebin name=source_decodebin ! \
     queue name=source_scale_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0  ! \
    videoscale name=source_videoscale n-threads=2 ! \
    queue name=source_convert_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0  ! \
    videoconvert n-threads=3 name=source_convert qos=false ! \
    video/x-raw, pixel-aspect-ratio=1/1, format=RGB, width=1280, height=720 ! \
    videorate name=source_videorate ! \
    capsfilter name=source_fps_caps caps="video/x-raw, framerate=30/1"  ! \
    queue name=plate_wrapper_input_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0  ! \
    hailocropper name=plate_wrapper_crop so-path=/usr/lib/x86_64-linux-gnu/hailo/tappas/post_processes/cropping_algorithms/libwhole_buffer.so function-name=create_crops use-letterbox=true resize-method=inter-area internal-offset=true hailoaggregator name=plate_wrapper_agg plate_wrapper_crop. ! \
    queue name=plate_wrapper_bypass_q leaky=no max-size-buffers=30 max-size-bytes=0 max-size-time=0  ! \
    plate_wrapper_agg.sink_0 plate_wrapper_crop. ! \
    queue name=plate_detection_scale_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0  ! \
    videoscale name=plate_detection_videoscale n-threads=2 qos=false ! \
    queue name=plate_detection_convert_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0  ! \
    video/x-raw, pixel-aspect-ratio=1/1 ! \
    videoconvert name=plate_detection_videoconvert n-threads=2 ! \
    queue name=plate_detection_hailonet_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0  ! \
    hailonet name=plate_detection_hailonet hef-path=/usr/local/hailo/resources/models/hailo8/yolov8n_relu6_global_lp_det.hef batch-size=4  vdevice-group-id=SHARED  scheduler-timeout-ms=100 nms-score-threshold=0.3 nms-iou-threshold=0.45 output-format-type=HAILO_FORMAT_TYPE_FLOAT32 force-writable=true  ! \
    queue name=plate_detection_hailofilter_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0  ! \
    hailofilter name=plate_detection_hailofilter so-path=/usr/local/hailo/resources/so/libyolo_hailortpp_postprocess.so  config-path=/home/omria/hailo/dev/lpr/hailo-apps-infra/hailo_apps/python/pipeline_apps/license_plate_recognition/configs/yolov8n_relu6_global_lp_det.json   function-name=yolov8n_relu6_license_plate  qos=false ! \
    queue name=plate_detection_output_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0   ! \
    plate_wrapper_agg.sink_1 plate_wrapper_agg. ! \
    queue name=plate_wrapper_output_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0   ! \
    hailotracker name=hailo_tracker class-id=-1 kalman-dist-thr=0.5 iou-thr=0.6 init-iou-thr=0.7 keep-new-frames=2 keep-tracked-frames=2 keep-lost-frames=2 keep-past-metadata=True qos=False ! \
    queue name=hailo_tracker_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0   ! \
    tee name=main_tee main_tee. ! \
    queue name=display_q leaky=downstream max-size-buffers=10 max-size-bytes=0 max-size-time=0  ! \
    queue name=hailo_display_overlay_q leaky=downstream max-size-buffers=10 max-size-bytes=0 max-size-time=0  ! \
    hailooverlay name=hailo_display_overlay  ! \
    queue name=hailo_display_videoconvert_q leaky=downstream max-size-buffers=10 max-size-bytes=0 max-size-time=0  ! \
    videoconvert name=hailo_display_videoconvert n-threads=2 qos=false ! \
    queue name=hailo_display_q leaky=downstream max-size-buffers=10 max-size-bytes=0 max-size-time=0  ! \
    fpsdisplaysink name=hailo_display video-sink=autovideosink sync=false text-overlay=False signal-fps-measurements=true  main_tee. ! \
    queue name=processing_q leaky=no max-size-buffers=10 max-size-bytes=0 max-size-time=0  ! \
    queue name=lp_cropper_input_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0  ! \
    hailocropper name=lp_cropper_cropper so-path=/usr/local/hailo/resources/so/liblpr_croppers.so function-name=license_plate_fullframe use-letterbox=true no-scaling-bbox=true internal-offset=true resize-method=bilinear hailoaggregator name=lp_cropper_agg lp_cropper_cropper. ! \
    queue name=lp_cropper_bypass_q leaky=no max-size-buffers=20 max-size-bytes=0 max-size-time=0  ! \
    lp_cropper_agg.sink_0 lp_cropper_cropper. ! \
    queue name=ocr_detection_scale_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0  ! \
    videoscale name=ocr_detection_videoscale n-threads=2 qos=false ! \
    queue name=ocr_detection_convert_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0  ! \
    video/x-raw, pixel-aspect-ratio=1/1 ! \
    videoconvert name=ocr_detection_videoconvert n-threads=2 ! \
    queue name=ocr_detection_hailonet_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0  ! \
    hailonet name=ocr_detection_hailonet hef-path=/usr/local/hailo/resources/models/hailo8/ocr.hef batch-size=1  vdevice-group-id=SHARED  force-writable=true  ! \
    queue name=ocr_detection_hailofilter_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0  ! \
    hailofilter name=ocr_detection_hailofilter so-path=/usr/local/hailo/resources/so/libocr_postprocess.so   function-name=paddleocr_recognize  qos=false ! \
    queue name=ocr_detection_output_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0   ! \
    lp_cropper_agg.sink_1 lp_cropper_agg. ! \
    queue name=lp_cropper_output_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0   ! \
    queue name=post_ocr_q leaky=no max-size-buffers=5 max-size-bytes=0 max-size-time=0  ! \
    identity name=identity_callback ! \
    hailofilter use-gst-buffer=true so-path=/usr/local/hailo/resources/so/liblpr_ocrsink.so qos=false ! \
    fakesink sync=false async=false

--- Available Pipeline Variants ---

  --pipeline simple               : Full LPR: Vehicle → Tracker → LP → OCR with display aggregators
  --pipeline complex              : Full LPR: Explicit low-level GStreamer elements
  --pipeline optimized            : Full LPR: Parallel display/processing with quality filter
  --pipeline optimized_direct     : Full LPR: Parallel display/processing, no quality filter
  --pipeline candidate            : Full LPR: Hardcoded paths (debugging)
  --pipeline vehicle_and_lp       : Vehicle + LP detection only (no OCR)
  --pipeline vehicle_only         : Vehicle detection only
  --pipeline lp_only              : LP detection on full frame only
  --pipeline lp_only_crops        : LP detection + crop saving (no display)
  --pipeline lp_and_ocr           : Full-frame LP + OCR (no vehicle detection) <-- CURRENT
  --pipeline lp_and_ocr_direct    : Full-frame LP + OCR with explicit elements
```

---

## Pipeline: `lp_and_ocr_direct`

```
================================================================================
PIPELINE VARIANT: lp_and_ocr_direct
================================================================================

--- GStreamer CLI Command ---

gst-launch-1.0 filesrc location="/usr/local/hailo/resources/videos/lpr_video.mp4" name=source ! queue name=source_queue_decode leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! decodebin name=source_decodebin caps=video/x-raw ! queue name=source_scale_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! videoscale name=source_videoscale n-threads=2 ! queue name=source_convert_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! videoconvert n-threads=3 name=source_convert qos=false ! video/x-raw, pixel-aspect-ratio=1/1, format=RGB, width=1280, height=720 ! videorate name=source_videorate ! capsfilter name=source_fps_caps caps="video/x-raw, framerate=30/1" ! queue name=plate_detection_scale_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! videoscale name=plate_detection_videoscale n-threads=2 qos=false ! queue name=plate_detection_convert_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! video/x-raw, pixel-aspect-ratio=1/1 ! videoconvert name=plate_detection_videoconvert n-threads=2 ! queue name=plate_detection_hailonet_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! hailonet name=plate_detection_hailonet hef-path=/usr/local/hailo/resources/models/hailo8/yolov8n_relu6_global_lp_det.hef batch-size=4 vdevice-group-id=SHARED scheduler-timeout-ms=100 nms-score-threshold=0.3 nms-iou-threshold=0.45 output-format-type=HAILO_FORMAT_TYPE_FLOAT32 force-writable=true ! queue name=plate_detection_hailofilter_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! hailofilter name=plate_detection_hailofilter so-path=/usr/local/hailo/resources/so/libyolo_hailortpp_postprocess.so config-path=/home/omria/hailo/dev/lpr/hailo-apps-infra/hailo_apps/python/pipeline_apps/license_plate_recognition/configs/yolov8n_relu6_global_lp_det.json function-name=yolov8n_relu6_license_plate qos=false ! queue name=plate_detection_output_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! hailotracker name=hailo_tracker class-id=-1 kalman-dist-thr=0.5 iou-thr=0.6 init-iou-thr=0.7 keep-new-frames=2 keep-tracked-frames=2 keep-lost-frames=2 keep-past-metadata=True qos=False ! queue name=hailo_tracker_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! tee name=main_tee main_tee. ! queue name=display_q leaky=no max-size-buffers=10 max-size-bytes=0 max-size-time=0 ! queue name=hailo_display_overlay_q leaky=no max-size-buffers=10 max-size-bytes=0 max-size-time=0 ! hailooverlay name=hailo_display_overlay ! queue name=hailo_display_videoconvert_q leaky=no max-size-buffers=10 max-size-bytes=0 max-size-time=0 ! videoconvert name=hailo_display_videoconvert n-threads=2 qos=false ! queue name=hailo_display_q leaky=no max-size-buffers=10 max-size-bytes=0 max-size-time=0 ! fpsdisplaysink name=hailo_display video-sink=xvimagesink sync=true text-overlay=False signal-fps-measurements=true main_tee. ! queue name=processing_q leaky=no max-size-buffers=10 max-size-bytes=0 max-size-time=0 ! queue name=lp_cropper_input_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! hailocropper name=lp_cropper_cropper so-path=/usr/local/hailo/resources/so/liblpr_croppers.so function-name=license_plate_no_quality use-letterbox=true no-scaling-bbox=true internal-offset=true resize-method=bilinear ! queue name=ocr_detection_scale_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! videoscale name=ocr_detection_videoscale n-threads=2 qos=false ! queue name=ocr_detection_convert_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! video/x-raw, pixel-aspect-ratio=1/1 ! videoconvert name=ocr_detection_videoconvert n-threads=2 ! queue name=ocr_detection_hailonet_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! hailonet name=ocr_detection_hailonet hef-path=/usr/local/hailo/resources/models/hailo8/ocr.hef batch-size=1 vdevice-group-id=SHARED force-writable=true ! queue name=ocr_detection_hailofilter_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! hailofilter name=ocr_detection_hailofilter so-path=/usr/local/hailo/resources/so/libocr_postprocess.so function-name=paddleocr_recognize qos=false ! queue name=ocr_detection_output_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! queue name=post_ocr_q leaky=no max-size-buffers=5 max-size-bytes=0 max-size-time=0 ! identity name=identity_callback ! hailofilter use-gst-buffer=true so-path=/usr/local/hailo/resources/so/liblpr_ocrsink.so qos=false ! fakesink sync=false async=false

--- Pipeline String (formatted) ---

gst-launch-1.0 \
    filesrc location="/usr/local/hailo/resources/videos/lpr_video.mp4" name=source ! \
    queue name=source_queue_decode leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! \
    decodebin name=source_decodebin caps=video/x-raw ! \
    queue name=source_scale_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! \
    videoscale name=source_videoscale n-threads=2 ! \
    queue name=source_convert_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! \
    videoconvert n-threads=3 name=source_convert qos=false ! \
    video/x-raw, pixel-aspect-ratio=1/1, format=RGB, width=1280, height=720 ! \
    videorate name=source_videorate ! \
    capsfilter name=source_fps_caps caps="video/x-raw, framerate=30/1" ! \
    queue name=plate_detection_scale_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! \
    videoscale name=plate_detection_videoscale n-threads=2 qos=false ! \
    queue name=plate_detection_convert_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! \
    video/x-raw, pixel-aspect-ratio=1/1 ! \
    videoconvert name=plate_detection_videoconvert n-threads=2 ! \
    queue name=plate_detection_hailonet_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! \
    hailonet name=plate_detection_hailonet hef-path=/usr/local/hailo/resources/models/hailo8/yolov8n_relu6_global_lp_det.hef batch-size=4 vdevice-group-id=SHARED scheduler-timeout-ms=100 nms-score-threshold=0.3 nms-iou-threshold=0.45 output-format-type=HAILO_FORMAT_TYPE_FLOAT32 force-writable=true ! \
    queue name=plate_detection_hailofilter_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! \
    hailofilter name=plate_detection_hailofilter so-path=/usr/local/hailo/resources/so/libyolo_hailortpp_postprocess.so config-path=/home/omria/hailo/dev/lpr/hailo-apps-infra/hailo_apps/python/pipeline_apps/license_plate_recognition/configs/yolov8n_relu6_global_lp_det.json function-name=yolov8n_relu6_license_plate qos=false ! \
    queue name=plate_detection_output_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! \
    hailotracker name=hailo_tracker class-id=-1 kalman-dist-thr=0.5 iou-thr=0.6 init-iou-thr=0.7 keep-new-frames=2 keep-tracked-frames=2 keep-lost-frames=2 keep-past-metadata=True qos=False ! \
    queue name=hailo_tracker_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! \
    tee name=main_tee main_tee. ! \
    queue name=display_q leaky=no max-size-buffers=10 max-size-bytes=0 max-size-time=0 ! \
    queue name=hailo_display_overlay_q leaky=no max-size-buffers=10 max-size-bytes=0 max-size-time=0 ! \
    hailooverlay name=hailo_display_overlay ! \
    queue name=hailo_display_videoconvert_q leaky=no max-size-buffers=10 max-size-bytes=0 max-size-time=0 ! \
    videoconvert name=hailo_display_videoconvert n-threads=2 qos=false ! \
    queue name=hailo_display_q leaky=no max-size-buffers=10 max-size-bytes=0 max-size-time=0 ! \
    fpsdisplaysink name=hailo_display video-sink=xvimagesink sync=true text-overlay=False signal-fps-measurements=true main_tee. ! \
    queue name=processing_q leaky=no max-size-buffers=10 max-size-bytes=0 max-size-time=0 ! \
    queue name=lp_cropper_input_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! \
    hailocropper name=lp_cropper_cropper so-path=/usr/local/hailo/resources/so/liblpr_croppers.so function-name=license_plate_no_quality use-letterbox=true no-scaling-bbox=true internal-offset=true resize-method=bilinear ! \
    queue name=ocr_detection_scale_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! \
    videoscale name=ocr_detection_videoscale n-threads=2 qos=false ! \
    queue name=ocr_detection_convert_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! \
    video/x-raw, pixel-aspect-ratio=1/1 ! \
    videoconvert name=ocr_detection_videoconvert n-threads=2 ! \
    queue name=ocr_detection_hailonet_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! \
    hailonet name=ocr_detection_hailonet hef-path=/usr/local/hailo/resources/models/hailo8/ocr.hef batch-size=1 vdevice-group-id=SHARED force-writable=true ! \
    queue name=ocr_detection_hailofilter_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! \
    hailofilter name=ocr_detection_hailofilter so-path=/usr/local/hailo/resources/so/libocr_postprocess.so function-name=paddleocr_recognize qos=false ! \
    queue name=ocr_detection_output_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! \
    queue name=post_ocr_q leaky=no max-size-buffers=5 max-size-bytes=0 max-size-time=0 ! \
    identity name=identity_callback ! \
    hailofilter use-gst-buffer=true so-path=/usr/local/hailo/resources/so/liblpr_ocrsink.so qos=false ! \
    fakesink sync=false async=false

--- Available Pipeline Variants ---

  --pipeline simple               : Full LPR: Vehicle → Tracker → LP → OCR with display aggregators
  --pipeline complex              : Full LPR: Explicit low-level GStreamer elements
  --pipeline optimized            : Full LPR: Parallel display/processing with quality filter
  --pipeline optimized_direct     : Full LPR: Parallel display/processing, no quality filter
  --pipeline candidate            : Full LPR: Hardcoded paths (debugging)
  --pipeline vehicle_and_lp       : Vehicle + LP detection only (no OCR)
  --pipeline vehicle_only         : Vehicle detection only
  --pipeline lp_only              : LP detection on full frame only
  --pipeline lp_only_crops        : LP detection + crop saving (no display)
  --pipeline lp_and_ocr           : Full-frame LP + OCR (no vehicle detection)
  --pipeline lp_and_ocr_direct    : Full-frame LP + OCR with explicit elements <-- CURRENT
```

---

## Pipeline: `ocr_only`

```
================================================================================
PIPELINE VARIANT: ocr_only
================================================================================

--- GStreamer CLI Command ---

gst-launch-1.0 filesrc location="/usr/local/hailo/resources/videos/lpr_video.mp4" name=source ! queue name=source_queue_decode leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! decodebin name=source_decodebin ! queue name=source_scale_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! videoscale name=source_videoscale n-threads=2 ! queue name=source_convert_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! videoconvert n-threads=3 name=source_convert qos=false ! video/x-raw, pixel-aspect-ratio=1/1, format=RGB, width=1280, height=720 ! videorate name=source_videorate ! capsfilter name=source_fps_caps caps="video/x-raw, framerate=30/1" ! queue name=inference_wrapper_input_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! hailocropper name=inference_wrapper_crop so-path=/usr/lib/x86_64-linux-gnu/hailo/tappas/post_processes/cropping_algorithms/libwhole_buffer.so function-name=create_crops use-letterbox=true resize-method=inter-area internal-offset=true hailoaggregator name=inference_wrapper_agg inference_wrapper_crop. ! queue name=inference_wrapper_bypass_q leaky=no max-size-buffers=20 max-size-bytes=0 max-size-time=0 ! inference_wrapper_agg.sink_0 inference_wrapper_crop. ! queue name=ocr_detection_scale_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! videoscale name=ocr_detection_videoscale n-threads=2 qos=false ! queue name=ocr_detection_convert_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! video/x-raw, pixel-aspect-ratio=1/1 ! videoconvert name=ocr_detection_videoconvert n-threads=2 ! queue name=ocr_detection_hailonet_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! hailonet name=ocr_detection_hailonet hef-path=/usr/local/hailo/resources/models/hailo8/ocr.hef batch-size=1 vdevice-group-id=SHARED force-writable=true ! queue name=ocr_detection_hailofilter_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! hailofilter name=ocr_detection_hailofilter so-path=/usr/local/hailo/resources/so/libocr_postprocess.so function-name=paddleocr_recognize qos=false ! queue name=ocr_detection_output_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! inference_wrapper_agg.sink_1 inference_wrapper_agg. ! queue name=inference_wrapper_output_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! identity name=identity_callback ! fakesink sync=false async=false

--- Pipeline String (formatted) ---

gst-launch-1.0 \
    filesrc location="/usr/local/hailo/resources/videos/lpr_video.mp4" name=source ! \
    queue name=source_queue_decode leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0  ! \
    decodebin name=source_decodebin ! \
     queue name=source_scale_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0  ! \
    videoscale name=source_videoscale n-threads=2 ! \
    queue name=source_convert_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0  ! \
    videoconvert n-threads=3 name=source_convert qos=false ! \
    video/x-raw, pixel-aspect-ratio=1/1, format=RGB, width=1280, height=720 ! \
    videorate name=source_videorate ! \
    capsfilter name=source_fps_caps caps="video/x-raw, framerate=30/1"  ! \
    queue name=inference_wrapper_input_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0  ! \
    hailocropper name=inference_wrapper_crop so-path=/usr/lib/x86_64-linux-gnu/hailo/tappas/post_processes/cropping_algorithms/libwhole_buffer.so function-name=create_crops use-letterbox=true resize-method=inter-area internal-offset=true hailoaggregator name=inference_wrapper_agg inference_wrapper_crop. ! \
    queue name=inference_wrapper_bypass_q leaky=no max-size-buffers=20 max-size-bytes=0 max-size-time=0  ! \
    inference_wrapper_agg.sink_0 inference_wrapper_crop. ! \
    queue name=ocr_detection_scale_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0  ! \
    videoscale name=ocr_detection_videoscale n-threads=2 qos=false ! \
    queue name=ocr_detection_convert_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0  ! \
    video/x-raw, pixel-aspect-ratio=1/1 ! \
    videoconvert name=ocr_detection_videoconvert n-threads=2 ! \
    queue name=ocr_detection_hailonet_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0  ! \
    hailonet name=ocr_detection_hailonet hef-path=/usr/local/hailo/resources/models/hailo8/ocr.hef batch-size=1  vdevice-group-id=SHARED  force-writable=true  ! \
    queue name=ocr_detection_hailofilter_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0  ! \
    hailofilter name=ocr_detection_hailofilter so-path=/usr/local/hailo/resources/so/libocr_postprocess.so   function-name=paddleocr_recognize  qos=false ! \
    queue name=ocr_detection_output_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0   ! \
    inference_wrapper_agg.sink_1 inference_wrapper_agg. ! \
    queue name=inference_wrapper_output_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0   ! \
    identity name=identity_callback ! \
    fakesink sync=false async=false

--- Available Pipeline Variants ---

  --pipeline simple               : Full LPR: Vehicle → Tracker → LP → OCR with display aggregators
  --pipeline complex              : Full LPR: Explicit low-level GStreamer elements
  --pipeline optimized            : Full LPR: Parallel display/processing with quality filter
  --pipeline optimized_direct     : Full LPR: Parallel display/processing, no quality filter
  --pipeline candidate            : Full LPR: Hardcoded paths (debugging)
  --pipeline vehicle_and_lp       : Vehicle + LP detection only (no OCR)
  --pipeline vehicle_only         : Vehicle detection only
  --pipeline lp_only              : LP detection on full frame only
  --pipeline lp_only_crops        : LP detection + crop saving (no display)
  --pipeline lp_and_ocr           : Full-frame LP + OCR (no vehicle detection)
  --pipeline lp_and_ocr_direct    : Full-frame LP + OCR with explicit elements
```

