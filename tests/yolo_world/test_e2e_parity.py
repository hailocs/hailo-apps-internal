"""Phase 0 — end-to-end parity: do HF-CLIP embeddings vs on-device-CLIP
embeddings produce equivalent detections from the YOLO World detector on
a fixed video clip?

Isolates the encoder swap by holding the detector HEF, frames, and
postprocess fixed across both runs. Reports per-frame and aggregate
precision/recall at IoU 0.5 + score MAE on matched detections.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

# Dual purpose: a manual hardware verification CLI (`main()`, needs a Hailo
# device + cv2 + the HEFs) AND a home for the pure matching-logic unit test
# below. Hardware/cv2/torch imports are lazy (inside functions) so pytest can
# collect this module and run test_match_logic in CI without those deps.

MAX_CLASSES = 80
EMBED_DIM = 512


def _pad(embs: np.ndarray) -> np.ndarray:
    """Pad (N, 512) → (1, 80, 512) float32."""
    out = np.zeros((1, MAX_CLASSES, EMBED_DIM), dtype=np.float32)
    out[0, :embs.shape[0], :] = embs
    return out


def _hf_embed(prompts):
    import torch
    from transformers import AutoTokenizer, CLIPTextModelWithProjection
    tok = AutoTokenizer.from_pretrained("openai/clip-vit-base-patch32")
    model = CLIPTextModelWithProjection.from_pretrained("openai/clip-vit-base-patch32")
    model.eval()
    with torch.no_grad():
        inputs = tok(prompts, return_tensors="pt", padding=True)
        out = model(**inputs).text_embeds  # (N, 512)
        out = out / out.norm(p=2, dim=-1, keepdim=True)
    return out.cpu().numpy().astype(np.float32)


def _hailo_embed(prompts, hef_path):
    from hailo_platform import HEF
    from hailo_apps.python.pipeline_apps.clip.clip_text_utils import (
        DEFAULT_TEXT_PROJECTION_PATH,
        load_clip_tokenizer,
        load_token_embeddings,
        run_text_encoder_inference,
    )
    tokenizer = load_clip_tokenizer()
    token_lut = load_token_embeddings()
    text_projection = np.load(DEFAULT_TEXT_PROJECTION_PATH)
    # Auto-detect vstream layer names (they vary per recompile).
    hef = HEF(hef_path)
    in_name = hef.get_input_vstream_infos()[0].name
    out_name = hef.get_output_vstream_infos()[0].name
    embs = np.zeros((len(prompts), EMBED_DIM), dtype=np.float32)
    for i, p in enumerate(prompts):
        e = run_text_encoder_inference(
            text=p,
            hef_path=hef_path,
            tokenizer=tokenizer,
            token_embeddings=token_lut,
            text_projection=text_projection,
            input_layer_name=in_name,
            output_layer_name=out_name,
        )
        embs[i] = e[0]
    return embs


def _iou(a, b):
    x1 = max(a[0], b[0]); y1 = max(a[1], b[1])
    x2 = min(a[2], b[2]); y2 = min(a[3], b[3])
    inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    aa = (a[2] - a[0]) * (a[3] - a[1])
    bb = (b[2] - b[0]) * (b[3] - b[1])
    return inter / (aa + bb - inter + 1e-9)


def _match(refs, hyps, iou_thresh=0.5):
    """Greedy IoU match within same class; return (matched_pairs, unmatched_refs, unmatched_hyps)."""
    matched = []
    used_h = set()
    refs_by_score = sorted(range(len(refs)), key=lambda i: -refs[i]["score"])
    for ri in refs_by_score:
        r = refs[ri]
        best_h, best_iou = -1, 0.0
        for hi, h in enumerate(hyps):
            if hi in used_h or h["class_id"] != r["class_id"]:
                continue
            i = _iou(r["bbox"], h["bbox"])
            if i > best_iou:
                best_iou, best_h = i, hi
        if best_h >= 0 and best_iou >= iou_thresh:
            matched.append((ri, best_h, best_iou))
            used_h.add(best_h)
    unmatched_r = [i for i in range(len(refs)) if i not in {m[0] for m in matched}]
    unmatched_h = [i for i in range(len(hyps)) if i not in used_h]
    return matched, unmatched_r, unmatched_h


def _run_video(video_path, detector_hef, text_embs_padded, num_frames, conf, prompts):
    """Run detector over the first `num_frames` of the video with the given embeddings."""
    import cv2
    from hailo_apps.python.pipeline_apps.yolo_world.postprocess import postprocess
    from hailo_apps.python.pipeline_apps.yolo_world.yolo_world_inference import YoloWorldInference

    eng = YoloWorldInference(hef_path=detector_hef, text_embeddings=text_embs_padded)
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open {video_path}")

    per_frame = []
    idx = 0
    while idx < num_frames:
        ok, frame = cap.read()
        if not ok:
            break
        # Mirror the GStreamer videoscale step: BGR → RGB then resize to 640x640
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        resized = cv2.resize(rgb, (640, 640), interpolation=cv2.INTER_LINEAR)
        outputs = eng.run(resized)
        dets = postprocess(outputs, score_threshold=conf, iou_threshold=0.7,
                           num_classes=len(prompts))
        per_frame.append(dets)
        idx += 1

    cap.release()
    eng.close()
    return per_frame


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--detector-hef", required=True)
    ap.add_argument("--text-encoder-hef", required=True)
    ap.add_argument("--video", required=True)
    ap.add_argument("--prompts-file", default=None,
                    help="JSON list of prompts. Defaults to COCO-80.")
    ap.add_argument("--frames", type=int, default=60)
    ap.add_argument("--confidence", type=float, default=0.3)
    ap.add_argument("--report", default="e2e_report.json")
    args = ap.parse_args()

    if args.prompts_file:
        prompts = json.loads(Path(args.prompts_file).read_text())
    else:
        prompts = json.loads(
            (Path(__file__).resolve().parents[1] / "default_prompts.json").read_text()
        )
    prompts = prompts[:MAX_CLASSES]

    print(f"Encoding {len(prompts)} prompts via HF CLIP (reference)...")
    e_hf = _hf_embed(prompts)
    print(f"Encoding {len(prompts)} prompts via Hailo CLIP HEF...")
    e_hailo = _hailo_embed(prompts, args.text_encoder_hef)

    print(f"Running detector over {args.frames} frames with HF embeddings...")
    refs = _run_video(args.video, args.detector_hef, _pad(e_hf), args.frames,
                      args.confidence, prompts)
    print(f"Running detector over {args.frames} frames with Hailo embeddings...")
    hyps = _run_video(args.video, args.detector_hef, _pad(e_hailo), args.frames,
                      args.confidence, prompts)

    total_ref = sum(len(f) for f in refs)
    total_hyp = sum(len(f) for f in hyps)
    matched_total = 0
    score_errors = []
    class_matches = 0

    for fr_refs, fr_hyps in zip(refs, hyps):
        matched, _, _ = _match(fr_refs, fr_hyps)
        matched_total += len(matched)
        for ri, hi, _iou_val in matched:
            class_matches += 1  # match() already enforces same class
            score_errors.append(abs(fr_refs[ri]["score"] - fr_hyps[hi]["score"]))

    recall = matched_total / total_ref if total_ref else 0.0
    precision = matched_total / total_hyp if total_hyp else 0.0
    score_mae = float(np.mean(score_errors)) if score_errors else 0.0

    summary = {
        "frames": len(refs),
        "prompts": prompts,
        "total_ref_detections": total_ref,
        "total_hyp_detections": total_hyp,
        "matched": matched_total,
        "recall": recall,
        "precision": precision,
        "score_mae_on_matched": score_mae,
        "pass_bar": {
            "recall_min": 0.92,
            "precision_min": 0.90,
            "score_mae_max": 0.05,
        },
        "passed": recall >= 0.92 and precision >= 0.90 and score_mae <= 0.05,
    }
    Path(args.report).write_text(json.dumps(summary, indent=2))

    print()
    print(f"frames                : {len(refs)}")
    print(f"detections (HF / Hailo): {total_ref} / {total_hyp}")
    print(f"matched (IoU≥0.5)     : {matched_total}")
    print(f"recall                : {recall:.4f}  (≥0.92)")
    print(f"precision             : {precision:.4f}  (≥0.90)")
    print(f"score MAE on matched  : {score_mae:.4f}  (≤0.05)")
    print(f"=> {'PASS' if summary['passed'] else 'FAIL'}")
    print(f"\nReport: {args.report}")
    sys.exit(0 if summary["passed"] else 1)


# ---------------------------------------------------------------------------
# CI unit test for the pure matching logic (no hardware/cv2/torch needed).
# The full hardware parity sweep runs via main() on a device.
# ---------------------------------------------------------------------------

def test_match_logic():
    refs = [
        {"bbox": [0.0, 0.0, 0.4, 0.4], "class_id": 0, "score": 0.9},
        {"bbox": [0.6, 0.6, 1.0, 1.0], "class_id": 1, "score": 0.8},
    ]
    # hyp[0] overlaps ref[0] (same class) → match; hyp[1] is wrong class → no match.
    hyps = [
        {"bbox": [0.02, 0.02, 0.42, 0.42], "class_id": 0, "score": 0.7},
        {"bbox": [0.6, 0.6, 1.0, 1.0], "class_id": 2, "score": 0.7},
    ]
    matched, unmatched_r, unmatched_h = _match(refs, hyps, iou_thresh=0.5)
    assert len(matched) == 1
    assert matched[0][0] == 0 and matched[0][1] == 0
    assert unmatched_r == [1]              # ref[1] class 1 unmatched
    assert sorted(unmatched_h) == [1]      # hyp[1] class 2 unmatched
    assert abs(_iou([0, 0, 1, 1], [0, 0, 1, 1]) - 1.0) < 1e-6
    assert _iou([0, 0, 1, 1], [2, 2, 3, 3]) == 0.0


if __name__ == "__main__":
    main()
