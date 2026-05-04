from __future__ import annotations

import pytest

from reachy_mini_conversation_app.config import config
from reachy_mini_conversation_app.gemini_live.handler import build_live_config, build_function_declarations


def test_gemini_live_declares_only_utterance_handler() -> None:
    """Gemini sees only the utterance handler, not physical robot tools."""
    declarations = build_function_declarations()

    assert [declaration["name"] for declaration in declarations] == ["handle_user_utterance"]
    assert "move_head" not in str(declarations)
    assert "dance" not in str(declarations)


def test_gemini_live_config_uses_audio_and_function_tool() -> None:
    """Live config enables audio, transcription, and the utterance function."""
    live_config = build_live_config()

    assert live_config["response_modalities"] == ["AUDIO"]
    assert live_config["input_audio_transcription"] == {}
    assert live_config["output_audio_transcription"] == {}
    assert live_config["tools"] == [{"function_declarations": build_function_declarations()}]


@pytest.mark.asyncio
async def test_gemini_live_startup_fails_fast_without_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Gemini mode raises clearly when the API key is missing."""
    from reachy_mini_conversation_app.gemini_live.handler import GeminiLiveSessionHandler

    monkeypatch.setattr(config, "GEMINI_API_KEY", "")
    handler = object.__new__(GeminiLiveSessionHandler)

    with pytest.raises(ValueError, match="GEMINI_API_KEY"):
        await handler.start_up()
