"""Phase 0 — verify on-device CLIP text encoder is equivalent to the
HuggingFace openai/clip-vit-base-patch32 model that YOLO World was trained
against.

Three tiers from cheap to expensive:

  --tier 1  Static parity (no Hailo HW): tokenizer, token-embedding LUT, and
            text-projection matrix vs. HuggingFace weights.
  --tier 2  Runtime equivalence (needs Hailo-10H + text encoder HEF): cosine
            similarity between on-device and HF embeddings on a prompt set,
            plus pairwise similarity-matrix Frobenius distance.
  --tier 3  Repeatability sanity (needs Hailo-10H + text encoder HEF): run
            the encoder twice on the same prompts and check determinism.

Pass bars (recorded in report.json):
  tier 1: tokenizer exact match; LUT/projection max-abs < 1e-5
  tier 2: median cosine ≥ 0.99, 5th-percentile ≥ 0.97, min ≥ 0.95,
          ||M_hf − M_hailo||_F ≤ 0.1 on the pairwise similarity matrix
  tier 3: mean cosine ≥ 1 − 1e-6 across repeated runs

End-to-end (Tier 4 in the plan) lives outside this script: drive both
yolo_world.py runs (baseline vs swapped embeddings) on a fixed clip and diff
the detection JSONLs.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

import numpy as np


PROMPTS = [
    # COCO-80 sample
    "person", "bicycle", "car", "motorcycle", "airplane", "bus", "train",
    "truck", "boat", "traffic light", "cat", "dog", "horse", "umbrella",
    "cup", "fork", "knife", "bottle", "laptop", "keyboard", "cell phone",
    # Open-vocab phrases
    "coffee mug", "person on bike", "red car at night", "yellow umbrella",
    "kid wearing helmet", "stop sign at intersection", "wooden chair",
    "stack of books", "pizza on a plate",
]


# ---------------------------------------------------------------------------
# Tier 1 — static parity
# ---------------------------------------------------------------------------

def _load_hf_components():
    """Import HuggingFace CLIP — lazy so non-tier-1 runs don't need torch."""
    from transformers import AutoTokenizer, CLIPTextModelWithProjection
    tok = AutoTokenizer.from_pretrained("openai/clip-vit-base-patch32")
    model = CLIPTextModelWithProjection.from_pretrained("openai/clip-vit-base-patch32")
    model.eval()
    return tok, model


def tier1_tokenizer_parity(report):
    """Compare CLIP tokenizer output.

    HF and the repo tokenizer use different pad tokens (HF: 49407=EOT, repo: 0).
    Since the Hailo encoder is causal and we pool at the EOT position, only the
    content tokens up to and including the first EOT need to match.
    """
    from hailo_apps.python.pipeline_apps.clip.clip_text_utils import (
        load_clip_tokenizer,
        tokenize_text,
    )
    EOT = 49407
    hf_tok, _ = _load_hf_components()
    repo_tok = load_clip_tokenizer()

    content_mismatches = []
    pad_mismatches = []
    for p in PROMPTS:
        hf_ids = list(hf_tok(p, padding="max_length", max_length=77, truncation=True).input_ids)
        repo_ids = list(tokenize_text(p, repo_tok, max_length=77)["input_ids"][0].tolist())

        # Find first EOT in each and compare content up to and including it.
        try:
            hf_eot = hf_ids.index(EOT)
            repo_eot = repo_ids.index(EOT)
        except ValueError:
            content_mismatches.append({"prompt": p, "reason": "no EOT found"})
            continue

        if hf_eot != repo_eot or hf_ids[:hf_eot + 1] != repo_ids[:repo_eot + 1]:
            content_mismatches.append({
                "prompt": p,
                "hf_content": hf_ids[:hf_eot + 1],
                "repo_content": repo_ids[:repo_eot + 1],
            })

        # Track the (harmless) padding-token difference separately.
        if hf_ids[hf_eot + 1:] != repo_ids[repo_eot + 1:]:
            pad_mismatches.append(p)

    report["tokenizer"] = {
        "total": len(PROMPTS),
        "content_mismatches": content_mismatches,
        "padding_differs_count": len(pad_mismatches),
        "padding_note": (
            "HF pads with 49407 (EOT), repo pads with 0. Harmless because the "
            "Hailo encoder is causal and pooling happens at the EOT position."
        ),
        "passed": len(content_mismatches) == 0,
    }
    print(f"[tier 1] tokenizer content: "
          f"{len(PROMPTS) - len(content_mismatches)}/{len(PROMPTS)} match "
          f"(padding differs on {len(pad_mismatches)} prompts — expected)")


