# Simple VLM Chat

## What This App Does
A minimal example demonstrating image analysis using Hailo's Vision Language Model. The script loads a static image from the repository (`doc/images/barcode-example.png`), resizes it to 336x336, sends it to the Qwen2-VL-2B-Instruct model with the question "How many people in the image?", and prints the generated response. This is a non-interactive, single-shot example for learning the VLM API. Models are auto-downloaded on first run.

## Architecture
- **Type:** GenAI app (Hailo-10H only)
- **Models:** Qwen2-VL-2B-Instruct (VLM)
- **SDK:** `hailo_platform.genai` (VLM class with `generate_all` for single-shot generation)
- **Dependencies:** OpenCV, NumPy, Hailo Platform SDK

## Key Files
| File | Purpose |
|------|---------|
| `simple_vlm_chat.py` | Single-file example: VDevice init, VLM load, image preprocessing, prompt with image, generation, cleanup |

## How It Works
1. Parse optional `--hef-path` and `--list-models` arguments
2. Resolve VLM HEF path with auto-download (Hailo-10H only)
3. Create VDevice with shared group ID, initialize VLM
4. Load image from `doc/images/barcode-example.png`, convert BGR to RGB, resize to 336x336
5. Construct multi-modal prompt: system message + user message with `{"type": "image"}` and text question
6. Call `vlm.generate_all()` with image frame, temperature=0.1, seed=42, max_tokens=200
7. Print response and clean up resources

## Common Use Cases
- Learning the Hailo GenAI VLM API
- Verifying VLM model installation and device setup
- Starting point for building image analysis applications
- Quick test of visual question answering on Hailo-10H

## How to Extend
- Change image: modify `image_path` to load a different image
- Change question: modify the text in the user prompt content
- Add camera input: use OpenCV `VideoCapture` for live frames (see `vlm_chat` app)
- Make interactive: add a loop to ask multiple questions about the same or different images
- Add streaming: use `vlm.generate()` context manager for token-by-token output

## Related Apps
| App | When to use instead |
|-----|-------------------|
| `vlm_chat` | Need interactive real-time camera-based visual Q&A |
| `simple_llm_chat` | Need text-only LLM without image analysis |
| `simple_whisper_chat` | Need speech-to-text transcription |
