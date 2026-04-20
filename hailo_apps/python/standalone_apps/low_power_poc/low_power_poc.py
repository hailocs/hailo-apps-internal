"""
Hailo Low-Power Mode Proof of Concept

Benchmarks a Hailo-8 M.2 module across three states:
  1. Active inference (baseline)
  2. Sleep mode (low power)
  3. Active inference (post-wake validation)

Measures: power consumption, sleep/wake transition times, FPS.
Validates the device recovers to the same performance after waking.

Usage:
    python3 -m hailo_apps.python.standalone_apps.low_power_poc.low_power_poc
    python3 -m hailo_apps.python.standalone_apps.low_power_poc.low_power_poc --inference-duration 20 --sleep-duration 30
"""

import argparse
import json
import math
import os
import re
import signal
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field, asdict


# ---------------------------------------------------------------------------
# Data classes for structured results
# ---------------------------------------------------------------------------

@dataclass
class PowerStats:
    avg: float = 0.0
    min_val: float = 0.0
    max_val: float = 0.0
    samples: int = 0

    def as_str(self):
        if self.samples == 0:
            return "N/A"
        return f"{self.avg:.3f} / {self.min_val:.3f} / {self.max_val:.3f} W"


@dataclass
class PhaseResult:
    fps: float = 0.0
    power: PowerStats = field(default_factory=PowerStats)


@dataclass
class Report:
    device_id: str = ""
    device_arch: str = ""
    fw_version: str = ""
    model: str = "yolov6n (640x640)"
    video: str = "example_640.mp4"
    inference_duration_s: int = 0
    sleep_duration_s: int = 0
    idle_power_w: float = 0.0
    baseline: PhaseResult = field(default_factory=PhaseResult)
    sleep_entry_ms: float = 0.0
    sleep_power: PowerStats = field(default_factory=PowerStats)
    wake_exit_ms: float = 0.0
    postwake: PhaseResult = field(default_factory=PhaseResult)
    fps_delta_pct: float = 0.0
    fps_pass: bool = False
    power_reduction_pct: float = 0.0
    device_alive_after: bool = False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def log(msg):
    print(f"[PoC] {msg}", flush=True)


def run_cmd(cmd, timeout=15):
    """Run a shell command, return (returncode, stdout, stderr)."""
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "timeout"


def preflight_check():
    """Verify Hailo device is present and responsive."""
    log("Pre-flight: hailortcli fw-control identify")
    rc, stdout, stderr = run_cmd("hailortcli fw-control identify")
    output = stdout + stderr
    if rc != 0:
        log(f"FATAL: Device not found or not responding.\n{output}")
        sys.exit(1)

    device_id = ""
    arch = ""
    fw = ""
    for line in output.splitlines():
        if "Device Architecture" in line:
            arch = line.split(":")[-1].strip()
        if "Firmware Version" in line:
            fw = line.split(":")[-1].strip()
        if "Executing on device" in line:
            device_id = line.split(":")[-1].strip()
            # Handle BDF format "0000:04:00.0"
            m = re.search(r"(\w{4}:\w{2}:\w{2}\.\w)", output)
            if m:
                device_id = m.group(1)

    log(f"  Device: {device_id}, Arch: {arch}, FW: {fw}")
    return device_id, arch, fw


def measure_single_power(device):
    """Take a single instantaneous power measurement. Returns watts or None."""
    try:
        return device.control.power_measurement()
    except Exception as e:
        log(f"  WARNING: Single power measurement failed: {e}")
        return None


def measure_periodic_power(device, duration_s):
    """Run periodic power measurement for duration_s, return PowerStats."""
    from hailo_platform import MeasurementBufferIndex

    buf_idx = MeasurementBufferIndex.MEASUREMENT_BUFFER_INDEX_0
    samples = []

    try:
        device.control.stop_power_measurement()
    except Exception:
        pass

    try:
        device.control.set_power_measurement(buffer_index=buf_idx)
        device.control.start_power_measurement()
    except Exception as e:
        log(f"  WARNING: Could not start periodic power measurement: {e}")
        return PowerStats()

    for i in range(duration_s):
        time.sleep(1)
        try:
            m = device.control.get_power_measurement(buffer_index=buf_idx, should_clear=True)
            samples.append(m.average_value)
        except Exception as e:
            log(f"  WARNING: power sample {i} failed: {e}")

    try:
        device.control.stop_power_measurement()
    except Exception:
        pass

    if not samples:
        return PowerStats()

    log(f"  Collected {len(samples)} power samples: {[f'{s:.3f}' for s in samples]}")

    return PowerStats(
        avg=sum(samples) / len(samples),
        min_val=min(samples),
        max_val=max(samples),
        samples=len(samples),
    )


