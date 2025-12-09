import argparse
import sys
from hailo_platform import VDevice
from hailo_platform.genai import LLM
from hailo_apps.python.core.common.core import get_resource_path, handle_list_models_flag, resolve_hef_path
from hailo_apps.python.core.common.defines import LLM_CHAT_APP, LLM_MODEL_NAME_H10, RESOURCES_MODELS_DIR_NAME, SHARED_VDEVICE_GROUP_ID, HAILO10H_ARCH

# Parse arguments
parser = argparse.ArgumentParser(description="LLM Chat Example")
parser.add_argument("--hef-path", type=str, default=None, help="Path to HEF model file")
parser.add_argument("--list-models", action="store_true", help="List available models")

# Handle --list-models flag before full initialization
handle_list_models_flag(parser, LLM_CHAT_APP)

args = parser.parse_args()

# Resolve HEF path with auto-download (LLM is Hailo-10H only)
hef_path = resolve_hef_path(args.hef_path, app_name=LLM_CHAT_APP, arch=HAILO10H_ARCH)
if hef_path is None:
    print("Error: Failed to resolve HEF path for LLM model.")
    sys.exit(1)

print(f"Using HEF: {hef_path}")

vdevice = None
llm = None

try:
    params = VDevice.create_params()
    params.group_id = SHARED_VDEVICE_GROUP_ID
    vdevice = VDevice(params)
    llm = LLM(vdevice, str(hef_path))
    
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