def tier1_lut_parity(report):
    from hailo_apps.python.pipeline_apps.clip.clip_text_utils import load_token_embeddings
    _, hf_model = _load_hf_components()
    hf_lut = hf_model.text_model.embeddings.token_embedding.weight.detach().numpy()
    repo_lut = load_token_embeddings()

    info = {
        "hf_shape": list(hf_lut.shape),
        "repo_shape": list(repo_lut.shape),
        "passed": False,
    }
    if hf_lut.shape == repo_lut.shape:
        diff = np.abs(hf_lut - repo_lut)
        info["max_abs"] = float(diff.max())
        info["mean_abs"] = float(diff.mean())
        info["frobenius"] = float(np.linalg.norm(hf_lut - repo_lut))
        info["passed"] = info["max_abs"] < 1e-5

    report["token_embedding_lut"] = info
    print(f"[tier 1] token-embedding LUT: max|Δ|={info.get('max_abs', 'N/A')}")


def tier1_projection_parity(report):
    from hailo_apps.python.pipeline_apps.clip.clip_text_utils import (
        DEFAULT_TEXT_PROJECTION_PATH,
    )
    _, hf_model = _load_hf_components()
    hf_proj = hf_model.text_projection.weight.detach().numpy()  # (out, in)
    repo_proj = np.load(DEFAULT_TEXT_PROJECTION_PATH)

    info = {
        "hf_shape": list(hf_proj.shape),
        "repo_shape": list(repo_proj.shape),
        "passed": False,
    }
    # HF stores (out, in) = (512, 512); repo stores either orientation. Try both.
    for orientation, repo_oriented in (("identity", repo_proj), ("transposed", repo_proj.T)):
        if hf_proj.shape == repo_oriented.shape:
            diff = np.abs(hf_proj - repo_oriented)
            info[f"{orientation}_max_abs"] = float(diff.max())
            info[f"{orientation}_frobenius"] = float(np.linalg.norm(hf_proj - repo_oriented))
            if float(diff.max()) < 1e-5:
                info["passed"] = True
                info["matched_orientation"] = orientation

    report["text_projection"] = info
    print(f"[tier 1] text projection: passed={info['passed']}")


# ---------------------------------------------------------------------------
# Tier 2 — runtime equivalence
# ---------------------------------------------------------------------------

def _hf_embed(prompts):
    """HF reference: CLIPTextModelWithProjection + L2 normalize."""
    import torch
    tok, model = _load_hf_components()
    with torch.no_grad():
        inputs = tok(prompts, return_tensors="pt", padding=True)
        out = model(**inputs).text_embeds  # (N, 512)
        out = out / out.norm(p=2, dim=-1, keepdim=True)
    return out.cpu().numpy().astype(np.float32)


def _hef_layer_names(hef_path):
    """Auto-detect input/output vstream layer names (they vary per recompile)."""
    from hailo_platform import HEF
    hef = HEF(hef_path)
    return (
        hef.get_input_vstream_infos()[0].name,
        hef.get_output_vstream_infos()[0].name,
    )


def _hailo_embed(prompts, hef_path):
    """On-device CLIP encoder via clip_text_utils.run_text_encoder_inference."""
    from hailo_apps.python.pipeline_apps.clip.clip_text_utils import (
        load_clip_tokenizer,
        load_token_embeddings,
        run_text_encoder_inference,
        DEFAULT_TEXT_PROJECTION_PATH,
    )
    tokenizer = load_clip_tokenizer()
    token_lut = load_token_embeddings()
    text_projection = np.load(DEFAULT_TEXT_PROJECTION_PATH)
    in_name, out_name = _hef_layer_names(hef_path)

    embs = np.zeros((len(prompts), 512), dtype=np.float32)
    for i, p in enumerate(prompts):
        e = run_text_encoder_inference(
            text=p,
            hef_path=hef_path,
            tokenizer=tokenizer,
            token_embeddings=token_lut,
            text_projection=text_projection,
            input_layer_name=in_name,
            output_layer_name=out_name,
        )  # (1, 512), already L2-normalized
        embs[i] = e[0]
    return embs


