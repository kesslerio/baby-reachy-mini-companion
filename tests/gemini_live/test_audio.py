from __future__ import annotations

import numpy as np

from reachy_mini_conversation_app.gemini_live.audio import pcm16_bytes, pcm16_frame


def test_pcm16_round_trip() -> None:
    """PCM helpers preserve signed sample values."""
    audio = np.array([0.0, 0.5, -0.5], dtype=np.float32)

    data = pcm16_bytes(audio, 16000, 16000)
    frame = pcm16_frame(data)

    assert frame.dtype == np.int16
    assert frame.tolist() == [0, 16383, -16383]
