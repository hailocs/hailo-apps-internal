(venv_hailo_apps) omria@hlil-414-lap:~/hailo/current_work/CSG-145/hailo-apps$ GST_DEBUG=3 hailo-lpr &> lpr20.txt
^C(venv_hailo_apps) omria@hlil-414-lap:~/hailo/current_work/CSG-145/hailo-apps$ GST_DEBUG=6 hailo-lpr &> lpr21.txt
^C(venv_hailo_apps) omria@hlil-414-lap:~/hailo/current_work/CSG-145/hailo-apps$ hailortcli run resources/models/hailo8/ocr.hef --batch-size 8 
Running streaming inference (resources/models/hailo8/ocr.hef):
  Transform data: true
    Type:      auto
    Quantized: true
Network simplified/simplified: 100% | 3456 | FPS: 687.14 | ETA: 00:00:00
> Inference result:
 Network group: simplified
    Frames count: 3456
    FPS: 687.17
    Send Rate: 253.32 Mbit/s
    Recv Rate: 22.87 Mbit/s

(venv_hailo_apps) omria@hlil-414-lap:~/hailo/current_work/CSG-145/hailo-apps$ hailortcli run resources/models/hailo8/yolov8n_relu6_global_lp_det.hef --batch-size 8 
Running streaming inference (resources/models/hailo8/yolov8n_relu6_global_lp_det.hef):
  Transform data: true
    Type:      auto
    Quantized: true
Network yolov8n_relu6_global_lp_det_v8/yolov8n_relu6_global_lp_det_v8: 100% | 5409 | FPS: 1080.63 | ETA: 00:00:00
> Inference result:
 Network group: yolov8n_relu6_global_lp_det_v8
    Frames count: 5409
    FPS: 1080.66
    Send Rate: 10623.29 Mbit/s
    Recv Rate: 4765.27 Mbit/s

(venv_hailo_apps) omria@hlil-414-lap:~/hailo/current_work/CSG-145/hailo-apps$ hailortcli run resources/models/hailo8/yolov8n_relu6_global_lp_det.hef 
Running streaming inference (resources/models/hailo8/yolov8n_relu6_global_lp_det.hef):
  Transform data: true
    Type:      auto
    Quantized: true
Network yolov8n_relu6_global_lp_det_v8/yolov8n_relu6_global_lp_det_v8: 100% | 5382 | FPS: 1075.26 | ETA: 00:00:00
> Inference result:
 Network group: yolov8n_relu6_global_lp_det_v8
    Frames count: 5382
    FPS: 1075.28
    Send Rate: 10570.44 Mbit/s
    Recv Rate: 4741.56 Mbit/s

(venv_hailo_apps) omria@hlil-414-lap:~/hailo/current_work/CSG-145/hailo-apps$ hailortcli run resources/models/hailo8/yolov5m_vehicles.hef 
Running streaming inference (resources/models/hailo8/yolov5m_vehicles.hef):
  Transform data: true
    Type:      auto
    Quantized: true
Network yolov5m_vehicles/yolov5m_vehicles: 100% | 438 | FPS: 87.50 | ETA: 00:00:00
> Inference result:
 Network group: yolov5m_vehicles
    Frames count: 438
    FPS: 87.50
    Send Rate: 4354.80 Mbit/s
    Recv Rate: 106.85 Mbit/s

(venv_hailo_apps) omria@hlil-414-lap:~/hailo/current_work/CSG-145/hailo-apps$ 
