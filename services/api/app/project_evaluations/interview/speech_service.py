from __future__ import annotations

import logging
import time
from collections.abc import Iterator
from io import BytesIO
from typing import Any

import httpx

from services.api.app.settings import ApiSettings

SUPPORTED_AUDIO_EXTENSIONS = {
    ".flac",
    ".m4a",
    ".mp3",
    ".mp4",
    ".mpeg",
    ".mpga",
    ".ogg",
    ".wav",
    ".webm",
}

_TTS_STREAM_CHUNK_SIZE = 4096
_TTS_TIMEOUT = httpx.Timeout(connect=5.0, read=30.0, write=10.0, pool=5.0)
_TTS_RETRY_BACKOFF_SECONDS = (0.4, 0.8)

logger = logging.getLogger(__name__)


class SpeechService:
    def __init__(self, settings: ApiSettings) -> None:
        self.settings = settings
        self._client: Any | None = None
        if settings.OPENAI_API_KEY:
            from openai import OpenAI

            self._client = OpenAI(api_key=settings.OPENAI_API_KEY, timeout=_TTS_TIMEOUT)

    def transcribe_audio(
        self, audio: bytes, filename: str, content_type: str | None
    ) -> str:
        if self._client is None:
            raise RuntimeError("OpenAI API key가 설정되지 않아 오디오 전사를 수행할 수 없습니다.")
        buffer = BytesIO(audio)
        buffer.name = filename
        response = self._client.audio.transcriptions.create(
            model=self.settings.OPENAI_TRANSCRIBE_MODEL,
            file=(filename, buffer, content_type or "application/octet-stream"),
            language=self.settings.OPENAI_TRANSCRIBE_LANGUAGE,
            response_format="text",
        )
        if isinstance(response, str):
            transcript = response
        else:
            transcript = str(getattr(response, "text", ""))
        if not transcript.strip():
            raise RuntimeError("오디오 전사 결과가 비어 있습니다.")
        return transcript.strip()

    def _build_tts_kwargs(
        self,
        text: str,
        voice: str | None,
        instructions: str | None,
    ) -> dict[str, Any]:
        if not text or not text.strip():
            raise RuntimeError("음성 합성 입력 텍스트가 비어 있습니다.")
        kwargs: dict[str, Any] = {
            "model": self.settings.OPENAI_TTS_MODEL,
            "voice": voice or self.settings.OPENAI_TTS_VOICE,
            "input": text,
            "response_format": "mp3",
        }
        resolved_instructions = instructions or self.settings.OPENAI_TTS_INSTRUCTIONS
        if resolved_instructions:
            kwargs["instructions"] = resolved_instructions
        return kwargs

    def synthesize_speech_stream(
        self,
        text: str,
        voice: str | None = None,
        instructions: str | None = None,
    ) -> Iterator[bytes]:
        if self._client is None:
            raise RuntimeError("OpenAI API key가 설정되지 않아 음성 합성을 수행할 수 없습니다.")
        kwargs = self._build_tts_kwargs(text, voice, instructions)

        last_error: Exception | None = None
        attempts = len(_TTS_RETRY_BACKOFF_SECONDS) + 1
        for attempt in range(attempts):
            request_start = time.monotonic()
            produced_any = False
            try:
                with self._client.audio.speech.with_streaming_response.create(
                    **kwargs
                ) as response:
                    first_chunk_logged = False
                    for chunk in response.iter_bytes(_TTS_STREAM_CHUNK_SIZE):
                        if not chunk:
                            continue
                        if not first_chunk_logged:
                            logger.info(
                                "speech_first_byte model=%s voice=%s ms=%.1f",
                                kwargs["model"],
                                kwargs["voice"],
                                (time.monotonic() - request_start) * 1000.0,
                            )
                            first_chunk_logged = True
                        produced_any = True
                        yield chunk
                    if not produced_any:
                        raise RuntimeError("음성 합성 결과가 비어 있습니다.")
                    return
            except Exception as exc:
                last_error = exc
                if produced_any:
                    # Audio already partially delivered to caller — restarting
                    # would duplicate output. Surface the failure instead.
                    raise
                if attempt >= len(_TTS_RETRY_BACKOFF_SECONDS):
                    break
                backoff = _TTS_RETRY_BACKOFF_SECONDS[attempt]
                logger.warning(
                    "speech_retry attempt=%d backoff=%.2fs error=%s",
                    attempt + 1,
                    backoff,
                    exc,
                )
                time.sleep(backoff)

        assert last_error is not None
        raise last_error

    def synthesize_speech(
        self,
        text: str,
        voice: str | None = None,
        instructions: str | None = None,
    ) -> bytes:
        chunks = list(self.synthesize_speech_stream(text, voice, instructions))
        audio_bytes = b"".join(chunks)
        if not audio_bytes:
            raise RuntimeError("음성 합성 결과가 비어 있습니다.")
        return audio_bytes
