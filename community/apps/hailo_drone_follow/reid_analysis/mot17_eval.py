#!/usr/bin/env python3
"""
MOT17 ReID Gallery & Similarity Evaluation
===========================================
Evaluates ReID embedding quality using MOT17 ground-truth bounding boxes.
No detection pipeline — crops come directly from GT, isolating ReID accuracy.

Two tests:
  Test 1: Single-frame gallery (FirstOnly) — gallery built from frame 1 only
  Test 2: Enriched gallery (MultiEmbedding) — gallery updated every M frames with GT association

Only the selected gallery persons are evaluated (N-way identification).

Usage:
    # Step 1: Preview candidates (saves crops, no evaluation)
    python reid_analysis/mot17_eval.py --dataset-dir /tmp/MOT17-04-SDP/

    # Step 2: Run evaluation with chosen person IDs
    python reid_analysis/mot17_eval.py --dataset-dir /tmp/MOT17-04-SDP/ --person-ids 1,3,5,86,92
"""

import argparse
import os
import sys
import time
from pathlib import Path

import cv2
import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from hailo_apps.python.core.common.hailo_logger import get_logger, init_logging

from reid_analysis.gallery_strategies import FirstOnlyStrategy, MultiEmbeddingStrategy
from reid_analysis.reid_embedding_extractor import OSNetExtractor, RepVGG512Extractor

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# MOT17 GT loading
# ---------------------------------------------------------------------------

def load_mot17_gt(gt_path, vis_threshold=0.3):
    """
    Parse MOT17 gt.txt file.

    Returns:
        frame_annotations: dict[int, list[dict]] — frame_num -> list of {id, x, y, w, h, vis}
        person_frame_counts: dict[int, int] — person_id -> total frames visible
    """
    frame_annotations = {}
    person_frame_counts = {}

    with open(gt_path) as f:
        for line in f:
            parts = line.strip().split(",")
            if len(parts) < 9:
                continue
            frame = int(parts[0])
            pid = int(parts[1])
            x, y, w, h = float(parts[2]), float(parts[3]), float(parts[4]), float(parts[5])
            cls = int(parts[7])
            vis = float(parts[8])

            # Filter: pedestrians only, visible enough
            if cls != 1 or vis < vis_threshold:
                continue

            ann = {"id": pid, "x": int(x), "y": int(y), "w": int(w), "h": int(h), "vis": vis}
            frame_annotations.setdefault(frame, []).append(ann)
            person_frame_counts[pid] = person_frame_counts.get(pid, 0) + 1

    return frame_annotations, person_frame_counts


def extract_crop(frame_bgr, ann):
    """Crop a person from the frame using GT bbox, clipped to image bounds."""
    h_img, w_img = frame_bgr.shape[:2]
    x1 = max(0, ann["x"])
    y1 = max(0, ann["y"])
    x2 = min(w_img, ann["x"] + ann["w"])
    y2 = min(h_img, ann["y"] + ann["h"])
    if x2 <= x1 or y2 <= y1:
        return None
    return frame_bgr[y1:y2, x1:x2].copy()


def load_frame(dataset_dir, frame_num):
    """Load a frame image from the MOT17 img1/ directory."""
    path = os.path.join(dataset_dir, "img1", f"{frame_num:06d}.jpg")
    return cv2.imread(path)


# ---------------------------------------------------------------------------
# Interactive preview — save candidate crops for user review
# ---------------------------------------------------------------------------

