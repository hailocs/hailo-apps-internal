from hailo_platform import VDevice
from hailo_platform.genai import VLM
from hailo_apps.python.core.common.core import get_resource_path
from hailo_apps.python.core.common.defines import VLM_MODEL_NAME_H10, RESOURCES_MODELS_DIR_NAME
import numpy as np
import cv2

vdevice = None
vlm = None

try:
    vdevice = VDevice()
    vlm = VLM(vdevice, str(get_resource_path(pipeline_name=None, resource_type=RESOURCES_MODELS_DIR_NAME, model=VLM_MODEL_NAME_H10)))
    
    prompt = [
        {
            "role": "system", 
            "content": [{"type": "text", "text": 'You are a helpful assistant that analyzes images and answers questions about them.'}]
        },
        {
            "role": "user", 
            "content": [
                {"type": "image"}, 
                {"type": "text", "text": 'How many people in the image?.'}
            ]
        }
    ]
    
    # Load and convert image
    image = cv2.imread('../../../../doc/images/barcode-example.png')
    if image is None:
        raise FileNotFoundError("Could not load image file")
    
    if len(image.shape) == 3 and image.shape[2] == 3:
        image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)

    image = cv2.resize(image, (336, 336), interpolation=cv2.INTER_LINEAR).astype(np.uint8)
    response = vlm.generate_all(prompt=prompt, frames=[image], temperature=0.1, seed=42, max_generated_tokens=200)
    print(response.split(". [{'type'")[0].split("<|im_end|>")[0])
    
except Exception as e:
    print(f"Error occurred: {e}")
    
finally:
    # Clean up resources
    if vlm:
        try:
            vlm.clear_context()
            vlm.release()
        except Exception as e:
            print(f"Error releasing VLM: {e}")
    
    if vdevice:
        try:
            vdevice.release()
        except Exception as e:
            print(f"Error releasing VDevice: {e}")