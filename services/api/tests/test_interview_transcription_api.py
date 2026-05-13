from __future__ import annotations

from collections.abc import Iterator
from io import BytesIO

import pytest
from fastapi.testclient import TestClient

from services.api.app.main import app
from services.api.app.project_evaluations.persistence.repository import (
    ProjectEvaluationRepository,
)

client = TestClient(app)


class FakeSpeechService:
    def __init__(self, transcript: str = "전사된 답변입니다.") -> None:
        self.transcript = transcript
        self.calls: list[dict[str, object]] = []

    def transcribe_audio(self, audio: bytes, filename: str, content_type: str | None) -> str:
        self.calls.append(
            {"audio": audio, "filename": filename, "content_type": content_type}
        )
        return self.transcript


@pytest.fixture()
def evaluation_session() -> dict[str, str]:
    create_resp = client.post(
        "/api/project-evaluations",
        json={
            "project_name": "전사 테스트 프로젝트",
            "candidate_name": "지원자",
            "description": "오디오 전사 API 테스트",
            "room_name": "전사 방",
            "room_password": "room-pass",
            "admin_password": "admin-pass",
            "question_policy": {
                "total_question_count": 1,
                "bloom_ratios": {
                    "기억": 1,
                    "이해": 0,
                    "적용": 0,
                    "분석": 0,
                    "평가": 0,
                    "창안": 0,
                },
            },
        },
    )
    assert create_resp.status_code == 200, create_resp.text
    evaluation_id = create_resp.json()["id"]
    with app.state.session_factory() as session:
        ProjectEvaluationRepository(session).save_questions(
            evaluation_id,
            [
                {
                    "question": "전사 테스트 질문입니다.",
                    "intent": "STT 검증",
                    "bloom_level": "기억",
                    "difficulty": "medium",
                    "rubric_criteria": [],
                    "source_refs": [{"path": "main.py", "snippet": "app"}],
                    "expected_signal": "전사 결과 확인",
                }
            ],
        )
    join_resp = client.post(
        f"/api/project-evaluations/{evaluation_id}/join",
        json={"participant_name": "지원자", "room_password": "room-pass"},
    )
    assert join_resp.status_code == 200, join_resp.text
    session_data = join_resp.json()["session"]
    return {
        "evaluation_id": evaluation_id,
        "session_id": session_data["id"],
        "session_token": session_data["session_token"],
    }


@pytest.fixture()
def fake_speech_service(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeSpeechService]:
    service = FakeSpeechService()

    def make_service(settings):
        return service

    monkeypatch.setattr(
        "services.api.app.project_evaluations.router.SpeechService",
        make_service,
    )
    yield service


def _headers(data: dict[str, str]) -> dict[str, str]:
    return {"X-Session-Token": data["session_token"]}


def test_transcribe_audio_returns_transcript(
    evaluation_session: dict[str, str],
    fake_speech_service: FakeSpeechService,
) -> None:
    resp = client.post(
        f"/api/project-evaluations/{evaluation_session['evaluation_id']}"
        f"/sessions/{evaluation_session['session_id']}/interview/transcribe",
        headers=_headers(evaluation_session),
        data={"mode": "answer"},
        files={"audio": ("answer.webm", BytesIO(b"audio-bytes"), "audio/webm")},
    )

    assert resp.status_code == 200, resp.text
    assert resp.json() == {"transcript": "전사된 답변입니다.", "mode": "answer"}
    assert fake_speech_service.calls == [
        {
            "audio": b"audio-bytes",
            "filename": "answer.webm",
            "content_type": "audio/webm",
        }
    ]


def test_transcribe_rejects_unsupported_audio_extension(
    evaluation_session: dict[str, str],
    fake_speech_service: FakeSpeechService,
) -> None:
    resp = client.post(
        f"/api/project-evaluations/{evaluation_session['evaluation_id']}"
        f"/sessions/{evaluation_session['session_id']}/interview/transcribe",
        headers=_headers(evaluation_session),
        data={"mode": "answer"},
        files={"audio": ("answer.txt", BytesIO(b"not audio"), "text/plain")},
    )

    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"]["stage"] == "audio_transcription"
    assert resp.json()["detail"]["reason"] == "unsupported_audio_format"
    assert fake_speech_service.calls == []


def test_transcribe_rejects_too_large_audio(
    evaluation_session: dict[str, str],
    fake_speech_service: FakeSpeechService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(app.state.settings, "OPENAI_AUDIO_MAX_UPLOAD_MB", 1)

    resp = client.post(
        f"/api/project-evaluations/{evaluation_session['evaluation_id']}"
        f"/sessions/{evaluation_session['session_id']}/interview/transcribe",
        headers=_headers(evaluation_session),
        data={"mode": "answer"},
        files={"audio": ("answer.webm", BytesIO(b"a" * (1024 * 1024 + 1)), "audio/webm")},
    )

    assert resp.status_code == 413, resp.text
    assert resp.json()["detail"]["stage"] == "audio_transcription"
    assert resp.json()["detail"]["reason"] == "audio_too_large"
    assert fake_speech_service.calls == []


def test_transcribe_failure_is_explicit_not_empty_fallback(
    evaluation_session: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingSpeechService:
        def __init__(self, settings) -> None:
            pass

        def transcribe_audio(
            self, audio: bytes, filename: str, content_type: str | None
        ) -> str:
            raise RuntimeError("forced stt failure")

    monkeypatch.setattr(
        "services.api.app.project_evaluations.router.SpeechService",
        FailingSpeechService,
    )

    resp = client.post(
        f"/api/project-evaluations/{evaluation_session['evaluation_id']}"
        f"/sessions/{evaluation_session['session_id']}/interview/transcribe",
        headers=_headers(evaluation_session),
        data={"mode": "answer"},
        files={"audio": ("answer.webm", BytesIO(b"audio-bytes"), "audio/webm")},
    )

    assert resp.status_code == 502, resp.text
    detail = resp.json()["detail"]
    assert detail["stage"] == "audio_transcription"
    assert detail["model"] == app.state.settings.OPENAI_TRANSCRIBE_MODEL
    assert detail["filename"] == "answer.webm"
    assert detail["message"] == "오디오 전사 실패: STT 처리 중 오류가 발생했습니다."
    assert "forced stt failure" not in str(detail)
    assert "transcript" not in detail