def save_candidate_crops(dataset_dir, frame_annotations, person_frame_counts, output_dir):
    """Save frame-1 crops for all candidate persons so the user can choose."""
    candidates_dir = Path(output_dir) / "gallery_candidates"
    candidates_dir.mkdir(parents=True, exist_ok=True)

    frame1_anns = frame_annotations.get(1, [])
    if not frame1_anns:
        logger.error("No persons found in frame 1!")
        return

    frame1 = load_frame(dataset_dir, 1)
    if frame1 is None:
        logger.error("Failed to load frame 1!")
        return

    total_frames = len(frame_annotations)
    logger.info("Output directory: %s", output_dir)

    # Sort by annotation count (most visible persons first)
    frame1_person_ids = {ann["id"] for ann in frame1_anns}
    ranked = sorted(frame1_person_ids, key=lambda pid: person_frame_counts.get(pid, 0), reverse=True)

    # Save crops and draw annotated frame
    annotated = frame1.copy()
    saved_candidates = []  # (pid, w, h, frame_count)
    for pid in ranked:
        ann = next(a for a in frame1_anns if a["id"] == pid)
        crop = extract_crop(frame1, ann)
        if crop is not None and crop.shape[0] > 10 and crop.shape[1] > 10:
            crop_path = candidates_dir / f"person_{pid}.jpg"
            cv2.imwrite(str(crop_path), crop)
            count = person_frame_counts.get(pid, 0)
            saved_candidates.append((pid, crop.shape[1], crop.shape[0], count))

            # Draw bbox and label on annotated frame
            x1, y1 = ann["x"], ann["y"]
            x2, y2 = x1 + ann["w"], y1 + ann["h"]
            cv2.rectangle(annotated, (x1, y1), (x2, y2), (0, 255, 0), 2)
            label = f"ID {pid}"
            font = cv2.FONT_HERSHEY_SIMPLEX
            font_scale = 0.6
            thickness = 2
            (tw, th), _ = cv2.getTextSize(label, font, font_scale, thickness)
            cv2.rectangle(annotated, (x1, y1 - th - 6), (x1 + tw + 4, y1), (0, 255, 0), -1)
            cv2.putText(annotated, label, (x1 + 2, y1 - 4), font, font_scale, (0, 0, 0), thickness)

    # Save annotated frame
    annotated_path = Path(output_dir) / "candidates_frame1.jpg"
    cv2.imwrite(str(annotated_path), annotated)

    # Print compact summary
    logger.info("Saved %d candidates to %s/", len(saved_candidates), candidates_dir)
    header = f"  {'ID':>4}  {'Size':>9}  {'Visible':>14}"
    logger.info(header)
    for pid, w, h, count in saved_candidates:
        logger.info("  %4d  %4dx%-4d  %4d/%d frames", pid, w, h, count, total_frames)
    logger.info("Annotated frame: %s", annotated_path)
    logger.info("Review and re-run with --person-ids, e.g.:")
    logger.info(
        "  python %s --dataset-dir %s --person-ids %s",
        sys.argv[0], dataset_dir, ",".join(str(p) for p in ranked[:4]),
    )


# ---------------------------------------------------------------------------
# Embedding precomputation
# ---------------------------------------------------------------------------

def precompute_embeddings(extractor, dataset_dir, frame_annotations, person_ids, skip_frames=1):
    """
    Precompute embeddings for selected persons across all frames.

    Returns:
        cache: dict[(frame_num, person_id)] -> np.ndarray (L2-normalized embedding)
    """
    person_id_set = set(person_ids)
    cache = {}
    frames = sorted(frame_annotations.keys())
    total_crops = 0
    t0 = time.time()

    for frame_num in frames:
        if skip_frames > 1 and frame_num > 1 and (frame_num - 1) % skip_frames != 0:
            continue

        anns = [a for a in frame_annotations[frame_num] if a["id"] in person_id_set]
        if not anns:
            continue

        frame_bgr = load_frame(dataset_dir, frame_num)
        if frame_bgr is None:
            continue

        crops = []
        valid_anns = []
        for ann in anns:
            crop = extract_crop(frame_bgr, ann)
            if crop is not None:
                crops.append(crop)
                valid_anns.append(ann)

        if not crops:
            continue

        embeddings = extractor.extract_embeddings_batch(crops)
        for ann, emb in zip(valid_anns, embeddings):
            cache[(frame_num, ann["id"])] = emb
            total_crops += 1

        if frame_num % 200 == 0:
            logger.info("  Frame %d/%d, %d crops extracted...", frame_num, frames[-1], total_crops)

    elapsed = time.time() - t0
    logger.info("  Precomputed %d embeddings in %.1fs", total_crops, elapsed)
    return cache


# ---------------------------------------------------------------------------
# Cached evaluation
# ---------------------------------------------------------------------------

