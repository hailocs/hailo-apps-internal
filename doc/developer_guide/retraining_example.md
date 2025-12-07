# Using YOLOv8 Retraining Docker

In this example, we're going to retrain the model to detect barcodes using the barcode-detector dataset from Kaggle. After the retraining process, we're going to convert the model to HEF and test it on the Raspberry Pi 5 AI Kit (or any X86 platform with a Hailo accelerator).

#### This tutorial (training the model & compiling the result into HEF) was created on a development machine with the following specifications:

- CPU: Intel Xeon w7-3455
- GPU: 2x RTX 4500
- RAM: 202 GB
- OS: Ubuntu 24.04

#### However:
- Training phase can be executed on any cloud service providing GPU resources (including Python notebook based).
- Hailo compilation phase (convertion to HEF), although compute intensive, is managable on regular PC's (e.g., as an overnight task).

## On the training machine

First we recommened to set a Python virtual envioronment:

```bash
python -m venv env
source env/bin/activate
```

### Get the dataset:
 
In order to easily download the Kaggle dataset via CLI on the development machine (which in many cases might be accessible only remotely via CLI):

```bash
pip install kagglehub
```

Go to the dataset page on Kaggle [barcode-detector](https://www.kaggle.com/datasets/kushagrapandya/barcode-detection) - click "Download" and copy-paste the Python code to a new Python file (script) saved on the development machine. 
It should look like:

```bash
import kagglehub
path = kagglehub.dataset_download("kushagrapandya/barcode-detection")
print("Path to dataset files:", path)
```

Execute the script. This will download the dataset directly to the development machine to a location similar to: `~/.cache/kagglehub/datasets/kushagrapandya/barcode-detection/versions/1:/data`. 

Explore the folder structure, please pay attention to various data sets (test, train, valid), the structure - images & labels folders with files corresponding by name, how a label file looks like: object per row, leading with class number (0-Barcode or 1-QR Code in our case) and then represented via bounding box coordinates.

### Launch the retraining

This process might take a couple of hours. It's possible to execute with `epochs=1` to expedite testing the process validity end-to-end before launching full-scale training.

The following dependency installation takes time:
```bash
pip install ultralytics
```

Execute the script (we will use 20 epochs):

```bash
from ultralytics import YOLO
dataset_dir = '.cache/kagglehub/datasets/kushagrapandya/barcode-detection/versions/1'
model = YOLO('yolov8s.pt')
results = model.train(data=f'{dataset_dir}/data.yaml', epochs=20, imgsz=640, batch=8, name='retrain_yolov8s')
success = model.export(format='onnx', opset=11)
```

The trained model file (onnx) typically is saved to `~/runs/detect/retrain_yolov8s/weights/best.onnx`.

## Hailo compilation

1. Download Hailo Dataflow Compiler (DFC) & Hailo Model Zoo (HMZ) from the [Developer Zone](https://hailo.ai/developer-zone/software-downloads/). These are two `.whl` files.
2. pip install the two `.whl` files downloaded above (DFC & HMZ) (we recommend to use a Python virtual envioronment).
3. Download the corresponding YAML from [our networks configuration directory](https://github.com/hailo-ai/hailo_model_zoo/tree/833ae6175c06dbd6c3fc8faeb23659c9efaa2dbe/hailo_model_zoo/cfg/networks), i.e., `hailo_model_zoo/cfg/networks/yolov8s.yaml`.
4. `yolov8s_nms_config.json` file is required in a dedicated directory. Create the directory manually and move the required JSON file there:

    ```bash
    cd ~/lib/python3.12/site-packages/hailo_model_zoo/cfg/
    mkdir postprocess_config
    ```
    The JSON file can be found as follows: 
    In the YAML file mentioned above, find the zip URL - download the file - unzip - copy the JSON file into the above `postprocess_config` directory.

5. Use the Hailo Model Zoo command (this can take up to hours):

    - Note 1: In this example we are compiling to a target Hailo 10H device, other platforms (such as 8 or 8L) also available.
    - Note 2: For compilation use the validation set (`valid`) for calibration data, as it represents unseen data but is available during the model optimization process: Used to tune hyperparameters and monitor training progress.

```bash
hailomz compile --ckpt ~/path_to/best.onnx --calib-path ~/path_to_valid_data_set/ --yaml yolov8s.yaml --classes 2 --hw-arch hailo10h --performance
```

## The yolov8s.hef file is now ready and can be used on the Raspberry Pi 5 AI Kit

Load a custom model's HEF using the `--hef-path` flag. Default labels are [COCO labels](https://github.com/ultralytics/ultralytics/blob/main/ultralytics/cfg/datasets/coco.yaml) (80 classes). For custom models with different labels, use the `--labels-path` flag to load your labels file (e.g., `/resources/json/barcode_labels.json`).

Please note:

The Kaggle barcode dataset has 2 classes: ['Barcode', 'QR Code'].

YOLO assigns class IDs starting from 0:

    Class 0 = 'Barcode'
    Class 1 = 'QR Code'

Hailo Model Conversion: 

When YOLO models are converted to Hailo format, they allocate an extra class at index 0 for background/unlabeled detections. This shifts the actual classes:

    Class 0 = 'unlabeled' (background)
    Class 1 = 'Barcode'
    Class 2 = 'QR Code'

### Running the detection application with the example retrained model
To download the example retrained model, run the following command:
```bash
hailo-download-resources --group retrain
```

The default package installation downloads the network trained in the retraining example above, which can be used as a reference (including `/resources/json/barcode_labels.json`).

Here is an example of the command line required to run the application with the retrained custom model:
```bash
python hailo_apps/python/pipeline_apps/detection/detection.py --labels-json resources/json/barcode_labels.json --hef-path resources/models/hailo8l/yolov8s-hailo8l-barcode.hef --input resources/videos/barcode.mp4
```

Example output:

![Example output](../images/barcode-example.png)
