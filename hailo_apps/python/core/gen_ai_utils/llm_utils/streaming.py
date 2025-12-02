"""
Streaming utilities for LLM generation.

Handles streaming tokens, filtering XML tags, and cleaning up response content.
"""

import logging
import re
from typing import Callable, List, Optional

from hailo_platform.genai import LLM

# Setup logger
logger = logging.getLogger(__name__)


class StreamingTextFilter:
    """
    Filter streaming tokens on-the-fly to remove XML tags and special tokens.

    Maintains state to handle partial tags that arrive across token boundaries.
    """

    def __init__(self, debug_mode: bool = False):
        """
        Initialize the streaming text filter.

        Args:
            debug_mode (bool): If True, pass through all tokens without filtering.
        """
        self.buffer = ""
        self.inside_text_tag = False
        self.inside_tool_call_tag = False
        self.debug_mode = debug_mode

    def process_token(self, token: str) -> str:
        """
        Process a single token and return cleaned text ready for display.

        Args:
            token (str): Raw token from LLM.

        Returns:
            str: Cleaned text to print (may be empty if token should be suppressed).
        """
        # In debug mode, don't filter anything - show raw output
        if self.debug_mode:
            return token

        self.buffer += token

        # Remove <|im_end|> tokens immediately
        if "<|im_end|>" in self.buffer:
            self.buffer = self.buffer.replace("<|im_end|>", "")

        output = ""

        # Process buffer until no more complete tags are found
        changed = True
        while changed:
            changed = False

            # Check for <text> tag start
            text_start = self.buffer.find("<text>")
            if text_start != -1 and not self.inside_text_tag:
                # Extract anything before <text> tag (should be empty, but just in case)
                if text_start > 0:
                    output += self.buffer[:text_start]
                self.buffer = self.buffer[text_start + 6:]  # Remove "<text>"
                self.inside_text_tag = True
                changed = True
                continue

            # Check for </text> tag end
            text_end = self.buffer.find("</text>")
            if text_end != -1 and self.inside_text_tag:
                # Extract text content before </text>
                output += self.buffer[:text_end]
                self.buffer = self.buffer[text_end + 7:]  # Remove "</text>"
                self.inside_text_tag = False
                changed = True
                continue

            # Check for <tool_call> tag start
            tool_call_start = self.buffer.find("<tool_call>")
            if tool_call_start != -1 and not self.inside_tool_call_tag:
                # If we're inside <text>, output content before <tool_call>
                if self.inside_text_tag and tool_call_start > 0:
                    output += self.buffer[:tool_call_start]
                self.buffer = self.buffer[tool_call_start + 10:]  # Remove "<tool_call>"
                self.inside_tool_call_tag = True
                changed = True
                continue

            # Check for </tool_call> tag end
            tool_call_end = self.buffer.find("</tool_call>")
            if tool_call_end != -1 and self.inside_tool_call_tag:
                # Suppress everything inside <tool_call>
                self.buffer = self.buffer[tool_call_end + 12:]  # Remove "</tool_call>"
                self.inside_tool_call_tag = False
                changed = True
                continue

        # If we're inside <text> tag and not inside <tool_call>, output remaining buffer
        if self.inside_text_tag and not self.inside_tool_call_tag and self.buffer:
            output += self.buffer
            self.buffer = ""
        elif not self.inside_text_tag and not self.inside_tool_call_tag:
            # If not inside any tag, the text is still valid for streaming.
            # To avoid printing partial tags, we find the last complete chunk of text.
            # A simple heuristic: find the start of the next potential tag.
            next_tag_start = self.buffer.find('<')
            if next_tag_start != -1:
                # Output text up to the potential start of a tag
                output += self.buffer[:next_tag_start]
                self.buffer = self.buffer[next_tag_start:]
            else:
                # No partial tag found, output the whole buffer
                output += self.buffer
                self.buffer = ""

        return output

    def get_remaining(self) -> str:
        """
        Get any remaining buffered content after streaming completes.

        Returns:
            str: Remaining buffered text, cleaned of partial tags.
        """
        # In debug mode, return empty (everything was printed already)
        if self.debug_mode:
            return ""
        # Clean up any remaining partial tags or buffer content
        if self.inside_text_tag and not self.inside_tool_call_tag:
            # If we're still inside text tag, return the buffer (might have partial closing tag)
            remaining = self.buffer
            # Remove any partial closing tags like "</text" or "text>"
            remaining = remaining.replace("</text", "").replace("text>", "")
            return remaining
        # Also clean up any partial tags that might remain in buffer
        cleaned = self.buffer.replace("</text", "").replace("text>", "").replace("<text", "")

        # Remove orphan '<' which might be left over from <<|im_end|> or incomplete tags
        if cleaned.strip() == "<":
            return ""

        return cleaned