def evaluate_cached(embedding_cache, frame_annotations, gallery_person_ids,
                    strategy_factory, reid_match_threshold, update_interval=None, skip_frames=1):
    """
    Evaluate ReID matching using precomputed embeddings.
    Only evaluates crops of gallery persons — pure N-way identification.

    Returns: dict with precision, recall, f1, tp, fp, fn
    """
    gallery = strategy_factory()
    person_id_set = set(gallery_person_ids)
    person_id_strs = {pid: str(pid) for pid in gallery_person_ids}

    # Build gallery from frame 1
    for pid in gallery_person_ids:
        key = (1, pid)
        if key not in embedding_cache:
            continue
        gallery.add_person(str(pid), embedding_cache[key])

    tp, fp, fn = 0, 0, 0
    frames = sorted(set(f for f, _ in embedding_cache.keys()))
    frames = [f for f in frames if f > 1]

    frames_processed = 0
    for frame_num in frames:
        frames_processed += 1

        # Only evaluate gallery persons visible in this frame
        for pid in gallery_person_ids:
            key = (frame_num, pid)
            if key not in embedding_cache:
                continue

            emb = embedding_cache[key]
            matched_name, sim = gallery.match(emb, reid_match_threshold)

            true_name = str(pid)
            if matched_name is not None:
                if matched_name == true_name:
                    tp += 1
                else:
                    fp += 1
            else:
                fn += 1

        # Gallery enrichment (Test 2): update every M processed frames
        if update_interval and frames_processed % update_interval == 0:
            for pid in gallery_person_ids:
                key = (frame_num, pid)
                if key in embedding_cache:
                    gallery.update(str(pid), embedding_cache[key], frame_num)

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

    return {"precision": precision, "recall": recall, "f1": f1, "tp": tp, "fp": fp, "fn": fn}


# ---------------------------------------------------------------------------
# Threshold sweep
# ---------------------------------------------------------------------------

def sweep_reid_match_thresholds(embedding_cache, frame_annotations, gallery_person_ids,
                                strategy_factory, update_interval=None, skip_frames=1):
    """Sweep ReID match thresholds and return results for each."""
    reid_match_thresholds = [round(t, 2) for t in np.arange(0.30, 0.96, 0.05)]
    results = []
    for t in reid_match_thresholds:
        metrics = evaluate_cached(
            embedding_cache, frame_annotations, gallery_person_ids,
            strategy_factory, reid_match_threshold=t,
            update_interval=update_interval, skip_frames=skip_frames,
        )
        metrics["reid_match_threshold"] = t
        results.append(metrics)
    return results


def find_best_f1(sweep_results):
    """Return the result with highest F1 from a sweep."""
    return max(sweep_results, key=lambda r: r["f1"])


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def print_sweep_table(title, sweep_results):
    """Print a formatted ReID match threshold sweep table."""
    print(f"\n{title}")
    print(f"{'ReID Match Threshold':>22} {'Precision':>10} {'Recall':>10} {'F1':>10} {'TP':>8} {'FP':>8} {'FN':>8}")
    print("-" * 88)
    for r in sweep_results:
        print(f"{r['reid_match_threshold']:>22.2f} {r['precision']:>10.4f} {r['recall']:>10.4f} "
              f"{r['f1']:>10.4f} {r['tp']:>8} {r['fp']:>8} {r['fn']:>8}")


def plot_precision_recall(sweep_t1, sweep_t2, person_ids, output_path, model_name="repvgg"):
    """Save a Precision-Recall plot comparing Test 1 vs Test 2."""
    n = len(person_ids)

    # Extract P/R pairs (sorted by recall ascending for a proper PR curve)
    def pr_pairs(sweep):
        pairs = [(r["recall"], r["precision"], r["reid_match_threshold"]) for r in sweep]
        pairs.sort(key=lambda x: x[0])
        return pairs

    pairs_t1 = pr_pairs(sweep_t1)
    pairs_t2 = pr_pairs(sweep_t2)

    fig, axes = plt.subplots(1, 2, figsize=(14, 5))

    # --- Left: Precision-Recall curve ---
    ax = axes[0]
    ax.plot([p[0] for p in pairs_t1], [p[1] for p in pairs_t1],
            "o-", color="tab:blue", label="Test 1: FirstOnly", markersize=4)
    ax.plot([p[0] for p in pairs_t2], [p[1] for p in pairs_t2],
            "s-", color="tab:orange", label="Test 2: MultiEmbedding", markersize=4)
    for recall, precision, reid_thresh in pairs_t1:
        ax.annotate(f"{reid_thresh:.2f}", (recall, precision), textcoords="offset points",
                    xytext=(4, 4), fontsize=6, color="tab:blue", alpha=0.8)
    for recall, precision, reid_thresh in pairs_t2:
        ax.annotate(f"{reid_thresh:.2f}", (recall, precision), textcoords="offset points",
                    xytext=(4, -8), fontsize=6, color="tab:orange", alpha=0.8)
    ax.set_xlabel("Recall")
    ax.set_ylabel("Precision")
    ax.set_title(f"Precision-Recall Curve (N={n}, {model_name})")
    ax.set_xlim(0, 1.05)
    ax.set_ylim(0.5, 1.02)
    ax.legend(loc="lower left")
    ax.grid(True, alpha=0.3)

    # --- Right: P, R, F1 vs ReID Match Threshold ---
    ax = axes[1]
    reid_match_thresholds = [r["reid_match_threshold"] for r in sweep_t1]

    ax.plot(reid_match_thresholds, [r["precision"] for r in sweep_t1],
            "o--", color="tab:blue", label="T1 Precision", markersize=3, alpha=0.7)
    ax.plot(reid_match_thresholds, [r["recall"] for r in sweep_t1],
            "^--", color="tab:blue", label="T1 Recall", markersize=3, alpha=0.7)
    ax.plot(reid_match_thresholds, [r["f1"] for r in sweep_t1],
            "s-", color="tab:blue", label="T1 F1", markersize=4)

    ax.plot(reid_match_thresholds, [r["precision"] for r in sweep_t2],
            "o--", color="tab:orange", label="T2 Precision", markersize=3, alpha=0.7)
    ax.plot(reid_match_thresholds, [r["recall"] for r in sweep_t2],
            "^--", color="tab:orange", label="T2 Recall", markersize=3, alpha=0.7)
    ax.plot(reid_match_thresholds, [r["f1"] for r in sweep_t2],
            "s-", color="tab:orange", label="T2 F1", markersize=4)

    ax.set_xlabel("ReID Match Threshold")
    ax.set_ylabel("Score")
    ax.set_title(f"Metrics vs ReID Match Threshold (N={n}, {model_name})")
    ax.set_xlim(0.25, 1.0)
    ax.set_ylim(0, 1.05)
    ax.legend(loc="center left", fontsize=7, ncol=2)
    ax.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(str(output_path), dpi=150)
    plt.close()
    logger.info("Plot saved: %s", output_path)


