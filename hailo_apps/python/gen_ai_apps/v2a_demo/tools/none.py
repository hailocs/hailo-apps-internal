"""None tool - fallback when no other tool is matched."""

TOOL_PROMPT = (
    "You are a JSON-only output machine. The user's request does NOT match any tool.\n"
    "\n"
    "This tool takes NO parameters. Your ONLY output must be exactly: {}\n"
    "\n"
    "NEVER answer the question. NEVER write poems. NEVER explain concepts.\n"
    "NEVER do math. NEVER tell jokes. NEVER output anything other than: {}\n"
    "\n"
    "Examples:\n"
    '"Explain how gravity works." -> {}\n'
    '"Write me a short poem about the sea." -> {}\n'
    '"What is the capital of France?" -> {}\n'
    '"Tell me a joke" -> {}\n'
    '"Explain the difference between RAM and ROM in a computer." -> {}\n'
    '"How does photosynthesis work?" -> {}\n'
    '"What\'s 2+2?" -> {}\n'
    '"Tell me a story" -> {}\n'
    '"What is quantum physics?" -> {}\n'
    "\n"
    "NEVER DO THIS (these are ALL wrong):\n"
    '- "Gravity is a force that..." (WRONG - never answer questions)\n'
    '- "Here is a poem: Waves crash..." (WRONG - never write poems)\n'
    '- "RAM is volatile memory while ROM..." (WRONG - never explain)\n'
    '- "The capital of France is Paris" (WRONG - never answer)\n'
    '- {"answer": "Paris"} (WRONG - must be empty {})\n'
    "\n"
    "Your output must be ONLY: {}\n"
    "Nothing before it. Nothing after it. Just: {}"
)

TOOL_DESCRIPTIONS = [
    "Tell a joke",
    "Explain how something works",
    "Ask a general knowledge question",
    "Provide a science explanation",
    "Write a story or poem",
    "Give definitions or explanations",
    "Answer philosophy questions",
    "Perform simple math or logic questions",
    "Have a conversation",
    "Provide general advice or facts",
]


def none() -> str:
    """Fallback response when no specific tool is matched."""
    return "I can't help with that. Ask me to explain my tools to see what's available."
