from __future__ import annotations
from types import SimpleNamespace

from reachy_mini_conversation_app.console import LocalStream
from reachy_mini_conversation_app.media_runtime import MediaPreparationStatus


class _FakeHandler:
    def __init__(self) -> None:
        self._clear_queue = None


class _FakeMedia:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def start_recording(self) -> None:
        self.calls.append("start_recording")

    def start_playing(self) -> None:
        self.calls.append("start_playing")


class _FakeMediaRuntime:
    def __init__(self, calls: list[str]) -> None:
        self.calls = calls

    def prepare_for_audio_start(self) -> MediaPreparationStatus:
        self.calls.append("prepare")
        return MediaPreparationStatus()


def test_sdk_media_start_prepares_before_recording_and_playback() -> None:
    """SDK audio mode releases daemon media before app recording/playback starts."""
    media = _FakeMedia()
    runtime_calls: list[str] = []
    robot = SimpleNamespace(media=media)
    stream = LocalStream(_FakeHandler(), robot, media_runtime=_FakeMediaRuntime(runtime_calls))

    stream._prepare_and_start_media()

    assert runtime_calls == ["prepare"]
    assert media.calls == ["start_recording", "start_playing"]


def test_direct_mic_mode_prepares_before_sdk_playback_only() -> None:
    """Direct mic mode still prepares daemon media because playback uses the SDK."""
    media = _FakeMedia()
    runtime_calls: list[str] = []
    robot = SimpleNamespace(media=media)
    stream = LocalStream(_FakeHandler(), robot, media_runtime=_FakeMediaRuntime(runtime_calls))
    stream._mic_device = 3

    stream._prepare_and_start_media()

    assert runtime_calls == ["prepare"]
    assert media.calls == ["start_playing"]
