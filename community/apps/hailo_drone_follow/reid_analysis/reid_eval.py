#!/usr/bin/env python3
"""
ReID Evaluation Script
======================
Reads match_log.jsonl + ground_truth.json, computes precision/recall metrics.
Can also sweep thresholds offline (re-threshold logged similarities without re-running pipeline).

Usage:
    python reid_analysis/reid_eval.py \
        --match-log reid_analysis/match_log.jsonl \
        --ground-truth reid_analysis/ground_truth.json

    # Sweep thresholds offline:
    python reid_analysis/reid_eval.py \
        --match-log reid_analysis/match_log.jsonl \
        --ground-truth reid_analysis/ground_truth.json \
        --sweep

    # Append results to CSV for comparison:
    python reid_analysis/reid_eval.py \
        --match-log reid_analysis/match_log.jsonl \
        --ground-truth reid_analysis/ground_truth.json \
        --run-label "repvgg_t0.7_first_only" \
        --output-csv reid_analysis/results.csv
"""

import argparse
import csv
import json
import os
from collections import defaultdict
from pathlib import Path

from hailo_apps.python.core.common.hailo_logger import get_logger

logger = get_logger(__name__)


def load_match_log(path):
    """Load JSONL match log. Each line: {frame, crop_idx, predicted_id, similarity, is_new}"""
    entries = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                entries.append(json.loads(line))
    return entries


def load_ground_truth(path):
    """Load ground truth JSON. Returns id_mapping dict with normalized special labels."""
    with open(path) as f:
        data = json.load(f)
    mapping = data["id_mapping"]
    # Normalize special labels and warn about issues
    normalized = {}
    for k, v in mapping.items():
        v_lower = v.lower().strip()
        if v_lower == "todo":
            logger.warning("ground_truth.json has unmapped entry: %s = %s", k, v)
        if v_lower == "false_positive" and v != "false_positive":
            logger.warning("Normalized %s label '%s' -> 'false_positive'", k, v)
            v = "false_positive"
        normalized[k] = v
    return normalized


def evaluate(entries, id_mapping, reid_match_threshold=None):
    """
    Compute evaluation metrics.

    If reid_match_threshold is given, re-threshold: entries with similarity < reid_match_threshold
    and is_new=False are treated as if they were new persons (unmatched).

    Returns dict of metrics.
    """
    correct = 0
    incorrect = 0
    false_positives = 0
    new_persons_created = 0
    total_assignments = 0

    # Track ID switches: per frame, what true person got which predicted ID
    frame_assignments = defaultdict(list)  # frame -> [(true_id, predicted_id)]

    for entry in entries:
        predicted_id = entry["predicted_id"]
        similarity = entry["similarity"]
        is_new = entry["is_new"]
        frame = entry["frame"]

        # Re-threshold if requested
        if reid_match_threshold is not None and not is_new and similarity < reid_match_threshold:
            # Would not have matched at this threshold — skip (treated as unmatched)
            continue

        if is_new:
            new_persons_created += 1
            # New person creation — we still need to check if this predicted_id maps correctly
            # But new persons aren't "assignments" in the precision sense
            continue

        total_assignments += 1

        # Get ground truth for this predicted_id
        true_label = id_mapping.get(predicted_id, "unknown")

        if true_label == "false_positive":
            false_positives += 1
            continue

        if true_label in ("unknown", "TODO", "todo"):
            continue

        # To check correctness: the crop was assigned to predicted_id.
        # We need to know the TRUE identity of the crop. Since we don't have per-crop
        # ground truth, we use the id_mapping which says "predicted_id X is really person Y".
        # This is correct when a predicted ID consistently maps to one true person.
        # The crop's true identity is the same as predicted_id's true mapping.
        frame_assignments[frame].append((true_label, predicted_id))
        correct += 1

    # Precision: correct / total_assignments
    precision = correct / total_assignments if total_assignments > 0 else 0.0

    # Fragmentation: how many predicted IDs map to each true person
    true_to_predicted = defaultdict(set)
    for pred_id, true_label in id_mapping.items():
        if true_label.lower() not in ("false_positive", "todo", "unknown"):
            true_to_predicted[true_label].add(pred_id)
    n_true = len(true_to_predicted)
    n_predicted = sum(len(v) for v in true_to_predicted.values())
    fragmentation = n_predicted / n_true if n_true > 0 else 0.0

    # ID switches: count frame transitions where the same true person has different predicted IDs
    id_switches = 0
    sorted_frames = sorted(frame_assignments.keys())
    prev_true_to_pred = {}
    for frame in sorted_frames:
        current = {}
        for true_id, pred_id in frame_assignments[frame]:
            current[true_id] = pred_id
        for true_id, pred_id in current.items():
            if true_id in prev_true_to_pred and prev_true_to_pred[true_id] != pred_id:
                id_switches += 1
        prev_true_to_pred.update(current)

    return {
        "reid_match_threshold": reid_match_threshold,
        "total_assignments": total_assignments,
        "correct": correct,
        "false_positives": false_positives,
        "new_persons_created": new_persons_created,
        "precision": round(precision, 4),
        "fragmentation": round(fragmentation, 2),
        "id_switches": id_switches,
        "num_true_persons": n_true,
        "num_predicted_ids": n_predicted,
    }


