#!/usr/bin/env python3
"""
Audio Troubleshooting Tool for Hailo Voice Apps.

Diagnoses microphone and speaker issues, tests hardware, and recommends fixes.
"""

import argparse
import importlib
import logging
import platform
import re
import sys
import time

try:
    from .audio_diagnostics import AudioDiagnostics
except ImportError as e:
    # Check if it's a missing dependency issue
    missing_deps = []
    try:
        import sounddevice
    except ImportError:
        missing_deps.append("sounddevice")
    try:
        import numpy
    except ImportError:
        missing_deps.append("numpy")

    if missing_deps:
        print("❌ Missing required dependencies!")
        print(f"   Missing: {', '.join(missing_deps)}")
        print("\n   To install dependencies:")
        print("   1. Navigate to the repository root directory")
        print("   2. Run: pip install -e \".[gen-ai]\"")
        print("\n   Or install individually:")
        for dep in missing_deps:
            print(f"   pip install {dep}")
        sys.exit(1)
    else:
        raise

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


def is_hdmi_device(device_name: str) -> bool:
    """
    Check if a device is an HDMI audio device.

    Args:
        device_name (str): Device name to check.

    Returns:
        bool: True if device appears to be HDMI audio.
    """
    name_lower = device_name.lower()
    return 'hdmi' in name_lower


def is_real_hardware_device(device_name: str) -> bool:
    """
    Check if a device name represents real hardware vs virtual device.

    Args:
        device_name (str): Device name to check.

    Returns:
        bool: True if device appears to be real hardware.
    """
    name_lower = device_name.lower().strip()

    # Explicitly virtual device names (exact matches)
    virtual_exact = ['default', 'pulse', 'dmix', 'sysdefault']
    if name_lower in virtual_exact:
        return False

    # Real hardware indicators (presence indicates hardware)
    hardware_keywords = ['usb', 'alsa', 'card', 'hdmi', 'analog', 'iec958', 'hw:', 'plughw:', 'i2s', 'pcm']

    # If it contains hardware indicators, it's likely real hardware
    for keyword in hardware_keywords:
        if keyword in name_lower:
            return True

    # If name contains "hw:" or "card" followed by a number, it's hardware
    if re.search(r'hw:\d+|card\s*\d+', name_lower):
        return True

    # If it's just "default" or "pulse" (already checked above), it's virtual
    # Otherwise, if it has any complexity, assume it might be hardware
    # (conservative approach - better to test than skip)
    return len(name_lower) > 10  # Simple names are more likely virtual


def filter_real_hardware_devices(devices):
    """
    Filter out virtual devices, keeping only real hardware.

    Args:
        devices: List of AudioDeviceInfo objects.

    Returns:
        List of AudioDeviceInfo objects representing real hardware.
    """
    return [d for d in devices if is_real_hardware_device(d.name)]


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


def check_dependencies():
    """
    Check if required dependencies are available.

    Returns:
        Tuple[bool, List[str]]: (All dependencies available, List of missing dependencies)
    """
    missing = []
    required = {
        'sounddevice': 'sounddevice',
        'numpy': 'numpy',
    }

    for package_name, import_name in required.items():
        try:
            importlib.import_module(import_name)
        except ImportError:
            missing.append(package_name)

    return len(missing) == 0, missing


