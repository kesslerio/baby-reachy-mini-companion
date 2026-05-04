from __future__ import annotations

import numpy as np
import pytest

from reachy_mini_conversation_app.tools.camera import Camera
from reachy_mini_conversation_app.tools.core_tools import ToolDependencies


class _CameraWorker:
    def __init__(self, frame) -> None:
        self._frame = frame

    def get_latest_frame(self):
        return self._frame


class _VisionManager:
    class Processor:
        def process_image(self, frame, question: str) -> str:
            assert frame.shape == (2, 2, 3)
            assert question == "What is here?"
            return "A desk and a Reachy Mini."

    processor = Processor()


@pytest.mark.asyncio
async def test_camera_tool_reports_unavailable_frame() -> None:
    """Camera tool results must be explicit when no post-handoff frame is available."""
    deps = ToolDependencies(
        reachy_mini=object(),
        movement_manager=object(),
        camera_worker=_CameraWorker(None),
        vision_manager=_VisionManager(),
    )

    result = await Camera()(deps, question="What is here?")

    assert result == {"success": False, "error": "Camera frame unavailable"}


@pytest.mark.asyncio
async def test_camera_tool_returns_description_for_buffered_frame() -> None:
    """Camera tool uses the buffered frame when vision processing is available."""
    frame = np.zeros((2, 2, 3), dtype=np.uint8)
    deps = ToolDependencies(
        reachy_mini=object(),
        movement_manager=object(),
        camera_worker=_CameraWorker(frame),
        vision_manager=_VisionManager(),
    )

    result = await Camera()(deps, question="What is here?")

    assert result == {"success": True, "image_description": "A desk and a Reachy Mini."}
