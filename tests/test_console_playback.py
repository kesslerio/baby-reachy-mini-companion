from __future__ import annotations
import asyncio
from types import SimpleNamespace

import numpy as np

from reachy_mini_conversation_app.console import LocalStream


class _FakeHandler:
    def __init__(self, output: tuple[int, np.ndarray]) -> None:
        self._clear_queue = None
        self.output = output

    async def emit(self):
        return self.output


class _FakeMedia:
    def __init__(self, output_sample_rate: int = 0) -> None:
        self.pushed: list[np.ndarray] = []
        self.output_sample_rate = output_sample_rate

    def get_output_audio_samplerate(self) -> int:
        return self.output_sample_rate

    def push_audio_sample(self, audio_frame: np.ndarray) -> None:
        self.pushed.append(audio_frame)


def test_play_loop_tolerates_unavailable_output_sample_rate() -> None:
    """Playback does not crash when the robot reports sample rate zero."""

    async def run_test() -> None:
        audio = np.array([0.0, 0.25, -0.25], dtype=np.float32)
        handler = _FakeHandler((24_000, audio))
        media = _FakeMedia()
        robot = SimpleNamespace(media=media)
        stream = LocalStream(handler, robot)

        original_push = media.push_audio_sample

        def push_and_stop(audio_frame: np.ndarray) -> None:
            original_push(audio_frame)
            stream._stop_event.set()

        media.push_audio_sample = push_and_stop

        await stream.play_loop()

        assert len(media.pushed) == 1
        np.testing.assert_allclose(media.pushed[0], audio)

    asyncio.run(run_test())


def test_play_loop_drops_invalid_input_sample_rate() -> None:
    """Playback skips frames that cannot be resampled safely."""

    async def run_test() -> None:
        audio = np.array([0.0, 0.25, -0.25], dtype=np.float32)
        handler = _FakeHandler((0, audio))
        media = _FakeMedia()
        robot = SimpleNamespace(media=media)
        stream = LocalStream(handler, robot)
        original_emit = handler.emit

        async def emit_once():
            stream._stop_event.set()
            return await original_emit()

        handler.emit = emit_once

        await stream.play_loop()

        assert media.pushed == []

    asyncio.run(run_test())


def test_play_loop_drops_tiny_resample_frames() -> None:
    """Playback skips frames that would resample to zero output samples."""

    async def run_test() -> None:
        handler = _FakeHandler((24_000, np.array([0.25], dtype=np.float32)))
        media = _FakeMedia(output_sample_rate=16_000)
        robot = SimpleNamespace(media=media)
        stream = LocalStream(handler, robot)
        original_emit = handler.emit

        async def emit_once():
            stream._stop_event.set()
            return await original_emit()

        handler.emit = emit_once

        await stream.play_loop()

        assert media.pushed == []

    asyncio.run(run_test())
