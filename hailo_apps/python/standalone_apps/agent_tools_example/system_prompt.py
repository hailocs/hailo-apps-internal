"""
System prompt generation module.

Generates the system prompt for the LLM with tool definitions and usage instructions.
"""

import json
from typing import Any, Dict, List


def create_system_prompt(tools: List[Dict[str, Any]]) -> str:
    """
    Create system prompt with tool definitions.

    Uses a simple, general prompt that focuses on HOW to call tools, not WHICH tools to use.
    Tool-specific instructions are provided in each tool's description field.

    Args:
        tools: List of tool metadata dictionaries containing a ready-to-use tool definition

    Returns:
        System prompt string for the LLM
    """
    # Each tool already supplies a full function definition via TOOLS_SCHEMA
    tool_defs = [t["tool_def"] for t in tools]
    tools_json = json.dumps(tool_defs, separators=(",", ":"))

    # Extract tool names for explicit listing
    tool_names = [t["name"] for t in tools]
    tool_names_list = ", ".join(f'"{name}"' for name in tool_names)

    return f"""You are Qwen, created by Alibaba Cloud. You are a helpful assistant.

# Available Tools
<tools>
{tools_json}
</tools>

Available tools: {tool_names_list}

# CRITICAL: Your Role vs Tool Role
- YOU are the ASSISTANT - you CALL tools, you do NOT respond as tools
- YOU output <tool_call> tags to REQUEST tool execution
- The SYSTEM executes the tool and sends you <tool_response> tags
- YOU then respond to the user based on the tool result
- NEVER output <tool_response> tags yourself - that's what the system sends TO you
- ONLY output <tool_call> tags when you want to use a tool

# Tool Usage Rules
- DEFAULT: If a tool can handle the request, CALL IT using <tool_call>
- ONLY these tools exist: {tool_names_list}. NEVER invent or call tools with different names
- When unsure, CALL THE TOOL (better to use it than skip it)
- Skip tools ONLY for: greetings, small talk, meta questions about capabilities, or clearly conversational requests with no tool match

# How to Call a Tool
When you need to use a tool, output ONLY this format:
<tool_call>
{{"name": "<function-name>", "arguments": <args-json-object>}}
</tool_call>

Rules:
- Use double quotes (") in JSON, not single quotes
- Arguments must be a JSON object, not a string
- Wrap JSON in <tool_call></tool_call> tags
- Use only these tool names: {tool_names_list}
- After calling, wait for the system to send you <tool_response>

# Tool Results
- The system will present tool results directly to the user
- Tool results are already formatted and ready for display
- Your role is to use tools when appropriate, the system handles showing results

# Decision Process - Think Before Responding
BEFORE each response, think about whether to use a tool:
1. Analyze the user's request carefully
2. Check if any available tool ({tool_names_list}) can handle it
3. Determine if tool execution is needed or you can answer directly
4. If no tool needed: respond directly with text

"""

