"""
LLM Engine — Extracts tool parameters from user text.

Interface:
    - __init__(vdevice): Initialize the engine
    - run(text, tool_name) -> dict: Extract parameters as a JSON dict
    - close(): Clean up resources

To customize:
Replace the implementation in `__init__`, `run`, and `close` methods.
"""

import json_repair
import logging
from hailo_platform import VDevice
from hailo_platform.genai import LLM
from tools import TOOL_PROMPTS, NO_PARAM_TOOLS

logger = logging.getLogger("v2a_demo")

MODEL_PATH = "resources/Qwen2.5-Coder-1.5B-Instruct.hef"


class LLMEngine:
    """LLM engine for tool parameter extraction."""

    def __init__(self, vdevice: VDevice):
        self.llm = LLM(vdevice, MODEL_PATH)
        self._cached_contexts = {}  # {tool_name: saved_context}

    def run(self, text: str, tool_name: str) -> dict:
        """Extract parameters for the given tool from user text.

        Args:
            text: The user's transcribed speech
            tool_name: The tool selected by the tool selector

        Returns:
            dict of parsed parameters for the tool
        """
        if tool_name in NO_PARAM_TOOLS:
            logger.debug(f"Tool '{tool_name}' requires no params, skipping LLM")
            return {}

        if tool_name not in TOOL_PROMPTS:
            logger.warning(f"No prompt defined for tool '{tool_name}', returning empty params")
            return {}

        self.llm.load_context(self._cached_contexts[tool_name])

        raw_response = self.llm.generate_all(
            prompt=[{"role": "user", "content": text.strip()}]
        )
        logger.debug(f"LLM raw response for {tool_name}: {raw_response}")

        return self._parse_params(raw_response)

    def _parse_params(self, raw_response: str) -> dict:
        """Parse parameter JSON from LLM response."""
        parsed = json_repair.loads(raw_response)
        if isinstance(parsed, dict):
            return parsed
        logger.warning(f"LLM response parsed to non-dict: {type(parsed)}")
        return {}

    def close(self):
        if self.llm:
            self.llm.release()

    def __enter__(self):
        # Pre-cache each tool's system prompt context (skip no-param tools)
        for tool_name, prompt in TOOL_PROMPTS.items():
            if tool_name in NO_PARAM_TOOLS:
                continue
            self.llm.generate_all(
                prompt=[{"role": "system", "content": prompt}],
                max_generated_tokens=0,
                do_sample=False,
            )
            self._cached_contexts[tool_name] = self.llm.save_context()
            self.llm.clear_context()
        return self

    def __exit__(self, *_):
        self.close()