def prepare_video(inference_duration_s, margin_s=5):
    """Create a looped video that has enough frames for the full test duration.

    With --disable-sync, frames are consumed at ~300 FPS (not the video's
    native 30 FPS), so a 11s video is exhausted in ~1-2 seconds.
    We loop enough times so the frame count covers the full inference period.
    Returns the path to the prepared video file.
    """
    src = "/usr/local/hailo/resources/videos/example_640.mp4"
    if not os.path.exists(src):
        log(f"  WARNING: Source video not found: {src}")
        return None

    # Get source frame count
    rc, stdout, _ = run_cmd(
        f'ffprobe -v error -count_frames -select_streams v:0 '
        f'-show_entries stream=nb_read_frames -of csv=p=0 "{src}"',
        timeout=30,
    )
    if rc != 0 or not stdout.strip():
        log("  WARNING: Could not determine source video frame count, falling back to duration")
        # Fallback: estimate from duration * 30fps
        rc2, stdout2, _ = run_cmd(
            f'ffprobe -v error -show_entries format=duration -of csv=p=0 "{src}"'
        )
        if rc2 != 0 or not stdout2.strip():
            return None
        src_frames = int(float(stdout2.strip()) * 30)
    else:
        src_frames = int(stdout.strip())

    # At ~350 FPS processing speed (conservative estimate), how many frames
    # do we need for the full inference + margin?
    estimated_fps = 350
    target_frames = (inference_duration_s + margin_s) * estimated_fps
    loops = math.ceil(target_frames / src_frames)

    log(f"  Source: {src_frames} frames. Need ~{target_frames} frames for {inference_duration_s}+{margin_s}s @ ~{estimated_fps} FPS. Loops: {loops}")

    if loops <= 1:
        return src

    # Build looped video via ffmpeg concat
    out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "resources")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"example_640_looped_{loops}x.mp4")

    if os.path.exists(out_path):
        log(f"  Reusing existing looped video: {out_path} ({loops}x = {loops * src_frames} frames)")
        return out_path

    concat_file = tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False)
    for _ in range(loops):
        concat_file.write(f"file '{src}'\n")
    concat_file.close()

    log(f"  Creating looped video: {loops}x {src_frames} frames = {loops * src_frames} frames")
    rc, _, stderr = run_cmd(
        f'ffmpeg -y -f concat -safe 0 -i "{concat_file.name}" -c copy "{out_path}"',
        timeout=30,
    )
    os.unlink(concat_file.name)

    if rc != 0:
        log(f"  WARNING: ffmpeg failed: {stderr}")
        return None

    log(f"  Looped video ready: {out_path}")
    return out_path


def launch_inference(duration_s, video_path=None):
    """Launch detection_simple as subprocess. Returns (proc, start_time, stdout_file, stderr_file).

    stdout/stderr are redirected to temp files instead of PIPEs to avoid
    blocking the subprocess when the pipe buffer fills up (the detection
    callback prints every frame, which at 300+ FPS would overflow a 64KB
    pipe buffer instantly).
    """
    cmd = [
        sys.executable, "-m",
        "hailo_apps.python.pipeline_apps.detection_simple.detection_simple",
        "--disable-sync",
        "--show-fps",
    ]
    if video_path:
        cmd.extend(["--input", video_path])

    log(f"  Launching inference subprocess for {duration_s}s...")
    log(f"  CMD: {' '.join(cmd)}")

    env = os.environ.copy()
    env.setdefault("GST_DEBUG", "1")

    stdout_file = tempfile.NamedTemporaryFile(mode="w", prefix="poc_stdout_", suffix=".txt", delete=False)
    stderr_file = tempfile.NamedTemporaryFile(mode="w", prefix="poc_stderr_", suffix=".txt", delete=False)

    proc = subprocess.Popen(
        cmd,
        stdout=stdout_file,
        stderr=stderr_file,
        text=True,
        env=env,
        preexec_fn=os.setsid,
    )
    start_time = time.perf_counter()
    return proc, start_time, stdout_file, stderr_file


