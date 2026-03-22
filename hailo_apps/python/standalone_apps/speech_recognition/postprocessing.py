"""Whisper decoder postprocessing — repetition penalty and transcription cleanup."""

import re
import numpy as np

# Punctuation tokens excluded from repetition penalty
_PUNCT_TOKENS = [11, 13]


def apply_repetition_penalty(logits, generated_tokens, penalty=1.5, window=8):
    """Penalize recently generated tokens to reduce repetition."""
    logits = np.squeeze(logits, axis=0)
    recent = set(generated_tokens[-window:])
    for token in recent:
        if token not in _PUNCT_TOKENS:
            logits[token] /= penalty
    return logits


def clean_transcription(text: str) -> str:
    """Remove repeated sentences from transcription output."""
    sentences = re.split(r'(?<=[.?])\s+', text)
    unique = []
    for sentence in sentences:
        norm = sentence.lower().strip()
        for u in unique:
            nu = u.lower().strip()
            if norm in nu or nu in norm:
                result = ' '.join(unique)
                if not result.endswith(('.', '?')):
                    result += '.'
                return result
        unique.append(sentence.strip())
    result = ' '.join(unique)
    if not result.endswith(('.', '?')):
        result += '.'
    return result
