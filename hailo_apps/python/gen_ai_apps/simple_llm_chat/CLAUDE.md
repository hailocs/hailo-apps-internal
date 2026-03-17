# Simple LLM Chat

## What This App Does
A minimal example demonstrating text-based conversation with Hailo's Large Language Model. The script initializes the Hailo device, loads the Qwen2.5-1.5B-Instruct model, sends a single prompt ("Tell a short joke") with a system message, and prints the generated response. This is a non-interactive, single-shot example designed for learning the basic LLM API usage pattern. Models are auto-downloaded on first run.

## Architecture
- **Type:** GenAI app (Hailo-10H only)
- **Models:** Qwen2.5-1.5B-Instruct (LLM)
- **SDK:** `hailo_platform.genai` (LLM class with `generate_all` for single-shot generation)
- **Dependencies:** Hailo Platform SDK only (no extra pip packages needed)

## Key Files
| File | Purpose |
|------|---------|
| `simple_llm_chat.py` | Single-file example: VDevice init, LLM load, prompt construction, generation, resource cleanup |

## How It Works
1. Parse optional `--hef-path` and `--list-models` arguments
2. Resolve HEF path with auto-download (Hailo-10H only)
3. Create VDevice with shared group ID
4. Initialize LLM with model HEF
5. Construct prompt with system message ("You are a helpful assistant") and user message ("Tell a short joke")
6. Call `llm.generate_all()` with temperature=0.1, seed=42, max_tokens=200
7. Print response and clean up (release LLM context and VDevice)

## Common Use Cases
- Learning the Hailo GenAI LLM API
- Verifying LLM model installation and device setup
- Starting point for building custom LLM applications
- Quick smoke test that Hailo-10H GenAI stack is working

## How to Extend
- Change prompt: modify the `prompt` list to ask different questions
- Make interactive: add a loop with `input()` for multi-turn conversation
- Add streaming: use `llm.generate()` context manager instead of `generate_all()` for token-by-token output
- Add context management: see `gen_ai_utils/llm_utils/context_manager.py` for token tracking

## Related Apps
| App | When to use instead |
|-----|-------------------|
| `voice_assistant` | Need full interactive voice conversation |
| `agent_tools_example` | Need LLM with tool/function calling |
| `simple_vlm_chat` | Need image analysis with a Vision Language Model |
| `simple_whisper_chat` | Need speech-to-text transcription |
