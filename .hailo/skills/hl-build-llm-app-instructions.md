# Skill: Create LLM Chat Application

> **When to use**: Building a text-only LLM application (chatbot, Q&A, text processor) for Hailo-10H. For vision + language, use `create-vlm-app.md` instead.

## Prerequisites

- Hailo-10H accelerator (LLM is NOT available on Hailo-8/8L)
- `hailo_platform` with `genai` module installed
- LLM HEF file (resolved via `resolve_hef_path`)

## Architecture

```
User Input → Prompt Format → LLM.generate() → Filter tokens → Output
                                    ↑
                              VDevice (shared)
```

## Step-by-Step Build

### 1. Register App Constant

In `hailo_apps/python/core/common/defines.py`:
```python
MY_LLM_APP = "my_llm_app"
```

### 2. Create Directory

```
hailo_apps/python/gen_ai_apps/my_llm_app/
├── __init__.py
├── my_llm_app.py
└── README.md
```

### 3. Key Components

**VDevice with shared group:**
```python
params = VDevice.create_params()
params.group_id = SHARED_VDEVICE_GROUP_ID
vdevice = VDevice(params)
```

**LLM initialization:**
```python
hef_path = resolve_hef_path(args.hef_path, APP_NAME, arch=HAILO10H_ARCH)
llm = LLM(vdevice, str(hef_path))
```

**Prompt format (required structure):**
```python
prompt = [
    {"role": "system", "content": [{"type": "text", "text": system_prompt}]},
    {"role": "user", "content": [{"type": "text", "text": user_input}]},
]
```

**Generate (blocking):**
```python
response = llm.generate_all(prompt=prompt, temperature=0.1, seed=42, max_generated_tokens=200)
```

**Generate (streaming):**
```python
with llm.generate(prompt=prompt, temperature=0.1, max_generated_tokens=200) as gen:
    for chunk in gen:
        if chunk != "<|im_end|>":
            print(chunk, end="", flush=True)
```

**Cleanup (CRITICAL — always in finally block):**
```python
llm.clear_context()
llm.release()
vdevice.release()
```

### 4. CLI Pattern

```python
parser = get_standalone_parser()
parser.add_argument("--max-tokens", type=int, default=200)
parser.add_argument("--temperature", type=float, default=0.1)
parser.add_argument("--system-prompt", type=str, default="You are a helpful assistant.")
handle_list_models_flag(parser, APP_NAME)
args = parser.parse_args()
```

### 5. Signal Handling

```python
running = True
def signal_handler(sig, frame):
    nonlocal running
    running = False
signal.signal(signal.SIGINT, signal_handler)
```

## Conventions

| Rule | Detail |
|---|---|
| Hailo-10H only | Use `HAILO10H_ARCH` constant |
| VDevice sharing | `params.group_id = SHARED_VDEVICE_GROUP_ID` |
| Clear context | `llm.clear_context()` after EVERY generation |
| Cleanup order | `clear_context()` → `release()` → `vdevice.release()` |
| End token | Filter `<|im_end|>` from streaming output |
| Imports | Absolute only — `from hailo_apps.python.core.common...` |
| Logging | `get_logger(__name__)` |

## Common Variants

| Variant | Differences from Base |
|---|---|
| Interactive chat | Multi-turn with conversation history |
| Batch processor | Read prompts from file, output to file |
| Structured output | Instruct LLM to reply in JSON format |
| With voice | Add `SpeechToTextProcessor` + `TextToSpeechProcessor` |

## Validation Checklist

```bash
# No relative imports
grep -rn "^from \.\|^import \." hailo_apps/python/gen_ai_apps/my_llm_app/*.py
# Should return empty

# CLI works
python -m hailo_apps.python.gen_ai_apps.my_llm_app.my_llm_app --help

# Uses logger
grep -rn "get_logger" hailo_apps/python/gen_ai_apps/my_llm_app/*.py

# Uses SHARED_VDEVICE_GROUP_ID
grep -rn "SHARED_VDEVICE_GROUP_ID" hailo_apps/python/gen_ai_apps/my_llm_app/*.py

# Cleanup in finally block
grep -rn "finally:" hailo_apps/python/gen_ai_apps/my_llm_app/*.py
```
