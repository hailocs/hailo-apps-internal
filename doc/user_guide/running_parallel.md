# Running Multiple Hailo Applications in Parallel
This guide explains how to run multiple Hailo applications simultaneously on the same device, supporting combinations of vision (GStreamer) and GenAI applications.

## Overview
The Hailo platform allows running multiple applications in parallel by using shared virtual device groups. This is achieved through the SHARED_VDEVICE_GROUP_ID constant, which ensures all applications access the same device resources efficiently.

## Supported Combinations
✅ Supported:

- Vision + Vision (multiple GStreamer pipelines)
- Vision + GenAI (GStreamer pipeline + GenAI application)

❌ Not Supported:

- GenAI + GenAI (they use the same service and cannot run simultaneously)

## Configuration
### For Vision Applications (GStreamer)
When using the INFERENCE_PIPELINE helper function, ensure the vdevice_group_id parameter is set correctly:

```python
from hailo_apps.python.core.common.defines import SHARED_VDEVICE_GROUP_ID
from hailo_apps.python.core.gstreamer.gstreamer_helper_pipelines import INFERENCE_PIPELINE

# Create your inference pipeline with shared vdevice group
inference_pipeline = INFERENCE_PIPELINE(
    hef_path="path/to/model.hef",
    post_process_so="path/to/postprocess.so",
    batch_size=1,
    vdevice_group_id=SHARED_VDEVICE_GROUP_ID,  # ⚠️ Required for parallel execution
    name="my_inference"
)
```

#### Important Notes:

The vdevice_group_id parameter is already set to SHARED_VDEVICE_GROUP_ID by default in INFERENCE_PIPELINE.

The constant SHARED_VDEVICE_GROUP_ID = "SHARED" is defined in defines.py

⚠️ Critical Reminder: Do not modify the SHARED_VDEVICE_GROUP_ID constant or use different group IDs between applications - this will prevent parallel execution.

### For GenAI Applications
When creating a VDevice in your GenAI application, configure it with the shared group ID:

```python
from hailo_platform import VDevice

# Create VDevice parameters with shared group ID
params = VDevice.create_params()
params.group_id = "SHARED"  # ⚠️ Must match SHARED_VDEVICE_GROUP_ID
self._vdevice = VDevice(params)
```

## Performance considerations:

- Each application shares device resources

- Total throughput may be lower than running a single application

- Consider batch sizes and frame rates accordingly

- Error handling: Implement proper error handling for device initialization failures

## Testing: 
Test your multi-application setup under expected load conditions

## Troubleshooting

- Applications Not Running in Parallel

    Problem: Only one application runs at a time.

    Solution: Verify both applications use vdevice_group_id=SHARED_VDEVICE_GROUP_ID (or params.group_id = "SHARED" for GenAI apps).

- Device Resource Errors

    Problem: "Insufficient device resources" error.

    Solution:

    Reduce batch sizes, Lower frame rates, Check if you're attempting to run multiple GenAI applications (not supported)