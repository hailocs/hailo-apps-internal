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
    <img src="output_aigym.gif" width="220" alt="AIGym trail demo" />
</p>



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
4. The desired "debug reference ONNX = HEF + postproc-onnx" equivalence can be tested by passing --neural-onnx-ref <path>, which bypasses HEF inference and feeds postprocessing from a user-provided reference ONNX model. This is useful for quick dry tests and for isolating pipeline-vs-compilation differences.

Install and requirements
------------------------
Requirements: 
[same as base pose estimation](https://github.com/hailo-ai/hailo-apps/blob/main/hailo_apps/python/standalone_apps/pose_estimation/README.md#requirements) + onnx-runtime.

Install: [same as base pose estimation](https://github.com/hailo-ai/hailo-apps/blob/main/hailo_apps/python/standalone_apps/pose_estimation/README.md#option-1-standalone-installation).

The postprocessing ONNX binary is lazy-downloaded alongside the HEF.


Arguments
--------------
[As in base pose estimation](https://github.com/hailo-ai/hailo-apps/blob/main/hailo_apps/python/standalone_apps/pose_estimation/README.md#arguments) + the following additions:

- `--onnx ONNX_PP_FILE`: [optional] Override path to ONNX postprocessing model file (2nd part of split). If omitted, use existing resource lazy-downloaded from preconfigured cloud path (alongside the HEF)
- `--onnx-config ONNX_CONFIG_FILE`: [optional] Path to the ONNX postprocessing configuration file. If omitted, a default configuration is used if available.
- `--aigym EXERCISE`: [optional] Enable exercise rep-counting mode. Adds ByteTrack multi-person tracking and angle-based hysteresis counting. Choices of EXERCISE: squats, pushups, pullups.
- `--pose-trail N`: [optional]Number of previous frames whose pose skeletons are kept and drawn as a fading trail behind the current detection. 0 (default) disables the trail. Typical value: 10.
- `--mute-background ALPHA`: [optional] Dim the background image to emphasize pose skeletons.
- `--neural-onnx-ref ONNX_HEF_EQ_FILE`: [optional] For debug or quality/speed benchmarking - use a 'neural ONNX' file (1st part of splitting - corresponding to the HEF) to bypass hardware and run reference hef-equivalent model on the host CPU via the onnx-runtime engine.


Examples:

[Note - exemplified for video but available for real-time feed with --i usb or --i rpi as in other apps]

Draw a trail of 10 past frames (~0.3sec) and deemphasize background:
```
python pose_estimation_onnx_postproc.py --i example.mp4 --hef yolo26m_pose --no-display --mute-background 0.5 --pose-trail 10
```
![Reflection-loop trail demo](output.gif)

Count squats for a whole class at once ("aigym"):
```
python pose_estimation_onnx_postproc.py --i grok-squats.mp4 --hef yolo26m_pose --no-display --aigym squats
```
try pushups, pullups as well :)

![aigym trail demo](output_aigym.gif)