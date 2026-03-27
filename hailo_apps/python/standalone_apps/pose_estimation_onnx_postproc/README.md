Pose Estimation -  *yolo26* with lightweight onnx postprocessing
================================================================

Similar to ../pose_estimation, adding and exemplifying the following capabilities:
1. Using the new 2026 Ultralytics release of top performing, NMS-free networks. 
1. Using onnx-runtime engine for the lightweight postprocessing, exemplifying this easy integration pathway.
1. Adding demo variations exposing the applicative potential of high-quality high-speed pose estimation:
    1. Skeleton tracklet ("following shadow"), showcasing the "dense" (on time axis) recognitions unlocked by the high FPS.
    1. Integrating [Ultralytics' AIgym](https://docs.ultralytics.com/guides/workouts-monitoring/) - counting fitness exercise repetitions; showcasing the general action-recognition potential. Note that in practice it ONLY works smoothly with Hailo's acceleration; the 2-3FPS achievable on RPi CPU by using the smallest network are not sufficient for capturing reasonably fast movement. 

<p align="center">
    <img src="output.gif" width="320" alt="Reflection-loop trail demo" />
    <img src="output_aigym.gif" width="320" alt="AIGym trail demo" />
</p>

See usage options for these demos below.


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


Usage examples
--------------

Draw a trail of 10 past frames (~0.3sec) and deemphasize background:
```
python pose_estimation_onnx_postproc.py --i example.mp4 --hef yolo26m_pose --no-display --mute-background 0.5 --pose-trail 10
```
![Reflection-loop trail demo](output.gif)

Count squats for a whole class at once ("aigym"):
```
python pose_estimation_onnx_postproc.py --i grok-squats.mp4 --hef yolo26m_pose --no-display --aigym squats
```
(try pushups, pullups as well :)
![aigym trail demo](output_aigym.gif)