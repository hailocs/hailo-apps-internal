#!/usr/bin/env python3
"""
Analyze GST-Shark CTF trace data and produce structured metrics.

Usage:
    python analyze_trace.py <trace_dir> [--format json|text]
"""

import argparse
import json
import sys
from pathlib import Path

# Add scripts dir to path for sibling import
sys.path.insert(0, str(Path(__file__).parent))
from ctf_parser import parse_trace


def percentile(values, pct):
    """Compute percentile from sorted list."""
    if not values:
        return 0
    k = (len(values) - 1) * pct / 100
    f = int(k)
    c = f + 1
    if c >= len(values):
        return values[f]
    return values[f] + (k - f) * (values[c] - values[f])


def analyze_proctime(events):
    """Analyze processing time per element."""
    by_element = {}
    for ev in events:
        name = ev["element"]
        time_us = ev["_time"] / 1000  # ns -> us
        by_element.setdefault(name, []).append(time_us)

    results = []
    for name, times in by_element.items():
        times.sort()
        n = len(times)
        mean = sum(times) / n
        results.append({
            "element": name,
            "count": n,
            "mean_us": round(mean, 1),
            "p50_us": round(percentile(times, 50), 1),
            "p95_us": round(percentile(times, 95), 1),
            "p99_us": round(percentile(times, 99), 1),
            "max_us": round(max(times), 1),
        })

    results.sort(key=lambda x: x["mean_us"], reverse=True)
    return results


def analyze_interlatency(events):
    """Analyze inter-element latency."""
    by_pair = {}
    for ev in events:
        pair = f"{ev['from_pad']} -> {ev['to_pad']}"
        time_us = ev["_time"] / 1000
        by_pair.setdefault(pair, []).append(time_us)

    results = []
    for pair, times in by_pair.items():
        times.sort()
        n = len(times)
        mean = sum(times) / n
        results.append({
            "path": pair,
            "count": n,
            "mean_us": round(mean, 1),
            "p95_us": round(percentile(times, 95), 1),
            "max_us": round(max(times), 1),
        })

    results.sort(key=lambda x: x["mean_us"], reverse=True)

    # Find end-to-end latency (longest path)
    e2e = results[0] if results else None
    return {"pairs": results, "end_to_end": e2e}


def analyze_framerate(events):
    """Analyze framerate per pad."""
    by_pad = {}
    for ev in events:
        pad = ev["pad"]
        # _fps is in 1000ths of fps (milliFPS)
        fps = ev["_fps"] / 1000.0
        by_pad.setdefault(pad, []).append(fps)

    results = []
    for pad, fps_list in by_pad.items():
        n = len(fps_list)
        mean = sum(fps_list) / n
        variance = sum((x - mean) ** 2 for x in fps_list) / n if n > 1 else 0
        stddev = variance ** 0.5
        results.append({
            "pad": pad,
            "count": n,
            "avg_fps": round(mean, 1),
            "min_fps": round(min(fps_list), 1),
            "max_fps": round(max(fps_list), 1),
            "stddev": round(stddev, 2),
        })

    results.sort(key=lambda x: x["avg_fps"])
    return results


def analyze_queuelevel(events):
    """Analyze queue fill levels."""
    by_queue = {}
    for ev in events:
        name = ev["queue"]
        by_queue.setdefault(name, []).append(ev)

    results = []
    for name, samples in by_queue.items():
        fill_pcts = []
        for s in samples:
            max_buf = s["max_size_buffers"]
            if max_buf > 0:
                fill_pcts.append(s["size_buffers"] / max_buf * 100)
            else:
                fill_pcts.append(0)

        avg_fill = sum(fill_pcts) / len(fill_pcts) if fill_pcts else 0
        max_fill = max(fill_pcts) if fill_pcts else 0
        entry = {
            "queue": name,
            "count": len(samples),
            "avg_fill_pct": round(avg_fill, 1),
            "max_fill_pct": round(max_fill, 1),
            "warning": avg_fill > 70,
        }
        results.append(entry)

    results.sort(key=lambda x: x["avg_fill_pct"], reverse=True)
    return results


def analyze_cpuusage(events):
    """Analyze CPU usage across cores."""
    if not events:
        return {"per_core": [], "overall_avg": 0}

    # Discover CPU field names dynamically
    sample = events[0]
    cpu_keys = sorted([k for k in sample if k.startswith("_cpu")])

    per_core = {}
    for key in cpu_keys:
        values = [ev[key] for ev in events]
        per_core[key] = round(sum(values) / len(values), 1)

    overall = sum(per_core.values()) / len(per_core) if per_core else 0
    return {
        "per_core": per_core,
        "overall_avg": round(overall, 1),
        "num_samples": len(events),
    }


