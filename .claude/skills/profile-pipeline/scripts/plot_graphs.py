#!/usr/bin/env python3
"""
Generate performance visualization graphs from GST-Shark trace analysis.

Usage:
    python plot_graphs.py <trace_dir> [--output-dir <dir>] [--open]

Generates:
    - proctime_chart.png    — Horizontal bar chart of element processing times (mean/P50/P95)
    - npu_breakdown.png     — Pie chart (NPU/CPU/queue) + NPU model bar chart
    - latency_waterfall.png — End-to-end latency waterfall with inline labels
    - queue_levels.png      — Queue fill levels in pipeline flow order with section labels

Requires matplotlib. Reads JSON output from analyze_trace.py.
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
import numpy as np


def load_analysis(trace_dir):
    """Run analyze_trace.py and return parsed JSON."""
    script_dir = Path(__file__).parent
    result = subprocess.run(
        [sys.executable, str(script_dir / "analyze_trace.py"), str(trace_dir), "--format", "json"],
        capture_output=True, text=True,
    )
    output = result.stdout
    # Skip non-JSON preamble (e.g. from setup_env.sh)
    idx = output.index('{')
    return json.loads(output[idx:])


# =============================================================================
# 1. Processing Time Bar Chart
# =============================================================================
def plot_proctime(data, output_dir, top_n=15):
    """Horizontal bar chart of mean/P50/P95 processing time per element."""
    elements = data["proctime"][:top_n]

    names = [e["element"] for e in elements]
    means = [e["mean_us"] / 1000 for e in elements]
    p50s = [e["p50_us"] / 1000 for e in elements]
    p95s = [e["p95_us"] / 1000 for e in elements]

    fig, ax = plt.subplots(figsize=(14, max(7, len(names) * 0.55)))
    y = np.arange(len(names))
    bar_height = 0.25

    bars_mean = ax.barh(y + bar_height, means, bar_height, label='Mean', color='#2196F3', zorder=3)
    bars_p50 = ax.barh(y, p50s, bar_height, label='P50', color='#4CAF50', zorder=3)
    bars_p95 = ax.barh(y - bar_height, p95s, bar_height, label='P95', color='#FF9800', zorder=3)

    for bars in [bars_mean, bars_p50, bars_p95]:
        for bar in bars:
            w = bar.get_width()
            if w > 1:
                ax.text(w + 0.3, bar.get_y() + bar.get_height() / 2, f'{w:.1f}ms',
                        va='center', fontsize=8)

    ax.set_yticks(y)
    ax.set_yticklabels(names, fontsize=10)
    ax.set_xlabel('Processing Time (ms)', fontsize=12)
    ax.set_title('Pipeline — Element Processing Time', fontsize=14, fontweight='bold')
    ax.legend(loc='lower right', fontsize=10)
    ax.grid(axis='x', alpha=0.3, zorder=0)
    ax.invert_yaxis()
    plt.tight_layout()

    path = output_dir / "proctime_chart.png"
    plt.savefig(str(path), dpi=150)
    plt.close()
    return path


# =============================================================================
# 2. NPU Breakdown (Pie + Bar)
# =============================================================================
def plot_npu_breakdown(data, output_dir):
    """Pie chart of NPU/CPU/queue time + bar chart of NPU models."""
    elements = data["proctime"]

    # Classify elements
    npu_elements = [e for e in elements if "hailonet" in e["element"] and "_q" not in e["element"]]
    queue_elements = [e for e in elements if e["element"].endswith("_q") or e["element"].endswith("bypass_q")]
    cpu_elements = [e for e in elements if e not in npu_elements and e not in queue_elements]

    npu_total = sum(e["mean_us"] for e in npu_elements) / 1000
    cpu_total = sum(e["mean_us"] for e in cpu_elements[:10]) / 1000  # top 10 CPU
    queue_total = sum(e["mean_us"] for e in queue_elements[:5]) / 1000  # top 5 queues

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))

    # Pie chart
    sizes = [npu_total, cpu_total, queue_total]
    labels = [f'NPU Inference\n{npu_total:.1f}ms', f'CPU Processing\n{cpu_total:.1f}ms',
              f'Queue Wait\n{queue_total:.1f}ms']
    colors = ['#E53935', '#2196F3', '#9E9E9E']
    ax1.pie(sizes, explode=(0.05, 0, 0), labels=labels, colors=colors, autopct='%1.0f%%',
            shadow=False, startangle=90, textprops={'fontsize': 11})
    ax1.set_title('Time Breakdown per Frame', fontsize=13, fontweight='bold')

    # NPU model bar chart
    npu_names = [e["element"].replace("_hailonet", "") for e in npu_elements]
    npu_times = [e["mean_us"] / 1000 for e in npu_elements]
    npu_colors = ['#E53935', '#FF7043', '#FFAB91', '#FFCCBC'][:len(npu_elements)]
    bars = ax2.bar(npu_names, npu_times, color=npu_colors, edgecolor='white', linewidth=1.5, zorder=3)
    for bar, val in zip(bars, npu_times):
        ax2.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.3,
                 f'{val:.1f}ms', ha='center', fontsize=11, fontweight='bold')
    ax2.set_ylabel('Processing Time (ms)', fontsize=11)
    ax2.set_title('NPU Inference Time by Model', fontsize=13, fontweight='bold')
    ax2.grid(axis='y', alpha=0.3, zorder=0)
    ax2.set_ylim(0, max(npu_times) * 1.2 if npu_times else 10)

    plt.tight_layout()
    path = output_dir / "npu_breakdown.png"
    plt.savefig(str(path), dpi=150)
    plt.close()
    return path


# =============================================================================
# 3. Latency Waterfall
# =============================================================================
def plot_latency_waterfall(data, output_dir, stages=None):
    """End-to-end latency waterfall with inline stage labels.

    Args:
        stages: List of (name, duration_ms, color) tuples. If None, auto-derived
                from interlatency data.
    """
    if stages is None:
        stages = _derive_latency_stages(data)

    fig, ax = plt.subplots(figsize=(16, 4))
    left = 0
    total = sum(s[1] for s in stages)

    for name, duration, color in stages:
        label_text = f"{name}\n{duration:.1f}ms"
        ax.barh(0, duration, left=left, height=0.6, color=color, edgecolor='white', linewidth=2)
        if duration > 3:
            text_color = 'white' if _is_dark(color) else 'black'
            ax.text(left + duration / 2, 0, label_text, ha='center', va='center',
                    fontsize=9, fontweight='bold', color=text_color)
        elif duration > 0.3:
            ax.text(left + duration / 2, 0.45, label_text, ha='center', va='bottom',
                    fontsize=7, fontweight='bold', color='#333')
        left += duration

    ax.set_xlim(0, left + 2)
    ax.set_xlabel('Time (ms)', fontsize=12)
    ax.set_title(f'End-to-End Latency Waterfall — Total: {total:.1f}ms (mean)',
                 fontsize=14, fontweight='bold')
    ax.set_yticks([])
    ax.grid(axis='x', alpha=0.3)
    ax.set_ylim(-0.5, 1.2)
    plt.tight_layout()

    path = output_dir / "latency_waterfall.png"
    plt.savefig(str(path), dpi=150, bbox_inches='tight')
    plt.close()
    return path


def _is_dark(hex_color):
    rgb = mcolors.to_rgb(hex_color)
    luminance = 0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]
    return luminance < 0.5


def _derive_latency_stages(data):
    """Auto-derive waterfall stages from interlatency pairs."""
    pairs = data.get("interlatency", {}).get("pairs", [])
    if not pairs:
        return [("No latency data", 1, '#9E9E9E')]

    # Find key waypoints from interlatency paths
    waypoints = {}
    for p in pairs:
        path = p["path"]
        mean = p["mean_us"] / 1000
        dest = path.split(" -> ")[-1] if " -> " in path else path
        waypoints[dest] = mean

    # Build stages from known element patterns
    stages = []
    stage_defs = [
        ("Source/Decode", ["source_fps_caps_src", "source_videorate_src", "videoflip_source_src"], '#90CAF9'),
        ("Pose Inference", ["pose_inference_hailonet_src", "pose_wrapper_output_q_src"], '#E53935'),
        ("Tracker", ["hailo_tracker_src"], '#81C784'),
        ("Palm Inference", ["palm_detection_hailonet_src", "palm_wrapper_output_q_src"], '#FF7043'),
        ("Cropper → Hand", ["palm_agg_src", "palm_cropper_output_q_src"], '#FFAB91'),
        ("Gesture + CB", ["gesture_classification_src", "identity_callback_src"], '#A5D6A7'),
        ("Overlay + Display", ["hailo_display_videoconvert_src", "autovideosink"], '#64B5F6'),
    ]

    prev_time = 0
    for name, keys, color in stage_defs:
        best = 0
        for k in keys:
            for wp_name, wp_time in waypoints.items():
                if k in wp_name:
                    best = max(best, wp_time)
        if best > prev_time:
            stages.append((name, best - prev_time, color))
            prev_time = best

    return stages if stages else [("Pipeline", waypoints.get(max(waypoints, key=waypoints.get), 0), '#2196F3')]


# =============================================================================
# 4. Queue Fill Levels
# =============================================================================
def plot_queue_levels(data, output_dir):
    """Queue fill levels with color-coded pipeline sections."""
    queues = [q for q in data["queuelevel"] if q["max_fill_pct"] > 0]

    if not queues:
        return None

    # Sort by max fill descending
    queues.sort(key=lambda q: q["max_fill_pct"], reverse=True)

    # Auto-color by section
    def section_color(name):
        if "pose" in name: return '#E53935'
        if "palm_detection" in name or "palm_wrapper" in name: return '#FF9800'
        if "palm_cropper" in name or "palm_bypass" in name or "hand" in name: return '#9C27B0'
        if "gesture" in name or "callback" in name: return '#009688'
        if "display" in name: return '#607D8B'
        if "source" in name: return '#42A5F5'
        return '#78909C'

    fig, ax = plt.subplots(figsize=(max(14, len(queues) * 1.1), 7))

    names = [q["queue"].replace("_q", "").replace("queue_", "") for q in queues]
    avg_fills = [q["avg_fill_pct"] for q in queues]
    max_fills = [q["max_fill_pct"] for q in queues]
    colors = [section_color(q["queue"]) for q in queues]

    light_colors = [tuple(min(1, v + 0.35) for v in mcolors.to_rgb(c)) for c in colors]

    x = np.arange(len(names))
    width = 0.32

    ax.bar(x - width / 2, avg_fills, width, color=light_colors, edgecolor='white', linewidth=1,
           label='Avg Fill %', zorder=3)
    ax.bar(x + width / 2, max_fills, width, color=colors, edgecolor='white', linewidth=1,
           label='Max Fill %', alpha=0.65, zorder=3)

    ax.axhline(y=70, color='red', linestyle='--', alpha=0.6, linewidth=2, label='Warning (70%)')

    for i, (avg, mx) in enumerate(zip(avg_fills, max_fills)):
        if avg >= 0.3:
            ax.text(i - width / 2, avg + 1.5, f'{avg:.1f}%', ha='center', va='bottom',
                    fontsize=9, fontweight='bold')
        if mx > 0:
            ax.text(i + width / 2, mx + 1.5, f'{mx:.0f}%', ha='center', va='bottom',
                    fontsize=9, color='#333')

    ax.set_xticks(x)
    ax.set_xticklabels(names, rotation=40, ha='right', fontsize=9)
    ax.set_ylabel('Fill Level (%)', fontsize=12)
    ax.set_title('Queue Fill Levels', fontsize=15, fontweight='bold')
    ax.set_ylim(0, 110)
    ax.legend(loc='upper right', fontsize=10)
    ax.grid(axis='y', alpha=0.2, zorder=0)
    plt.tight_layout()

    path = output_dir / "queue_levels.png"
    plt.savefig(str(path), dpi=150)
    plt.close()
    return path


# =============================================================================
# Main
# =============================================================================
def generate_all(trace_dir, output_dir=None, open_files=False):
    """Generate all graphs for a trace directory.

    Returns list of generated file paths.
    """
    trace_dir = Path(trace_dir)
    if output_dir is None:
        output_dir = trace_dir
    else:
        output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    data = load_analysis(trace_dir)
    paths = []

    print("Generating graphs...")
    paths.append(plot_proctime(data, output_dir))
    print(f"  ✓ {paths[-1].name}")

    paths.append(plot_npu_breakdown(data, output_dir))
    print(f"  ✓ {paths[-1].name}")

    paths.append(plot_latency_waterfall(data, output_dir))
    print(f"  ✓ {paths[-1].name}")

    queue_path = plot_queue_levels(data, output_dir)
    if queue_path:
        paths.append(queue_path)
        print(f"  ✓ {paths[-1].name}")

    print(f"\nAll graphs saved to: {output_dir}")

    if open_files:
        for p in paths:
            subprocess.Popen(["xdg-open", str(p)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print(f"Opened {len(paths)} graphs.")

    return paths


def main():
    parser = argparse.ArgumentParser(description="Generate pipeline performance graphs")
    parser.add_argument("trace_dir", help="Trace directory from profile_pipeline.py")
    parser.add_argument("--output-dir", default=None, help="Output directory (default: same as trace_dir)")
    parser.add_argument("--open", action="store_true", help="Open graphs with xdg-open")
    args = parser.parse_args()

    generate_all(args.trace_dir, args.output_dir, args.open)


if __name__ == "__main__":
    main()
