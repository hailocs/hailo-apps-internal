# Toolset: Gen AI Utilities Reference

> API reference for shared gen AI utilities: LLM tools, voice processing, and agent support.

## LLM Utilities (`gen_ai_utils/llm_utils/`)

### streaming.py — Token Streaming
```python
from hailo_apps.python.gen_ai_apps.gen_ai_utils.llm_utils.streaming import (
    stream_llm_response,    # Stream and collect LLM tokens
)
```

### tool_parsing.py — Parse Tool Calls from LLM Output
```python
from hailo_apps.python.gen_ai_apps.gen_ai_utils.llm_utils.tool_parsing import (
    parse_tool_call,        # Extract tool name and args from LLM response
    is_tool_call,           # Check if response contains a tool call
)
```

### tool_execution.py — Execute Parsed Tool Calls
```python
from hailo_apps.python.gen_ai_apps.gen_ai_utils.llm_utils.tool_execution import (
    execute_tool,           # Run a tool with parsed arguments
)
```

### tool_discovery.py — Auto-Discover Tools from Directory
```python
from hailo_apps.python.gen_ai_apps.gen_ai_utils.llm_utils.tool_discovery import (
    discover_tools,         # Scan directory for tool modules
    get_tool_info,          # Get tool metadata
)
```

### tool_selection.py — Interactive Tool Selection
```python
from hailo_apps.python.gen_ai_apps.gen_ai_utils.llm_utils.tool_selection import (
    select_tool,            # Interactive tool picker
    list_available_tools,   # List all discovered tools
)
```

### context_manager.py — Conversation Context
```python
from hailo_apps.python.gen_ai_apps.gen_ai_utils.llm_utils.context_manager import (
    ContextManager,         # Manage multi-turn conversation history
)
```

### message_formatter.py — Format Messages for LLM
```python
from hailo_apps.python.gen_ai_apps.gen_ai_utils.llm_utils.message_formatter import (
    format_system_message,  # Format system prompt
    format_user_message,    # Format user input
    format_tool_result,     # Format tool execution result for LLM
)
```

### agent_utils.py — Agent Loop Helpers
```python
from hailo_apps.python.gen_ai_apps.gen_ai_utils.llm_utils.agent_utils import (
    run_agent_loop,         # Main agent reasoning loop
)
```

### terminal_ui.py — Terminal UI Components
```python
from hailo_apps.python.gen_ai_apps.gen_ai_utils.llm_utils.terminal_ui import (
    print_header,           # Print formatted header
    print_response,         # Print formatted response
    get_user_input,         # Get input with prompt
)
```

---

## Voice Processing (`gen_ai_utils/voice_processing/`)

### speech_to_text.py
```python
from hailo_apps.python.gen_ai_apps.gen_ai_utils.voice_processing.speech_to_text import SpeechToTextProcessor

stt = SpeechToTextProcessor(vdevice, whisper_hef_path)
text = stt.transcribe(audio_numpy_array)
stt.release()
```

### text_to_speech.py
```python
from hailo_apps.python.gen_ai_apps.gen_ai_utils.voice_processing.text_to_speech import TextToSpeechProcessor

tts = TextToSpeechProcessor()
tts.speak("Hello, the scene is quiet and peaceful.")
tts.stop()
```

Uses **Piper TTS** (CPU-based, lightweight). Models stored in `local_resources/piper_models/`.

### audio_recorder.py
```python
from hailo_apps.python.gen_ai_apps.gen_ai_utils.voice_processing.audio_recorder import AudioRecorder

recorder = AudioRecorder(sample_rate=16000)
audio_data = recorder.record(duration=5)  # Returns numpy array
recorder.stop()
```

### audio_player.py
```python
from hailo_apps.python.gen_ai_apps.gen_ai_utils.voice_processing.audio_player import AudioPlayer

player = AudioPlayer()
player.play(audio_numpy_array, sample_rate=22050)
player.stop()
```

### vad.py — Voice Activity Detection
```python
from hailo_apps.python.gen_ai_apps.gen_ai_utils.voice_processing.vad import VAD, add_vad_args

vad = VAD(aggressiveness=3, energy_threshold=0.005)
is_speech = vad.is_speech(audio_chunk)

# CLI args helper
add_vad_args(parser)  # Adds --vad, --vad-aggressiveness, --vad-energy-threshold
```

### interaction.py — High-Level Voice Interaction
```python
from hailo_apps.python.gen_ai_apps.gen_ai_utils.voice_processing.interaction import VoiceInteractionManager

vim = VoiceInteractionManager(
    vdevice=vdevice,
    whisper_hef_path=whisper_hef_path,
    vad_enabled=True,
    vad_aggressiveness=3,
)

user_text = vim.listen()        # Listen and transcribe
vim.speak("Response text")      # Speak response
vim.cleanup()                   # Release resources
```

### audio_diagnostics.py / audio_troubleshoot.py
```python
from hailo_apps.python.gen_ai_apps.gen_ai_utils.voice_processing.audio_diagnostics import run_diagnostics
from hailo_apps.python.gen_ai_apps.gen_ai_utils.voice_processing.audio_troubleshoot import troubleshoot_audio

run_diagnostics()    # Check audio hardware
troubleshoot_audio() # Interactive troubleshooting
```

---

## Agent Tools Framework (`agent_tools_example/tools/`)

### Tool Base Class
```python
from hailo_apps.python.gen_ai_apps.agent_tools_example.tools.base import (
    BaseTool,       # Abstract base class for tools
    ToolResult,     # Standardized result: ToolResult.success(data) / ToolResult.failure(msg)
    ToolConfig,     # YAML-loaded tool configuration dataclass
)
```

### Tool Structure
Each tool lives in its own directory:
```
tools/{tool_name}/
├── __init__.py
├── tool.py         # Implements BaseTool or has module-level: name, description, schema, run
└── config.yaml     # Tool configuration (optional)
```

### YAML Configuration
```python
from hailo_apps.python.gen_ai_apps.agent_tools_example.yaml_config import (
    load_yaml_config,   # Load and validate tool YAML config
    ToolYamlConfig,     # Parsed config object
)
```

### State Management
```python
from hailo_apps.python.gen_ai_apps.agent_tools_example.state_manager import StateManager

sm = StateManager(tool_name="my_tool", contexts_dir=Path("./contexts"))
sm.save_state(state_data)
state = sm.load_state("default")
```

