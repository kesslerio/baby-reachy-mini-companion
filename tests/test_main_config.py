from __future__ import annotations
from types import SimpleNamespace

from reachy_mini_conversation_app.main import _load_instance_voice_settings
from reachy_mini_conversation_app.config import config
from reachy_mini_conversation_app.console import LocalStream


def test_load_instance_voice_settings_applies_runtime_settings(tmp_path, monkeypatch) -> None:
    """Instance .env values are available before startup components are created."""
    env_path = tmp_path / ".env"
    env_path.write_text(
        "\n".join(
            [
                "VOICE_FRONTEND=gemini_live",
                "GEMINI_API_KEY=test-key",
                "GEMINI_MODEL=gemini-live-test",
                "GEMINI_VOICE=Kore",
                "LOCAL_LLM_URL=http://127.0.0.1:11435/v1",
                "LOCAL_LLM_MODEL=reachy-companion",
                "LOCAL_LLM_API_KEY=sidecar",
                "LOCAL_STT_MODEL=tiny.en",
                "SIGNAL_USER_PHONE=+15555550123",
                "MIC_GAIN=1.5",
                "RELEASE_DAEMON_MEDIA=false",
                "CLEAN_STALE_ALSA_IPC=false",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(config, "VOICE_FRONTEND", "local")
    monkeypatch.setattr(config, "GEMINI_API_KEY", "")
    monkeypatch.setattr(config, "GEMINI_MODEL", "gemini-3.1-flash-live-preview")
    monkeypatch.setattr(config, "GEMINI_VOICE", "Kore")
    monkeypatch.setattr(config, "LOCAL_LLM_URL", "http://localhost:11434/v1")
    monkeypatch.setattr(config, "LOCAL_LLM_MODEL", "ministral-3:3b")
    monkeypatch.setattr(config, "LOCAL_LLM_API_KEY", "ollama")
    monkeypatch.setattr(config, "LOCAL_STT_MODEL", "small.en")
    monkeypatch.setattr(config, "SIGNAL_USER_PHONE", None)
    monkeypatch.setattr(config, "MIC_GAIN", 1.0)
    monkeypatch.setattr(config, "RELEASE_DAEMON_MEDIA", True)
    monkeypatch.setattr(config, "CLEAN_STALE_ALSA_IPC", True)

    _load_instance_voice_settings(str(tmp_path))

    assert config.VOICE_FRONTEND == "gemini_live"
    assert config.GEMINI_API_KEY == "test-key"
    assert config.GEMINI_MODEL == "gemini-live-test"
    assert config.LOCAL_LLM_URL == "http://127.0.0.1:11435/v1"
    assert config.LOCAL_LLM_MODEL == "reachy-companion"
    assert config.LOCAL_LLM_API_KEY == "sidecar"
    assert config.LOCAL_STT_MODEL == "tiny.en"
    assert config.SIGNAL_USER_PHONE == "+15555550123"
    assert config.MIC_GAIN == 1.5
    assert config.RELEASE_DAEMON_MEDIA is False
    assert config.CLEAN_STALE_ALSA_IPC is False


def test_local_settings_do_not_persist_numeric_mic_device(tmp_path) -> None:
    """Mic device indexes are per-boot diagnostics and must not become durable config."""

    class FakeHandler:
        def __init__(self) -> None:
            self._clear_queue = None

    robot = SimpleNamespace(media=SimpleNamespace())
    stream = LocalStream(FakeHandler(), robot, instance_path=str(tmp_path))

    stream._persist_local_llm_settings(
        {
            "LOCAL_LLM_URL": "http://127.0.0.1:11435/v1",
            "LOCAL_LLM_MODEL": "reachy-companion",
            "LOCAL_LLM_API_KEY": "sidecar",
            "LOCAL_STT_MODEL": "tiny.en",
            "MIC_GAIN": "1.5",
            "MIC_DEVICE": "3",
        }
    )

    env_text = (tmp_path / ".env").read_text(encoding="utf-8")

    assert "MIC_GAIN=\"1.5\"" in env_text
    assert "MIC_DEVICE" not in env_text
