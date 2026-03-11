#!/usr/bin/env python3
"""
Find the best (highest sustainable) frame rate for a GStreamer pipeline.

Sweeps frame rates from high to low, profiles each, and identifies the highest
rate where the pipeline runs in real-time without bottlenecks.

Real-time criteria:
  - Actual throughput >= 95% of requested FPS
  - E2E latency P95/mean ratio < 3.0 (no accumulation)
  - No queue avg fill > 15%

Usage:
    python find_best_framerate.py <app_path> [--rates 30,25,20,15,10] [--duration 10] [-- extra_args]
"""

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path


DEFAULT_RATES = [30, 25, 20, 15, 10]
DEFAULT_DURATION = 10

# Real-time thresholds
THROUGHPUT_RATIO = 0.95       # actual_fps / requested_fps >= this
LATENCY_JITTER_RATIO = 3.0   # p95/mean < this
MAX_QUEUE_AVG_FILL = 15.0    # no queue avg fill above this %


def profile_at_rate(app_path, fps, duration, extra_args, output_base):
    """Profile the app at a specific frame rate. Returns trace dir."""
    trace_dir = output_base / f"fps_{fps}"
    trace_dir.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env["GST_SHARK_LOCATION"] = str(trace_dir)
    env["GST_TRACERS"] = "proctime;interlatency;queuelevel;cpuusage"
    env["GST_DEBUG"] = env.get("GST_DEBUG", "GST_TRACER:2")

    cmd = [sys.executable, str(app_path), "--frame-rate", str(fps)]
    if extra_args:
        cmd.extend(extra_args)

    proc = subprocess.Popen(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

    start = time.monotonic()
    while time.monotonic() - start < duration:
        if proc.poll() is not None:
            break
        try:
            line = proc.stdout.readline()
        except Exception:
            pass
        time.sleep(0.05)
    else:
        proc.send_signal(signal.SIGINT)
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.terminate()
            proc.wait(timeout=5)

    # Find trace dir with metadata
    for p in trace_dir.rglob("metadata"):
        return p.parent
    return trace_dir


def analyze_trace(trace_dir):
    """Run analyze_trace.py and return parsed JSON."""
    script = Path(__file__).parent / "analyze_trace.py"
    result = subprocess.run(
        [sys.executable, str(script), str(trace_dir), "--format", "json"],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        return None
    return json.loads(result.stdout)


def evaluate(data, requested_fps, duration):
    """Evaluate whether the pipeline is running in real-time at this FPS.

    Returns dict with metrics and pass/fail for each criterion.
    """
    result = {
        "requested_fps": requested_fps,
        "criteria": {},
        "realtime": False,
    }

    # 1. Actual throughput from frame count
    # Use the element with the most samples as frame count proxy
    max_count = 0
    for e in data.get("proctime", []):
        if e["count"] > max_count:
            max_count = e["count"]
    actual_fps = max_count / duration if duration > 0 else 0
    throughput_ratio = actual_fps / requested_fps if requested_fps > 0 else 0

    result["actual_fps"] = round(actual_fps, 1)
    result["throughput_ratio"] = round(throughput_ratio, 3)
    result["criteria"]["throughput"] = throughput_ratio >= THROUGHPUT_RATIO

    # 2. E2E latency jitter (P95 / mean)
    e2e = data.get("interlatency", {}).get("end_to_end", {})
    mean_lat = e2e.get("mean_us", 0)
    p95_lat = e2e.get("p95_us", 0)
    jitter_ratio = p95_lat / mean_lat if mean_lat > 0 else float("inf")

    result["e2e_mean_ms"] = round(mean_lat / 1000, 1)
    result["e2e_p95_ms"] = round(p95_lat / 1000, 1)
    result["jitter_ratio"] = round(jitter_ratio, 2)
    result["criteria"]["latency_stable"] = jitter_ratio < LATENCY_JITTER_RATIO

    # 3. Queue health — max avg fill across all queues
    max_avg_fill = 0
    worst_queue = ""
    for q in data.get("queuelevel", []):
        if q["avg_fill_pct"] > max_avg_fill:
            max_avg_fill = q["avg_fill_pct"]
            worst_queue = q["queue"]

    result["max_queue_avg_fill"] = round(max_avg_fill, 1)
    result["worst_queue"] = worst_queue
    result["criteria"]["queue_healthy"] = max_avg_fill <= MAX_QUEUE_AVG_FILL

    # 4. CPU usage
    result["cpu_pct"] = round(data.get("cpuusage", {}).get("overall_avg", 0), 1)

    # Overall verdict
    result["realtime"] = all(result["criteria"].values())

    return result


def main():
    parser = argparse.ArgumentParser(
        description="Find the best sustainable frame rate for a pipeline",
    )
    parser.add_argument("app_path", help="Path to the pipeline app")
    parser.add_argument("--rates", default=",".join(str(r) for r in DEFAULT_RATES),
                        help=f"Comma-separated FPS values to test (default: {DEFAULT_RATES})")
    parser.add_argument("--duration", type=int, default=DEFAULT_DURATION,
                        help=f"Seconds per test (default: {DEFAULT_DURATION})")
    parser.add_argument("--output-dir", default=None,
                        help="Base output directory for all traces")

    argv = sys.argv[1:]
    extra_args = []
    if "--" in argv:
        split_idx = argv.index("--")
        extra_args = argv[split_idx + 1:]
        argv = argv[:split_idx]

    args = parser.parse_args(argv)
    app_path = Path(args.app_path).resolve()
    rates = [int(r) for r in args.rates.split(",")]
    duration = args.duration

    if args.output_dir:
        output_base = Path(args.output_dir)
    else:
        timestamp = datetime.now().strftime("%Y-%m-%d_%H:%M:%S")
        output_base = app_path.parent / "gst_profiler_traces" / f"fps_sweep_{timestamp}"

    output_base.mkdir(parents=True, exist_ok=True)

    print(f"=== Frame Rate Sweep ===")
    print(f"App: {app_path}")
    print(f"Rates: {rates}")
    print(f"Duration per test: {duration}s")
    print(f"Extra args: {extra_args}")
    print(f"Output: {output_base}")
    print()

    results = []

    for fps in sorted(rates, reverse=True):
        print(f"--- Testing {fps} FPS ---")
        trace_dir = profile_at_rate(app_path, fps, duration, extra_args, output_base)
        data = analyze_trace(trace_dir)

        if data is None:
            print(f"  FAILED: Could not analyze trace at {fps} FPS")
            results.append({"requested_fps": fps, "realtime": False, "error": "analysis_failed"})
            continue

        evaluation = evaluate(data, fps, duration)
        evaluation["trace_dir"] = str(trace_dir)
        results.append(evaluation)

        status = "PASS" if evaluation["realtime"] else "FAIL"
        print(f"  {status} | actual={evaluation['actual_fps']} fps "
              f"({evaluation['throughput_ratio']:.0%}) | "
              f"latency={evaluation['e2e_mean_ms']}ms (P95={evaluation['e2e_p95_ms']}ms, "
              f"jitter={evaluation['jitter_ratio']}x) | "
              f"max_queue={evaluation['max_queue_avg_fill']}% ({evaluation['worst_queue']}) | "
              f"cpu={evaluation['cpu_pct']}%")

        # Detail on failures
        for criterion, passed in evaluation["criteria"].items():
            if not passed:
                print(f"    FAIL: {criterion}")

        print()

    # Summary
    print("=" * 70)
    print(f"{'FPS':>4} | {'Actual':>6} | {'Ratio':>5} | {'Latency Mean':>12} | {'P95':>8} | {'Jitter':>6} | {'Queue':>5} | {'CPU':>4} | {'Result':>6}")
    print("-" * 70)

    best_fps = None
    for r in sorted(results, key=lambda x: x["requested_fps"], reverse=True):
        if "error" in r:
            print(f"{r['requested_fps']:>4} | {'ERR':>6} |")
            continue

        status = "OK" if r["realtime"] else "SLOW"
        print(f"{r['requested_fps']:>4} | {r['actual_fps']:>6.1f} | {r['throughput_ratio']:>4.0%} | "
              f"{r['e2e_mean_ms']:>9.1f} ms | {r['e2e_p95_ms']:>5.1f} ms | {r['jitter_ratio']:>5.1f}x | "
              f"{r['max_queue_avg_fill']:>4.1f}% | {r['cpu_pct']:>3.0f}% | {status:>6}")

        if r["realtime"] and best_fps is None:
            best_fps = r["requested_fps"]

    print("-" * 70)
    if best_fps:
        print(f"BEST FRAME RATE: {best_fps} FPS")
    else:
        lowest = min(r["requested_fps"] for r in results if "error" not in r)
        print(f"No rate passed all criteria. Lowest tested: {lowest} FPS. Try lower rates.")

    # Write JSON results
    results_file = output_base / "sweep_results.json"
    with open(results_file, "w") as f:
        json.dump({"rates_tested": rates, "duration": duration, "results": results,
                    "best_fps": best_fps}, f, indent=2)
    print(f"\nDetailed results: {results_file}")

    return best_fps


if __name__ == "__main__":
    main()
