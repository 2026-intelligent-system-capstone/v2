from __future__ import annotations

from io import BytesIO
from typing import Any

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


class SpeechService:
    def __init__(self, settings: ApiSettings) -> None:
        self.settings = settings
        self._client: Any | None = None
        if settings.OPENAI_API_KEY:
            from openai import OpenAI

            self._client = OpenAI(api_key=settings.OPENAI_API_KEY)

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

    def synthesize_speech(
        self,
        text: str,
        voice: str | None = None,
        instructions: str | None = None,
    ) -> bytes:
        if self._client is None:
            raise RuntimeError("OpenAI API key가 설정되지 않아 음성 합성을 수행할 수 없습니다.")
        if not text or not text.strip():
            raise RuntimeError("음성 합성 입력 텍스트가 비어 있습니다.")
        create_kwargs: dict[str, Any] = {
            "model": self.settings.OPENAI_TTS_MODEL,
            "voice": voice or self.settings.OPENAI_TTS_VOICE,
            "input": text,
            "response_format": "mp3",
        }
        resolved_instructions = instructions or self.settings.OPENAI_TTS_INSTRUCTIONS
        if resolved_instructions:
            create_kwargs["instructions"] = resolved_instructions
        response = self._client.audio.speech.create(**create_kwargs)
        if hasattr(response, "read"):
            audio_bytes = response.read()
        elif hasattr(response, "content"):
            audio_bytes = response.content
        else:
            audio_bytes = bytes(response)
        if not audio_bytes:
            raise RuntimeError("음성 합성 결과가 비어 있습니다.")
        return audio_bytes
