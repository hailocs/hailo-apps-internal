"""Explain tools — lists available tools in a TTS-friendly format.

Takes no parameters; the LLM prompt forces an empty {} response.
"""

# Meta-tools excluded from the capability list shown to the user.
_EXCLUDED_TOOLS = {"none", "explain_tools"}

TOOL_PROMPT = (
    "You are a JSON-only output machine. The user is asking about your capabilities.\n"
    "\n"
    "This tool takes NO parameters. Your ONLY output must be exactly: {}\n"
    "\n"
    "NEVER explain tools. NEVER list capabilities. NEVER describe what you can do.\n"
    "NEVER output anything other than: {}\n"
    "\n"
    "Examples:\n"
    '"What can you do?" -> {}\n'
    '"List your tools" -> {}\n'
    '"What are your capabilities?" -> {}\n'
    '"Explain all of your available tools." -> {}\n'
    '"Tell me what actions you support." -> {}\n'
    '"What functions can you perform?" -> {}\n'
    '"Show me what you can help with" -> {}\n'
    '"What tools do you have?" -> {}\n'
    '"What are your abilities?" -> {}\n'
    "\n"
    "NEVER DO THIS (these are ALL wrong):\n"
    '- "I can help with weather, LED control..." (WRONG - never explain)\n'
    '- "My available tools are: 1. get_weather..." (WRONG - never list tools)\n'
    '- "I have the following capabilities..." (WRONG - never describe)\n'
    '- {"tools": ["get_weather", "control_led"]} (WRONG - must be empty {})\n'
    '- "Here are my functions:" (WRONG - never output text)\n'
    "\n"
    "Your output must be ONLY: {}\n"
    "Nothing before it. Nothing after it. Just: {}"
)

TOOL_DESCRIPTIONS = [
    "Explain what actions and tools are available",
    "List supported tools and capabilities",
    "Describe what the assistant can do",
    "Answer questions about available actions",
    "Explain the supported commands and features",
    "Provide an overview of assistant capabilities",
    "Handle requests asking about available tools",
    "Respond to questions about supported functionality",
    "Explain what help the assistant can provide",
]


def explain_tools() -> str:
    """Return a TTS-friendly description of available tools."""
    from tools import TOOLS  # lazy import to avoid circular dependency

    tool_names = [name for name in TOOLS if name not in _EXCLUDED_TOOLS]

    if not tool_names:
        return "I don't have any tools available right now."

    formatted = [name.replace("_", " ") for name in tool_names]
    if len(formatted) > 1:
        listed = ", ".join(formatted[:-1]) + ", and " + formatted[-1]
    else:
        listed = formatted[0]
    return f"I have the following tools: {listed}."
