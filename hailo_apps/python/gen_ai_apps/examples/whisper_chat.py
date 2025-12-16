import argparse
import sys
import wave
import numpy as np
from hailo_platform import VDevice
from hailo_platform.genai import Speech2Text, Speech2TextTask
from hailo_apps.python.core.common.core import get_resource_path, handle_list_models_flag, resolve_hef_path
from hailo_apps.python.core.common.defines import WHISPER_CHAT_APP, RESOURCES_MODELS_DIR_NAME, WHISPER_MODEL_NAME_H10, SHARED_VDEVICE_GROUP_ID, HAILO10H_ARCH

# Parse arguments
parser = argparse.ArgumentParser(description="Whisper Speech-to-Text Example")
parser.add_argument("--hef-path", type=str, default=None, help="Path to HEF model file")
parser.add_argument("--list-models", action="store_true", help="List available models")
parser.add_argument("--audio", type=str, default="audio.wav", help="Path to audio file")

# Handle --list-models flag before full initialization
handle_list_models_flag(parser, WHISPER_CHAT_APP)

args = parser.parse_args()

# Resolve HEF path with auto-download (Whisper is Hailo-10H only)
hef_path = resolve_hef_path(args.hef_path, app_name=WHISPER_CHAT_APP, arch=HAILO10H_ARCH)
if hef_path is None:
    print("Error: Failed to resolve HEF path for Whisper model.")
    sys.exit(1)

print(f"Using HEF: {hef_path}")

vdevice = None
speech2text = None

try:
    params = VDevice.create_params()
    params.group_id = SHARED_VDEVICE_GROUP_ID
    vdevice = VDevice(params)
    speech2text = Speech2Text(vdevice, str(hef_path))

    # Load audio file using wave module instead of librosa
    audio_path = args.audio
    
    with wave.open(audio_path, 'rb') as wav_file:
        # Get audio parameters
        frames = wav_file.getnframes()
        sample_rate = wav_file.getframerate()
        channels = wav_file.getnchannels()
        sample_width = wav_file.getsampwidth()
        # Read raw audio data
        raw_audio = wav_file.readframes(frames)
    
    # Convert to numpy array based on sample width
    audio_data = np.frombuffer(raw_audio, dtype=np.int16)
    # Convert 16-bit to float32 and normalize
    audio_data = audio_data.astype(np.float32) / 32768.0
    # Ensure little-endian format as expected by the model
    audio_data = audio_data.astype('<f4')
    
    # Create generator parameters and generate segments
    segments = speech2text.generate_all_segments(
        audio_data=audio_data, 
        task=Speech2TextTask.TRANSCRIBE,
        language="en",
        timeout_ms=15000)
    
    if segments and len(segments) > 0:
        # Combine all segments into a single transcription
        transcription = ''.join([seg.text for seg in segments])
        print(transcription.strip())
    else:
        print("No transcription generated")
    
except FileNotFoundError as e:
    print(f"Audio file not found: {e}")
except wave.Error as e:
    print(f"Error reading WAV file: {e}")
except Exception as e:
    print(f"Error occurred: {e}")
    
finally:
    # Clean up resources
    if speech2text:
        try:
            speech2text.release()
        except Exception as e:
            print(f"Error releasing Speech2Text: {e}")
    
    if vdevice:
        try:
            vdevice.release()
        except Exception as e:
            print(f"Error releasing VDevice: {e}")