def run_diagnostics(args):
    print_header("Hailo Audio Troubleshooter")

    print(f"System: {platform.system()} {platform.release()} ({platform.machine()})")
    print(f"Python: {sys.version.split()[0]}")

    # Check dependencies first
    deps_ok, missing_deps = check_dependencies()
    if not deps_ok:
        print("\n❌ Missing required dependencies!")
        print(f"   Missing: {', '.join(missing_deps)}")
        print("\n   To install dependencies:")
        print("   1. Navigate to the repository root directory")
        print("   2. Run: pip install -e \".[gen-ai]\"")
        print("\n   Or install individually:")
        for dep in missing_deps:
            print(f"   pip install {dep}")
        sys.exit(1)

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

    # Check for real hardware devices
    real_input_devs = filter_real_hardware_devices(input_devs)
    real_output_devs = filter_real_hardware_devices(output_devs)

    # Check for HDMI devices
    hdmi_outputs = [d for d in real_output_devs if is_hdmi_device(d.name)]
    has_hdmi_only = len(hdmi_outputs) > 0 and len([d for d in real_output_devs if not is_hdmi_device(d.name)]) == 0

    if not real_input_devs and not real_output_devs:
        print("\n⚠️  WARNING: No real hardware audio devices detected!")
        print("   Only virtual devices (default, pulse) were found.")
        print("   This usually means:")
        print("   - No USB audio device is connected")
        print("   - USB device is not recognized by the system")
        print("   - Audio drivers are not properly loaded")
        print("\n   Try:")
        print("   - Plugging in your USB audio device")
        print("   - Running: lsusb (to verify USB device is detected)")
        print("   - Running: arecord -l (to list ALSA capture devices)")
        print("   - Running: aplay -l (to list ALSA playback devices)")
        if not args.no_interactive:
            if input("\nContinue with virtual devices anyway? [y/N]: ").lower() != 'y':
                print("Exiting.")
                return
    elif not real_input_devs:
        print("\n⚠️  WARNING: No real hardware input devices detected!")
        print("   Only virtual input devices found. Your microphone may not be connected or recognized.")
    elif not real_output_devs:
        print("\n⚠️  WARNING: No real hardware output devices detected!")
        print("   Only virtual output devices found. Your speakers/headphones may not be connected or recognized.")

    # Warn about HDMI-only audio
    if has_hdmi_only:
        print("\n⚠️  NOTE: Only HDMI audio output detected!")
        print("   HDMI audio only works if your display/monitor supports audio passthrough.")
        print("   Many monitors and some TVs do not support HDMI audio.")
        print("   If you don't hear audio, try:")
        print("   - Connecting USB headphones or speakers")
        print("   - Using a 3.5mm audio jack if available")
        print("   - Checking your display's audio settings")

    # 2. Auto-detection
    print_header("2. Auto-Detection")
    best_in, best_out = AudioDiagnostics.auto_detect_devices()

    if best_in is not None:
        in_dev = next((d for d in input_devs if d.id == best_in), None)
        is_real = in_dev and is_real_hardware_device(in_dev.name) if in_dev else False
        marker = " (virtual)" if not is_real else ""
        print(f"✅ Best Input Device: [{best_in}] {in_dev.name if in_dev else 'Unknown'}{marker}")
    else:
        print("❌ No suitable input device found!")

    if best_out is not None:
        out_dev = next((d for d in output_devs if d.id == best_out), None)
        is_real = out_dev and is_real_hardware_device(out_dev.name) if out_dev else False
        marker = " (virtual)" if not is_real else ""
        print(f"✅ Best Output Device: [{best_out}] {out_dev.name if out_dev else 'Unknown'}{marker}")
    else:
        print("❌ No suitable output device found!")

    # 3. Interactive Testing
    if not args.no_interactive:
        print_header("3. Interactive Testing")

        # Test Microphone
        recorded_audio = None
        recording_successful = False
        mic_test_failed = False
        if best_in is not None:
            if input(f"\nTest Microphone (ID {best_in})? [Y/n]: ").lower() != 'n':
                print("Recording 3 seconds... Speak now!")
                success, msg, max_amp, recorded_audio = AudioDiagnostics.test_microphone(best_in, duration=3.0)
                if success:
                    print(f"✅ Success! Max Amplitude: {max_amp:.4f}")
                    recording_successful = True
                else:
                    print(f"❌ Failed: {msg}")
                    recording_successful = False
                    mic_test_failed = True
                    # Clear recorded_audio if recording failed
                    recorded_audio = None
        else:
            print("\n⚠️  No input device available for testing.")
            mic_test_failed = True

        # Test Speaker
        speaker_test_failed = False
        if best_out is not None:
            if input(f"\nTest Speaker (ID {best_out})? [Y/n]: ").lower() != 'n':
                playback_attempted = False

                # Only try playing back recording if it was successful
                if recording_successful and recorded_audio is not None and len(recorded_audio) > 0:
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
                                speaker_test_failed = True
                        else:
                            print(f"⚠️  Playback of recording failed: {msg}")
                            speaker_test_failed = True

                if not playback_attempted:
                    print("Playing test tone...")
                    success, msg = AudioDiagnostics.test_speaker(best_out)
                    if success:
                        print("✅ Playback command sent.")
                        if input("Did you hear the tone? [y/N]: ").lower() == 'y':
                            print("✅ Speaker confirmed working.")
                        else:
                            print("❌ User did not hear audio.")
                            speaker_test_failed = True
                    else:
                        print(f"❌ Playback failed: {msg}")
                        speaker_test_failed = True
        else:
            print("\n⚠️  No output device available for testing.")
            speaker_test_failed = True

        # Check if we're using virtual devices for the tested devices
        using_virtual_input = False
        using_virtual_output = False

        if best_in is not None:
            in_dev = next((d for d in input_devs if d.id == best_in), None)
            using_virtual_input = in_dev is not None and not is_real_hardware_device(in_dev.name)

        if best_out is not None:
            out_dev = next((d for d in output_devs if d.id == best_out), None)
            using_virtual_output = out_dev is not None and not is_real_hardware_device(out_dev.name)

        # Check if only virtual devices exist (no real hardware at all)
        no_real_hardware = not real_input_devs and not real_output_devs

        # Notify if tests failed and virtual devices are being used
        if (mic_test_failed or speaker_test_failed) and (no_real_hardware or (mic_test_failed and using_virtual_input) or (speaker_test_failed and using_virtual_output)):
            print("\n" + "="*60)
            print("⚠️  IMPORTANT: Tests failed and you're using virtual devices!")
            print("   Virtual devices (like 'default' or 'pulse') often don't work properly")
            print("   for actual audio input/output. This is likely why your tests failed.")
            print("\n   To fix this:")
            print("   1. Connect a real USB audio device (microphone/headphones)")
            print("   2. Run: hailo-audio-troubleshoot --configure --auto-fix")
            print("   3. Or manually configure your USB device in PulseAudio Volume Control")
            print("="*60)
        # Suggest auto-configuration if devices exist but tests failed
        elif (mic_test_failed or speaker_test_failed) and (real_input_devs or real_output_devs):
            print("\n" + "="*60)
            print("💡 SUGGESTION: Devices are detected but not working properly.")
            print("   Try running the auto-configuration tool:")
            print("   hailo-audio-troubleshoot --configure")
            print("   or with automatic fixes:")
            print("   hailo-audio-troubleshoot --configure --auto-fix")
            print("="*60)

    # 4. Troubleshooting Tips
    print_header("4. Troubleshooting Tips")

    is_rpi = platform.machine().startswith(('arm', 'aarch')) or "raspberry" in platform.release().lower()

    if is_rpi:
        print("RASPBERRY PI SPECIFIC:")
        print("  - If USB mic/speaker not working, try auto-configuration:")
        print("    hailo-audio-troubleshoot --configure --auto-fix")
        print("  - Or manually check 'Device Profiles' in Volume Control (pavucontrol).")
        print("  - Select 'Pro Audio' or 'Analog Stereo Duplex'.")
        print("  - Ensure current user is in 'audio' group: `sudo usermod -aG audio $USER`")

    print("\nGENERAL:")
    print("  - If devices are detected but not working, try auto-configuration:")
    print("    hailo-audio-troubleshoot --configure")
    print("  - Check system volume and mute status (`alsamixer` on Linux).")
    print("  - Ensure no other app is blocking the audio device.")
    print("  - If using PulseAudio, try restarting it: `pulseaudio -k && pulseaudio --start`")

    print("\n" + "="*60)