def generate_and_stream_response(
    llm: LLM,
    prompt: List[dict],
    temperature: float = 0.1,
    seed: int = 42,
    max_tokens: int = 200,
    prefix: str = "Assistant: ",
    debug_mode: bool = False,
    token_callback: Optional[Callable[[str], None]] = None,
    abort_callback: Optional[Callable[[], bool]] = None,
) -> str:
    """
    Generate response from LLM and stream it to stdout with filtering.

    Handles streaming tokens, filtering XML tags, and cleaning up remaining content.

    Args:
        llm (LLM): The LLM instance to use for generation.
        prompt (List[dict]): List of message dictionaries to send to the LLM.
        temperature (float): Sampling temperature. Defaults to 0.1.
        seed (int): Random seed. Defaults to 42.
        max_tokens (int): Maximum tokens to generate. Defaults to 200.
        prefix (str): Prefix to print before streaming. Defaults to "Assistant: ".
        debug_mode (bool): If True, don't filter tokens (show raw output).
        token_callback (Optional[Callable[[str], None]]): Optional callback function
            called with each cleaned token/chunk. Useful for TTS integration.
        abort_callback (Optional[Callable[[], bool]]): Optional callback function
            that returns True if generation should be aborted.

    Returns:
        str: Raw response string (before filtering, for tool call parsing).
    """
    print(prefix, end="", flush=True)
    response_parts: List[str] = []
    token_filter = StreamingTextFilter(debug_mode=debug_mode)

    # Get recovery sequence to filter it out
    recovery_seq = None
    try:
        recovery_seq = llm.get_generation_recovery_sequence()
        logger.debug("Recovery sequence configured")
    except AttributeError:
        logger.debug("Recovery sequence not available")

    with llm.generate(
        prompt=prompt,
        temperature=temperature,
        seed=seed,
        max_generated_tokens=max_tokens,
    ) as gen:
        for token in gen:
            # Check for abort signal
            if abort_callback and abort_callback():
                logger.info("Generation aborted by user")
                print("\n[Aborted]", end="", flush=True)
                break

            # Filter recovery sequence if present
            if recovery_seq and token == recovery_seq:
                continue

            response_parts.append(token)
            # Filter and print clean tokens on the fly
            cleaned_chunk = token_filter.process_token(token)
            if cleaned_chunk:
                print(cleaned_chunk, end="", flush=True)
                if token_callback:
                    token_callback(cleaned_chunk)

    # Print any remaining content after streaming
    remaining = token_filter.get_remaining()
    if remaining:
        # Final cleanup: remove any remaining XML tags and partial tags
        if not debug_mode:
            # Remove complete tags and partial tags (handles cases like </text>, </text, text>, etc.)
            remaining = re.sub(r"</?text>?", "", remaining)  # </text>, </text, <text>, text>
            remaining = re.sub(r"</?tool_call>?", "", remaining)  # </tool_call>, <tool_call>, etc.
            remaining = re.sub(r"<\|im_end\|>", "", remaining)  # Special tokens
        print(remaining, end="", flush=True)
        if token_callback:
            token_callback(remaining)

    print()  # New line after streaming completes

    raw_response = "".join(response_parts)
    logger.debug("Generated %d tokens", len(response_parts))
    return raw_response


def clean_response(response: str) -> str:
    """
    Clean LLM response by removing special tokens and extracting text from XML tags.

    Removes:
    - <|im_end|> tokens
    - <text>...</text> wrapper tags (extracts content)
    - <tool_call>...</tool_call> tags (tool calls are parsed separately)

    Args:
        response (str): Raw response string from LLM.

    Returns:
        str: Cleaned response text ready for display.
    """
    # Remove special tokens
    cleaned = response.replace("<|im_end|>", "")

    # Extract text from <text>...</text> tags
    text_match = re.search(r"<text>(.*?)</text>", cleaned, re.DOTALL)
    if text_match:
        cleaned = text_match.group(1).strip()

    # Remove <tool_call>...</tool_call> tags if present (we parse these separately)
    cleaned = re.sub(r"<tool_call>.*?</tool_call>", "", cleaned, flags=re.DOTALL)

    # Clean up any remaining whitespace
    return cleaned.strip()
