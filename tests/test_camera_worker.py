from __future__ import annotations
from types import SimpleNamespace

import numpy as np

from reachy_mini_conversation_app.camera_worker import CameraWorker


def test_camera_worker_recovers_after_transient_frame_error(monkeypatch) -> None:
    """A transient media error does not permanently disable camera buffering."""
    frame = np.ones((2, 2, 3), dtype=np.uint8)
    calls = {"frames": 0, "sleeps": 0}

    def get_frame():
        calls["frames"] += 1
        if calls["frames"] == 1:
            raise RuntimeError("camera stream reset")
        return frame

    robot = SimpleNamespace(media=SimpleNamespace(get_frame=get_frame))
    worker = CameraWorker(robot)

    def sleep(_duration: float) -> None:
        calls["sleeps"] += 1
        if calls["sleeps"] >= 2:
            worker._stop_event.set()

    monkeypatch.setattr("time.sleep", sleep)

    worker.working_loop()

    buffered = worker.get_latest_frame()
    assert buffered is not None
    assert worker.last_frame_at is not None
    np.testing.assert_array_equal(buffered, frame)
    assert buffered is not frame
