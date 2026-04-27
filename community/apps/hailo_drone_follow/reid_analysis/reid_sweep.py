#!/usr/bin/env python3
"""
ReID Parameter Sweep Runner
============================
Runs the ReID pipeline with different parameter combinations, evaluates each,
and produces a comparison table.

Usage:
    source setup_env.sh
    python reid_analysis/reid_sweep.py \
        --input 12354541-hd_1280_720_25fps.mp4 \
        --ground-truth reid_analysis/ground_truth.json \
        --tiles-x 2 --tiles-y 3

    # Or with a custom sweep config:
    python reid_analysis/reid_sweep.py \
        --input 12354541-hd_1280_720_25fps.mp4 \
        --ground-truth reid_analysis/ground_truth.json \
        --sweep-config reid_analysis/sweep_config.json
"""

import argparse
import itertools
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from hailo_apps.python.core.common.hailo_logger import get_logger

from reid_analysis.reid_eval import append_csv, evaluate, load_ground_truth, load_match_log

logger = get_logger(__name__)


DEFAULT_SWEEP = {
    "reid_model": ["repvgg", "osnet"],
    "reid_match_threshold": [0.5, 0.6, 0.7, 0.8, 0.9],
    "gallery_strategy": ["first_only", "running_average", "multi_embedding"],
}


def run_pipeline(input_video, output_dir, reid_model, reid_match_threshold, gallery_strategy,
                 extra_args=None):
    """Run reid_analysis_app.py with given parameters. Returns match_log path."""
    script_dir = Path(__file__).parent
    app_path = script_dir / "reid_analysis_app.py"

    cmd = [
        sys.executable, str(app_path),
        "--input", input_video,
        "--output-dir", str(output_dir),
        "--reid-model", reid_model,
        "--reid-match-threshold", str(reid_match_threshold),
        "--gallery-strategy", gallery_strategy,
        "--disable-sync",
        "--video-sink", "fakesink",
    ]
    if extra_args:
        cmd.extend(extra_args)

    logger.info("Running: model=%s threshold=%s strategy=%s", reid_model, reid_match_threshold, gallery_strategy)
    logger.info("Output: %s", output_dir)

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        logger.error("Pipeline failed (exit code %d): %s", result.returncode,
                      result.stderr.strip()[-500:] if result.stderr else "no stderr")

    return output_dir / "match_log.jsonl"


def main():
    parser = argparse.ArgumentParser(description="ReID parameter sweep runner")
    parser.add_argument("--input", type=str, required=True, help="Input video file")
    parser.add_argument("--ground-truth", type=str, required=True, help="Path to ground_truth.json")
    parser.add_argument("--sweep-config", type=str, default=None,
                        help="JSON file with parameter grid (default: built-in grid)")
    parser.add_argument("--output-base", type=str,
                        default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "sweep_results"),
                        help="Base directory for sweep results")
    parser.add_argument("--output-csv", type=str, default=None,
                        help="CSV file for results (default: <output-base>/sweep_results.csv)")
    # Pass through pipeline args
    parser.add_argument("--tiles-x", type=int, default=None)
    parser.add_argument("--tiles-y", type=int, default=None)
    args, unknown_args = parser.parse_known_args()

    # Load sweep config
    if args.sweep_config:
        with open(args.sweep_config) as f:
            sweep = json.load(f)
    else:
        sweep = DEFAULT_SWEEP

    # Load ground truth
    id_mapping = load_ground_truth(args.ground_truth)

    # Build extra pipeline args
    extra_args = list(unknown_args)
    if args.tiles_x is not None:
        extra_args.extend(["--tiles-x", str(args.tiles_x)])
    if args.tiles_y is not None:
        extra_args.extend(["--tiles-y", str(args.tiles_y)])

    # Output paths
    output_base = Path(args.output_base)
    output_base.mkdir(parents=True, exist_ok=True)
    csv_path = args.output_csv or str(output_base / "sweep_results.csv")

    # Generate parameter combinations
    param_names = list(sweep.keys())
    param_values = list(sweep.values())
    combinations = list(itertools.product(*param_values))

    logger.info("Sweep: %d combinations", len(combinations))
    logger.info("Parameters: %s", param_names)
    logger.info("Ground truth: %d IDs mapped", len(id_mapping))

    results = []
    for combo in combinations:
        params = dict(zip(param_names, combo))
        label = f"{params.get('reid_model', 'repvgg')}_t{params.get('reid_match_threshold', 0.7)}_{params.get('gallery_strategy', 'first_only')}"

        run_dir = output_base / label
        # Clean previous run
        if run_dir.exists():
            shutil.rmtree(run_dir)
        run_dir.mkdir(parents=True)

        match_log_path = run_pipeline(
            input_video=args.input,
            output_dir=run_dir,
            reid_model=params.get("reid_model", "repvgg"),
            reid_match_threshold=params.get("reid_match_threshold", 0.7),
            gallery_strategy=params.get("gallery_strategy", "first_only"),
            extra_args=extra_args,
        )

        # Evaluate
        if match_log_path.exists():
            entries = load_match_log(str(match_log_path))
            metrics = evaluate(entries, id_mapping)
            metrics["run_label"] = label
            results.append(metrics)
            append_csv(csv_path, label, metrics)
            logger.info(
                "  -> Precision: %.4f, Fragmentation: %.2f, Switches: %d",
                metrics["precision"], metrics["fragmentation"], metrics["id_switches"],
            )
        else:
            logger.warning("  -> No match log produced!")

    # Final summary table
    print(f"\n{'='*90}")
    print("SWEEP SUMMARY")
    print(f"{'='*90}")
    print(f"{'Run Label':<45} {'Precision':>10} {'Frag':>6} {'Switches':>9} {'Assignments':>12}")
    print("-" * 90)
    for m in sorted(results, key=lambda x: -x["precision"]):
        print(f"{m['run_label']:<45} {m['precision']:>10.4f} {m['fragmentation']:>6.2f} "
              f"{m['id_switches']:>9} {m['total_assignments']:>12}")
    print(f"{'='*90}")
    print(f"\nFull results saved to: {csv_path}")


if __name__ == "__main__":
    main()