def print_summary(person_ids, best_t1, best_t2):
    """Print comparison summary for one N value."""
    n = len(person_ids)
    print(f"\n  N={n:>2}  persons={person_ids}")
    print(f"    Test 1 (FirstOnly):       P={best_t1['precision']:.4f}  R={best_t1['recall']:.4f}  "
          f"F1={best_t1['f1']:.4f}  (reid_match_threshold={best_t1['reid_match_threshold']:.2f})")
    print(f"    Test 2 (MultiEmbedding):  P={best_t2['precision']:.4f}  R={best_t2['recall']:.4f}  "
          f"F1={best_t2['f1']:.4f}  (reid_match_threshold={best_t2['reid_match_threshold']:.2f})")
    dp = best_t2["precision"] - best_t1["precision"]
    dr = best_t2["recall"] - best_t1["recall"]
    df = best_t2["f1"] - best_t1["f1"]
    print(f"    Delta:                    dP={dp:+.4f}  dR={dr:+.4f}  dF1={df:+.4f}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    init_logging()

    parser = argparse.ArgumentParser(
        description="MOT17 ReID Gallery & Similarity Evaluation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--dataset-dir", type=str, required=True,
                        help="Path to MOT17 sequence dir (e.g., /tmp/MOT17-04-SDP/)")
    parser.add_argument("--reid-model", type=str, choices=["repvgg", "osnet"], default="repvgg",
                        help="ReID model (default: repvgg)")
    parser.add_argument("--person-ids", type=str, default=None,
                        help="Comma-separated person IDs for gallery (e.g., 1,3,5,86). "
                             "If omitted, saves candidate crops for review.")
    parser.add_argument("--top-n", type=int, default=None,
                        help="Auto-select top N persons from frame 1 by frame count "
                             "and run evaluation. Mutually exclusive with --person-ids.")
    parser.add_argument("--vis-threshold", type=float, default=0.3,
                        help="Minimum visibility for GT annotations (default: 0.3)")
    parser.add_argument("--update-interval", type=int, default=30,
                        help="Frames between gallery updates for Test 2 (default: 30)")
    parser.add_argument("--max-k", type=int, default=20,
                        help="Max embeddings per person in MultiEmbedding (default: 20)")
    parser.add_argument("--skip-frames", type=int, default=1,
                        help="Process every Nth frame (default: 1 = all frames)")
    parser.add_argument("--output-dir", type=str, default=None,
                        help="Output directory (default: reid_analysis/mot17_results/)")
    args = parser.parse_args()

    dataset_dir = args.dataset_dir
    gt_path = os.path.join(dataset_dir, "gt", "gt.txt")
    if not os.path.isfile(gt_path):
        logger.error("GT file not found: %s", gt_path)
        sys.exit(1)

    output_dir = args.output_dir or str(Path(__file__).resolve().parent / "mot17_results")

    # Load GT
    logger.info("Loading GT from %s (vis >= %.1f)...", gt_path, args.vis_threshold)
    frame_annotations, person_frame_counts = load_mot17_gt(gt_path, args.vis_threshold)
    total_anns = sum(len(v) for v in frame_annotations.values())
    logger.info(
        "  %d frames, %d annotations, %d unique persons",
        len(frame_annotations), total_anns, len(person_frame_counts),
    )

    # --- Resolve person IDs ---
    if args.person_ids and args.top_n:
        logger.error("--person-ids and --top-n are mutually exclusive.")
        sys.exit(1)

    if args.top_n is not None:
        frame1_ids = {a["id"] for a in frame_annotations.get(1, [])}
        ranked = sorted(frame1_ids, key=lambda pid: person_frame_counts.get(pid, 0), reverse=True)
        person_ids = ranked[:args.top_n]
        if len(person_ids) < args.top_n:
            logger.warning("Requested top %d but only %d persons in frame 1", args.top_n, len(person_ids))
        logger.info("Auto-selected top %d persons by frame count: %s", len(person_ids), person_ids)
    elif args.person_ids is not None:
        person_ids = [int(x.strip()) for x in args.person_ids.split(",")]
    else:
        logger.info("No --person-ids or --top-n specified. Saving candidate crops from frame 1...")
        save_candidate_crops(dataset_dir, frame_annotations, person_frame_counts, output_dir)
        return
    logger.info("Evaluating %d persons: %s", len(person_ids), person_ids)
    logger.info("Output directory: %s", output_dir)

    # Validate person IDs exist in frame 1
    frame1_ids = {a["id"] for a in frame_annotations.get(1, [])}
    missing = [pid for pid in person_ids if pid not in frame1_ids]
    if missing:
        logger.error("Person IDs %s not found in frame 1. Available: %s", missing, sorted(frame1_ids))
        sys.exit(1)

    # Init ReID extractor
    logger.info("Loading ReID model: %s", args.reid_model)
    if args.reid_model == "repvgg":
        extractor = RepVGG512Extractor()
    else:
        extractor = OSNetExtractor()
    logger.info("  Model: %s, dim=%d", extractor.model_name, extractor.embedding_dim)

    # Precompute embeddings for selected persons only
    logger.info("Precomputing embeddings (skip_frames=%d)...", args.skip_frames)
    embedding_cache = precompute_embeddings(
        extractor, dataset_dir, frame_annotations, person_ids,
        skip_frames=args.skip_frames,
    )
    extractor.release()

    # --- Test 1: Single-frame gallery (FirstOnly) ---
    print("\n" + "=" * 76)
    print("Test 1: Single-frame gallery (FirstOnly)")
    print("=" * 76)
    sweep_t1 = sweep_reid_match_thresholds(
        embedding_cache, frame_annotations, person_ids,
        strategy_factory=FirstOnlyStrategy,
        skip_frames=args.skip_frames,
    )
    print_sweep_table("Test 1 — ReID Match Threshold Sweep", sweep_t1)
    best_t1 = find_best_f1(sweep_t1)

    # --- Test 2: Enriched gallery (MultiEmbedding) ---
    print("\n" + "=" * 76)
    print(f"Test 2: Enriched gallery (MultiEmbedding max_k={args.max_k}, "
          f"update every {args.update_interval} frames)")
    print("=" * 76)
    sweep_t2 = sweep_reid_match_thresholds(
        embedding_cache, frame_annotations, person_ids,
        strategy_factory=lambda: MultiEmbeddingStrategy(max_k=args.max_k),
        update_interval=args.update_interval,
        skip_frames=args.skip_frames,
    )
    print_sweep_table("Test 2 — ReID Match Threshold Sweep", sweep_t2)
    best_t2 = find_best_f1(sweep_t2)

    # --- Plot ---
    plot_path = Path(output_dir) / f"pr_plot_N{len(person_ids)}_{args.reid_model}.png"
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    plot_precision_recall(sweep_t1, sweep_t2, person_ids, plot_path, model_name=args.reid_model)
    logger.info("Created %s", plot_path)

    # --- Summary ---
    print("\n" + "=" * 76)
    print("SUMMARY")
    print("=" * 76)
    print_summary(person_ids, best_t1, best_t2)
    print()


if __name__ == "__main__":
    main()
