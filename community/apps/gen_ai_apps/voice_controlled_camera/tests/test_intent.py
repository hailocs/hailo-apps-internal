"""Pure-Python unit tests for the voice-command intent classification and
VLM-prompt construction in the voice_controlled_camera app.

The app module imports OpenCV + HailoRT GenAI backends at import time, so we
install ``sys.modules`` stubs first. We then exercise the pure logic methods
(``classify_intent``, ``_build_vlm_prompt``) on an instance built *without*
running ``__init__`` (which would try to allocate real models / a VDevice).
"""

import pytest

from . import _stubs

_stubs.install()

from community.apps.gen_ai_apps.voice_controlled_camera import (  # noqa: E402
    voice_controlled_camera as app_mod,
)

pytestmark = pytest.mark.community

CommandIntent = app_mod.CommandIntent


@pytest.fixture
def app():
    """A VoiceControlledCameraApp whose __init__ (model allocation) is skipped.

    classify_intent / _build_vlm_prompt are pure and read no instance state, so
    a bare object is sufficient and avoids touching any hardware backend.
    """
    return object.__new__(app_mod.VoiceControlledCameraApp)


# ============================================================
# Intent classification — happy paths
# ============================================================


class TestClassifyDescribe:
    @pytest.mark.parametrize(
        "text",
        [
            "describe the scene",
            "What do you see?",
            "tell me what is happening",
            "show me the room",
            "take a look around",
        ],
    )
    def test_describe_phrases(self, app, text):
        assert app.classify_intent(text) == CommandIntent.DESCRIBE


class TestClassifyDetect:
    @pytest.mark.parametrize(
        "text",
        [
            "detect people",
            "count the cars",
            "find my keys",
            "how many cups are there",
            "where is the dog",
            "can you spot a chair",
        ],
    )
    def test_detect_phrases(self, app, text):
        assert app.classify_intent(text) == CommandIntent.DETECT


class TestClassifyRead:
    @pytest.mark.parametrize(
        "text",
        [
            "read that sign",
            "what does the text say",
            "do some ocr on this",
            "what is the writing on the wall",
            "the label says what",
        ],
    )
    def test_read_phrases(self, app, text):
        assert app.classify_intent(text) == CommandIntent.READ


class TestClassifyChatFallback:
    @pytest.mark.parametrize(
        "text",
        [
            "hello there",
            "what is the capital of France",
            "tell me a joke",
            "thanks",
        ],
    )
    def test_unknown_command_falls_back_to_chat(self, app, text):
        assert app.classify_intent(text) == CommandIntent.CHAT


# ============================================================
# Intent classification — edge cases & precedence
# ============================================================


class TestClassifyEdges:
    def test_empty_string_is_chat(self, app):
        assert app.classify_intent("") == CommandIntent.CHAT

    def test_whitespace_only_is_chat(self, app):
        assert app.classify_intent("   ") == CommandIntent.CHAT

    def test_classification_is_case_insensitive(self, app):
        assert app.classify_intent("DESCRIBE THE SCENE") == CommandIntent.DESCRIBE
        assert app.classify_intent("DeTeCt PeOpLe") == CommandIntent.DETECT

    def test_substring_keyword_matches(self, app):
        # "reading" contains "read" -> READ wins (substring match by design).
        assert app.classify_intent("keep reading") == CommandIntent.READ

    def test_read_takes_precedence_over_detect(self, app):
        # READ keywords are checked first in the source, so a phrase containing
        # both ("read" + "count") resolves to READ.
        assert app.classify_intent("read and count the signs") == CommandIntent.READ

    def test_detect_takes_precedence_over_describe(self, app):
        # DETECT is checked before DESCRIBE; "find" + "describe" -> DETECT.
        assert app.classify_intent("find and describe the objects") == CommandIntent.DETECT


# ============================================================
# VLM prompt construction
# ============================================================


class TestBuildVlmPrompt:
    def test_describe_prompt_mentions_scene(self, app):
        prompt = app._build_vlm_prompt(CommandIntent.DESCRIBE, "what do you see")
        assert "scene" in prompt.lower()
        # Describe prompt is static and ignores the raw user text.
        assert "what do you see" not in prompt

    def test_detect_prompt_embeds_user_text(self, app):
        user_text = "count the red cars"
        prompt = app._build_vlm_prompt(CommandIntent.DETECT, user_text)
        assert user_text in prompt
        assert "count" in prompt.lower()

    def test_read_prompt_mentions_text(self, app):
        prompt = app._build_vlm_prompt(CommandIntent.READ, "read the sign")
        low = prompt.lower()
        assert "text" in low or "read" in low

    def test_chat_intent_returns_user_text_verbatim(self, app):
        user_text = "tell me a joke"
        assert app._build_vlm_prompt(CommandIntent.CHAT, user_text) == user_text

    def test_prompts_are_nonempty_strings(self, app):
        for intent in CommandIntent:
            prompt = app._build_vlm_prompt(intent, "anything")
            assert isinstance(prompt, str) and prompt.strip()


# ============================================================
# Keyword tables / enum sanity
# ============================================================


class TestModuleConstants:
    def test_command_intent_values(self):
        assert {e.value for e in CommandIntent} == {"describe", "detect", "read", "chat"}

    def test_keyword_lists_nonempty_and_lowercase(self):
        for kws in (
            app_mod.DESCRIBE_KEYWORDS,
            app_mod.DETECT_KEYWORDS,
            app_mod.READ_KEYWORDS,
        ):
            assert kws, "keyword list must not be empty"
            assert all(k == k.lower() for k in kws), "keywords must be lowercase for matching"

    def test_keyword_sets_are_disjoint(self):
        # No literal keyword should appear in two different intent tables,
        # otherwise the (read -> detect -> describe) precedence becomes ambiguous.
        d = set(app_mod.DESCRIBE_KEYWORDS)
        de = set(app_mod.DETECT_KEYWORDS)
        r = set(app_mod.READ_KEYWORDS)
        assert d.isdisjoint(de)
        assert d.isdisjoint(r)
        assert de.isdisjoint(r)