def stop_inference(proc, stdout_file, stderr_file, grace_timeout=5):
    """Stop inference subprocess gracefully, return (stdout_text, stderr_text)."""
    if proc.poll() is None:
        # SIGTERM first — GStreamer handles it cleanly
        log("  Sending SIGTERM to inference subprocess...")
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except ProcessLookupError:
            pass

        try:
            proc.wait(timeout=grace_timeout)
        except subprocess.TimeoutExpired:
            # Try SIGINT as fallback
            log("  Sending SIGINT...")
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGINT)
            except ProcessLookupError:
                pass
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                log("  WARNING: Grace period expired, sending SIGKILL.")
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                except ProcessLookupError:
                    pass
                proc.wait(timeout=5)

    # Close file handles and read contents
    stdout_file.close()
    stderr_file.close()

    with open(stdout_file.name, "r") as f:
        stdout = f.read()
    with open(stderr_file.name, "r") as f:
        stderr = f.read()

    # Cleanup temp files
    os.unlink(stdout_file.name)
    os.unlink(stderr_file.name)

    return stdout, stderr


def parse_fps(stdout, stderr, elapsed_s):
    """Parse FPS from inference output. Returns (frame_count_fps, fpsdisplaysink_fps)."""
    combined = (stdout or "") + "\n" + (stderr or "")

    # Primary method: frame count / elapsed time (most reliable)
    frame_counts = [int(m) for m in re.findall(r"Frame count:\s*(\d+)", combined)]
    fc_fps = 0.0
    if frame_counts:
        last_frame = max(frame_counts)
        fc_fps = last_frame / elapsed_s if elapsed_s > 0 else 0.0
        log(f"  Frame count FPS: {last_frame} frames / {elapsed_s:.1f}s = {fc_fps:.1f} FPS")

    # Secondary method: fpsdisplaysink reported FPS (pipeline-level, no Python overhead)
    sink_fps = 0.0
    fps_values = []
    for m in re.finditer(r"FPS measurement:\s*([\d.]+),\s*drop=([\d.]+),\s*avg=([\d.]+)", combined):
        fps_values.append(float(m.group(3)))  # avg fps

    if fps_values:
        sink_fps = fps_values[-1]
        log(f"  fpsdisplaysink FPS: {sink_fps:.1f} (from {len(fps_values)} reports)")

    # Frame-count / elapsed is the most stable metric for validation
    # (257.0 vs 256.5 = 0.2% delta). fpsdisplaysink fires infrequently
    # and reports instantaneous peaks, making it noisy for comparison.
    if fc_fps > 0:
        return fc_fps, sink_fps
    if sink_fps > 0:
        log("  Using fpsdisplaysink FPS (no frame counts found)")
        return sink_fps, 0.0

    log("  WARNING: Could not determine FPS from subprocess output.")
    return 0.0, 0.0


def run_inference_phase(device, duration_s, phase_name, video_path=None):
    """Run inference + power measurement for a phase. Returns PhaseResult."""
    log(f"--- {phase_name}: inference for {duration_s}s ---")

    # Start inference subprocess
    proc, start_time, stdout_file, stderr_file = launch_inference(duration_s, video_path)

    # Give pipeline 3s to initialize before starting power measurement
    time.sleep(3)

    # Measure power for remaining duration
    power_duration = max(1, duration_s - 3)
    log(f"  Measuring power for {power_duration}s (after 3s pipeline warmup)...")
    power = measure_periodic_power(device, power_duration)
    log(f"  Power: {power.as_str()}")

    # Stop inference
    stdout, stderr = stop_inference(proc, stdout_file, stderr_file)
    elapsed_s = time.perf_counter() - start_time

    # Parse FPS
    fc_fps, sink_fps = parse_fps(stdout, stderr, elapsed_s)
    log(f"  Elapsed: {elapsed_s:.1f}s | FPS (frame-count): {fc_fps:.1f} | FPS (sink): {sink_fps:.1f}")

    return PhaseResult(fps=fc_fps, power=power)


