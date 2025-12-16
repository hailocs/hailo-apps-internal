# CLIP Text Encoder Setup

This directory contains utilities for CLIP text encoding with Hailo hardware acceleration.

## Quick Start

### 1. Generate Required Files (One-Time Setup)

You need three files for the text encoder to work. All generator scripts and generated files are in the `setup/` subfolder:

```bash
cd setup

# Step 1: Generate tokenizer (text → token IDs)
python3 generate_tokenizer.py

# Step 2: Generate token embedding LUT (token IDs → embeddings)
python3 generate_token_embedding_lut_openai_clip.py

# Step 3: Generate text projection matrix (for postprocessing)
python3 generate_text_projection_openai_clip.py
```

**Requirements for generation:**
```bash
pip install tokenizers transformers torch
pip install git+https://github.com/openai/CLIP.git
```

**Note:** The generated files will be created in the `setup/` folder and automatically used by `clip_text_utils.py`.

### 2. Generate Sample Embeddings JSON Files (Optional)

After generating the required files above, you can create sample embeddings JSON files with pre-computed text embeddings:

```bash
cd setup

# Generate example_embeddings.json
python3 build_sample_embeddings_json.py
```

This will create **one** JSON file in the parent directory:

- **`example_embeddings.json`** - Example embeddings with entries for:
  - cat, dog, person, car, tree, building

**Note:** This step requires:
- All three files from Step 1 must be generated first
- A valid Hailo text encoder HEF file
- The `hailo_platform` package installed

The generated JSON file can be used as a starting point for your own custom embeddings.

### 3. Use the Text Encoder

Once the files are generated, you can use them:

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

### 4. Run the CLIP Application

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

### Generated Files (in `setup/` folder)

| File | Size | Purpose | Generator Script |
|------|------|---------|------------------|
| `setup/clip_tokenizer.json` | ~3.5 MB | Converts text → token IDs | `setup/generate_tokenizer.py` |
| `setup/token_embedding_lut.npy` | ~97 MB | Converts token IDs → embeddings | `setup/generate_token_embedding_lut_openai_clip.py` |
| `setup/text_projection.npy` | ~1 MB | Projects encoder output to final embeddings | `setup/generate_text_projection_openai_clip.py` |

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
| `generate_tokenizer.py` | `setup/` | One-time script to generate tokenizer |
| `generate_token_embedding_lut_openai_clip.py` | `setup/` | One-time script to generate embedding LUT |
| `generate_text_projection_openai_clip.py` | `setup/` | One-time script to generate text projection matrix |
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
- `clip_text_utils.py` automatically looks for files in the `setup/` folder using `DEFAULT_*_PATH` constants
- **Running `build_sample_embeddings_json.py` will overwrite existing `example_embeddings.json`** - back up custom embeddings first
- **CRITICAL**: Always provide `text_projection_path` when calling `run_text_encoder_inference()` for correct results

## Testing

Test the setup:

```bash
python3 clip_text_utils.py
```

This will verify:
1. Tokenizer loading
2. Token embedding LUT loading  
3. Text preparation pipeline
4. Batch processing

## Troubleshooting

### "Tokenizer not found"
```bash
cd setup
python3 generate_tokenizer.py
```

### "Token embeddings not found"
```bash
cd setup
python3 generate_token_embedding_lut_openai_clip.py
```

### "Text projection file not found"
```bash
cd setup
python3 generate_text_projection_openai_clip.py
```

### "example_embeddings.json was overwritten"
- **Solution**: The `build_sample_embeddings_json.py` script always overwrites the output file
- **Prevention**: Back up your custom JSON files before running the script
- **Alternative**: Modify the output filename in the script to save to a different location

### Incorrect embeddings / Low similarity scores
- **Problem**: Forgot to provide `text_projection_path` parameter
- **Solution**: Always pass `text_projection_path="setup/text_projection.npy"` to `run_text_encoder_inference()`
- **Symptom**: Cosine similarity ~0.02 instead of expected ~0.3-0.9

### Missing dependencies
```bash
# For one-time generation
pip install tokenizers transformers torch
pip install git+https://github.com/openai/CLIP.git

# For runtime (after files are generated)
pip install tokenizers hailo_platform  # Only these are needed
```
