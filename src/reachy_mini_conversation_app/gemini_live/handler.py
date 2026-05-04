from __future__ import annotations
import time
import base64
import asyncio
import logging
from typing import Any, Final, Tuple, Literal
from dataclasses import replace

import numpy as np

from reachy_mini_conversation_app.config import config
from reachy_mini_conversation_app.prompts import get_session_instructions
from reachy_mini_conversation_app.local.llm import LocalLLM
from reachy_mini_conversation_app.local.handler import LocalSessionHandler
from reachy_mini_conversation_app.tools.core_tools import ToolDependencies, get_tool_specs, dispatch_tool_call
from reachy_mini_conversation_app.gemini_live.audio import pcm16_bytes, pcm16_frame
from reachy_mini_conversation_app.conversation.tool_loop import ConversationToolLoop
from reachy_mini_conversation_app.conversation.speech_sink import GeminiSpeechSink


logger = logging.getLogger(__name__)

GEMINI_INPUT_SAMPLE_RATE: Final[Literal[16000]] = 16000
GEMINI_OUTPUT_SAMPLE_RATE: Final[Literal[24000]] = 24000

DEFAULT_GEMINI_SYSTEM_INSTRUCTION = """You are Reachy Mini's voice front-end.
You are not the reasoning brain and you do not choose robot actions.
For every user utterance, call handle_user_utterance with the full transcript.
Speak the returned answer naturally and do not add extra claims about robot actions."""


def build_function_declarations() -> list[dict[str, Any]]:
    """Build the single Gemini function that hands control to the baby app."""
    return [
        {
            "name": "handle_user_utterance",
            "description": (
                "MANDATORY: call this for every user utterance. This local function runs the "
                "baby companion prompt, DeepSeek/Ollama sidecar brain, and robot tool dispatcher. "
                "Do not answer directly when this function is available."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The user's complete utterance transcript.",
                    }
                },
                "required": ["query"],
            },
        }
    ]


def build_live_config() -> dict[str, Any]:
    """Build Gemini Live session configuration for voice-front-end mode."""
    live_config: dict[str, Any] = {
        "response_modalities": ["AUDIO"],
        "system_instruction": config.GEMINI_SYSTEM_INSTRUCTION or DEFAULT_GEMINI_SYSTEM_INSTRUCTION,
        "input_audio_transcription": {},
        "output_audio_transcription": {},
        "tools": [{"function_declarations": build_function_declarations()}],
    }

    if config.GEMINI_VOICE:
        live_config["speech_config"] = {
            "voice_config": {
                "prebuilt_voice_config": {"voice_name": config.GEMINI_VOICE},
            },
        }

    return live_config