def tier2_runtime(report, hef_path):
    print(f"[tier 2] computing HF reference embeddings for {len(PROMPTS)} prompts...")
    e_hf = _hf_embed(PROMPTS)
    print(f"[tier 2] computing Hailo embeddings via {hef_path}...")
    e_hailo = _hailo_embed(PROMPTS, hef_path)

    cos = np.einsum("ij,ij->i", e_hf, e_hailo)  # both already L2-normalized
    cos = cos.astype(float)

    sim_hf = e_hf @ e_hf.T
    sim_hailo = e_hailo @ e_hailo.T
    frob = float(np.linalg.norm(sim_hf - sim_hailo))

    median = float(np.median(cos))
    p5 = float(np.percentile(cos, 5))
    minimum = float(cos.min())

    passed = median >= 0.99 and p5 >= 0.97 and minimum >= 0.95 and frob <= 0.1
    report["runtime"] = {
        "median_cosine": median,
        "p5_cosine": p5,
        "min_cosine": minimum,
        "pairwise_frobenius": frob,
        "per_prompt": [
            {"prompt": p, "cosine": float(c)} for p, c in zip(PROMPTS, cos)
        ],
        "passed": passed,
    }
    print(f"[tier 2] median={median:.4f} p5={p5:.4f} min={minimum:.4f} frob={frob:.4f} → "
          f"{'PASS' if passed else 'FAIL'}")


# ---------------------------------------------------------------------------
# Tier 3 — repeatability sanity
# ---------------------------------------------------------------------------

def tier3_repeatability(report, hef_path):
    print(f"[tier 3] running Hailo encoder twice on {len(PROMPTS)} prompts...")
    a = _hailo_embed(PROMPTS, hef_path)
    b = _hailo_embed(PROMPTS, hef_path)
    cos = np.einsum("ij,ij->i", a, b).astype(float)
    mean = float(cos.mean())
    passed = mean >= 1.0 - 1e-6
    report["repeatability"] = {
        "mean_cosine": mean,
        "min_cosine": float(cos.min()),
        "passed": passed,
    }
    print(f"[tier 3] mean cosine across reruns = {mean:.8f} → "
          f"{'PASS' if passed else 'FAIL'}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tier", type=int, choices=[1, 2, 3], action="append", required=True,
                    help="Tiers to run (repeatable, e.g. --tier 1 --tier 2)")
    ap.add_argument("--text-encoder-hef", type=str, default=None,
                    help="Path to clip_vit_b_32_text_encoder HEF (required for tiers 2/3)")
    ap.add_argument("--report", type=str, default="report.json",
                    help="Where to write the JSON report")
    args = ap.parse_args()

    tiers = set(args.tier)
    if (2 in tiers or 3 in tiers) and not args.text_encoder_hef:
        print("--text-encoder-hef is required for tiers 2/3", file=sys.stderr)
        sys.exit(2)

    report: dict = {"prompts": PROMPTS}

    if 1 in tiers:
        tier1_tokenizer_parity(report)
        tier1_lut_parity(report)
        tier1_projection_parity(report)

    if 2 in tiers:
        tier2_runtime(report, args.text_encoder_hef)

    if 3 in tiers:
        tier3_repeatability(report, args.text_encoder_hef)

    Path(args.report).write_text(json.dumps(report, indent=2))
    print(f"\nReport written to {args.report}")

    passed_keys = [k for k, v in report.items()
                   if isinstance(v, dict) and v.get("passed") is True]
    failed_keys = [k for k, v in report.items()
                   if isinstance(v, dict) and v.get("passed") is False]
    print(f"Passed: {passed_keys}")
    if failed_keys:
        print(f"Failed: {failed_keys}")
        sys.exit(1)


# ---------------------------------------------------------------------------
# CI test: static weight parity (Tier 1). Skips unless torch + transformers and
# the CLIP resources are present; runtime tiers (2/3) run via main() on a device.
# ---------------------------------------------------------------------------

def _tier1_ready():
    try:
        import torch  # noqa: F401
        import transformers  # noqa: F401
    except ImportError:
        return False
    from pathlib import Path
    from hailo_apps.python.pipeline_apps.clip.clip_text_utils import DEFAULT_TEXT_PROJECTION_PATH
    return Path(DEFAULT_TEXT_PROJECTION_PATH).exists()


def test_tier1_static_parity():
    import pytest
    if not _tier1_ready():
        pytest.skip("needs torch + transformers and the CLIP resources")
    report = {}
    tier1_lut_parity(report)
    tier1_projection_parity(report)
    assert report["token_embedding_lut"]["passed"], "token-embedding LUT must match HF bit-exactly"
    assert report["text_projection"]["passed"], "text projection must match HF"


if __name__ == "__main__":
    main()
