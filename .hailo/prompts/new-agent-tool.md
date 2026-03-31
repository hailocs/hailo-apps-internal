# Prompt: Create New Agent Tool

> Template prompt for adding a new tool to the agent framework.

## Instructions for Agent

You are adding a new tool to the agent tools framework in hailo-apps.

### Required Context (Read These First)
1. `.hailo/skills/hl-build-agent-app.md` — Agent app skill
2. `.hailo/toolsets/gen-ai-utilities.md` — Gen AI utilities reference
3. `hailo_apps/python/gen_ai_apps/agent_tools_example/tools/base.py` — Tool base class
4. `hailo_apps/python/gen_ai_apps/agent_tools_example/tools/weather/` — Example tool

### Build Steps
1. Create tool directory: `agent_tools_example/tools/{tool_name}/`
2. Create `__init__.py`
3. Create `tool.py` implementing `BaseTool`:
   - `name` property → unique identifier
   - `description` property → what it does (for LLM)
   - `schema` property → JSON Schema for parameters
   - `run(input_data)` method → actual tool logic
4. Create `config.yaml` with persona, capabilities, examples
5. Tool is auto-discovered by the agent framework

### Tool Implementation Template

```python
from hailo_apps.python.gen_ai_apps.agent_tools_example.tools.base import BaseTool, ToolResult

class MyTool(BaseTool):
    @property
    def name(self) -> str:
        return "{tool_name}"

    @property
    def description(self) -> str:
        return "{tool_description}"

    @property
    def schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "param1": {"type": "string", "description": "What this param does"}
            },
            "required": ["param1"]
        }

    def run(self, input_data: dict) -> dict:
        try:
            # Tool logic here
            result = do_something(input_data["param1"])
            return ToolResult.success(result).to_dict()
        except Exception as e:
            return ToolResult.failure(str(e)).to_dict()

# Module-level attributes for auto-discovery
name = MyTool().name
description = MyTool().description
schema = MyTool().schema
TOOLS_SCHEMA = [{"type": "function", "function": {"name": name, "description": description, "parameters": schema}}]
run = MyTool().run