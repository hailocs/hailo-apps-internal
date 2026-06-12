#!/usr/bin/env python3
"""
Launch a GStreamer pipeline app with GST-Shark tracing enabled.

Usage:
    python profile_pipeline.py <app_path> [--duration 15] [--tracers all] [--output-dir <dir>] [-- extra app args]

The profiler forks a watchdog process that guarantees the app will be shut down
after the specified duration, even if the parent profiler process is killed.
"""

import argparse
import os
import signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path


DEFAULT_TRACERS = "proctime;interlatency;framerate;scheduletime;cpuusage;queuelevel"


def _kill_process_group(pgid, sig=signal.SIGTERM):
    """Send signal to an entire process group."""
    try:
        os.killpg(pgid, sig)
    except (ProcessLookupError, PermissionError):
        pass


def _kill_orphans():
    """Kill mavsdk_server and other orphans that escape the process group."""
    subprocess.run(["pkill", "-9", "-f", "mavsdk_server"], capture_output=True)


def _cleanup_app(proc, timeout_graceful=10, timeout_force=5):
    """Shut down app: SIGINT → SIGTERM → SIGKILL (all to process group)."""
    if proc.poll() is not None:
        _kill_orphans()
        return

    try:
        pgid = os.getpgid(proc.pid)
    except ProcessLookupError:
        _kill_orphans()
        return

    # 1. SIGINT — allows GStreamer/GST-Shark to flush traces
    print(f"\n--- Sending SIGINT to process group {pgid} ---")
    _kill_process_group(pgid, signal.SIGINT)
    try:
        proc.wait(timeout=timeout_graceful)
        _kill_orphans()
        return
    except subprocess.TimeoutExpired:
        pass

    # 2. SIGTERM
    print("--- App didn't stop, sending SIGTERM ---")
    _kill_process_group(pgid, signal.SIGTERM)
    try:
        proc.wait(timeout=timeout_force)
        _kill_orphans()
        return
    except subprocess.TimeoutExpired:
        pass

    # 3. SIGKILL
    print("--- Force killing process group ---")
    _kill_process_group(pgid, signal.SIGKILL)
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass
    _kill_orphans()


def _start_watchdog(app_pid, duration):
    """Fork a watchdog that will kill the app after duration, even if parent dies.

    The watchdog is a background process that:
    1. Sleeps for the duration
    2. Sends SIGINT to the app's process group (for clean GST-Shark flush)
    3. Waits a few seconds, then SIGKILL if still alive
    4. Kills mavsdk_server orphans
    """
    # Use a shell background process — survives parent death
    script = (
        f"sleep {duration}; "
        f"kill -INT -{app_pid} 2>/dev/null; "  # SIGINT to process group
        f"sleep 10; "
        f"kill -TERM -{app_pid} 2>/dev/null; "
        f"sleep 5; "
        f"kill -9 -{app_pid} 2>/dev/null; "
        f"pkill -9 -f mavsdk_server 2>/dev/null"
    )
    watchdog = subprocess.Popen(
        ["bash", "-c", script],
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return watchdog


def _kill_watchdog(watchdog):
    """Kill the watchdog if we're shutting down early."""
    try:
        os.killpg(os.getpgid(watchdog.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


def profile(app_path, duration=15, tracers=None, output_dir=None, extra_args=None):
    """Launch app with GST-Shark tracing."""
    app_path = Path(app_path).resolve()
    if not app_path.exists():
        print(f"Error: {app_path} does not exist", file=sys.stderr)
        sys.exit(1)

    if tracers is None:
        tracers = DEFAULT_TRACERS

    # Create output directory
    if output_dir is None:
        timestamp = datetime.now().strftime("%Y-%m-%d_%H:%M:%S")
        output_dir = app_path.parent / "gst_profiler_traces" / timestamp
    else:
        output_dir = Path(output_dir)

    output_dir.mkdir(parents=True, exist_ok=True)

    # Set GST-Shark environment variables
    env = os.environ.copy()
    env["GST_SHARK_LOCATION"] = str(output_dir)
    env["GST_TRACERS"] = tracers
    env["GST_DEBUG"] = env.get("GST_DEBUG", "GST_TRACER:2")

    # Build command
    cmd = [sys.executable, str(app_path)]
    if extra_args:
        cmd.extend(extra_args)

    print(f"Profiling: {' '.join(cmd)}")
    print(f"Duration: {duration}s")
    print(f"Tracers: {tracers}")
    print(f"Output: {output_dir}")
    print(f"---")

    # Inject --run-duration so the app stops itself gracefully via GStreamerApp.
    # This ensures GStreamer EOS propagates and GST-Shark flushes traces.
    # Falls back to --mission-duration for drone-follow specific apps.
    has_duration = any(a in ("--run-duration", "--mission-duration") for a in cmd)
    if not has_duration:
        cmd.extend(["--run-duration", str(duration)])

    # Launch app in its own process group
    proc = subprocess.Popen(
        cmd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )

    # Start watchdog as safety net — kills app if it outlives duration + grace period
    grace = 30  # seconds after duration before watchdog force-kills
    watchdog = _start_watchdog(proc.pid, duration + grace)

    try:
        # Stream output until app exits (it will self-terminate via --mission-duration)
        while proc.poll() is None:
            try:
                line = proc.stdout.readline()
                if line:
                    sys.stdout.buffer.write(line)
                    sys.stdout.buffer.flush()
            except Exception:
                pass

        print(f"\nApp exited with code {proc.returncode}")
        _kill_watchdog(watchdog)
        _kill_orphans()
    except KeyboardInterrupt:
        print("\n--- Interrupted by user, shutting down ---")
        _kill_watchdog(watchdog)
        _cleanup_app(proc)

    # Find the actual trace directory
    trace_dir = _find_trace_dir(output_dir)

    print(f"\n=== Profiling complete ===")
    print(f"Trace directory: {trace_dir}")
    return trace_dir


def _find_trace_dir(output_dir):
    """Find the actual trace directory containing metadata + datastream."""
    output_dir = Path(output_dir)

    if (output_dir / "metadata").exists():
        return output_dir

    for p in output_dir.rglob("metadata"):
        return p.parent

    return output_dir


def main():
    parser = argparse.ArgumentParser(
        description="Profile a GStreamer pipeline app with GST-Shark",
        usage="%(prog)s <app_path> [options] [-- extra_app_args]",
    )
    parser.add_argument("app_path", help="Path to the Python app to profile")
    parser.add_argument("--duration", type=int, default=15,
                        help="Seconds to run (default: 15)")
    parser.add_argument("--tracers", default=None,
                        help=f"GST tracer string (default: {DEFAULT_TRACERS})")
    parser.add_argument("--output-dir", default=None,
                        help="Output directory for traces")

    argv = sys.argv[1:]
    extra_args = []
    if "--" in argv:
        split_idx = argv.index("--")
        extra_args = argv[split_idx + 1:]
        argv = argv[:split_idx]

    args = parser.parse_args(argv)
    profile(args.app_path, args.duration, args.tracers, args.output_dir, extra_args)


if __name__ == "__main__":
    main()
