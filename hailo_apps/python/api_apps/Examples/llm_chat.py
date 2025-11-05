from hailo_platform import VDevice
from hailo_platform.genai import LLM
from hailo_apps.python.core.common.core import get_resource_path
from hailo_apps.python.core.common.defines import LLM_MODEL_NAME_H10, RESOURCES_MODELS_DIR_NAME, SHARED_VDEVICE_GROUP_ID

vdevice = None
llm = None

try:
    params = VDevice.create_params()
    params.group_id = SHARED_VDEVICE_GROUP_ID
    vdevice = VDevice(params)
    print(get_resource_path(pipeline_name=None, resource_type=RESOURCES_MODELS_DIR_NAME, model=LLM_MODEL_NAME_H10))
    llm = LLM(vdevice, str(get_resource_path(pipeline_name=None, resource_type=RESOURCES_MODELS_DIR_NAME, model=LLM_MODEL_NAME_H10)))
    
    prompt = [
        {"role": "system", "content": [{"type": "text", "text": 'You are a helpful assistant.'}]},
        {"role": "user", "content": [{"type": "text", "text": 'Tell a short joke.'}]}
    ]
    
    response = llm.generate_all(prompt=prompt, temperature=0.1, seed=42, max_generated_tokens=200)
    print(response.split(". [{'type'")[0])
    
except Exception as e:
    print(f"Error occurred: {e}")
    
finally:
    if llm:
        try:
            llm.clear_context()
            llm.release()
        except Exception as e:
            print(f"Error releasing LLM: {e}")
    
    if vdevice:
        try:
            vdevice.release()
        except Exception as e:
            print(f"Error releasing VDevice: {e}")