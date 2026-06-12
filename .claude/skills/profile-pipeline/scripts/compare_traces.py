#!/usr/bin/env python3
"""
A/B comparison of two GST-Shark trace directories.

Usage:
    python compare_traces.py <baseline_dir> <experiment_dir> [--format json|text]
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from analyze_trace import analyze


def compare(baseline_dir, experiment_dir):
    """Compare two trace analyses."""
    base = analyze(baseline_dir)
    exp = analyze(experiment_dir)

    comparison = {
        "baseline": str(baseline_dir),
        "experiment": str(experiment_dir),
    }

    # Compare proctime
    if "proctime" in base and "proctime" in exp:
        base_pt = {p["element"]: p for p in base["proctime"]}
        exp_pt = {p["element"]: p for p in exp["proctime"]}
        all_elements = set(base_pt) | set(exp_pt)

        proctime_cmp = []
        for elem in sorted(all_elements):
            b = base_pt.get(elem)
            e = exp_pt.get(elem)
            entry = {"element": elem}
            if b and e:
                delta = e["mean_us"] - b["mean_us"]
                pct = (delta / b["mean_us"] * 100) if b["mean_us"] else 0
                entry["baseline_mean_us"] = b["mean_us"]
                entry["experiment_mean_us"] = e["mean_us"]
                entry["delta_us"] = round(delta, 1)
                entry["delta_pct"] = round(pct, 1)
                entry["improved"] = delta < 0
            elif b:
                entry["baseline_mean_us"] = b["mean_us"]
                entry["experiment_mean_us"] = None
                entry["note"] = "removed in experiment"
            else:
                entry["baseline_mean_us"] = None
                entry["experiment_mean_us"] = e["mean_us"]
                entry["note"] = "new in experiment"
            proctime_cmp.append(entry)
        comparison["proctime"] = sorted(proctime_cmp, key=lambda x: abs(x.get("delta_pct", 0)), reverse=True)

    # Compare framerate
    if "framerate" in base and "framerate" in exp:
        base_fr = {f["pad"]: f for f in base["framerate"]}
        exp_fr = {f["pad"]: f for f in exp["framerate"]}
        fps_cmp = []
        for pad in set(base_fr) | set(exp_fr):
            b = base_fr.get(pad)
            e = exp_fr.get(pad)
            if b and e:
                delta = e["avg_fps"] - b["avg_fps"]
                fps_cmp.append({
                    "pad": pad,
                    "baseline_fps": b["avg_fps"],
                    "experiment_fps": e["avg_fps"],
                    "delta_fps": round(delta, 1),
                    "improved": delta > 0,
                })
        comparison["framerate"] = fps_cmp

    # Compare queue levels
    if "queuelevel" in base and "queuelevel" in exp:
        base_ql = {q["queue"]: q for q in base["queuelevel"]}
        exp_ql = {q["queue"]: q for q in exp["queuelevel"]}
        queue_cmp = []
        for name in set(base_ql) | set(exp_ql):
            b = base_ql.get(name)
            e = exp_ql.get(name)
            if b and e:
                delta = e["avg_fill_pct"] - b["avg_fill_pct"]
                queue_cmp.append({
                    "queue": name,
                    "baseline_fill_pct": b["avg_fill_pct"],
                    "experiment_fill_pct": e["avg_fill_pct"],
                    "delta_pct": round(delta, 1),
                    "improved": delta < 0,
                })
        comparison["queuelevel"] = queue_cmp

    # Compare latency
    if "interlatency" in base and "interlatency" in exp:
        b_e2e = base["interlatency"].get("end_to_end")
        e_e2e = exp["interlatency"].get("end_to_end")
        if b_e2e and e_e2e:
            delta = e_e2e["mean_us"] - b_e2e["mean_us"]
            pct = (delta / b_e2e["mean_us"] * 100) if b_e2e["mean_us"] else 0
            comparison["latency"] = {
                "baseline_mean_us": b_e2e["mean_us"],
                "experiment_mean_us": e_e2e["mean_us"],
                "delta_us": round(delta, 1),
                "delta_pct": round(pct, 1),
                "improved": delta < 0,
            }

    # Compare CPU usage
    if "cpuusage" in base and "cpuusage" in exp:
        comparison["cpuusage"] = {
            "baseline_avg": base["cpuusage"]["overall_avg"],
            "experiment_avg": exp["cpuusage"]["overall_avg"],
            "delta": round(exp["cpuusage"]["overall_avg"] - base["cpuusage"]["overall_avg"], 1),
        }

    return comparison


def _color(text, improved):
    """ANSI color: green for improved, red for regression."""
    if improved:
        return f"\033[92m{text}\033[0m"
    return f"\033[91m{text}\033[0m"


def format_text(cmp):
    """Format comparison as human-readable text."""
    lines = []
    lines.append(f"=== A/B Comparison ===")
    lines.append(f"  Baseline:   {cmp['baseline']}")
    lines.append(f"  Experiment: {cmp['experiment']}")
    lines.append("")

    if "proctime" in cmp:
        lines.append("--- Processing Time ---")
        lines.append(f"  {'Element':<35} {'Baseline':>10} {'Experiment':>10} {'Delta':>10} {'%':>8}")
        for p in cmp["proctime"]:
            if p.get("baseline_mean_us") is not None and p.get("experiment_mean_us") is not None:
                improved = p.get("improved", False)
                delta_str = f"{p['delta_us']:+.1f}"
                pct_str = f"{p['delta_pct']:+.1f}%"
                line = (f"  {p['element']:<35} {p['baseline_mean_us']:>10.1f} "
                        f"{p['experiment_mean_us']:>10.1f} {delta_str:>10} {pct_str:>8}")
                lines.append(_color(line, improved))
        lines.append("")

    if "framerate" in cmp:
        lines.append("--- Framerate ---")
        for f in cmp["framerate"]:
            improved = f.get("improved", False)
            line = f"  {f['pad']:<35} {f['baseline_fps']:>6.1f} -> {f['experiment_fps']:>6.1f} fps ({f['delta_fps']:+.1f})"
            lines.append(_color(line, improved))
        lines.append("")

    if "latency" in cmp:
        lat = cmp["latency"]
        improved = lat.get("improved", False)
        line = f"  End-to-end latency: {lat['baseline_mean_us']:.1f} -> {lat['experiment_mean_us']:.1f} us ({lat['delta_pct']:+.1f}%)"
        lines.append("--- Latency ---")
        lines.append(_color(line, improved))
        lines.append("")

    if "queuelevel" in cmp:
        lines.append("--- Queue Levels ---")
        for q in cmp["queuelevel"]:
            improved = q.get("improved", False)
            line = f"  {q['queue']:<35} {q['baseline_fill_pct']:.1f}% -> {q['experiment_fill_pct']:.1f}% ({q['delta_pct']:+.1f}%)"
            lines.append(_color(line, improved))
        lines.append("")

    if "cpuusage" in cmp:
        cpu = cmp["cpuusage"]
        lines.append(f"--- CPU Usage ---")
        lines.append(f"  Overall: {cpu['baseline_avg']:.1f}% -> {cpu['experiment_avg']:.1f}% ({cpu['delta']:+.1f}%)")
        lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Compare two GST-Shark traces")
    parser.add_argument("baseline_dir", help="Baseline trace directory")
    parser.add_argument("experiment_dir", help="Experiment trace directory")
    parser.add_argument("--format", choices=["json", "text"], default="text")
    args = parser.parse_args()

    cmp = compare(args.baseline_dir, args.experiment_dir)

    if args.format == "json":
        print(json.dumps(cmp, indent=2))
    else:
        print(format_text(cmp))


if __name__ == "__main__":
    main()
