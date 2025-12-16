#!/usr/bin/env python3
"""
Generate Token Embedding LUT for CLIP text encoder using OpenAI CLIP library.

This script extracts the token embedding layer (Look-Up Table) from CLIP models
and saves it as a numpy array for use with the Hailo text encoder.

This version uses the OpenAI CLIP library which supports both ViT and ResNet models.

Requirements:
    pip install clip-by-openai torch

Usage:
    # For CLIP ViT-B/32 (default)
    python generate_token_embedding_lut_openai_clip.py
    
    # For RN50x4 (ResNet-50 x4, 640-dim embeddings)
    python3 generate_token_embedding_lut_openai_clip.py --model RN50x4
    
    # For other models
    python generate_token_embedding_lut_openai_clip.py --model ViT-B/16
    python generate_token_embedding_lut_openai_clip.py --model RN50
"""

import argparse
import numpy as np
from pathlib import Path


def generate_embeddings(model_name="ViT-B/32", output_path=None):
    """
    Extract and save token embeddings from CLIP model.
    
    Args:
        model_name: OpenAI CLIP model name (e.g., 'RN50x4', 'ViT-B/32')
        output_path: Path to save embeddings. Defaults to token_embedding_lut_{model}.npy
    
    Returns:
        True if successful, False otherwise
    """
    try:
        import clip
        import torch
    except ImportError:
        print("❌ Error: clip and torch are required!")
        print("\nInstall with:")
        print("  pip install clip-by-openai torch")
        return False
    
    if output_path is None:
        # Create filename based on model name
        safe_model_name = model_name.replace('/', '_').replace('-', '_')
        output_path = Path(__file__).parent / f"token_embedding_lut_{safe_model_name}.npy"
    
    print("="*80)
    print(f"Generating Token Embeddings for CLIP (OpenAI)")
    print("="*80)
    print(f"Model: {model_name}")
    print(f"Output: {output_path}")
    print()
    
    # Load the CLIP model
    print("[1/3] Loading CLIP model from OpenAI...")
    print(f"      Model: {model_name}")
    print("      (This may take a few minutes on first run - downloading model)")
    
    try:
        model, preprocess = clip.load(model_name, device="cpu")
    except Exception as e:
        print(f"❌ Failed to load model: {e}")
        print(f"\nAvailable models: {clip.available_models()}")
        return False
    
    print("      ✓ Model loaded successfully")
    
    # Extract token embeddings
    print("\n[2/3] Extracting token embedding layer (LUT)...")
    print("      Location: model.token_embedding.weight")
    
    # This is the embedding matrix: shape (vocab_size, embedding_dim)
    # For CLIP ViT-B/32: (49408, 512)
    # For CLIP RN50x4: (49408, 640)
    embeddings = model.token_embedding.weight.detach().cpu().numpy()
    
    print(f"      ✓ Embeddings extracted")
    print(f"      - Shape: {embeddings.shape}")
    print(f"      - Vocabulary size: {embeddings.shape[0]}")
    print(f"      - Embedding dimension: {embeddings.shape[1]}")
    print(f"      - Data type: {embeddings.dtype}")
    print(f"      - Memory: {embeddings.nbytes / (1024 * 1024):.1f} MB")
    
    # Verify expected dimensions for common CLIP models
    expected_dims = {
        "RN50": (49408, 1024),
        "RN101": (49408, 512),
        "RN50x4": (49408, 640),
        "RN50x16": (49408, 768),
        "RN50x64": (49408, 1024),
        "ViT-B/32": (49408, 512),
        "ViT-B/16": (49408, 512),
        "ViT-L/14": (49408, 768),
        "ViT-L/14@336px": (49408, 768),
    }
    
    if model_name in expected_dims:
        expected = expected_dims[model_name]
        if embeddings.shape != expected:
            print(f"      ⚠ Warning: Expected shape {expected}, got {embeddings.shape}")
        else:
            print(f"      ✓ Shape matches expected dimensions for {model_name}")
    
    # Save to file
    print(f"\n[3/3] Saving embeddings to {output_path}...")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    np.save(output_path, embeddings)
    file_size_mb = Path(output_path).stat().st_size / (1024 * 1024)
    print(f"      ✓ Saved successfully ({file_size_mb:.1f} MB)")
    
    print("\n" + "="*80)
    print("✓ Token embeddings generated successfully!")
    print("="*80)
    print(f"\nFile: {output_path}")
    print(f"Shape: {embeddings.shape}")
    print(f"Size: {file_size_mb:.1f} MB")
    print(f"\nUsage in clip_text_utils.py:")
    print(f"  1. Tokenizer converts: text → token_ids")
    print(f"  2. This LUT converts: token_ids → embeddings")
    print(f"  3. Hailo text encoder processes: embeddings → text features")
    
    return True


def main():
    parser = argparse.ArgumentParser(
        description="Generate CLIP token embeddings using OpenAI CLIP library (supports ResNet models)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Generate for CLIP ViT-B/32 (default, 512-dim)
  python generate_token_embedding_lut_openai_clip.py
  
  # Generate for CLIP RN50x4 (ResNet-50 x4, 640-dim)
  python generate_token_embedding_lut_openai_clip.py --model RN50x4
  
  # Generate for CLIP ViT-L/14 (768-dim)
  python generate_token_embedding_lut_openai_clip.py --model ViT-L/14
  
  # Save to custom location
  python generate_token_embedding_lut_openai_clip.py --model RN50x4 --output /path/to/embeddings.npy

Supported Models:
  ResNet models:
    - RN50        (ResNet-50, 1024-dim)
    - RN101       (ResNet-101, 512-dim)
    - RN50x4      (ResNet-50 x4, 640-dim) ← Use this for 640-dim
    - RN50x16     (ResNet-50 x16, 768-dim)
    - RN50x64     (ResNet-50 x64, 1024-dim)
  
  Vision Transformer models:
    - ViT-B/32    (ViT Base patch32, 512-dim) [default]
    - ViT-B/16    (ViT Base patch16, 512-dim)
    - ViT-L/14    (ViT Large patch14, 768-dim)
    - ViT-L/14@336px (ViT Large patch14 high-res, 768-dim)

Note: All models have 49408 vocabulary size (same tokenizer).
      Only the embedding dimension differs between models.
        """
    )
    
    parser.add_argument(
        "--model",
        type=str,
        default="ViT-B/32",
        help="OpenAI CLIP model name (default: ViT-B/32). Use 'RN50x4' for 640-dim embeddings"
    )
    
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Output path for token embedding LUT .npy file (default: ./token_embedding_lut_{model}.npy)"
    )
    
    parser.add_argument(
        "--list-models",
        action="store_true",
        help="List all available CLIP models and exit"
    )
    
    args = parser.parse_args()
    
    # List models if requested
    if args.list_models:
        try:
            import clip
            print("Available CLIP models:")
            for model in clip.available_models():
                print(f"  - {model}")
            return 0
        except ImportError:
            print("❌ Error: clip library not installed!")
            print("Install with: pip install clip-by-openai")
            return 1
    
    # Convert output to Path if provided
    output_path = Path(args.output) if args.output else None
    
    success = generate_embeddings(args.model, output_path)
    
    if not success:
        return 1
    
    print("\n✓ Done! You can now use this token embedding LUT with:")
    print("  - clip_text_utils.py (pass embeddings_path parameter)")
    print("  - python clip_app.py --input usb")
    
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