class GeminiLiveSessionHandler(LocalSessionHandler):
    """Gemini Live voice front-end backed by the baby companion tool loop."""

    def __init__(
        self,
        deps: ToolDependencies,
        llm_url: str | None = None,
        llm_model: str | None = None,
        enable_signal: bool = True,
    ) -> None:
        """Initialize Gemini mode while preserving the local handler contract."""
        super().__init__(deps, llm_url, llm_model, enable_signal)
        self.deps.speak_func = self._ignore_background_speech_tool
        self.client: Any = None
        self.connection: Any = None
        self.types: Any = None
        self.tool_loop: ConversationToolLoop | None = None
        self._tool_loop_lock = asyncio.Lock()
        self._assistant_transcript_parts: list[str] = []
        self._shutdown_requested = False

    def copy(self) -> "GeminiLiveSessionHandler":
        """Create a handler copy for stream managers that need clone support."""
        return GeminiLiveSessionHandler(self.deps, self.llm_url, self.llm_model, self.enable_signal)

    async def start_up(self) -> None:
        """Start Gemini Live and lightweight baby companion services."""
        if not config.GEMINI_API_KEY:
            raise ValueError("GEMINI_API_KEY is required when VOICE_FRONTEND=gemini_live")

        from google import genai
        from google.genai import types

        self.client = genai.Client(api_key=config.GEMINI_API_KEY)
        self.types = types

        exclusions = self._build_tool_exclusions()
        if exclusions:
            logger.info("Feature flags: excluding tools %s", exclusions)
        self.tool_specs = get_tool_specs(exclusion_list=exclusions)

        logger.info("Loading baby companion LLM client for Gemini Live mode")
        self.llm = LocalLLM(base_url=self.llm_url, model=self.llm_model, api_key=config.LOCAL_LLM_API_KEY)
        self.llm.set_system_prompt(get_session_instructions())
        self.tool_loop = ConversationToolLoop(
            llm=self.llm,
            deps=self.deps,
            tool_specs=self.tool_specs,
            dispatch_tool_call=dispatch_tool_call,
        )

        await self._start_lightweight_services()
        await self._run_live_session()

    async def receive(self, frame: Tuple[int, np.ndarray]) -> None:
        """Forward microphone audio to Gemini and keep cry detection active."""
        await self._process_audio_classifier_frame(frame)

        if self.connection is None or self.types is None:
            return

        sample_rate, audio = frame
        audio_bytes = pcm16_bytes(audio, sample_rate, GEMINI_INPUT_SAMPLE_RATE)
        if not audio_bytes:
            return

        try:
            await self.connection.send_realtime_input(
                audio=self.types.Blob(
                    data=audio_bytes,
                    mime_type=f"audio/pcm;rate={GEMINI_INPUT_SAMPLE_RATE}",
                )
            )
        except Exception as exc:
            logger.warning("Gemini Live input stream closed: %s", exc)
            self.connection = None

    async def shutdown(self):
        """Close Gemini Live and inherited background services."""
        self._shutdown_requested = True
        if self.connection is not None:
            try:
                await self.connection.close()
            except Exception as exc:
                logger.debug("Gemini connection close failed: %s", exc)
            self.connection = None
        await super().shutdown()

    async def _run_live_session(self) -> None:
        while not self._shutdown_requested:
            logger.info("Connecting to Gemini Live model=%s voice=%s", config.GEMINI_MODEL, config.GEMINI_VOICE)
            try:
                async with self.client.aio.live.connect(
                    model=config.GEMINI_MODEL, config=build_live_config()
                ) as session:
                    self.connection = session
                    logger.info("Gemini Live session ready with baby companion tool loop")
                    async for response in session.receive():
                        if self._shutdown_requested:
                            return
                        await self._handle_response(response)
            except Exception as exc:
                if not self._shutdown_requested:
                    logger.warning("Gemini Live session ended: %s; reconnecting", exc)
                    await self._sleep_before_reconnect()
            finally:
                self.connection = None

    async def _sleep_before_reconnect(self) -> None:
        import asyncio

        await asyncio.sleep(1)

    async def _handle_response(self, response: Any) -> None:
        data = getattr(response, "data", None)
        if data is not None:
            await self._queue_audio(data)

        tool_call = getattr(response, "tool_call", None)
        if tool_call is not None:
            await self._handle_tool_call(tool_call)

        server_content = getattr(response, "server_content", None)
        if server_content is not None:
            await self._handle_server_content(server_content, queue_model_audio=data is None)

    async def _handle_server_content(self, server_content: Any, queue_model_audio: bool = True) -> None:
        input_transcription = getattr(server_content, "input_transcription", None)
        if input_transcription is not None:
            transcript = getattr(input_transcription, "text", "") or ""
            if transcript.strip() and getattr(input_transcription, "finished", True):
                logger.info("User transcript: %s", transcript.strip())

        output_transcription = getattr(server_content, "output_transcription", None)
        if output_transcription is not None:
            text = getattr(output_transcription, "text", "") or ""
            if text:
                self._assistant_transcript_parts.append(text)
            if getattr(output_transcription, "finished", False):
                self._log_assistant_transcript()

        model_turn = getattr(server_content, "model_turn", None)
        if queue_model_audio and model_turn is not None:
            for part in getattr(model_turn, "parts", []) or []:
                inline_data = getattr(part, "inline_data", None)
                if inline_data is not None:
                    await self._queue_audio(getattr(inline_data, "data", b""))

        if getattr(server_content, "turn_complete", False):
            self._log_assistant_transcript()

    async def _queue_audio(self, data: bytes | str) -> None:
        audio_bytes = base64.b64decode(data) if isinstance(data, str) else data
        if audio_bytes:
            await self.output_queue.put((GEMINI_OUTPUT_SAMPLE_RATE, pcm16_frame(audio_bytes)))

    async def _handle_tool_call(self, tool_call: Any) -> None:
        if self.tool_loop is None:
            return

        function_calls = getattr(tool_call, "function_calls", []) or []
        responses = []

        for function_call in function_calls:
            name = getattr(function_call, "name", "")
            args = getattr(function_call, "args", {}) or {}
            call_id = getattr(function_call, "id", None)
            started_at = time.monotonic()

            if name != "handle_user_utterance":
                answer = f"Unknown Gemini Live tool: {name}"
            else:
                query = str(args.get("query", "")).strip()
                logger.info("Baby tool loop started chars=%d", len(query))
                result = await self._run_tool_loop_for_utterance(query)
                answer = result.text
                logger.info(
                    "Baby tool loop finished elapsedMs=%d tools=%s",
                    int((time.monotonic() - started_at) * 1000),
                    [item.name for item in result.tool_executions],
                )

            responses.append(self.types.FunctionResponse(id=call_id, name=name, response={"answer": answer}))

        if self.connection is not None and responses:
            await self.connection.send_tool_response(function_responses=responses)

    async def _run_tool_loop_for_utterance(self, query: str):
        tool_loop = self.tool_loop
        if tool_loop is None:
            raise RuntimeError("Gemini Live tool loop is not initialized")

        async with self._tool_loop_lock:
            speech_sink = GeminiSpeechSink()
            utterance_loop = ConversationToolLoop(
                llm=tool_loop.llm,
                deps=replace(self.deps, speak_func=speech_sink.speak),
                tool_specs=tool_loop.tool_specs,
                dispatch_tool_call=tool_loop.dispatch_tool_call,
                speech_sink=speech_sink,
                max_turns=tool_loop.max_turns,
            )
            return await utterance_loop.run(query)

    async def _ignore_background_speech_tool(self, text: str) -> None:
        logger.info("Ignoring background speak tool text while Gemini owns voice output: %d chars", len(text))

    async def _start_lightweight_services(self) -> None:
        import asyncio

        if config.FEATURE_CRY_DETECTION:
            logger.info("Loading Audio Classifier (YAMNet) for Gemini Live mode...")
            try:
                from reachy_mini_conversation_app.audio.classifier import AudioClassifier

                self.classifier = await asyncio.to_thread(AudioClassifier)
            except ImportError:
                logger.info("onnxruntime not installed, audio classification disabled.")
            except Exception as exc:
                logger.warning("Audio Classifier failed to load: %s", exc)
        else:
            logger.info("Baby cry detection disabled by feature flag.")

        if config.FEATURE_DANGER_DETECTION and self.deps.camera_worker is not None:
            logger.info("Loading Danger Detector (YOLO) for Gemini Live mode...")
            try:
                from reachy_mini_conversation_app.vision.danger_detector import DangerDetector

                self.danger_detector = await asyncio.to_thread(DangerDetector)  # type: ignore[func-returns-value,arg-type]
                self.danger_detection_task = asyncio.create_task(self._poll_danger_detection())
                logger.info("Danger detection started.")
            except ImportError:
                logger.info("YOLO not installed, danger detection disabled.")
            except Exception as exc:
                logger.warning("Danger Detector failed to load: %s", exc)
        elif not config.FEATURE_DANGER_DETECTION:
            logger.info("Danger detection disabled by feature flag.")

        if self.enable_signal and config.FEATURE_SIGNAL_ALERTS:
            from reachy_mini_conversation_app.input.signal_interface import SignalInterface

            self.signal = SignalInterface()
            if self.signal.available:
                self.signal_polling_task = asyncio.create_task(self._poll_signal())
                logger.info("Signal polling started.")
            else:
                logger.info("Signal not available, skipping.")
        elif not config.FEATURE_SIGNAL_ALERTS:
            logger.info("Signal alerts disabled by feature flag.")

    async def _process_audio_classifier_frame(self, frame: Tuple[int, np.ndarray]) -> None:
        import asyncio

        if self.classifier is None:
            return

        sample_rate, audio = frame
        audio_float = audio.copy() if audio.dtype == np.float32 else audio.astype(np.float32) / 32768.0
        if audio_float.ndim > 1:
            audio_float = np.mean(audio_float, axis=1)
        if sample_rate != 16000:
            from scipy.signal import resample

            audio_float = resample(audio_float, int(len(audio_float) * 16000 / sample_rate))

        self.classifier_buffer = np.concatenate((self.classifier_buffer, audio_float))
        if len(self.classifier_buffer) < 16000:
            return

        chunk_to_classify = self.classifier_buffer[:16000]
        self.classifier_buffer = self.classifier_buffer[16000:]
        now = time.time()
        if now - self.last_cry_time <= 10.0:
            return

        results = await asyncio.to_thread(self.classifier.classify, chunk_to_classify)
        for label, score in results:
            if label in ["Baby cry, infant cry", "Crying, sobbing", "Whimper"] and score > 0.4:
                logger.info("Audio Event Detected: %s (%.2f)", label, score)
                self.last_cry_time = now
                if self.deps.audio_classifier_status is not None:
                    self.deps.audio_classifier_status["latest_event"] = label
                    self.deps.audio_classifier_status["timestamp"] = now
                    self.deps.audio_classifier_status["score"] = float(score)
                asyncio.create_task(self._process_system_event(f"I hear a {label.lower()} nearby."))
                if config.FEATURE_SIGNAL_ALERTS and config.SIGNAL_USER_PHONE:
                    asyncio.create_task(self._send_cry_photo_alert())
                break

    def _log_assistant_transcript(self) -> None:
        transcript = "".join(self._assistant_transcript_parts).strip()
        self._assistant_transcript_parts = []
        if transcript:
            logger.info("Assistant transcript: %s", transcript[:160])
