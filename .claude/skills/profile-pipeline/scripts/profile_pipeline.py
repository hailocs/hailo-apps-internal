#!/usr/bin/env python3
"""
Launch a GStreamer pipeline app with GST-Shark tracing enabled.

Usage:
    python profile_pipeline.py <app_path> [--duration 15] [--tracers all] [--output-dir <dir>] [-- extra app args]
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


def profile(app_path, duration=15, tracers=None, output_dir=None, extra_args=None):
    """Launch app with GST-Shark tracing.

    Args:
        app_path: Path to the Python app to profile
        duration: Seconds to run before stopping
        tracers: GST tracer string (semicolon-separated)
        output_dir: Where to store traces (default: auto-generated)
        extra_args: Additional args to pass to the app

    Returns:
        Path to the trace output directory
    """
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

    # Launch subprocess
    proc = subprocess.Popen(
        cmd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )

    try:
        # Wait for duration, streaming output
        start = time.monotonic()
        while time.monotonic() - start < duration:
            if proc.poll() is not None:
                print(f"\nApp exited early with code {proc.returncode}")
                break
            # Read available output without blocking
            try:
                line = proc.stdout.readline()
                if line:
                    sys.stdout.buffer.write(line)
                    sys.stdout.buffer.flush()
            except Exception:
                pass
            time.sleep(0.1)
        else:
            print(f"\n--- Duration reached ({duration}s), sending SIGINT ---")
            proc.send_signal(signal.SIGINT)
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                print("App didn't stop, sending SIGTERM")
                proc.terminate()
                proc.wait(timeout=5)
    except KeyboardInterrupt:
        print("\n--- Interrupted, stopping app ---")
        proc.send_signal(signal.SIGINT)
        proc.wait(timeout=10)

    # Find the actual trace directory (GST-Shark may create subdirs)
    trace_dir = _find_trace_dir(output_dir)

    print(f"\n=== Profiling complete ===")
    print(f"Trace directory: {trace_dir}")
    return trace_dir


def _find_trace_dir(output_dir):
    """Find the actual trace directory containing metadata + datastream."""
    output_dir = Path(output_dir)

    # Check if metadata is directly in output_dir
    if (output_dir / "metadata").exists():
        return output_dir

    # Check subdirectories (GST-Shark sometimes nests them)
    for p in output_dir.rglob("metadata"):
        return p.parent

    # Return the output dir even if no traces found
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

    # Split on -- to separate our args from app args
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
