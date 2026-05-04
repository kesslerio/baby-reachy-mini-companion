from __future__ import annotations
from dataclasses import field, dataclass


@dataclass
class GeminiSpeechSink:
    """Collect speech requested by tools when Gemini Live owns TTS."""

    messages: list[str] = field(default_factory=list)

    async def speak(self, text: str) -> None:
        """Capture text requested by the baby app speak tool."""
        text = text.strip()
        if text:
            self.messages.append(text)

    def drain(self) -> list[str]:
        """Return captured speech and clear the sink."""
        messages = self.messages
        self.messages = []
        return messages