# ---------------------------------------------------------------------------
# Main PoC flow
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Hailo Low-Power Mode PoC")
    parser.add_argument("--inference-duration", type=int, default=15,
                        help="Duration of each inference phase in seconds (default: 15)")
    parser.add_argument("--sleep-duration", type=int, default=40,
                        help="Duration of sleep mode in seconds (default: 40)")
    parser.add_argument("--fps-threshold", type=float, default=5.0,
                        help="Max allowed FPS delta %% for PASS (default: 5.0)")
    parser.add_argument("--output-json", type=str, default="low_power_report.json",
                        help="Output JSON report file (default: low_power_report.json)")
    args = parser.parse_args()

    log("=" * 60)
    log("   HAILO LOW-POWER MODE PoC")
    log("=" * 60)

    # ---- Phase 1: Pre-flight ----
    log("\n[Phase 1] Pre-flight check")
    device_id, arch, fw = preflight_check()

    from hailo_platform import Device
    from hailo_platform.pyhailort._pyhailort import SleepState

    device = Device()
    log(f"  Opened Device: {device.device_id}")

    idle_power = measure_single_power(device)
    if idle_power is not None:
        log(f"  Idle power: {idle_power:.3f} W")
    else:
        log("  WARNING: Power measurement not available — continuing without power data.")

    # Prepare looped video to avoid pipeline rewind during test
    log("  Preparing test video...")
    video_path = prepare_video(args.inference_duration)
    if video_path:
        log(f"  Using video: {video_path}")
    else:
        log("  WARNING: Using default video (may rewind during test)")

    report = Report(
        device_id=device.device_id,
        device_arch=arch,
        fw_version=fw,
        inference_duration_s=args.inference_duration,
        sleep_duration_s=args.sleep_duration,
        idle_power_w=idle_power or 0.0,
    )

    # ---- Phase 2: Baseline inference ----
    log(f"\n[Phase 2] Baseline inference ({args.inference_duration}s)")
    report.baseline = run_inference_phase(device, args.inference_duration, "BASELINE", video_path)

    # ---- Phase 3: Enter sleep ----
    log(f"\n[Phase 3] Entering sleep mode")
    tic = time.perf_counter()
    try:
        device._device.set_sleep_state(SleepState.SLEEP_STATE_SLEEPING)
        toc = time.perf_counter()
        report.sleep_entry_ms = (toc - tic) * 1000
        log(f"  Sleep entry time: {report.sleep_entry_ms:.2f} ms")
    except Exception as e:
        log(f"  RISK RAISED: Sleep entry failed: {e}")
        log(f"  Continuing with remaining phases...")
        report.sleep_entry_ms = -1

    # ---- Phase 4: Sleep mode power measurement ----
    if report.sleep_entry_ms >= 0:
        log(f"\n[Phase 4] Sleep mode ({args.sleep_duration}s total)")
        stabilize_s = 3
        measure_s = args.sleep_duration - stabilize_s
        log(f"  Waiting {stabilize_s}s for power stabilization...")
        time.sleep(stabilize_s)

        log(f"  Measuring sleep power for {measure_s}s...")
        # Try periodic measurement first
        report.sleep_power = measure_periodic_power(device, measure_s)
        if report.sleep_power.samples == 0:
            # Fallback: try single measurements
            log("  Periodic measurement failed during sleep. Trying single samples...")
            samples = []
            for i in range(min(5, measure_s)):
                time.sleep(1)
                p = measure_single_power(device)
                if p is not None:
                    samples.append(p)
            if samples:
                report.sleep_power = PowerStats(
                    avg=sum(samples) / len(samples),
                    min_val=min(samples),
                    max_val=max(samples),
                    samples=len(samples),
                )
            else:
                log("  RISK RAISED: Cannot measure power during sleep (control path may be asleep).")
                log(f"  Sleeping for remaining {measure_s}s without measurement...")
                time.sleep(max(0, measure_s - 5))

        log(f"  Sleep power: {report.sleep_power.as_str()}")
    else:
        log(f"\n[Phase 4] Skipped (sleep entry failed). Waiting {args.sleep_duration}s...")
        time.sleep(args.sleep_duration)

    # ---- Phase 5: Exit sleep ----
    log(f"\n[Phase 5] Exiting sleep mode")
    if report.sleep_entry_ms >= 0:
        tic = time.perf_counter()
        try:
            device._device.set_sleep_state(SleepState.SLEEP_STATE_AWAKE)
            toc = time.perf_counter()
            report.wake_exit_ms = (toc - tic) * 1000
            log(f"  Wake exit time: {report.wake_exit_ms:.2f} ms")
        except Exception as e:
            log(f"  RISK RAISED: Wake exit failed: {e}")
            report.wake_exit_ms = -1

        log("  Waiting 3s for device stabilization...")
        time.sleep(3)
    else:
        log("  Skipped (sleep was not entered)")
        report.wake_exit_ms = -1

    # ---- Phase 6: Post-wake inference ----
    log(f"\n[Phase 6] Post-wake inference ({args.inference_duration}s)")
    report.postwake = run_inference_phase(device, args.inference_duration, "POST-WAKE", video_path)

    # ---- Phase 7: Post-flight & Report ----
    log(f"\n[Phase 7] Post-flight check")
    rc, stdout, stderr = run_cmd("hailortcli fw-control identify")
    report.device_alive_after = (rc == 0)
    log(f"  Device alive after test: {'YES' if report.device_alive_after else 'NO'}")

    # Compute validation metrics
    if report.baseline.fps > 0 and report.postwake.fps > 0:
        report.fps_delta_pct = abs(report.postwake.fps - report.baseline.fps) / report.baseline.fps * 100
        report.fps_pass = report.fps_delta_pct < args.fps_threshold
    else:
        report.fps_delta_pct = -1
        report.fps_pass = False

    if report.idle_power_w > 0 and report.sleep_power.avg > 0:
        report.power_reduction_pct = (1 - report.sleep_power.avg / report.idle_power_w) * 100

    # Release device
    device.release()

    # Print report
    print_report(report, args.fps_threshold)

    # Write JSON
    write_json_report(report, args.output_json)

    log(f"\nPoC complete. JSON report: {args.output_json}")


