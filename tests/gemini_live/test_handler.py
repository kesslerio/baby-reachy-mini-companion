from __future__ import annotations
import asyncio
from unittest.mock import AsyncMock

import pytest

from reachy_mini_conversation_app.config import config
from reachy_mini_conversation_app.tools.core_tools import ToolDependencies
from reachy_mini_conversation_app.gemini_live.handler import (
    GeminiLiveSessionHandler,
    build_live_config,
    build_function_declarations,
)
from reachy_mini_conversation_app.conversation.tool_loop import ConversationToolLoop


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


@pytest.mark.asyncio
async def test_gemini_live_uses_utterance_local_speak_dependency() -> None:
    """User utterance speech capture does not mutate shared dependencies."""
    shared_speak = AsyncMock()
    handler = object.__new__(GeminiLiveSessionHandler)
    handler.deps = ToolDependencies(reachy_mini=object(), movement_manager=object(), speak_func=shared_speak)
    handler._tool_loop_lock = asyncio.Lock()

    class FakeLLM:
        async def chat_stream(self, user_text=None, tools=None, tool_outputs=None):
            if user_text is not None:
                yield {
                    "type": "tool_call",
                    "tool_call": {
                        "id": "call_1",
                        "function": {"name": "speak", "arguments": '{"text":"Current answer."}'},
                    },
                }

    async def dispatch_tool_call(name: str, args: str, deps: ToolDependencies) -> dict[str, str]:
        assert deps is not handler.deps
        assert deps.speak_func is not shared_speak
        assert deps.speak_func is not None
        await deps.speak_func("Current answer.")
        return {"status": "success"}

    handler.tool_loop = ConversationToolLoop(
        llm=FakeLLM(),
        deps=handler.deps,
        tool_specs=[],
        dispatch_tool_call=dispatch_tool_call,
    )

    result = await handler._run_tool_loop_for_utterance("say the answer")

    assert result.text == "Current answer."
    assert handler.deps.speak_func is shared_speak
    shared_speak.assert_not_called()
