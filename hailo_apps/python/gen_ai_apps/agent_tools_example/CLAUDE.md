# Agent Tools Example

## What This App Does
An interactive CLI chat agent that uses a Hailo LLM (Qwen2.5-Coder-1.5B-Instruct) with function calling capabilities. The agent automatically discovers tool modules (files named `tool_*.py`), presents them for selection, and allows the LLM to call tools during conversations. Supports both text and voice interaction modes. Built-in tools include math operations, weather queries, RGB LED control, servo motor control, and an elevator simulator.

The agent uses context state caching to avoid re-initializing the system prompt on each startup, YAML-based tool configuration with few-shot examples, and single-turn or multi-turn conversation modes.

## Architecture
- **Type:** GenAI app (Hailo-10H only)
- **Models:** Qwen2.5-Coder-1.5B-Instruct (LLM with tool calling); Whisper-Base (voice mode only)
- **SDK:** `hailo_platform.genai` (LLM class via shared VDevice)
- **Dependencies:** `pip install -e ".[gen-ai]"` for voice mode (piper-tts, sounddevice)

## Key Files
| File | Purpose |
|------|---------|
| `agent.py` | Main `AgentApp` class: text/voice loops, query processing, tool execution, TTS integration |
| `config.py` | Configuration constants: temperature, seed, max tokens, hardware mode |
| `system_prompt.py` | System prompt construction with tool definitions and few-shot examples |
| `state_manager.py` | Context state save/load for fast startup (caches initialized LLM context) |
| `yaml_config.py` | YAML config loader for tool-specific settings and few-shot examples |
| `cli_state.py` | CLI state management utilities |
| `tool_*.py` | Auto-discovered tool modules (math, weather, RGB LED, servo, elevator) |

## How It Works
1. Discover tool modules from `tool_*.py` files in the app directory
2. User selects a tool (interactive menu or `--tool <name>`)
3. Initialize LLM with system prompt containing tool schema in OpenAI function calling format
4. Load cached context state if available; otherwise build fresh context with system prompt and few-shot examples
5. For each user query: add to context, stream LLM response, check for `<tool_call>` XML tags
6. If tool call detected: parse function name and arguments, execute tool's `run()` function, display result
7. In multi-turn mode, tool results are fed back to the LLM for verbal response generation
8. Voice mode adds Whisper STT input and Piper TTS output with streaming sentence chunking

## Common Use Cases
- Voice-controlled hardware (LED, servo) on Raspberry Pi
- Building custom tool-calling agents for edge AI
- Prototyping function calling with small LLMs
- Template for creating new tools (copy `tool_TEMPLATE.py`)

## How to Extend
- Create new tools: copy `tool_TEMPLATE.py` to `tool_<name>.py`, implement `name`, `description`, `schema`, and `run()` function
- Add YAML config: create `<tool_name>/config.yaml` with few-shot examples and custom settings
- Change LLM: provide `--hef-path <model>` for a different model
- Enable voice: add `--voice` flag; disable TTS with `--no-tts`
- Multi-turn conversations: use `--multi-turn` to preserve context between queries
- Skip cache: use `--no-cache` to force fresh context initialization

## Related Apps
| App | When to use instead |
|-----|-------------------|
| `voice_assistant` | Need simple voice Q&A without tool calling |
| `simple_llm_chat` | Just want to test basic LLM text generation |
| `hailo_ollama` | Need Ollama-compatible REST API for integration with web UIs |
