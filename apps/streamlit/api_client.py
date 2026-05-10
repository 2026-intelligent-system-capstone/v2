import os
from typing import BinaryIO

import requests
from requests import Response


class ApiClientError(RuntimeError):
    pass


def get_api_base_url() -> str:
    return os.getenv("API_BASE_URL", "http://localhost:8000").rstrip("/")


def request_json(method: str, path: str, timeout: int = 30, **kwargs: object) -> object:
    url = f"{get_api_base_url()}{path}"
    try:
        response = requests.request(method, url, timeout=timeout, **kwargs)
        response.raise_for_status()
        return response.json()
    except ValueError as exc:
        content_type = response.headers.get("content-type", "-")
        raise ApiClientError(
            "FastAPI 서버 응답을 JSON으로 해석할 수 없습니다. "
            f"요청={method} {url}, 상태={response.status_code}, "
            f"Content-Type={content_type}. API_BASE_URL이 FastAPI 서버 주소인지 확인하세요."
        ) from exc
    except requests.HTTPError as exc:
        response = exc.response
        detail = _error_detail(response) if response is not None else str(exc)
        raise ApiClientError(
            f"FastAPI 서버 요청에 실패했습니다. 요청={method} {url}. {detail}"
        ) from exc
    except requests.RequestException as exc:
        raise ApiClientError(f"FastAPI 서버 요청에 실패했습니다. 요청={method} {url}") from exc


def _error_detail(response: Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return f"상태={response.status_code}, 응답={response.text[:300]}"
    if isinstance(payload, dict):
        detail = payload.get("detail")
        if isinstance(detail, str):
            return detail
        if isinstance(detail, list):
            return "; ".join(str(item) for item in detail[:3])
    return f"상태={response.status_code}, 응답={str(payload)[:300]}"


def request_json_dict(
    method: str, path: str, timeout: int = 30, **kwargs: object
) -> dict[str, object]:
    payload = request_json(method, path, timeout=timeout, **kwargs)
    if not isinstance(payload, dict):
        raise ApiClientError("FastAPI 서버 응답 형식이 올바르지 않습니다.")
    return payload


def request_json_list(
    method: str, path: str, timeout: int = 30, **kwargs: object
) -> list[dict[str, object]]:
    payload = request_json(method, path, timeout=timeout, **kwargs)
    if not isinstance(payload, list) or not all(
        isinstance(item, dict) for item in payload
    ):
        raise ApiClientError("FastAPI 서버 응답 형식이 올바르지 않습니다.")
    return payload


def get_health() -> dict[str, object]:
    url = f"{get_api_base_url()}/health"
    try:
        response = requests.get(url, timeout=5)
        response.raise_for_status()
        payload = response.json()
    except ValueError as exc:
        raise ApiClientError("FastAPI 서버 상태 응답을 해석할 수 없습니다.") from exc
    except requests.RequestException as exc:
        raise ApiClientError("FastAPI 서버 상태를 확인할 수 없습니다.") from exc
    if not isinstance(payload, dict):
        raise ApiClientError("FastAPI 서버 상태 응답 형식이 올바르지 않습니다.")
    return payload


def create_evaluation(
    project_name: str,
    candidate_name: str = "",
    description: str = "",
    room_name: str = "",
    room_password: str = "",
    admin_password: str = "",
) -> dict[str, object]:
    return request_json_dict(
        "POST",
        "/api/project-evaluations",
        json={
            "project_name": project_name,
            "candidate_name": candidate_name,
            "description": description,
            "room_name": room_name,
            "room_password": room_password,
            "admin_password": admin_password,
        },
    )


def verify_admin(evaluation_id: str, admin_password: str) -> dict[str, object]:
    return request_json_dict(
        "POST",
        f"/api/project-evaluations/{evaluation_id}/admin/verify",
        json={"admin_password": admin_password},
    )


def join_evaluation(
    evaluation_id: str, participant_name: str, room_password: str
) -> dict[str, object]:
    return request_json_dict(
        "POST",
        f"/api/project-evaluations/{evaluation_id}/join",
        json={"participant_name": participant_name, "room_password": room_password},
    )


def upload_zip(
    evaluation_id: str,
    filename: str,
    file_obj: BinaryIO,
    admin_password: str = "",
) -> dict[str, object]:
    return request_json_dict(
        "POST",
        f"/api/project-evaluations/{evaluation_id}/artifacts/zip",
        timeout=120,
        files={"file": (filename, file_obj, "application/zip")},
        headers={"X-Admin-Password": admin_password},
    )


def extract_evaluation(evaluation_id: str, admin_password: str = "") -> dict[str, object]:
    return request_json_dict(
        "POST",
        f"/api/project-evaluations/{evaluation_id}/extract",
        timeout=120,
        headers={"X-Admin-Password": admin_password},
    )


def get_context(evaluation_id: str) -> dict[str, object]:
    return request_json_dict("GET", f"/api/project-evaluations/{evaluation_id}/context")


def generate_questions(evaluation_id: str, admin_password: str = "") -> list[dict[str, object]]:
    return request_json_list(
        "POST",
        f"/api/project-evaluations/{evaluation_id}/questions/generate",
        timeout=120,
        headers={"X-Admin-Password": admin_password},
    )


def get_questions(evaluation_id: str) -> list[dict[str, object]]:
    return request_json_list(
        "GET", f"/api/project-evaluations/{evaluation_id}/questions"
    )


def create_session(evaluation_id: str, admin_password: str = "") -> dict[str, object]:
    return request_json_dict(
        "POST",
        f"/api/project-evaluations/{evaluation_id}/sessions",
        headers={"X-Admin-Password": admin_password},
    )


def submit_turn(
    evaluation_id: str, session_id: str, question_id: str, answer_text: str
) -> dict[str, object]:
    return request_json_dict(
        "POST",
        f"/api/project-evaluations/{evaluation_id}/sessions/{session_id}/turns",
        json={"question_id": question_id, "answer_text": answer_text},
    )


def complete_session(evaluation_id: str, session_id: str) -> dict[str, object]:
    return request_json_dict(
        "POST",
        f"/api/project-evaluations/{evaluation_id}/sessions/{session_id}/complete",
        timeout=120,
    )


def get_latest_report(evaluation_id: str, admin_password: str = "") -> dict[str, object]:
    return request_json_dict(
        "GET",
        f"/api/project-evaluations/{evaluation_id}/reports/latest",
        headers={"X-Admin-Password": admin_password},
    )


def get_report(
    evaluation_id: str, report_id: str, admin_password: str = ""
) -> dict[str, object]:
    return request_json_dict(
        "GET",
        f"/api/project-evaluations/{evaluation_id}/reports/{report_id}",
        headers={"X-Admin-Password": admin_password},
    )