def analyze_scheduling(events):
    """Analyze scheduling time per pad."""
    by_pad = {}
    for ev in events:
        pad = ev["pad"]
        time_us = ev["_time"] / 1000
        by_pad.setdefault(pad, []).append(time_us)

    results = []
    for pad, times in by_pad.items():
        times.sort()
        mean = sum(times) / len(times)
        results.append({
            "pad": pad,
            "count": len(times),
            "mean_us": round(mean, 1),
            "p95_us": round(percentile(times, 95), 1),
            "max_us": round(max(times), 1),
        })

    results.sort(key=lambda x: x["mean_us"], reverse=True)
    return results


def analyze(trace_dir):
    """Run full analysis on a trace directory."""
    result = parse_trace(trace_dir)
    events = result["events"]

    analysis = {
        "trace_dir": str(trace_dir),
        "event_counts": {name: len(evs) for name, evs in events.items()},
    }

    if events.get("proctime"):
        analysis["proctime"] = analyze_proctime(events["proctime"])
    if events.get("interlatency"):
        latency = analyze_interlatency(events["interlatency"])
        analysis["interlatency"] = latency
    if events.get("framerate"):
        analysis["framerate"] = analyze_framerate(events["framerate"])
    if events.get("queuelevel"):
        analysis["queuelevel"] = analyze_queuelevel(events["queuelevel"])
    if events.get("cpuusage"):
        analysis["cpuusage"] = analyze_cpuusage(events["cpuusage"])
    if events.get("scheduling"):
        analysis["scheduling"] = analyze_scheduling(events["scheduling"])

    return analysis


def format_text(analysis):
    """Format analysis as human-readable text."""
    lines = []
    lines.append(f"=== Pipeline Trace Analysis: {analysis['trace_dir']} ===\n")

    counts = analysis["event_counts"]
    lines.append("Event counts:")
    for name, count in counts.items():
        lines.append(f"  {name}: {count}")
    lines.append("")

    if "proctime" in analysis:
        lines.append("--- Processing Time (sorted by mean, descending) ---")
        lines.append(f"{'Element':<40} {'Mean':>8} {'P50':>8} {'P95':>8} {'P99':>8} {'Max':>8}  (us)")
        for p in analysis["proctime"]:
            lines.append(
                f"  {p['element']:<38} {p['mean_us']:>8.1f} {p['p50_us']:>8.1f} "
                f"{p['p95_us']:>8.1f} {p['p99_us']:>8.1f} {p['max_us']:>8.1f}"
            )
        lines.append("")

    if "interlatency" in analysis:
        lat = analysis["interlatency"]
        lines.append("--- Inter-Element Latency ---")
        if lat["end_to_end"]:
            e2e = lat["end_to_end"]
            lines.append(f"  End-to-end: {e2e['path']}")
            lines.append(f"    Mean: {e2e['mean_us']:.1f} us, P95: {e2e['p95_us']:.1f} us, Max: {e2e['max_us']:.1f} us")
        lines.append(f"  ({len(lat['pairs'])} measured paths)")
        lines.append("")

    if "framerate" in analysis:
        lines.append("--- Framerate ---")
        for f in analysis["framerate"]:
            warn = " [LOW]" if f["avg_fps"] < 25 else ""
            lines.append(f"  {f['pad']:<40} avg={f['avg_fps']:.1f} min={f['min_fps']:.1f} stddev={f['stddev']:.2f}{warn}")
        lines.append("")

    if "queuelevel" in analysis:
        lines.append("--- Queue Levels ---")
        for q in analysis["queuelevel"]:
            warn = " [WARNING: >70%]" if q["warning"] else ""
            lines.append(f"  {q['queue']:<40} avg={q['avg_fill_pct']:.1f}% max={q['max_fill_pct']:.1f}%{warn}")
        lines.append("")

    if "cpuusage" in analysis:
        cpu = analysis["cpuusage"]
        lines.append(f"--- CPU Usage (overall avg: {cpu['overall_avg']:.1f}%) ---")
        for core, usage in cpu["per_core"].items():
            bar = "#" * int(usage / 5) + "-" * (20 - int(usage / 5))
            lines.append(f"  {core}: [{bar}] {usage:.1f}%")
        lines.append("")

    if "scheduling" in analysis:
        lines.append("--- Scheduling Time ---")
        for s in analysis["scheduling"][:10]:  # Top 10
            lines.append(f"  {s['pad']:<40} mean={s['mean_us']:.1f} us p95={s['p95_us']:.1f} us")
        lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Analyze GST-Shark trace data")
    parser.add_argument("trace_dir", help="Path to trace directory")
    parser.add_argument("--format", choices=["json", "text"], default="text",
                        help="Output format (default: text)")
    args = parser.parse_args()

    analysis = analyze(args.trace_dir)

    if args.format == "json":
        print(json.dumps(analysis, indent=2))
    else:
        print(format_text(analysis))


if __name__ == "__main__":
    main()
