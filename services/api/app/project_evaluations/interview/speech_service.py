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
