"""
Minimal tool template.

Copy this file to create a new tool. Keep the public contract:

- name: str            → unique tool name
- description: str     → short human description
- schema: dict | None  → JSON schema-like description of inputs
- run(input: dict) -> dict

If pydantic is available, you may validate inputs with a BaseModel.
"""

from __future__ import annotations

from typing import Any


name: str = "template_tool"
description: str = "A template tool. Replace with your own logic."

# Optional JSON-like schema for prompting and validation hints
# Note: Follow OpenAI function calling format. Do NOT use: default, minimum, maximum, minItems, maxItems, additionalProperties
schema: dict[str, Any] = {
    "type": "object",
    "properties": {
        "example_param": {"type": "string", "description": "An example string parameter."}
    },
    "required": ["example_param"],
}

TOOLS_SCHEMA: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": schema,
        },
    }
]


def run(input_data: dict[str, Any]) -> dict[str, Any]:
    """
    Execute the tool logic.

    Args:
        input_data: Tool input parameters dictionary.

    Returns:
        Tool result payload dictionary with 'ok' boolean and either
        'error' (if failed) or result data (if successful).
    """
    example_param = str(input_data.get("example_param", ""))
    if not example_param:
        return {"ok": False, "error": "Missing required 'example_param'."}

    # Replace with your tool's logic
    return {"ok": True, "echo": example_param}