def print_report(r, fps_threshold):
    """Print structured text report."""
    w = 60
    print()
    print("=" * w)
    print("       HAILO LOW-POWER MODE PoC REPORT")
    print("=" * w)
    print(f" Device              : {r.device_arch} (M.2, PCIe)")
    print(f" Device ID           : {r.device_id}")
    print(f" Firmware            : {r.fw_version}")
    print(f" Model               : {r.model}")
    print(f" Video               : {r.video}")
    print(f" Inference duration  : {r.inference_duration_s}s per phase")
    print(f" Sleep duration      : {r.sleep_duration_s}s")
    print("-" * w)
    print(f" {'PHASE':<20} | {'FPS':>7} | {'Power (avg/min/max)'}")
    print("-" * w)
    print(f" {'Idle (startup)':<20} | {'—':>7} | {r.idle_power_w:.3f} W")
    print(f" {'Baseline infer':<20} | {r.baseline.fps:>7.1f} | {r.baseline.power.as_str()}")
    print(f" {'Sleep mode':<20} | {'—':>7} | {r.sleep_power.as_str()}")
    print(f" {'Post-wake infer':<20} | {r.postwake.fps:>7.1f} | {r.postwake.power.as_str()}")
    print("-" * w)
    print(f" {'TRANSITIONS':<20} | {'Time (ms)':>10}")
    print("-" * w)
    entry_str = f"{r.sleep_entry_ms:.2f}" if r.sleep_entry_ms >= 0 else "FAILED"
    exit_str = f"{r.wake_exit_ms:.2f}" if r.wake_exit_ms >= 0 else "FAILED"
    print(f" {'Sleep entry':<20} | {entry_str:>10}")
    print(f" {'Wake exit':<20} | {exit_str:>10}")
    print("-" * w)
    print(f" {'VALIDATION':<20} | {'Result'}")
    print("-" * w)

    if r.fps_delta_pct >= 0:
        fps_verdict = "PASS" if r.fps_pass else "FAIL"
        print(f" {'FPS delta':<20} | {r.fps_delta_pct:.1f}% -> {fps_verdict} (<{fps_threshold}%)")
    else:
        print(f" {'FPS delta':<20} | N/A (missing FPS data)")

    if r.power_reduction_pct > 0:
        print(f" {'Power reduction':<20} | {r.power_reduction_pct:.1f}% (sleep vs idle)")
    else:
        print(f" {'Power reduction':<20} | N/A")

    print(f" {'Device alive':<20} | {'YES' if r.device_alive_after else 'NO'}")
    print("=" * w)


def write_json_report(r, path):
    """Write report as JSON."""
    data = {
        "device_id": r.device_id,
        "device_arch": r.device_arch,
        "fw_version": r.fw_version,
        "model": r.model,
        "video": r.video,
        "inference_duration_s": r.inference_duration_s,
        "sleep_duration_s": r.sleep_duration_s,
        "idle_power_w": r.idle_power_w,
        "baseline": {
            "fps": r.baseline.fps,
            "power_avg_w": r.baseline.power.avg,
            "power_min_w": r.baseline.power.min_val,
            "power_max_w": r.baseline.power.max_val,
        },
        "sleep": {
            "entry_ms": r.sleep_entry_ms,
            "power_avg_w": r.sleep_power.avg,
            "power_min_w": r.sleep_power.min_val,
            "power_max_w": r.sleep_power.max_val,
            "exit_ms": r.wake_exit_ms,
        },
        "postwake": {
            "fps": r.postwake.fps,
            "power_avg_w": r.postwake.power.avg,
            "power_min_w": r.postwake.power.min_val,
            "power_max_w": r.postwake.power.max_val,
        },
        "validation": {
            "fps_delta_pct": r.fps_delta_pct,
            "fps_pass": r.fps_pass,
            "power_reduction_pct": r.power_reduction_pct,
            "device_alive_after": r.device_alive_after,
        },
    }
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    log(f"  JSON report written to {path}")


if __name__ == "__main__":
    main()
