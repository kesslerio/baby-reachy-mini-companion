from __future__ import annotations

import numpy as np
from scipy.signal import resample


def pcm16_frame(data: bytes) -> np.ndarray:
    """Convert little-endian PCM16 bytes to a numpy int16 frame."""
    return np.frombuffer(data, dtype=np.int16)


def pcm16_bytes(audio: np.ndarray, input_sample_rate: int, output_sample_rate: int) -> bytes:
    """Convert robot audio frames to little-endian PCM16 bytes."""
    if audio.size == 0:
        return b""

    if audio.dtype == np.float32:
        audio_float = audio.copy()
    else:
        audio_float = audio.astype(np.float32) / 32768.0

    if audio_float.ndim > 1:
        audio_float = np.mean(audio_float, axis=1)

    if input_sample_rate != output_sample_rate:
        audio_float = resample(audio_float, int(len(audio_float) * output_sample_rate / input_sample_rate))

    clipped = np.clip(audio_float, -1.0, 1.0)
    return (clipped * 32767.0).astype(np.int16).tobytes()
