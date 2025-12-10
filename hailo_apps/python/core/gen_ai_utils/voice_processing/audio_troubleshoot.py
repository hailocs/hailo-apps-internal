#!/usr/bin/env python3
"""
Audio Troubleshooting Tool for Hailo Voice Apps.

Diagnoses microphone and speaker issues, tests hardware, and recommends fixes.
"""

import argparse
import logging
import platform
import sys
import time

from .audio_diagnostics import AudioDiagnostics

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(message)s'
)
logger = logging.getLogger(__name__)


def print_header(title):
    print(f"\n{'='*60}")
    print(f" {title}")
    print(f"{'='*60}")


def print_device_table(devices, title):
    print(f"\n--- {title} ---")
    if not devices:
        print("No devices found.")
        return

    print(f"{'ID':<4} {'Name':<40} {'Ch':<5} {'Rate':<8} {'Def':<5} {'Score':<5}")
    print("-" * 75)
    for dev in devices:
        is_def = "*" if dev.is_default else ""
        print(f"{dev.id:<4} {dev.name[:38]:<40} {dev.max_input_channels if 'Input' in title else dev.max_output_channels:<5} {int(dev.default_samplerate):<8} {is_def:<5} {dev.score:<5}")


def run_diagnostics(args):
    print_header("Hailo Audio Troubleshooter")

    print(f"System: {platform.system()} {platform.release()} ({platform.machine()})")
    print(f"Python: {sys.version.split()[0]}")

    # 1. Enumerate Devices
    print_header("1. Device Enumeration")
    input_devs, output_devs = AudioDiagnostics.list_audio_devices()

    # Score devices
    for d in input_devs:
        d.score = AudioDiagnostics.score_device(d, is_input=True)
    for d in output_devs:
        d.score = AudioDiagnostics.score_device(d, is_input=False)

    print_device_table(input_devs, "Input Devices")
    print_device_table(output_devs, "Output Devices")

    # 2. Auto-detection
    print_header("2. Auto-Detection")
    best_in, best_out = AudioDiagnostics.auto_detect_devices()

    if best_in is not None:
        in_dev = next((d for d in input_devs if d.id == best_in), None)
        print(f"✅ Best Input Device: [{best_in}] {in_dev.name if in_dev else 'Unknown'}")
    else:
        print("❌ No suitable input device found!")

    if best_out is not None:
        out_dev = next((d for d in output_devs if d.id == best_out), None)
        print(f"✅ Best Output Device: [{best_out}] {out_dev.name if out_dev else 'Unknown'}")
    else:
        print("❌ No suitable output device found!")

    # 3. Interactive Testing
    if not args.no_interactive:
        print_header("3. Interactive Testing")

        # Test Microphone
        recorded_audio = None
        if best_in is not None:
            if input(f"\nTest Microphone (ID {best_in})? [Y/n]: ").lower() != 'n':
                print("Recording 3 seconds... Speak now!")
                success, msg, max_amp, recorded_audio = AudioDiagnostics.test_microphone(best_in, duration=3.0)
                if success:
                    print(f"✅ Success! Max Amplitude: {max_amp:.4f}")
                else:
                    print(f"❌ Failed: {msg}")

        # Test Speaker
        if best_out is not None:
            if input(f"\nTest Speaker (ID {best_out})? [Y/n]: ").lower() != 'n':
                playback_attempted = False

                # Try playing back recording first if available
                if recorded_audio is not None and len(recorded_audio) > 0:
                    if input("Play back recorded audio? [Y/n]: ").lower() != 'n':
                        print("Playing back recorded audio...")
                        success, msg = AudioDiagnostics.test_speaker(best_out, audio_data=recorded_audio)
                        if success:
                            print("✅ Playback command sent.")
                            if input("Did you hear your recording? [y/N]: ").lower() == 'y':
                                print("✅ Speaker confirmed working.")
                                playback_attempted = True
                            else:
                                print("❌ User did not hear audio.")
                        else:
                            print(f"⚠️  Playback of recording failed: {msg}")

                if not playback_attempted:
                    print("Playing test tone...")
                    success, msg = AudioDiagnostics.test_speaker(best_out)
                    if success:
                        print("✅ Playback command sent.")
                        if input("Did you hear the tone? [y/N]: ").lower() == 'y':
                            print("✅ Speaker confirmed working.")
                        else:
                            print("❌ User did not hear audio.")
                    else:
                        print(f"❌ Playback failed: {msg}")

    # 4. Troubleshooting Tips
    print_header("4. Troubleshooting Tips")

    is_rpi = platform.machine().startswith(('arm', 'aarch')) or "raspberry" in platform.release().lower()

    if is_rpi:
        print("RASPBERRY PI SPECIFIC:")
        print("  - If USB mic/speaker not working, check 'Device Profiles' in Volume Control.")
        print("  - Select 'Pro Audio' or 'Analog Stereo Duplex'.")
        print("  - Ensure current user is in 'audio' group: `sudo usermod -aG audio $USER`")

    print("\nGENERAL:")
    print("  - Check system volume and mute status (`alsamixer` on Linux).")
    print("  - Ensure no other app is blocking the audio device.")
    print("  - If using PulseAudio, try restarting it: `pulseaudio -k && pulseaudio --start`")

    print("\n" + "="*60)


def main():
    parser = argparse.ArgumentParser(description="Hailo Audio Troubleshooting Tool")
    parser.add_argument("--no-interactive", action="store_true", help="Skip interactive tests")
    args = parser.parse_args()

    try:
        run_diagnostics(args)
    except KeyboardInterrupt:
        print("\nInterrupted.")
    except Exception as e:
        logger.exception(f"Unexpected error: {e}")

if __name__ == "__main__":
    main()

