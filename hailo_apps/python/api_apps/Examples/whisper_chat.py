from hailo_platform import VDevice
from hailo_platform.genai import Speech2Text
from hailo_apps.python.core.common.core import get_resource_path
from hailo_apps.python.core.common.defines import RESOURCES_MODELS_DIR_NAME, WHISPER_MODEL_NAME_H10
import wave
import numpy as np

vdevice = None
speech2text = None

try:
    vdevice = VDevice()
    speech2text = Speech2Text(vdevice, get_resource_path(resource_type=RESOURCES_MODELS_DIR_NAME, model=WHISPER_MODEL_NAME_H10))
    
    # Load audio file using wave module instead of librosa
    audio_path = 'audio.wav'
    
    with wave.open(audio_path, 'rb') as wav_file:
        # Get audio parameters
        frames = wav_file.getnframes()
        sample_rate = wav_file.getframerate()
        channels = wav_file.getnchannels()
        sample_width = wav_file.getsampwidth()
        
        # Read raw audio data
        raw_audio = wav_file.readframes(frames)
    
    # Convert to numpy array based on sample width
    if sample_width == 1:
        audio_data = np.frombuffer(raw_audio, dtype=np.uint8)
        # Convert unsigned 8-bit to signed and normalize
        audio_data = (audio_data.astype(np.float32) - 128) / 128.0
    elif sample_width == 2:
        audio_data = np.frombuffer(raw_audio, dtype=np.int16)
        # Convert 16-bit to float32 and normalize
        audio_data = audio_data.astype(np.float32) / 32768.0
    elif sample_width == 4:
        audio_data = np.frombuffer(raw_audio, dtype=np.int32)
        # Convert 32-bit to float32 and normalize
        audio_data = audio_data.astype(np.float32) / 2147483648.0
    else:
        raise ValueError(f"Unsupported sample width: {sample_width}")
    
    # Handle stereo to mono conversion if needed
    if channels == 2:
        audio_data = audio_data.reshape(-1, 2).mean(axis=1)
    
    # Ensure little-endian format as expected by the model
    audio_data = audio_data.astype('<f4')
    
    if audio_data is None or len(audio_data) == 0:
        raise ValueError("Could not load audio file or audio file is empty")
    
    # Create generator parameters and generate segments
    params = speech2text.create_generator_params()
    segments = speech2text.generate_all_segments(params, audio_data, timeout_ms=15000)
    
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