# CLIP Text Encoder Setup

This directory contains utilities for CLIP text encoding with Hailo hardware acceleration.

## Quick Start


## Required Files (One-Time Setup)

The scripts to generate the tokenizer, token embedding LUT, and text projection matrix are no longer included in this repository.

You must obtain the following files yourself and place them in the `setup/` directory:
- `clip_tokenizer.json` (CLIP tokenizer)
- `token_embedding_lut.npy` (Token embedding lookup table)
- `text_projection.npy` (Text projection matrix)

Refer to the official OpenAI CLIP and HuggingFace documentation for instructions on how to generate or download these files:
- [OpenAI CLIP GitHub](https://github.com/openai/CLIP)
- [HuggingFace Transformers Documentation](https://huggingface.co/docs/transformers/model_doc/clip)
- [CLIP Tokenizer Info](https://huggingface.co/openai/clip-vit-base-patch32)

Once you have these files, place them in the `setup/` directory or update your code to point to their location.

**This repository no longer provides scripts for generating these files.**


### Generate Sample Embeddings JSON Files (Optional)

After obtaining the required files above, you can create sample embeddings JSON files with pre-computed text embeddings using the provided script:

```bash
cd setup
python3 build_sample_embeddings_json.py
```

This will create **one** JSON file in the parent directory:
- **`example_embeddings.json`** - Example embeddings with entries for: cat, dog, person, car, tree, building

**Note:** This step requires:
- All three files listed above must be present
- A valid Hailo text encoder HEF file
- The `hailo_platform` package installed


### Use the Text Encoder

Once the required files are present, you can use them:

```python
from clip_text_utils import prepare_text_for_hailo_encoder

# Prepare text for Hailo text encoder
result = prepare_text_for_hailo_encoder("A photo of a cat")

# Get the embeddings ready for HEF model
token_embeddings = result['token_embeddings']  # Shape: (1, 77, 512)
last_token_position = result['last_token_position']  # For postprocessing
```

Or run the complete pipeline with inference:

```python
from clip_text_utils import run_text_encoder_inference

# Run inference on Hailo hardware
# IMPORTANT: Always provide text_projection_path!
text_features = run_text_encoder_inference(
    text="A photo of a cat",
    hef_path="clip_vit_b_32_text_encoder.hef",
    text_projection_path="setup/text_projection.npy"  # REQUIRED!
)
```

**⚠️ Important:** Always provide `text_projection_path` parameter when calling `run_text_encoder_inference()`. Without it, the embeddings will be incorrect!


### Run the CLIP Application

Once setup is complete, you can run the full CLIP application:

```bash
# Basic usage (default mode with example embeddings)
hailo-clip

# With person detection
hailo-clip --detector person

# With custom embeddings JSON
hailo-clip --json-path my_embeddings.json

# Disable runtime prompts (faster startup, uses only pre-computed embeddings)
hailo-clip --disable-runtime-prompts

# With live camera
hailo-clip --input rpi --detector person
```

The application provides:
- Interactive GUI for threshold control and text prompt editing
- Real-time video processing with CLIP inference
- Optional object detection and tracking
- Save/load embeddings from JSON files

See `README.md` for complete application usage documentation.

## File Overview


### Required Files (in `setup/` folder)

| File | Size | Purpose |
|------|------|---------|
| `setup/clip_tokenizer.json` | ~3.5 MB | Converts text → token IDs |
| `setup/token_embedding_lut.npy` | ~97 MB | Converts token IDs → embeddings |
| `setup/text_projection.npy` | ~1 MB | Projects encoder output to final embeddings |

### Generated Configuration Files (in main folder)

| File | Size | Purpose | Generator Script |
|------|------|---------|------------------|
| `example_embeddings.json` | ~200 KB | Pre-computed example embeddings (cat, dog, etc.) | `setup/build_sample_embeddings_json.py` |
| `embeddings.json` | Custom | User-defined text embeddings (created via GUI or custom script) | N/A |

**Note:** Running `build_sample_embeddings_json.py` will **overwrite** existing `example_embeddings.json`. Back up your custom embeddings before regenerating.

### Embeddings JSON Format

The JSON files follow this structure:

```json
{
  "threshold": 0.5,
  "text_prefix": "A photo of a ",
  "ensemble_template": [
    "a photo of a {}.",
    "a photo of the {}.",
    "a photo of my {}.",
    "a photo of a big {}.",
    "a photo of a small {}."
  ],
  "entries": [
    {
      "text": "cat",
      "embedding": [0.024, -0.063, ...],
      "negative": false,
      "ensemble": false
    }
  ]
}
```

- **threshold**: Minimum similarity score for matching (0.0 - 1.0)
- **text_prefix**: Prefix automatically added to text prompts
- **ensemble_template**: Multiple prompt variations for ensemble matching
- **entries**: Array of text-embedding pairs with metadata
  - **text**: The text description
  - **embedding**: 512-dim normalized embedding vector (for ViT-B/32)
  - **negative**: If true, match is inverted (useful for "not X" filtering)
  - **ensemble**: If true, uses ensemble_template variations


### Source Files

| File | Location | Purpose |
|------|----------|---------|
| `clip_text_utils.py` | Main folder | Main utilities for text encoding (load, prepare, infer) |
| `clip_app.py` | Main folder | Application entry point with argument parsing |
| `clip_pipeline.py` | Main folder | GStreamer pipeline with detection/tracking/CLIP |
| `text_image_matcher.py` | Main folder | Singleton for text-image similarity matching |
| `gui.py` | Main folder | GTK GUI for threshold control and text prompts |
| `build_sample_embeddings_json.py` | `setup/` | Script to generate sample embeddings JSON file |

## Architecture

```
Text Input ("a photo of a cat")
    ↓
[Tokenizer] (setup/clip_tokenizer.json)
    ↓ Token IDs: [49406, 320, 1125, 539, 320, 2368, 49407, 0, ...]
[Token Embedding LUT] (setup/token_embedding_lut.npy)
    ↓ Token Embeddings: (1, 77, 512)
[Hailo Text Encoder] (clip_vit_b_32_text_encoder.hef)
    ↓ Encoder Output: (1, 77, 512) hidden states
[Extract EOT Token + Text Projection] (setup/text_projection.npy)
    ↓ Projected embeddings: (1, 512)
[L2 Normalization]
    ↓ Text Features: (1, 512) normalized embeddings
    ↓
[Save to example_embeddings.json] (Optional, for runtime use)
    or
[Use directly for matching with image embeddings]
```

### Key Components

1. **Tokenizer**: Converts text to token IDs (vocabulary of 49,408 tokens)
2. **Token Embedding LUT**: Look-up table mapping token IDs to embedding vectors
3. **Hailo Text Encoder**: Runs on Hailo hardware, processes sequence of embeddings
4. **Text Projection**: Linear transformation applied to EOT token's hidden state
5. **L2 Normalization**: Normalizes embeddings for cosine similarity comparison

## Customizing Sample Embeddings

To create custom embeddings, edit `setup/build_sample_embeddings_json.py`:

```python
# Text entries for example_embeddings.json
main_text_entries = ['desk', 'keyboard', 'spinner', 'Raspberry Pi', 'Unicorn mouse pad', 'Xenomorph']

# Change to your desired text descriptions
main_text_entries = ['your', 'custom', 'text', 'descriptions', 'here']
```

Then regenerate:
```bash
cd setup
python3 build_sample_embeddings_json.py
```

Alternatively, use the GUI to create embeddings interactively at runtime (when not using `--disable-runtime-prompts`).

## Model Information

- **Model**: CLIP ViT-B/32 (default) or RN50x4
- **HuggingFace ID**: `openai/clip-vit-base-patch32` (for ViT-B/32)
- **OpenAI CLIP**: Uses OpenAI's official CLIP library for extraction
- **Vocabulary Size**: 49,408 tokens (same for all models)
- **Embedding Dimension**: 
  - ViT-B/32: 512
  - RN50x4: 640
- **Max Sequence Length**: 77 tokens

## Notes

- All setup files (tokenizer, embedding LUT, text projection) are stored in the `setup/` subfolder
- These files are extracted using OpenAI's CLIP library to ensure compatibility
- Generator scripts use `_openai_clip` suffix to indicate they use OpenAI CLIP library
- Generated files have simple names (e.g., `token_embedding_lut.npy`) for easy use
- All files only need to be generated once
- After generation, you can uninstall `transformers`, `torch`, and `clip` if desired
- The `tokenizers` package must remain installed for runtime use

## How to Extract Required Files from OpenAI CLIP

To extract the required files directly from the official OpenAI CLIP implementation (no transpose needed for text projection):

1. **Install dependencies:**
   ```bash
   pip install torch
   pip install git+https://github.com/openai/CLIP.git
   ```

2. **Extract the tokenizer, token embedding LUT, and text projection matrix:**
   - Clone the OpenAI CLIP repo or use a Python script like below:

   ```python
   import clip
   import torch
   import numpy as np
   from pathlib import Path

   model_name = "ViT-B/32"  # or e.g. "RN50x4"
   model, _ = clip.load(model_name, device="cpu")

   # Save tokenizer (uses the built-in BPE tokenizer)
   # OpenAI CLIP does not provide a JSON tokenizer file, but you can use the model's tokenizer directly in Python.

   # Save token embedding LUT
   token_embedding = model.token_embedding.weight.detach().cpu().numpy()
   np.save("token_embedding_lut.npy", token_embedding)

   # Save text projection matrix (NO transpose needed)
   text_projection = model.text_projection.detach().cpu().numpy()
   np.save("text_projection.npy", text_projection)
   ```

   - Place the resulting `.npy` files in your `setup/` directory.

3. **Note:**
   - The OpenAI CLIP tokenizer is not distributed as a standalone JSON file. You must use the tokenizer via the `clip` Python package, or use HuggingFace's tokenizer if you need a JSON file (but then you must transpose the projection matrix as described above).
   - The `.npy` files from OpenAI CLIP are ready to use with this repository (no transpose needed for text projection).

For more details, see the [OpenAI CLIP GitHub](https://github.com/openai/CLIP).

