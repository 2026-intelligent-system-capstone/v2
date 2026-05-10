"""Golden path integration test: upload → context → questions → session → complete → report."""

from __future__ import annotations

import io
import zipfile

import pytest
from fastapi.testclient import TestClient

from services.api.app.main import app

client = TestClient(app)


def _make_zip() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(
            "README.md",
            "# 샘플 프로젝트\n\nFastAPI와 SQLite를 사용한 프로젝트입니다.\n기능: 사용자 인증, CRUD API",
        )
        zf.writestr(
            "main.py",
            (
                "from fastapi import FastAPI\n"
                "app = FastAPI()\n\n"
                "@app.get('/health')\n"
                "def health():\n"
                "    return {'status': 'ok'}\n"
            ),
        )
        zf.writestr(
            "models.py",
            (
                "from sqlalchemy import Column, String\n"
                "from sqlalchemy.orm import DeclarativeBase\n\n"
                "class Base(DeclarativeBase):\n"
                "    pass\n\n"
                "class User(Base):\n"
                "    __tablename__ = 'users'\n"
                "    id = Column(String, primary_key=True)\n"
                "    name = Column(String)\n"
            ),
        )
    return buf.getvalue()


@pytest.fixture()
def evaluation_id() -> str:
    resp = client.post(
        "/api/project-evaluations",
        json={
            "project_name": "테스트 프로젝트",
            "candidate_name": "테스트 지원자",
            "description": "FastAPI 기반 REST API",
            "room_name": "테스트 방",
            "room_password": "room-pass",
            "admin_password": "admin-pass",
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


@pytest.fixture()
def evaluation_with_upload(evaluation_id: str) -> str:
    zip_bytes = _make_zip()
    resp = client.post(
        f"/api/project-evaluations/{evaluation_id}/artifacts/zip",
        files={"file": ("project.zip", zip_bytes, "application/zip")},
        headers={"X-Admin-Password": "admin-pass"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["accepted_count"] >= 1
    return evaluation_id


@pytest.fixture()
def evaluation_with_context(evaluation_with_upload: str) -> str:
    evaluation_id = evaluation_with_upload
    resp = client.post(
        f"/api/project-evaluations/{evaluation_id}/extract",
        headers={"X-Admin-Password": "admin-pass"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert "summary" in data
    return evaluation_id


@pytest.fixture()
def evaluation_with_questions(evaluation_with_context: str) -> str:
    evaluation_id = evaluation_with_context
    resp = client.post(
        f"/api/project-evaluations/{evaluation_id}/questions/generate",
        headers={"X-Admin-Password": "admin-pass"},
    )
    assert resp.status_code == 200, resp.text
    questions = resp.json()
    assert len(questions) >= 1
    return evaluation_id


def test_create_evaluation() -> None:
    resp = client.post(
        "/api/project-evaluations",
        json={
            "project_name": "My Project",
            "candidate_name": "Alice",
            "description": "A test project",
            "room_name": "My Room",
            "room_password": "room-pass",
            "admin_password": "admin-pass",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["project_name"] == "My Project"
    assert data["room_name"] == "My Room"
    assert data["id"]


def test_upload_zip(evaluation_id: str) -> None:
    zip_bytes = _make_zip()
    resp = client.post(
        f"/api/project-evaluations/{evaluation_id}/artifacts/zip",
        files={"file": ("project.zip", zip_bytes, "application/zip")},
        headers={"X-Admin-Password": "admin-pass"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["accepted_count"] >= 1
    assert "reason_counts" in data
    assert "artifacts" in data


def test_upload_non_zip_rejected(evaluation_id: str) -> None:
    resp = client.post(
        f"/api/project-evaluations/{evaluation_id}/artifacts/zip",
        files={"file": ("project.txt", b"hello", "text/plain")},
        headers={"X-Admin-Password": "admin-pass"},
    )
    assert resp.status_code == 400


def test_extract_context(evaluation_with_upload: str) -> None:
    resp = client.post(
        f"/api/project-evaluations/{evaluation_with_upload}/extract",
        headers={"X-Admin-Password": "admin-pass"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "summary" in data
    assert isinstance(data["tech_stack"], list)
    assert isinstance(data["areas"], list)


def test_generate_questions(evaluation_with_context: str) -> None:
    resp = client.post(
        f"/api/project-evaluations/{evaluation_with_context}/questions/generate",
        headers={"X-Admin-Password": "admin-pass"},
    )
    assert resp.status_code == 200
    questions = resp.json()
    assert len(questions) >= 1
    q = questions[0]
    assert "question" in q
    forbidden_terms = ["회사", "직무", "입사", "지원 동기", "채용"]
    assert not any(term in q["question"] for term in forbidden_terms)
    assert any(
        term in q["question"] for term in ["설명", "흐름", "구조", "이유", "개선"]
    )
    assert "main.py" in q["question"] or "models.py" in q["question"]
    assert "bloom_level" in q


def test_list_questions(evaluation_with_questions: str) -> None:
    resp = client.get(
        f"/api/project-evaluations/{evaluation_with_questions}/questions",
        headers={"X-Admin-Password": "admin-pass"},
    )
    assert resp.status_code == 200
    assert len(resp.json()) >= 1


def test_golden_path_session_and_report(evaluation_with_questions: str) -> None:
    evaluation_id = evaluation_with_questions

    resp = client.post(
        f"/api/project-evaluations/{evaluation_id}/join",
        json={"participant_name": "테스트 지원자", "room_password": "room-pass"},
    )
    assert resp.status_code == 200
    session_id = resp.json()["session"]["id"]

    # List questions and submit answers in order
    questions = client.get(
        f"/api/project-evaluations/{evaluation_id}/questions",
        headers={"X-Admin-Password": "admin-pass"},
    ).json()
    for q in questions:
        resp = client.post(
            f"/api/project-evaluations/{evaluation_id}/sessions/{session_id}/turns",
            json={"question_id": q["id"], "answer_text": "테스트 답변입니다. 직접 구현했습니다."},
        )
        assert resp.status_code == 200, resp.text

    # Complete session → report
    resp = client.post(
        f"/api/project-evaluations/{evaluation_id}/sessions/{session_id}/complete"
    )
    assert resp.status_code == 200, resp.text
    report = resp.json()
    assert "final_decision" in report
    assert "authenticity_score" in report
    assert "summary" in report

    # Latest report endpoint must return the same report
    resp = client.get(
        f"/api/project-evaluations/{evaluation_id}/reports/latest",
        headers={"X-Admin-Password": "admin-pass"},
    )
    assert resp.status_code == 200
    latest = resp.json()
    assert latest["id"] == report["id"]


def test_latest_report_404_when_no_report(evaluation_id: str) -> None:
    resp = client.get(
        f"/api/project-evaluations/{evaluation_id}/reports/latest",
        headers={"X-Admin-Password": "admin-pass"},
    )
    assert resp.status_code == 404


def test_create_session_without_questions_rejected(evaluation_with_upload: str) -> None:
    client.post(
        f"/api/project-evaluations/{evaluation_with_upload}/extract",
        headers={"X-Admin-Password": "admin-pass"},
    )
    resp = client.post(
        f"/api/project-evaluations/{evaluation_with_upload}/sessions",
        headers={"X-Admin-Password": "admin-pass"},
    )
    assert resp.status_code == 409
