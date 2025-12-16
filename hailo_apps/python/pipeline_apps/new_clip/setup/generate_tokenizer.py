#!/usr/bin/env python3
"""
Generate CLIP Tokenizer JSON file.

This script downloads the CLIP tokenizer from HuggingFace and saves it locally
as a JSON file for use with the Hailo CLIP text encoder.

The tokenizer converts text strings to token IDs (integer sequences).
This is a one-time setup - once generated, the tokenizer file can be reused.

Requirements:
    pip install tokenizers

Usage:
    python generate_tokenizer.py
    
    # Or save to custom location
    python generate_tokenizer.py --output /path/to/tokenizer.json
"""

import argparse
from pathlib import Path


def generate_tokenizer(model_name="openai/clip-vit-base-patch32", output_path=None):
    """
    Download CLIP tokenizer from HuggingFace and save locally.
    
    Args:
        model_name: HuggingFace model name (default: openai/clip-vit-base-patch32)
        output_path: Path to save tokenizer. Defaults to clip_tokenizer.json
    
    Returns:
        True if successful, False otherwise
    """
    try:
        from tokenizers import Tokenizer
    except ImportError:
        print("❌ Error: tokenizers package is required!")
        print("\nInstall with:")
        print("  pip install tokenizers")
        return False
    
    if output_path is None:
        output_path = Path(__file__).parent / "clip_tokenizer.json"
    
    print("="*80)
    print("Generating CLIP Tokenizer")
    print("="*80)
    print(f"Model: {model_name}")
    print(f"Output: {output_path}")
    print()
    
    # Download tokenizer from HuggingFace
    print("[1/2] Downloading CLIP tokenizer from HuggingFace...")
    print(f"      Model: {model_name}")
    print("      (This may take a moment on first run)")
    
    try:
        tokenizer = Tokenizer.from_pretrained(model_name)
    except Exception as e:
        print(f"❌ Failed to download tokenizer: {e}")
        return False
    
    print("      ✓ Tokenizer downloaded successfully")
    
    # Get tokenizer info
    vocab_size = tokenizer.get_vocab_size()
    print(f"      - Vocabulary size: {vocab_size}")
    
    # Save to file
    print(f"\n[2/2] Saving tokenizer to {output_path}...")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tokenizer.save(str(output_path))
    
    file_size_kb = output_path.stat().st_size / 1024
    print(f"      ✓ Saved successfully ({file_size_kb:.1f} KB)")
    
    # Test the tokenizer
    print("\n[Test] Testing tokenizer with example text...")
    test_text = "A photo of a cat"
    encoding = tokenizer.encode(test_text)
    token_ids = encoding.ids[:10]  # First 10 tokens
    
    print(f"      Text: '{test_text}'")
    print(f"      Token IDs (first 10): {token_ids}")
    print(f"      ✓ Tokenizer working correctly")
    
    print("\n" + "="*80)
    print("✓ Tokenizer generated successfully!")
    print("="*80)
    print(f"\nFile: {output_path}")
    print(f"Size: {file_size_kb:.1f} KB")
    print(f"Vocabulary size: {vocab_size}")
    print(f"\nUsage:")
    print(f"  The tokenizer converts: text → token_ids")
    print(f"  Then use token_embedding_lut.npy to get: token_ids → embeddings")
    
    return True


def main():
    parser = argparse.ArgumentParser(
        description="Generate CLIP tokenizer for Hailo text encoder",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Generate tokenizer for CLIP ViT-B/32 (default)
  python generate_tokenizer.py
  
  # Save to custom location
  python generate_tokenizer.py --output /path/to/tokenizer.json

Notes:
  - All CLIP ViT-B/32 variants use the same tokenizer
  - The tokenizer is ~2 MB and only needs to be generated once
  - Works with clip_vit_b_32_text_encoder.hef model
        """
    )
    
    parser.add_argument(
        "--model",
        type=str,
        default="openai/clip-vit-base-patch32",
        help="HuggingFace model name (default: openai/clip-vit-base-patch32)"
    )
    
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Output path for tokenizer JSON file (default: ./clip_tokenizer.json)"
    )
    
    args = parser.parse_args()
    
    # Convert output to Path if provided
    output_path = Path(args.output) if args.output else None
    
    success = generate_tokenizer(args.model, output_path)
    
    if not success:
        return 1
    
    print("\n✓ Done! You can now use:")
    print("  - clip_text_utils.py functions")
    print("  - python clip_app.py --input usb")
    print("\nNext step:")
    print("  - Generate token embedding LUT: python generate_token_embedding_lut.py")
    
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
