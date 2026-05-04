from __future__ import annotations

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
