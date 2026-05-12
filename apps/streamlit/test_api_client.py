import pytest
import requests

from apps.streamlit.api_client import (
    ApiClientError,
    create_evaluation,
    get_api_base_url,
    get_evaluation_status,
    get_health,
    list_questions,
)


class FakeResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return self.payload


def test_get_api_base_url_uses_env_value_without_trailing_slash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("API_BASE_URL", "http://api.example.test/")

    assert get_api_base_url() == "http://api.example.test"


def test_get_health_returns_json_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {"status": "ok"}

    def fake_get(url: str, timeout: int) -> FakeResponse:
        assert url == "http://localhost:8000/health"
        assert timeout == 5
        return FakeResponse(payload)

    monkeypatch.delenv("API_BASE_URL", raising=False)
    monkeypatch.setattr(requests, "get", fake_get)

    assert get_health() == payload


def test_get_health_raises_api_client_error_on_request_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_get(url: str, timeout: int) -> FakeResponse:
        raise requests.Timeout("timeout")

    monkeypatch.setattr(requests, "get", fake_get)

    with pytest.raises(ApiClientError, match="FastAPI 서버 상태를 확인할 수 없습니다."):
        get_health()


def test_get_evaluation_status_sends_admin_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = {
        "evaluation_id": "evaluation-1",
        "phase": "questions_ready",
        "question_count": 6,
        "can_join": True,
    }

    def fake_request(
        method: str,
        url: str,
        timeout: int,
        **kwargs: object,
    ) -> FakeResponse:
        assert method == "GET"
        assert url == "http://localhost:8000/api/project-evaluations/evaluation-1/status"
        assert timeout == 30
        assert kwargs["headers"] == {"X-Admin-Password": "admin-pass"}
        return FakeResponse(payload)

    monkeypatch.delenv("API_BASE_URL", raising=False)
    monkeypatch.setattr(requests, "request", fake_request)

    assert get_evaluation_status("evaluation-1", "admin-pass") == payload


def test_list_questions_sends_admin_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = [{"id": "question-1", "question": "자료 기반 질문"}]

    class FakeListResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> list[dict[str, object]]:
            return payload

    def fake_request(
        method: str,
        url: str,
        timeout: int,
        **kwargs: object,
    ) -> FakeListResponse:
        assert method == "GET"
        assert url == "http://localhost:8000/api/project-evaluations/evaluation-1/questions"
        assert timeout == 30
        assert kwargs["headers"] == {"X-Admin-Password": "admin-pass"}
        return FakeListResponse()

    monkeypatch.delenv("API_BASE_URL", raising=False)
    monkeypatch.setattr(requests, "request", fake_request)

    assert list_questions("evaluation-1", "admin-pass") == payload


def test_create_evaluation_includes_question_policy_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    question_policy = {
        "total_questions": 20,
        "bloom_ratios": {
            "기억": 1,
            "이해": 1,
            "적용": 1,
            "분석": 1,
            "평가": 1,
            "창안": 1,
        },
        "planned_counts": {
            "기억": 4,
            "이해": 4,
            "적용": 3,
            "분석": 3,
            "평가": 3,
            "창안": 3,
        },
    }
    expected_payload = {
        "project_name": "Portfolio Verifier",
        "candidate_name": "Kim Candidate",
        "description": "Check project authorship",
        "room_name": "demo-room",
        "room_password": "room-pass",
        "admin_password": "admin-pass",
        "question_policy": question_policy,
    }

    def fake_request(
        method: str,
        url: str,
        timeout: int,
        **kwargs: object,
    ) -> FakeResponse:
        assert method == "POST"
        assert url == "http://localhost:8000/api/project-evaluations"
        assert timeout == 30
        assert kwargs["json"] == expected_payload
        assert kwargs["json"]["question_policy"] is question_policy
        return FakeResponse({"id": "evaluation-1"})

    monkeypatch.delenv("API_BASE_URL", raising=False)
    monkeypatch.setattr(requests, "request", fake_request)

    assert create_evaluation(
        project_name="Portfolio Verifier",
        candidate_name="Kim Candidate",
        description="Check project authorship",
        room_name="demo-room",
        room_password="room-pass",
        admin_password="admin-pass",
        question_policy=question_policy,
    ) == {"id": "evaluation-1"}