def run_auto_configure(args):
    """Run automatic USB audio configuration for Raspberry Pi."""
    print_header("USB Audio Auto-Configuration (Raspberry Pi)")

    if not AudioDiagnostics.is_raspberry_pi():
        print("⚠️  Warning: This tool is designed for Raspberry Pi.")
        if input("Continue anyway? [y/N]: ").lower() != 'y':
            return

    print("\nThis will attempt to configure your USB audio device.")
    if not args.yes:
        if input("Continue? [y/N]: ").lower() != 'y':
            print("Cancelled.")
            return

    print("\nRunning configuration...")
    results = AudioDiagnostics.configure_usb_audio_rpi(auto_fix=args.auto_fix)

    print_header("Configuration Results")

    if results['success']:
        print("✅ Configuration completed successfully!\n")
    else:
        print("⚠️  Configuration completed with warnings/errors.\n")

    if results['steps']:
        print("Steps completed:")
        for step in results['steps']:
            print(f"  {step}")

    if results['warnings']:
        print("\n⚠️  Warnings:")
        for warning in results['warnings']:
            print(f"  - {warning}")

    if results['errors']:
        print("\n❌ Errors:")
        for error in results['errors']:
            print(f"  - {error}")

    if results['device_info']:
        print("\n📱 Detected USB Devices:")
        if results['device_info'].get('usb_inputs'):
            print("  Input devices:")
            for dev in results['device_info']['usb_inputs']:
                print(f"    - [{dev['id']}] {dev['name']}")
        if results['device_info'].get('usb_outputs'):
            print("  Output devices:")
            for dev in results['device_info']['usb_outputs']:
                print(f"    - [{dev['id']}] {dev['name']}")

    print("\n" + "="*60)
    print("\nNext steps:")
    print("  1. If permissions were changed, log out and back in")
    print("  2. Test your microphone: hailo-audio-troubleshoot")
    print("  3. If issues persist, check PulseAudio Volume Control (pavucontrol)")
    print("     and ensure USB device profile is set to 'Pro Audio' or 'Analog Stereo Duplex'")


def main():
    parser = argparse.ArgumentParser(description="Hailo Audio Troubleshooting Tool")
    parser.add_argument("--no-interactive", action="store_true", help="Skip interactive tests")
    parser.add_argument("--configure", action="store_true", help="Run USB audio auto-configuration for RPi")
    parser.add_argument("--auto-fix", action="store_true", help="Automatically fix issues (requires sudo)")
    parser.add_argument("--yes", "-y", action="store_true", help="Skip confirmation prompts")
    args = parser.parse_args()

    try:
        if args.configure:
            run_auto_configure(args)
        else:
            run_diagnostics(args)
    except KeyboardInterrupt:
        print("\nInterrupted.")
    except Exception as e:
        logger.exception(f"Unexpected error: {e}")

if __name__ == "__main__":
    main()

