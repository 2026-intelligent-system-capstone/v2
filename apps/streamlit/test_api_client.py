import pytest
import requests

from apps.streamlit.api_client import ApiClientError, get_api_base_url, get_health


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
