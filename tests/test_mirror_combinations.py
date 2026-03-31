#!/usr/bin/env python3
"""
Test mirror/flip combinations across input source types for the detection pipeline.

Runs hailo-detect for 10 seconds with each combination of:
  - Input types: usb (/dev/video0), file (.mp4), image (.jpg)
  - Mirror options: none, --horizontal-mirror, --vertical-mirror, both

Usage:
    source setup_env.sh && python tests/test_mirror_combinations.py
"""

import itertools
import os
import signal
import subprocess
import sys
import threading
import time

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
DETECTION_MODULE = "hailo_apps.python.pipeline_apps.detection.detection"
RUN_TIME = 10  # seconds per test
TERM_TIMEOUT = 5

RESOURCES_ROOT = os.environ.get("RESOURCES_ROOT", "/usr/local/hailo/resources")
VIDEO_FILE = os.path.join(RESOURCES_ROOT, "videos", "example.mp4")
IMAGE_FILE = os.path.join(RESOURCES_ROOT, "images", "bus.jpg")
USB_DEVICE = "/dev/video0"

LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_logs")

# Mirror flag combos: (horizontal, vertical)
MIRROR_COMBOS = [
    (False, False),
    (True, False),
    (False, True),
    (True, True),
]

SOURCE_TYPES = ["usb", "file", "image"]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def mirror_id(h: bool, v: bool) -> str:
    if not h and not v:
        return "no_mirror"
    parts = []
    if h:
        parts.append("hmirror")
    if v:
        parts.append("vmirror")
    return "+".join(parts)


def source_available(source_type: str) -> bool:
    if source_type == "usb":
        return os.path.exists(USB_DEVICE)
    if source_type == "file":
        return os.path.isfile(VIDEO_FILE)
    if source_type == "image":
        return os.path.isfile(IMAGE_FILE)
    return False


def build_args(source_type: str, h_mirror: bool, v_mirror: bool) -> list:
    if source_type == "usb":
        input_src = USB_DEVICE
    elif source_type == "file":
        input_src = VIDEO_FILE
    elif source_type == "image":
        input_src = IMAGE_FILE
    else:
        raise ValueError(f"Unknown source type: {source_type}")

    args = ["--input", input_src, "--disable-sync", "--print-pipeline"]
    if h_mirror:
        args.append("--horizontal-mirror")
    if v_mirror:
        args.append("--vertical-mirror")
    return args


def run_pipeline(args: list, log_file: str):
    """Run detection module, collect output for RUN_TIME seconds, then terminate."""
    cmd = [sys.executable, "-u", "-m", DETECTION_MODULE] + args

    stdout_buf = []
    stderr_buf = []

    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0)

    def reader(pipe, buf):
        try:
            for line in iter(pipe.readline, b""):
                buf.append(line)
        except Exception:
            pass
        finally:
            pipe.close()

    t_out = threading.Thread(target=reader, args=(proc.stdout, stdout_buf), daemon=True)
    t_err = threading.Thread(target=reader, args=(proc.stderr, stderr_buf), daemon=True)
    t_out.start()
    t_err.start()

    # Poll for early exit
    elapsed = 0.0
    early_exit = False
    while elapsed < RUN_TIME:
        time.sleep(0.5)
        elapsed += 0.5
        if proc.poll() is not None:
            early_exit = True
            break

    if not early_exit:
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=TERM_TIMEOUT)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()

    t_out.join(timeout=2)
    t_err.join(timeout=2)

    out = b"".join(stdout_buf).decode(errors="replace")
    err = b"".join(stderr_buf).decode(errors="replace")

    with open(log_file, "w") as f:
        f.write(f"CMD: {' '.join(cmd)}\n\n")
        f.write("=== STDOUT ===\n" + out + "\n")
        f.write("=== STDERR ===\n" + err + "\n")
        if early_exit:
            f.write(f"\n[EARLY EXIT] after {elapsed:.1f}s, code={proc.returncode}\n")

    return out, err, early_exit, proc.returncode


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    os.makedirs(LOG_DIR, exist_ok=True)

    cases = list(itertools.product(SOURCE_TYPES, MIRROR_COMBOS))
    total = len(cases)
    passed = 0
    failed = 0
    skipped = 0
    results = []

    print(f"\n{'='*70}")
    print(f"  Mirror Combination Test  ({total} cases, {RUN_TIME}s each)")
    print(f"{'='*70}\n")

    for i, (src, (h, v)) in enumerate(cases, 1):
        mid = mirror_id(h, v)
        label = f"[{i:2d}/{total}] {src:<6s} / {mid}"

        if not source_available(src):
            print(f"  SKIP  {label}  (source not available)")
            results.append(("SKIP", src, mid, "source not available"))
            skipped += 1
            continue

        args = build_args(src, h, v)
        log_file = os.path.join(LOG_DIR, f"detection_{src}_{mid}.log")
        print(f"  RUN   {label} ...", end="", flush=True)

        out, err, early_exit, rc = run_pipeline(args, log_file)
        combined = out + err

        # Failure checks
        errors = []
        if "gst_parse_error" in combined:
            errors.append("pipeline parse error")
        if "Error creating pipeline" in combined:
            errors.append("pipeline creation failed")
        if early_exit and rc != 0:
            errors.append(f"early exit code={rc}")
        if "Frame count:" not in out:
            errors.append("no frames processed")

        # Verify videoflip presence matches mirror flags
        has_flip = "videoflip" in out
        expect_flip = h or v
        if expect_flip and not has_flip:
            errors.append("videoflip missing from pipeline")
        elif not expect_flip and has_flip:
            errors.append("unexpected videoflip in pipeline")

        if errors:
            reason = "; ".join(errors)
            print(f"\r  FAIL  {label}  ({reason})")
            results.append(("FAIL", src, mid, reason))
            failed += 1
        else:
            # Count frames
            frame_lines = [l for l in out.splitlines() if l.startswith("Frame count:")]
            n_frames = len(frame_lines)
            print(f"\r  PASS  {label}  ({n_frames} frames)")
            results.append(("PASS", src, mid, f"{n_frames} frames"))
            passed += 1

    # Summary
    print(f"\n{'='*70}")
    print(f"  Results: {passed} passed, {failed} failed, {skipped} skipped  (of {total})")
    print(f"  Logs:    {LOG_DIR}/")
    print(f"{'='*70}")

    if failed:
        print("\n  Failed cases:")
        for status, src, mid, reason in results:
            if status == "FAIL":
                print(f"    - {src} / {mid}: {reason}")
        print()

    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
