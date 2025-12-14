"""
Message formatting utilities for LLM interactions.

Provides helper functions to create formatted messages for system, user, assistant, and tool roles.
"""

from typing import Any, Dict


def messages_system(system_text: str) -> Dict[str, Any]:
    """
    Create a system message in the format expected by Hailo LLM.

    Args:
        system_text (str): System prompt text.

    Returns:
        Dict[str, Any]: Formatted message dictionary.
    """
    return {"role": "system", "content": [{"type": "text", "text": system_text}]}


def messages_user(text: str) -> Dict[str, Any]:
    """
    Create a user message in the format expected by Hailo LLM.

    Args:
        text (str): User message text.

    Returns:
        Dict[str, Any]: Formatted message dictionary.
    """
    return {"role": "user", "content": [{"type": "text", "text": text}]}


def messages_assistant(text: str) -> Dict[str, Any]:
    """
    Create an assistant message in the format expected by Hailo LLM.

    Args:
        text (str): Assistant message text.

    Returns:
        Dict[str, Any]: Formatted message dictionary.
    """
    return {"role": "assistant", "content": [{"type": "text", "text": text}]}


def messages_tool(text: str) -> Dict[str, Any]:
    """
    Create a tool message in the format expected by Hailo LLM.

    Args:
        text (str): Tool message text.

    Returns:
        Dict[str, Any]: Formatted message dictionary.
    """
    return {"role": "tool", "content": [{"type": "text", "text": text}]}
