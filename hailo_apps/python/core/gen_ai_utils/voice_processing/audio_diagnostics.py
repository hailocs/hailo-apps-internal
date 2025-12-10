import logging
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np
import sounddevice as sd

from hailo_apps.python.core.common.defines import TARGET_SR

# Setup logger
logger = logging.getLogger(__name__)


@dataclass
class AudioDeviceInfo:
    """Dataclass to store audio device information."""
    id: int
    name: str
    host_api: int
    max_input_channels: int
    max_output_channels: int
    default_samplerate: float
    is_default: bool = False
    score: int = 0
    test_result: bool = False
    error_msg: str = ""


class AudioDiagnostics:
    """
    Provides tools for diagnosing audio issues, enumerating devices,
    and auto-detecting the best available hardware.
    """

    @staticmethod
    def list_audio_devices() -> Tuple[List[AudioDeviceInfo], List[AudioDeviceInfo]]:
        """
        Enumerate all audio devices.

        Returns:
            Tuple[List[AudioDeviceInfo], List[AudioDeviceInfo]]:
                Lists of (input_devices, output_devices).
        """
        try:
            devices = sd.query_devices()
            default_input = sd.default.device[0]
            default_output = sd.default.device[1]
        except Exception as e:
            logger.error(f"Failed to query audio devices: {e}")
            return [], []

        input_devices = []
        output_devices = []

        for i, dev in enumerate(devices):
            try:
                device_info = AudioDeviceInfo(
                    id=i,
                    name=dev['name'],
                    host_api=dev['hostapi'],
                    max_input_channels=dev['max_input_channels'],
                    max_output_channels=dev['max_output_channels'],
                    default_samplerate=dev['default_samplerate'],
                    is_default=(i == default_input if dev['max_input_channels'] > 0 else i == default_output)
                )

                if dev['max_input_channels'] > 0:
                    input_devices.append(device_info)
                if dev['max_output_channels'] > 0:
                    output_devices.append(device_info)

            except Exception as e:
                logger.warning(f"Error parsing device {i}: {e}")

        return input_devices, output_devices

    @staticmethod
    def test_microphone(device_id: int, duration: float = 1.0, threshold: float = 0.001) -> Tuple[bool, str, float, Optional[np.ndarray]]:
        """
        Test a microphone device by recording a short clip.

        Args:
            device_id (int): Device ID to test.
            duration (float): Duration of test recording in seconds.
            threshold (float): RMS amplitude threshold to consider signal valid.

        Returns:
            Tuple[bool, str, float, Optional[np.ndarray]]: (Success, Message, Max Amplitude, Recorded Data)
        """
        try:
            logger.debug(f"Testing microphone device {device_id}...")
            # Record short clip
            recording = sd.rec(
                int(duration * TARGET_SR),
                samplerate=TARGET_SR,
                channels=1,
                device=device_id,
                dtype='float32',
                blocking=True
            )

            # Calculate levels
            max_amp = float(np.max(np.abs(recording)))
            rms = float(np.sqrt(np.mean(recording**2)))

            logger.debug(f"Mic test result - Max: {max_amp:.4f}, RMS: {rms:.4f}")

            if max_amp < threshold:
                return False, f"Signal too low (Max: {max_amp:.4f}). Check mute/volume.", max_amp, recording

            return True, "Microphone working correctly", max_amp, recording

        except Exception as e:
            msg = f"Recording failed: {str(e)}"
            logger.error(msg)
            return False, msg, 0.0, None

    @staticmethod
    def test_speaker(device_id: int, duration: float = 1.0, audio_data: Optional[np.ndarray] = None) -> Tuple[bool, str]:
        """
        Test a speaker device by playing a generated tone or provided audio.

        Args:
            device_id (int): Device ID to test.
            duration (float): Duration of test tone (ignored if audio_data provided).
            audio_data (Optional[np.ndarray]): Audio data to play. If None, generates a tone.

        Returns:
            Tuple[bool, str]: (Success, Message)
        """
        try:
            logger.debug(f"Testing speaker device {device_id}...")

            if audio_data is not None:
                to_play = audio_data
            else:
                # Generate 440Hz sine wave
                t = np.linspace(0, duration, int(duration * TARGET_SR), False)
                to_play = 0.5 * np.sin(2 * np.pi * 440 * t)

            sd.play(to_play, samplerate=TARGET_SR, device=device_id, blocking=True)
            return True, "Audio playback successful"

        except Exception as e:
            msg = f"Playback failed: {str(e)}"
            logger.error(msg)
            return False, msg

    @staticmethod
    def score_device(device: AudioDeviceInfo, is_input: bool) -> int:
        """
        Calculate a suitability score for a device.
        Higher score = better candidate.
        """
        score = 0

        # Prefer default devices
        if device.is_default:
            score += 100

        # Penalize "default", "sysdefault", "dmix" virtual devices to prefer hardware names
        # But only if we have other options. For now, let's just prefer hardware-looking names
        name_lower = device.name.lower()

        if "usb" in name_lower:
            score += 50  # Prefer USB devices (likely the plugged in mic/speaker)

        if "hdmi" in name_lower and is_input:
            score -= 50  # HDMI inputs are rarely used for voice

        # Prefer devices that support our target sample rate naturally (though sounddevice resamples)
        if abs(device.default_samplerate - TARGET_SR) < 1.0:
            score += 20

        return score

    @classmethod
    def auto_detect_devices(cls) -> Tuple[Optional[int], Optional[int]]:
        """
        Automatically detect best input and output devices.

        Returns:
            Tuple[Optional[int], Optional[int]]: (Best Input ID, Best Output ID)
        """
        input_devices, output_devices = cls.list_audio_devices()

        best_input = None
        best_input_score = -9999

        best_output = None
        best_output_score = -9999

        # Find best input
        for dev in input_devices:
            score = cls.score_device(dev, is_input=True)
            # Optional: actively test device if needed, but that takes time.
            # We'll rely on static properties for auto-selection to be fast.

            if score > best_input_score:
                best_input_score = score
                best_input = dev.id

        # Find best output
        for dev in output_devices:
            score = cls.score_device(dev, is_input=False)

            if score > best_output_score:
                best_output_score = score
                best_output = dev.id

        logger.info(f"Auto-detected devices - Input: {best_input}, Output: {best_output}")
        return best_input, best_output

