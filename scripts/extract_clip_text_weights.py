"""Offline (one-time) extraction of CLIP ViT-B/32 text-encoder body weights.

NOT part of the runtime pipeline. The yolo_world app consumes the prebuilt
``clip_text_vitb32_body_fp16.npz`` resource at runtime via numpy only — torch
and transformers are not imported by the app. This script is the *build-side*
producer of that resource; run it only when you need to regenerate the npz
(e.g. upstream CLIP weights change, or to validate the encoder body bit-for-
bit against HuggingFace).

Produces:
  - clip_text_vitb32_body_fp16.npz  (12 transformer layers + positional emb +
    final LayerNorm; token embedding + projection are reused from the repo's
    existing shared CLIP resources, so they're intentionally excluded here)
  - clip_text_vitb32_meta.json

Usage:
    pip install torch transformers   # build-time only
    python scripts/extract_clip_text_weights.py \\
        --out-dir /usr/local/hailo/resources/npy
"""
import argparse
import json
from pathlib import Path

import numpy as np

CLIP_MODEL = "openai/clip-vit-base-patch32"


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args()
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)

    from transformers import CLIPTextModelWithProjection

    model = CLIPTextModelWithProjection.from_pretrained(CLIP_MODEL).eval()
    sd = model.state_dict()
    tm = "text_model."

    w = {}

    def put(key, t):
        w[key] = t.detach().cpu().numpy().astype(np.float16)

    # Body only — token_embedding + text_projection are reused from repo resources.
    put("position_embedding", sd[tm + "embeddings.position_embedding.weight"])
    put("final_ln_w", sd[tm + "final_layer_norm.weight"])
    put("final_ln_b", sd[tm + "final_layer_norm.bias"])
    for i in range(model.config.num_hidden_layers):
        p = f"{tm}encoder.layers.{i}."
        put(f"l{i}.ln1_w", sd[p + "layer_norm1.weight"])
        put(f"l{i}.ln1_b", sd[p + "layer_norm1.bias"])
        put(f"l{i}.q_w", sd[p + "self_attn.q_proj.weight"])
        put(f"l{i}.q_b", sd[p + "self_attn.q_proj.bias"])
        put(f"l{i}.k_w", sd[p + "self_attn.k_proj.weight"])
        put(f"l{i}.k_b", sd[p + "self_attn.k_proj.bias"])
        put(f"l{i}.v_w", sd[p + "self_attn.v_proj.weight"])
        put(f"l{i}.v_b", sd[p + "self_attn.v_proj.bias"])
        put(f"l{i}.o_w", sd[p + "self_attn.out_proj.weight"])
        put(f"l{i}.o_b", sd[p + "self_attn.out_proj.bias"])
        put(f"l{i}.ln2_w", sd[p + "layer_norm2.weight"])
        put(f"l{i}.ln2_b", sd[p + "layer_norm2.bias"])
        put(f"l{i}.fc1_w", sd[p + "mlp.fc1.weight"])
        put(f"l{i}.fc1_b", sd[p + "mlp.fc1.bias"])
        put(f"l{i}.fc2_w", sd[p + "mlp.fc2.weight"])
        put(f"l{i}.fc2_b", sd[p + "mlp.fc2.bias"])

    np.savez_compressed(out / "clip_text_vitb32_body_fp16.npz", **w)
    # The big .npz is a downloaded resource (--out-dir → S3 resources/npy/).
    # meta is tiny architecture config that ships in-package, so write it next
    # to the encoder module to keep the committed copy in sync on regeneration.
    meta = dict(n_layers=model.config.num_hidden_layers, hidden=model.config.hidden_size,
                heads=model.config.num_attention_heads, ln_eps=model.config.layer_norm_eps)
    meta_dst = Path(__file__).parent / "clip_text_vitb32_meta.json"
    meta_dst.write_text(json.dumps(meta))
    print(f"wrote {out/'clip_text_vitb32_body_fp16.npz'} (upload to S3) and {meta_dst} (commit); meta={meta}")


if __name__ == "__main__":
    main()
