Pose Estimation -  *yolo26* with lightweight onnx postprocessing
================================================================

Similar to ../pose_estimation, adding and exemplifying the following capabilities:
1. Using the new 2026 Ultralytics release of top performing, NMS-free networks. 
1. Using onnx-runtime engine for the lightweight postprocessing, exemplifying this easy integration pathway.
1. Adding demo variations exposing the applicative potential of high-quality high-speed pose estimation:
    1. Skeleton tracklet ("following shadow"), showcasing the "dense" (on time axis) recognitions unlocked by the high FPS.
    1. Integrating ultralytics aigym (LINK) - counting fitness exercise repetitions; showcasing the general action-recognition potential


TODO visual examples of both.


Supported Models
----------------

The variants currently supported include:
- yolov26n_pose, compiled for H10
- yolov26s_pose, compiled for H10
- yolov26m_pose, compiled for H10

ONNX postprocessing
-------------------
Similarly to hailo_apps/cpp/onnxrt_hailo_pipeline, this example uses onnxruntime for the postprocessing part.  This makes integration of new networks especially convenient, by following these steps:
1. Split the ONNX into the "neural processing" and the "postprocessing" parts using extract_postprocessing.py script
2. Process the first part into a HEF using the DFC
3. In runtime, apply the second part on the HEF outputs with onnx-runtime engine to complete an accelerated equivalent of the original ONNX. This runtime part is implemented and exemplified in this app.
4. The desired "full-onnx = HEF + postproc-onnx" equivalence can be conveniently debugged (isolating pipeline vs. compilation issues and HEF degradation) using --full-onnx flag that applies a bypass of the HEF (using the 'neural-processing' split-onnx 1st part). This is also useful for quick 'dry' tests without hardware or compilation at all - as well as benchmarking the acceleration provided by Hailo's offloading of the neural part to HEF running on hardware.

Install and requirements
------------------------
Same as for base pose estimation.  The postprocessing ONNX binary is lazy-downloaded alongside the HEF.
