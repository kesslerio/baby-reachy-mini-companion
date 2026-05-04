from __future__ import annotations
from typing import Any

import pytest

from reachy_mini_conversation_app.conversation.tool_loop import ConversationToolLoop
from reachy_mini_conversation_app.conversation.speech_sink import GeminiSpeechSink


class FakeLLM:
    """Scripted async LLM used by tool-loop tests."""

    def __init__(self, turns: list[list[dict[str, Any]]]) -> None:
        """Store scripted model turns."""
        self.turns = turns
        self.calls: list[dict[str, Any]] = []

    async def chat_stream(self, user_text=None, tools=None, tool_outputs=None):
        """Yield the next scripted turn."""
        self.calls.append({"user_text": user_text, "tools": tools, "tool_outputs": tool_outputs})
        for event in self.turns.pop(0):
            yield event


@pytest.mark.asyncio
async def test_tool_loop_returns_plain_model_text() -> None:
    """Plain model text returns without dispatching tools."""
    llm = FakeLLM([[{"type": "text", "content": "Hello there."}]])
    dispatched: list[str] = []

    async def dispatch_tool_call(name: str, args: str, deps: object) -> dict[str, Any]:
        dispatched.append(name)
        return {"status": "success"}

    loop = ConversationToolLoop(
        llm=llm,
        deps=object(),
        tool_specs=[{"type": "function", "function": {"name": "move_head"}}],
        dispatch_tool_call=dispatch_tool_call,
    )

    result = await loop.run("hi")

    assert result.text == "Hello there."
    assert dispatched == []
    assert llm.calls[0]["user_text"] == "hi"
    assert llm.calls[0]["tools"] == [{"type": "function", "function": {"name": "move_head"}}]


@pytest.mark.asyncio
async def test_tool_loop_dispatches_tool_and_feeds_output_back_to_brain() -> None:
    """Tool calls dispatch locally and feed results into the next model turn."""
    llm = FakeLLM(
        [
            [
                {
                    "type": "tool_call",
                    "tool_call": {
                        "id": "call_1",
                        "function": {"name": "move_head", "arguments": '{"direction":"left"}'},
                    },
                }
            ],
            [{"type": "text", "content": "I moved my head left."}],
        ]
    )

    async def dispatch_tool_call(name: str, args: str, deps: object) -> dict[str, Any]:
        return {"status": "success", "name": name, "args": args}

    loop = ConversationToolLoop(
        llm=llm,
        deps=object(),
        tool_specs=[],
        dispatch_tool_call=dispatch_tool_call,
    )

    result = await loop.run("move your head")

    assert result.text == "I moved my head left."
    assert [item.name for item in result.tool_executions] == ["move_head"]
    assert llm.calls[1]["user_text"] is None
    assert llm.calls[1]["tool_outputs"] == [
        {
            "role": "tool",
            "content": '{"status": "success", "name": "move_head", "args": "{\\"direction\\":\\"left\\"}"}',
            "tool_call_id": "call_1",
        }
    ]


@pytest.mark.asyncio
async def test_tool_loop_uses_speech_sink_when_tool_call_has_no_final_text() -> None:
    """Captured speak-tool text becomes the Gemini response fallback."""
    sink = GeminiSpeechSink()
    llm = FakeLLM(
        [
            [
                {
                    "type": "tool_call",
                    "tool_call": {
                        "id": "call_1",
                        "function": {"name": "speak", "arguments": '{"text":"Five plus ten is fifteen."}'},
                    },
                }
            ],
            [],
        ]
    )

    async def dispatch_tool_call(name: str, args: str, deps: object) -> dict[str, Any]:
        await sink.speak("Five plus ten is fifteen.")
        return {"status": "success"}

    loop = ConversationToolLoop(
        llm=llm,
        deps=object(),
        tool_specs=[],
        dispatch_tool_call=dispatch_tool_call,
        speech_sink=sink,
    )

    result = await loop.run("say the answer")

    assert result.text == "Five plus ten is fifteen."
    assert sink.messages == []


@pytest.mark.asyncio
async def test_tool_loop_prefers_captured_speech_over_generic_follow_up_text() -> None:
    """Speak-tool text wins over generic tool follow-up text."""
    sink = GeminiSpeechSink()
    llm = FakeLLM(
        [
            [
                {
                    "type": "tool_call",
                    "tool_call": {
                        "id": "call_1",
                        "function": {"name": "speak", "arguments": '{"text":"Five plus ten is fifteen."}'},
                    },
                }
            ],
            [{"type": "text", "content": "I said it."}],
        ]
    )

    async def dispatch_tool_call(name: str, args: str, deps: object) -> dict[str, Any]:
        await sink.speak("Five plus ten is fifteen.")
        return {"status": "success", "message": "Spoke: Five plus ten is fifteen."}

    loop = ConversationToolLoop(
        llm=llm,
        deps=object(),
        tool_specs=[],
        dispatch_tool_call=dispatch_tool_call,
        speech_sink=sink,
    )

    result = await loop.run("what is five plus ten")

    assert result.text == "Five plus ten is fifteen."


@pytest.mark.asyncio
async def test_tool_loop_discards_stale_speech_before_current_utterance() -> None:
    """Stale speech captured before this run cannot replace the current answer."""
    sink = GeminiSpeechSink()
    await sink.speak("Old lullaby text.")
    llm = FakeLLM([[{"type": "text", "content": "Current answer."}]])

    async def dispatch_tool_call(name: str, args: str, deps: object) -> dict[str, Any]:
        return {"status": "success"}

    loop = ConversationToolLoop(
        llm=llm,
        deps=object(),
        tool_specs=[],
        dispatch_tool_call=dispatch_tool_call,
        speech_sink=sink,
    )

    result = await loop.run("current question")

    assert result.text == "Current answer."
    assert sink.messages == []


@pytest.mark.asyncio
async def test_tool_loop_preserves_unavailable_camera_result_for_brain() -> None:
    """Unavailable camera results stay visible to the model for grounded responses."""
    llm = FakeLLM(
        [
            [
                {
                    "type": "tool_call",
                    "tool_call": {
                        "id": "call_camera",
                        "function": {"name": "camera", "arguments": '{"question":"what do you see?"}'},
                    },
                }
            ],
            [{"type": "text", "content": "I cannot see right now because the camera frame is unavailable."}],
        ]
    )

    async def dispatch_tool_call(name: str, args: str, deps: object) -> dict[str, Any]:
        return {"success": False, "error": "Camera frame unavailable"}

    loop = ConversationToolLoop(
        llm=llm,
        deps=object(),
        tool_specs=[],
        dispatch_tool_call=dispatch_tool_call,
    )

    result = await loop.run("what do you see?")

    assert result.text == "I cannot see right now because the camera frame is unavailable."
    assert llm.calls[1]["tool_outputs"] == [
        {
            "role": "tool",
            "content": '{"success": false, "error": "Camera frame unavailable"}',
            "tool_call_id": "call_camera",
        }
    ]