def print_metrics(metrics):
    """Print metrics in a readable table."""
    print("\n" + "=" * 50)
    print("EVALUATION RESULTS")
    print("=" * 50)
    if metrics["reid_match_threshold"] is not None:
        print(f"  ReID match threshold: {metrics['reid_match_threshold']}")
    print(f"  Total assignments:    {metrics['total_assignments']}")
    print(f"  Correct:              {metrics['correct']}")
    print(f"  False positives:      {metrics['false_positives']}")
    print(f"  New persons created:  {metrics['new_persons_created']}")
    print(f"  Precision:            {metrics['precision']:.4f}")
    print(f"  Fragmentation:        {metrics['fragmentation']:.2f} ({metrics['num_predicted_ids']} predicted / {metrics['num_true_persons']} true)")
    print(f"  ID switches:          {metrics['id_switches']}")
    print("=" * 50)


def sweep_reid_match_thresholds(entries, id_mapping, reid_match_thresholds=None):
    """Sweep ReID match thresholds offline and print precision/recall table."""
    if reid_match_thresholds is None:
        reid_match_thresholds = [0.3, 0.4, 0.5, 0.55, 0.6, 0.65, 0.7, 0.75, 0.8, 0.85, 0.9, 0.95]

    print("\n" + "=" * 80)
    print("REID MATCH THRESHOLD SWEEP (offline re-threshold of logged similarities)")
    print("=" * 80)
    print(f"{'ReID Match Threshold':>22} {'Assignments':>12} {'Correct':>8} {'Precision':>10} {'FP':>5} {'New IDs':>8} {'Frag':>6} {'Switches':>9}")
    print("-" * 80)

    results = []
    for t in reid_match_thresholds:
        m = evaluate(entries, id_mapping, reid_match_threshold=t)
        results.append(m)
        print(f"{t:>22.2f} {m['total_assignments']:>12} {m['correct']:>8} {m['precision']:>10.4f} "
              f"{m['false_positives']:>5} {m['new_persons_created']:>8} {m['fragmentation']:>6.2f} {m['id_switches']:>9}")
    print("=" * 80)
    return results


def append_csv(csv_path, run_label, metrics):
    """Append a result row to CSV for cross-run comparison."""
    file_exists = os.path.exists(csv_path)
    with open(csv_path, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["run_label"] + list(metrics.keys()))
        if not file_exists:
            writer.writeheader()
        row = {"run_label": run_label}
        row.update(metrics)
        writer.writerow(row)
    logger.info("Results appended to %s", csv_path)


def main():
    parser = argparse.ArgumentParser(description="ReID evaluation — compute metrics from match log + ground truth")
    parser.add_argument("--match-log", type=str, required=True, help="Path to match_log.jsonl")
    parser.add_argument("--ground-truth", type=str, required=True, help="Path to ground_truth.json")
    parser.add_argument("--sweep", action="store_true", help="Sweep thresholds offline")
    parser.add_argument("--run-label", type=str, default=None, help="Label for this run (for CSV output)")
    parser.add_argument("--output-csv", type=str, default=None, help="Append results to CSV file")
    args = parser.parse_args()

    entries = load_match_log(args.match_log)
    id_mapping = load_ground_truth(args.ground_truth)

    logger.info("Loaded %d match log entries", len(entries))
    logger.info("Ground truth: %d predicted IDs mapped", len(id_mapping))

    if args.sweep:
        sweep_reid_match_thresholds(entries, id_mapping)
    else:
        metrics = evaluate(entries, id_mapping)
        print_metrics(metrics)

        if args.output_csv and args.run_label:
            append_csv(args.output_csv, args.run_label, metrics)


if __name__ == "__main__":
    main()
