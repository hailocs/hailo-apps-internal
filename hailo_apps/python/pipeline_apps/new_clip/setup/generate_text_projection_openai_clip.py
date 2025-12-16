#!/usr/bin/env python3
"""
Generate Text Projection Matrix for CLIP text encoder using OpenAI CLIP library.

This script extracts the text projection layer from CLIP models and saves it
as a numpy array for use in postprocessing after Hailo text encoder inference.

The text projection matrix converts the encoder's hidden state to the final
text embedding dimension and is applied after the text encoder runs.

This version uses the OpenAI CLIP library which supports both ViT and ResNet models.

Requirements:
    pip install clip-by-openai torch

Usage:
    # For CLIP ViT-B/32 (default)
    python generate_text_projection_openai_clip.py
    
    # For RN50x4 (ResNet-50 x4, 640-dim)
    python generate_text_projection_openai_clip.py --model RN50x4
    
    # For other models
    python generate_text_projection_openai_clip.py --model ViT-B/16
"""

import argparse
import numpy as np
from pathlib import Path


def generate_text_projection(model_name="ViT-B/32", output_path=None):
    """
    Extract and save text projection matrix from CLIP model.
    
    Args:
        model_name: OpenAI CLIP model name (e.g., 'RN50x4', 'ViT-B/32')
        output_path: Path to save projection. Defaults to text_projection_{model}.npy
    
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
        output_path = Path(__file__).parent / f"text_projection_{safe_model_name}.npy"
    
    print("="*80)
    print(f"Generating Text Projection Matrix for CLIP (OpenAI)")
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
    
    # Extract text projection
    print("\n[2/3] Extracting text projection layer...")
    print("      Location: model.text_projection")
    
    # The text projection is a matrix that projects from transformer width to embedding dim
    # For CLIP ViT-B/32: (512, 512) - projects 512-dim hidden state to 512-dim embedding
    # For CLIP RN50x4: (640, 640) - projects 640-dim hidden state to 640-dim embedding
    # Note: In OpenAI CLIP, text_projection is stored as a parameter (not a nn.Linear layer)
    text_projection = model.text_projection.detach().cpu().numpy()
    
    print(f"      ✓ Text projection extracted")
    print(f"      - Shape: {text_projection.shape}")
    print(f"      - Transformer width (input): {text_projection.shape[0]}")
    print(f"      - Embedding dimension (output): {text_projection.shape[1]}")
    print(f"      - Data type: {text_projection.dtype}")
    print(f"      - Memory: {text_projection.nbytes / (1024 * 1024):.2f} MB")
    
    # Verify expected dimensions for common CLIP models
    expected_dims = {
        "RN50": (1024, 1024),
        "RN101": (512, 512),
        "RN50x4": (640, 640),
        "RN50x16": (768, 768),
        "RN50x64": (1024, 1024),
        "ViT-B/32": (512, 512),
        "ViT-B/16": (512, 512),
        "ViT-L/14": (768, 768),
        "ViT-L/14@336px": (768, 768),
    }
    
    if model_name in expected_dims:
        expected = expected_dims[model_name]
        if text_projection.shape != expected:
            print(f"      ⚠ Warning: Expected shape {expected}, got {text_projection.shape}")
        else:
            print(f"      ✓ Shape matches expected dimensions for {model_name}")
    
    # Important note about matrix orientation
    print("\n      ℹ️  Note: OpenAI CLIP stores text_projection as (width, embed_dim)")
    print("          In postprocessing, use: output @ text_projection")
    print("          (No transpose needed for OpenAI CLIP format)")
    
    # Save to file
    print(f"\n[3/3] Saving text projection to {output_path}...")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    np.save(output_path, text_projection)
    file_size_kb = output_path.stat().st_size / 1024
    print(f"      ✓ Saved successfully ({file_size_kb:.1f} KB)")
    
    print("\n" + "="*80)
    print("✓ Text projection matrix generated successfully!")
    print("="*80)
    print(f"\nFile: {output_path}")
    print(f"Shape: {text_projection.shape}")
    print(f"Size: {file_size_kb:.1f} KB")
    print(f"\nUsage in clip_text_utils.py:")
    print(f"  This matrix is applied in postprocessing AFTER Hailo text encoder inference:")
    print(f"  1. Extract EOT token position from encoder output")
    print(f"  2. Apply projection: final_embedding = encoder_output @ text_projection")
    print(f"  3. L2 normalize the result")
    print(f"\n  Note: OpenAI CLIP format doesn't need .T transpose!")
    
    return True


def main():
    parser = argparse.ArgumentParser(
        description="Generate CLIP text projection matrix using OpenAI CLIP library (supports ResNet models)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Generate for CLIP ViT-B/32 (default, 512x512)
  python generate_text_projection_openai_clip.py
  
  # Generate for CLIP RN50x4 (ResNet-50 x4, 640x640)
  python generate_text_projection_openai_clip.py --model RN50x4
  
  # Generate for CLIP ViT-L/14 (768x768)
  python generate_text_projection_openai_clip.py --model ViT-L/14
  
  # Save to custom location
  python generate_text_projection_openai_clip.py --model RN50x4 --output /path/to/projection.npy

Supported Models:
  ResNet models:
    - RN50        (ResNet-50, 1024x1024)
    - RN101       (ResNet-101, 512x512)
    - RN50x4      (ResNet-50 x4, 640x640) ← Use this for 640-dim
    - RN50x16     (ResNet-50 x16, 768x768)
    - RN50x64     (ResNet-50 x64, 1024x1024)
  
  Vision Transformer models:
    - ViT-B/32    (ViT Base patch32, 512x512) [default]
    - ViT-B/16    (ViT Base patch16, 512x512)
    - ViT-L/14    (ViT Large patch14, 768x768)
    - ViT-L/14@336px (ViT Large patch14 high-res, 768x768)

Note:
  The text projection is applied AFTER the Hailo text encoder inference,
  not inside the HEF model. It's part of the Python postprocessing.
  
  OpenAI CLIP stores text_projection in shape (width, embed_dim), so you
  use it as: output @ text_projection (no transpose needed).
        """
    )
    
    parser.add_argument(
        "--model",
        type=str,
        default="ViT-B/32",
        help="OpenAI CLIP model name (default: ViT-B/32). Use 'RN50x4' for 640-dim"
    )
    
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Output path for text projection .npy file (default: ./text_projection_{model}.npy)"
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
    
    success = generate_text_projection(args.model, output_path)
    
    if not success:
        return 1
    
    print("\n✓ Done! You can now use this text projection with:")
    print("  - text_encoding_postprocessing() in clip_text_utils.py")
    print("  - run_text_encoder_inference() for complete pipeline")
    
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
