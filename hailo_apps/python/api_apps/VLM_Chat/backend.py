import time
import multiprocessing as mp
import numpy as np
import cv2
from hailo_platform import VDevice
from hailo_platform.genai import VLM

def vlm_worker_process(request_queue, response_queue, hef_path, max_tokens, temperature, seed):
    try:
        vdevice = VDevice()
        vlm = VLM(vdevice, hef_path)
        while True:
            item = request_queue.get()
            if item is None:
                break
            response_queue.put({'result': _hailo_inference_inner(item['numpy_image'], item['prompts'], vlm, max_tokens, temperature, seed), 'error': None})
    except Exception as e:
        response_queue.put({'result': None, 'error': f"{str(e)}"})
    finally:
        try:
            vlm.release()
            vdevice.release()
        except:
            pass

def _hailo_inference_inner(image, prompts, vlm, max_tokens, temperature, seed):
    try:
        response = ''
        start_time = time.time()
        prompt = [
            {
                "role": "system", 
                "content": [{"type": "text", "text": prompts['system_prompt']}]
            },
            {
                "role": "user", 
                "content": [
                    {"type": "image"}, 
                    {"type": "text", "text": prompts['user_prompt']}
                ]
            }
        ]
        with vlm.generate(prompt=prompt, frames=[image], temperature=temperature, seed=seed, max_generated_tokens=max_tokens) as generation:
            for chunk in generation:
                if chunk != '<|im_end|>':
                    print(chunk, end='', flush=True)
                    response += chunk  
        vlm.clear_context()
        end_time = time.time()
        return {'answer': response.replace('<|im_end|>', '').strip(), 'time': f"{end_time - start_time:.2f} seconds"}
    except Exception as e:
        return {'answer': f'Error: {str(e)}', 'time': f"{time.time() - start_time:.2f} seconds"}

class Backend:
    def __init__(self, hef_path, max_tokens=200, temperature=0.1, seed=42):
        self.hef_path = hef_path
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.seed = seed
        self.system_prompt = 'You are a helpful assistant that analyzes images and answers questions about them.'
        
        self._request_queue = mp.Queue(maxsize=10)  # Limit queue size
        self._response_queue = mp.Queue(maxsize=10)
        self._process = mp.Process(
            target=vlm_worker_process, 
            args=(self._request_queue, self._response_queue, self.hef_path, self.max_tokens, self.temperature, self.seed)
        )
        self._process.start()

    def vlm_inference(self, image, prompt):
        request_data = {
            'numpy_image': self.convert_resize_image(image),
            'prompts': {
                'system_prompt': self.system_prompt,
                'user_prompt': prompt,
            }
        }
        return self._execute_inference(request_data)

    def _execute_inference(self, request_data):
        self._request_queue.put(request_data)
        try:
            response = self._response_queue.get(timeout=30)
            if response['error']:
                return {'answer': f"Error: {response['error']}", 'time': 'error'}
            return response['result']
        except mp.TimeoutError:
            while not self._request_queue.empty():
                try:
                    self._request_queue.get_nowait()
                except:
                    break
            while not self._response_queue.empty():
                try:
                    self._response_queue.get_nowait()
                except:
                    break
            return {'answer': 'Request timed out after 30 seconds', 'time': '30+ seconds'}
        except Exception as e:
            return {'answer': f'Queue error: {str(e)}', 'time': 'error'}

    @staticmethod
    def convert_resize_image(image_array, target_size=(336, 336)):
        """Simplified image processing"""
        # Convert BGR to RGB if needed
        if len(image_array.shape) == 3 and image_array.shape[2] == 3:
            image_array = cv2.cvtColor(image_array, cv2.COLOR_BGR2RGB)
        
        # Resize to target size
        resized = cv2.resize(image_array, target_size, interpolation=cv2.INTER_LINEAR)
        return resized.astype(np.uint8)

    def close(self):
        try:
            self._request_queue.put(None)
            self._process.join(timeout=2)
            if self._process.is_alive():
                self._process.terminate()
        except:
            pass