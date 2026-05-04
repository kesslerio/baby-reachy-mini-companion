from __future__ import annotations

import pytest

from reachy_mini_conversation_app.local import llm as llm_module


class _EmptyStream:
    def __aiter__(self):
        return self

    async def __anext__(self):
        raise StopAsyncIteration


@pytest.mark.asyncio
async def test_local_llm_disables_reasoning_for_openai_compatible_chat(monkeypatch) -> None:
    """Ollama Cloud thinking models should return spoken content, not reasoning-only deltas."""
    captured: dict[str, object] = {}

    class _FakeCompletions:
        async def create(self, **kwargs):
            captured.update(kwargs)
            return _EmptyStream()

    class _FakeClient:
        def __init__(self, **_kwargs) -> None:
            self.chat = type("Chat", (), {"completions": _FakeCompletions()})()

    monkeypatch.setattr(llm_module, "AsyncOpenAI", _FakeClient)

    client = llm_module.LocalLLM(base_url="http://127.0.0.1:11435/v1", model="reachy-companion", api_key="sidecar")
    tools = [{"type": "function", "function": {"name": "move_head"}}]
    async for _event in client.chat_stream(user_text="hello", tools=tools):
        pass

    assert captured["reasoning_effort"] == "none"
    assert captured["tools"] == tools
    assert captured["parallel_tool_calls"] is False
