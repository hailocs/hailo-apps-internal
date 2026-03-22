# Skill: Create Agent Application with Tool Calling

> Build an AI agent that uses Hailo LLM for reasoning and can execute tools/actions.

## When to Use This Skill

- User wants an **AI agent that can take actions** (control hardware, query APIs, etc.)
- User needs **tool calling** capabilities with the Hailo LLM
- User wants to combine **reasoning + execution** in a loop

## Reference Implementation

Study `hailo_apps/python/gen_ai_apps/agent_tools_example/` thoroughly:
- `agent.py` — `AgentApp` class with tool-calling loop
- `tools/base.py` — `BaseTool` abstract class and `ToolResult` dataclass
- `tools/weather/`, `tools/servo/`, etc. — Example tool implementations
- `yaml_config.py` — YAML-based tool configuration
- `state_manager.py` — Context state persistence
- `system_prompt.py` — System prompt generation

## Architecture

```
User Input → LLM (reasoning) → Tool Parsing → Tool Execution → LLM (response) → User Output
                ↑                                    │
                └────────────── context ─────────────┘
```

## Step-by-Step Build Process

### Step 1: Define Tool Schema

Each tool needs: `name`, `description`, `schema` (JSON Schema), `run()`:

```python
from hailo_apps.python.gen_ai_apps.agent_tools_example.tools.base import BaseTool, ToolResult

class MyTool(BaseTool):
    @property
    def name(self) -> str:
        return "check_water_bowl"

    @property
    def description(self) -> str:
        return "Check if the dog's water bowl needs refilling"

    @property
    def schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "bowl_id": {"type": "string", "description": "Which bowl to check"}
            },
            "required": ["bowl_id"]
        }

    def run(self, input_data: dict) -> dict:
        # Tool logic here
        return ToolResult.success({"water_level": "low"}).to_dict()
```

### Step 2: Configure Tool via YAML

```yaml
version: "1.0"
tool_name: "check_water_bowl"
persona:
  role: "Pet Care Assistant"
  tone: "friendly and helpful"
capabilities:
  - "Check water bowl levels"
  - "Report when refill is needed"
tool_instructions: |
  Use this tool when the user asks about the dog's water.
  Always report the current level.
few_shot_examples:
  - input: "Is the dog's water bowl full?"
    expected_tool: "check_water_bowl"
    expected_args: {"bowl_id": "main"}
```

### Step 3: Register and Wire Up

The agent auto-discovers tools from the `tools/` directory. Place your tool module in:
```
agent_tools_example/tools/my_tool/
├── __init__.py
├── tool.py       # Implements BaseTool or module-level attributes
└── config.yaml   # Tool configuration
```

## LLM Utility Modules

| Module | Purpose |
|---|---|
| `llm_utils.streaming` | Stream LLM tokens |
| `llm_utils.tool_parsing` | Parse tool calls from LLM output |
| `llm_utils.tool_execution` | Execute parsed tool calls |
| `llm_utils.tool_discovery` | Auto-discover tools from directory |
| `llm_utils.tool_selection` | Interactive tool selection UI |
| `llm_utils.context_manager` | Manage conversation context |
| `llm_utils.message_formatter` | Format messages for LLM |
| `llm_utils.agent_utils` | Agent loop utilities |
| `llm_utils.terminal_ui` | Terminal-based UI helpers |

## Voice-Enabled Agent

Add `--voice` flag to enable voice input/output:
```python
from hailo_apps.python.gen_ai_apps.gen_ai_utils.voice_processing.interaction import VoiceInteractionManager
```
