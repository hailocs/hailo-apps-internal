"""
Math tool with optional pydantic validation.
Supports basic arithmetic operations: add, sub, mul, div.
"""

from __future__ import annotations

from typing import Any

name: str = "math"

# User-facing description (shown in CLI tool list)
display_description: str = (
    "Perform basic arithmetic operations: addition, subtraction, multiplication, and division."
)

# LLM instruction description (includes warnings for model)
description: str = (
    "CRITICAL: You MUST use this tool for ALL arithmetic operations. "
    "NEVER calculate math directly - ALWAYS call this tool. "
    "The function name is 'math' (use this exact name in tool calls). "
    "Supported operations: add (+), sub (-), mul (*), div (/). "
    "The 'op' parameter specifies which operation: 'add', 'sub', 'mul', or 'div'."
)

# Minimal JSON-like schema to assist prompting/validation
schema: dict[str, Any] = {
    "type": "object",
    "properties": {
        "op": {
            "type": "string",
            "enum": ["add", "sub", "mul", "div"],
            "description": (
                "Operation to perform: 'add' (+), 'sub' (-), 'mul' (*), 'div' (/). "
                "MUST use this tool for ANY calculation - do NOT calculate directly."
            ),
        },
        "numbers": {
            "type": "array",
            "items": {"type": "number"},
            "description": (
                "List of numbers to operate on (must contain at least 1 number). "
                "Examples: [5, 3] for '5*3', [123, 1231] for '123*1231', [10, 2] for '10/2'. "
                "Extract ALL numbers from the user's question into this array."
            ),
        },
    },
    "required": ["op", "numbers"],
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


def _validate_with_pydantic(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        from pydantic import BaseModel, Field, field_validator

        class MathInput(BaseModel):
            op: str = Field(description="Operation: add|sub|mul|div")
            numbers: list[float] = Field(description="Numbers to operate on", min_length=1)

            @field_validator("op")
            @classmethod
            def _op_valid(cls, v: str) -> str:
                valid_ops = {"add", "sub", "mul", "div"}
                if v not in valid_ops:
                    raise ValueError(f"op must be one of: {', '.join(sorted(valid_ops))}")
                return v

        data = MathInput(**payload).model_dump()
        return {"ok": True, "data": data}
    except Exception:  # pydantic not installed or validation error
        try:
            # Best-effort fallback without pydantic
            op = str(payload.get("op", "")).strip()
            numbers_raw = payload.get("numbers", [])
            numbers = [float(x) for x in numbers_raw]
            valid_ops = {"add", "sub", "mul", "div"}
            if op not in valid_ops:
                return {"ok": False, "error": f"Invalid op. Use one of: {', '.join(sorted(valid_ops))}"}
            if not numbers:
                return {"ok": False, "error": "'numbers' must be a non-empty list"}
            return {"ok": True, "data": {"op": op, "numbers": numbers}}
        except Exception as inner_exc:
            return {"ok": False, "error": f"Validation failed: {inner_exc}"}


def run(input_data: dict[str, Any]) -> dict[str, Any]:
    """
    Execute the math operation.

    Args:
        input_data: Dictionary with keys:
            - op: Operation type: 'add', 'sub', 'mul', or 'div'
            - numbers: List of numbers to operate on (at least 1 number required)

    Returns:
        Dictionary with 'ok' and 'result' (if successful) or 'error' (if failed).
    """
    validated = _validate_with_pydantic(input_data)
    if not validated.get("ok"):
        return validated

    data = validated["data"]
    op = data["op"]
    numbers = data["numbers"]

    if op == "add":
        result = 0.0
        for n in numbers:
            result += n
        return {"ok": True, "result": result}

    if op == "sub":
        result = numbers[0]
        for n in numbers[1:]:
            result -= n
        return {"ok": True, "result": result}

    if op == "mul":
        result = 1.0
        for n in numbers:
            result *= n
        return {"ok": True, "result": result}

    if op == "div":
        result = numbers[0]
        for n in numbers[1:]:
            if n == 0:
                return {"ok": False, "error": "Division by zero"}
            result /= n
        return {"ok": True, "result": result}

    return {"ok": False, "error": "Unknown operation"}


