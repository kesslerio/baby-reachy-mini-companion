from __future__ import annotations
import json
import logging
from typing import Any, Callable, Sequence, Awaitable
from dataclasses import field, dataclass

from reachy_mini_conversation_app.conversation.speech_sink import GeminiSpeechSink


logger = logging.getLogger(__name__)

ToolDispatcher = Callable[[str, str, Any], Awaitable[dict[str, Any]]]


@dataclass
class ToolExecution:
    """A tool call executed by the baby companion dispatcher."""

    name: str
    result: dict[str, Any]


@dataclass
class ToolLoopResult:
    """Final text and tool execution metadata from one user utterance."""

    text: str
    tool_executions: list[ToolExecution] = field(default_factory=list)


class ConversationToolLoop:
    """Run the baby companion LLM/tool loop for non-local voice front-ends."""

    def __init__(
        self,
        *,
        llm: Any,
        deps: Any,
        tool_specs: Sequence[dict[str, Any]],
        dispatch_tool_call: ToolDispatcher,
        speech_sink: GeminiSpeechSink | None = None,
        max_turns: int = 5,
    ) -> None:
        """Initialize the loop with an LLM client and tool dispatcher."""
        self.llm = llm
        self.deps = deps
        self.tool_specs = list(tool_specs)
        self.dispatch_tool_call = dispatch_tool_call
        self.speech_sink = speech_sink
        self.max_turns = max_turns

    async def run(self, user_text: str) -> ToolLoopResult:
        """Process user text through the model and existing baby tools."""
        turn = 0
        tool_outputs: list[dict[str, Any]] | None = None
        final_text = ""
        tool_executions: list[ToolExecution] = []

        while turn < self.max_turns:
            turn += 1
            llm_user_input = user_text if turn == 1 else None
            response_text = ""
            tool_calls: list[dict[str, Any]] = []

            logger.info("LLM turn %d via Gemini voice front-end", turn)
            async for event in self.llm.chat_stream(
                user_text=llm_user_input,
                tools=self.tool_specs,
                tool_outputs=tool_outputs,
            ):
                event_type = event.get("type")
                if event_type == "text":
                    response_text += str(event.get("content", ""))
                elif event_type == "tool_call":
                    tool_call = event.get("tool_call")
                    if isinstance(tool_call, dict):
                        tool_calls.append(tool_call)
                elif event_type == "error":
                    logger.error("LLM error: %s", event.get("content"))

            if response_text.strip():
                final_text = response_text.strip()

            if not tool_calls:
                break

            tool_outputs = []
            for tool_call in tool_calls:
                function = tool_call.get("function", {})
                if not isinstance(function, dict):
                    continue

                function_name = str(function.get("name", "")).strip()
                arguments = str(function.get("arguments", "") or "{}")
                call_id = str(tool_call.get("id", f"call_{len(tool_outputs)}"))
                if not function_name:
                    continue

                logger.info("Tool call from baby brain: %s(%s)", function_name, arguments)
                result = await self.dispatch_tool_call(function_name, arguments, self.deps)
                tool_executions.append(ToolExecution(name=function_name, result=result))
                result_text = json.dumps(result)
                tool_outputs.append({"role": "tool", "content": result_text, "tool_call_id": call_id})
                logger.info("Tool result: %s", result_text)

        if self.speech_sink is not None:
            captured_speech = " ".join(self.speech_sink.drain()).strip()
            if captured_speech:
                final_text = captured_speech

        if not final_text:
            final_text = "I handled that, but I do not have anything else to say."

        return ToolLoopResult(text=final_text, tool_executions=tool_executions)
