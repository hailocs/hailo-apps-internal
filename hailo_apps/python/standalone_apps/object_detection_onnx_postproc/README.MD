Object detection - *yolo26* with lightweight onnx postprocessing
=============================================================

Similar to ../object_detection, adding and exemplifying the following capabilities:
1. Using the new 2026 Ultralytics release of top performing, NMS-free networks. 
1. Using onnx-runtime engine for the lightweight postprocessing, exemplifying this easy integration pathway.

Supported Models
----------------

The variants currently supported include:
- yolov26n, compiled for H8

ONNX postprocessing
-------------------
Similarly to hailo_apps/cpp/onnxrt_hailo_pipeline, this example uses onnxruntime for the postprocessing part.  This makes integration of new networks especially convenient, by following these steps:
1. Split the ONNX into the "neural processing" and the "postprocessing" parts using extract_postprocessing.py script
2. Process the first part into a HEF using the DFC
3. In runtime, apply the second part on the HEF outputs with onnx-runtime engine to complete an accelerated equivalent of the original ONNX. This runtime part is implemented and exemplified in this app.
4. The desired "full-onnx = HEF + postproc-onnx" equivalence can be conveniently debugged (isolating pipeline vs. compilation issues and HEF degradation) using --full-onnx flag that applies a bypass of the HEF (using the 'neural-processing' split-onnx 1st part). This is also useful for quick 'dry' tests without hardware or compilation at all - as well as benchmarking the acceleration provided by Hailo's offloading of the neural part to HEF running on hardware.

Install and requirements
------------------------
Same as for base object detection.  The postprocessing ONNX binary is lazy-downloaded alongside the HEF.
