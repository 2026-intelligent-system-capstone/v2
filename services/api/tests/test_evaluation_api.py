"""Golden path integration test: upload → context → questions → session → complete → report."""

from __future__ import annotations

from collections import Counter
import io
import re
import zipfile

import pytest
from fastapi.testclient import TestClient

from services.api.app.main import app
from services.api.app.project_evaluations.analysis.prompts import (
    AnswerEvalSchema,
    AreaSchema,
    ProjectContextSchema,
    PromptSourceRefSchema,
    QuestionSchema,
    QuestionsSchema,
    ReportSchema,
    RubricScoreSchema,
)
from services.api.app.project_evaluations.domain.models import (
    ArtifactRole,
    ArtifactSourceType,
    FinalDecision,
    RubricCriterion,
)
from services.api.app.project_evaluations.rag.chunk_models import ChunkType, RetrievedChunk
from services.api.app.project_evaluations.rag.embedder import IngestResult
from services.api.app.project_evaluations.interview.question_generator import (
    QUESTION_GENERATION_BASE_TOKENS,
    QUESTION_GENERATION_TOKENS_PER_QUESTION,
)
from services.api.app.project_evaluations.service import ProjectEvaluationService

client = TestClient(app)

BLOOM_LEVELS = ["기억", "이해", "적용", "분석", "평가", "창안"]
DEFAULT_BLOOM_DISTRIBUTION = {level: 1 for level in BLOOM_LEVELS}


class FakeLlm:
    def __init__(
        self,
        enabled: bool = True,
        fail_schema: type | None = None,
        question_source_paths: list[str] | None = None,
    ) -> None:
        self._enabled = enabled
        self.fail_schema = fail_schema
        self.question_source_paths = question_source_paths or ["main.py", "README.md"]
        self.calls: list[dict[str, object]] = []

    def enabled(self) -> bool:
        return self._enabled

    def parse(self, messages, schema, max_tokens):
        self.calls.append({"schema": schema, "max_tokens": max_tokens})
        if schema is self.fail_schema:
            raise RuntimeError(f"forced {schema.__name__} failure")
        if schema is ProjectContextSchema:
            return ProjectContextSchema(
                summary="FastAPI와 SQLite 기반 프로젝트 평가 서비스입니다.",
                tech_stack=["FastAPI", "SQLite"],
                features=["zip 업로드", "질문 생성"],
                architecture_notes=["API와 persistence 계층이 분리되어 있습니다."],
                data_flow=["zip 업로드 후 context와 질문을 생성합니다."],
                risk_points=["문서와 코드 근거를 함께 확인해야 합니다."],
                question_targets=["API 흐름"],
                areas=[AreaSchema(name="API 흐름", summary="업로드와 질문 생성 흐름", confidence=0.9)],
            )
        if schema is QuestionsSchema:
            distribution = _question_distribution_from_messages(messages)
            questions = []
            for level, count in distribution.items():
                for index in range(count):
                    questions.append(
                        QuestionSchema(
                            question=f"{level} 단계에서 main.py와 README.md 근거로 업로드 이후 흐름을 설명해 주세요. ({index + 1})",
                            intent="제출 코드와 문서의 연결 이해를 검증합니다.",
                            bloom_level=level,
                            verification_focus="FastAPI 라우터와 README 설명의 연결",
                            expected_signal="main.py의 FastAPI 구성과 README의 기능 설명을 함께 언급해야 합니다.",
                            expected_evidence="main.py, README.md",
                            source_ref_requirements="코드 구현 근거와 문서 설명 근거를 함께 사용해야 합니다.",
                            difficulty="medium",
                            source_refs=[
                                PromptSourceRefSchema(path=path, reason="질문 생성 근거")
                                for path in self.question_source_paths
                            ],
                        )
                    )
            return QuestionsSchema(questions=questions)
        if schema is AnswerEvalSchema:
            return AnswerEvalSchema(
                score=82.0,
                evaluation_summary="제출 자료와 대체로 일치하는 구현 설명입니다.",
                rubric_scores=[
                    RubricScoreSchema(criterion=criterion.value, score=2, rationale="근거가 확인됩니다.")
                    for criterion in RubricCriterion
                ],
                evidence_matches=["main.py의 FastAPI 흐름과 일치합니다."],
                evidence_mismatches=[],
                suspicious_points=[],
                strengths=["구현 흐름을 설명했습니다."],
                authenticity_signals=["구체적인 파일 근거를 언급했습니다."],
                missing_expected_signals=[],
                confidence=0.86,
                follow_up_question=None,
            )
        if schema is ReportSchema:
            return ReportSchema(
                final_decision=FinalDecision.VERIFIED.value,
                authenticity_score=84.0,
                summary="제출 자료와 답변이 대체로 일치합니다. 구현 흐름 설명이 구체적입니다.",
                area_analyses=[{"area": "API 흐름", "confidence": 0.84}],
                question_evaluations=[{"summary": "자료 근거와 일치"}],
                bloom_summary={"기억": 1},
                rubric_summary={"자료 근거 일치도": "양호"},
                evidence_alignment=["main.py와 README.md 설명이 답변과 일치합니다."],
                strengths=["구현 흐름 설명"],
                suspicious_points=[],
                recommended_followups=[],
            )
        raise AssertionError(f"unexpected schema: {schema}")


def _question_distribution_from_messages(messages) -> dict[str, int]:
    content = "\n".join(str(message.get("content", "")) for message in messages)
    distribution = {}
    for level in BLOOM_LEVELS:
        match = re.search(rf"- {level}: (\d+)개", content)
        if match:
            distribution[level] = int(match.group(1))
    return distribution or DEFAULT_BLOOM_DISTRIBUTION


def _fake_ingest(self, evaluation_id: str, artifacts: list) -> IngestResult:
    return IngestResult(
        inserted_count=4,
        code_chunk_count=2,
        document_chunk_count=1,
        manifest_chunk_count=1,
        skipped_count=0,
    )


def _fake_retriever(self, evaluation_id: str):
    def retrieve(_query: str, **kwargs: object) -> list[RetrievedChunk]:
        chunks = [
            RetrievedChunk(
                text="FastAPI 앱은 main.py에서 생성되고 health endpoint를 제공합니다.",
                source_path="main.py",
                artifact_id="code-artifact",
                source_type=ArtifactSourceType.CODE.value,
                artifact_role=ArtifactRole.CODEBASE_SOURCE.value,
                chunk_type=ChunkType.CODE_SYMBOL.value,
                score=0.9,
                line_start=1,
                line_end=5,
            ),
            RetrievedChunk(
                text="README는 FastAPI와 SQLite 기반 프로젝트라고 설명합니다.",
                source_path="README.md",
                artifact_id="doc-artifact",
                source_type=ArtifactSourceType.DOCUMENT.value,
                artifact_role=ArtifactRole.CODEBASE_OVERVIEW.value,
                chunk_type=ChunkType.CODEBASE_OVERVIEW.value,
                score=0.8,
            ),
        ]
        artifact_roles = kwargs.get("artifact_roles")
        if artifact_roles:
            allowed = set(artifact_roles)
            return [chunk for chunk in chunks if chunk.artifact_role in allowed]
        return chunks

    return retrieve


@pytest.fixture(autouse=True)
def llm_and_rag_doubles(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(app.state.settings, "RAG_ENABLED", True)
    monkeypatch.setattr(ProjectEvaluationService, "_ingest_rag", _fake_ingest)
    monkeypatch.setattr(ProjectEvaluationService, "_make_retriever", _fake_retriever)
    original_init = ProjectEvaluationService.__init__

    def init_with_fake_llms(self, repository, settings):
        original_init(self, repository, settings)
        self._analysis_llm = FakeLlm()
        self._question_llm = FakeLlm()
        self._eval_llm = FakeLlm()
        self._report_llm = FakeLlm()

    monkeypatch.setattr(ProjectEvaluationService, "__init__", init_with_fake_llms)


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
    assert data["question_policy"] == {
        "total_question_count": 6,
        "bloom_ratios": {level: 1 for level in BLOOM_LEVELS},
        "bloom_distribution": DEFAULT_BLOOM_DISTRIBUTION,
    }



def test_create_evaluation_with_question_policy_uses_largest_remainder_distribution() -> None:
    resp = client.post(
        "/api/project-evaluations",
        json={
            "project_name": "질문 정책 프로젝트",
            "candidate_name": "정책 지원자",
            "description": "Bloom 비율 배분 검증",
            "room_name": "정책 방",
            "room_password": "room-pass",
            "admin_password": "admin-pass",
            "question_policy": {
                "total_question_count": 7,
                "bloom_ratios": {
                    "기억": 1,
                    "이해": 1,
                    "적용": 1,
                    "분석": 1,
                    "평가": 1,
                    "창안": 1,
                },
            },
        },
    )

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["question_policy"] == {
        "total_question_count": 7,
        "bloom_ratios": {level: 1 for level in BLOOM_LEVELS},
        "bloom_distribution": {
            "기억": 2,
            "이해": 1,
            "적용": 1,
            "분석": 1,
            "평가": 1,
            "창안": 1,
        },
    }

    read_resp = client.get(
        f"/api/project-evaluations/{data['id']}",
        headers={"X-Admin-Password": "admin-pass"},
    )
    assert read_resp.status_code == 200, read_resp.text
    assert read_resp.json()["question_policy"] == data["question_policy"]



def test_create_evaluation_question_policy_distributes_by_largest_remainder() -> None:
    resp = client.post(
        "/api/project-evaluations",
        json={
            "project_name": "비율 배분 프로젝트",
            "candidate_name": "비율 지원자",
            "description": "소수점 잔여 큰 순서와 Bloom 순서 동률 검증",
            "room_name": "비율 방",
            "room_password": "room-pass",
            "admin_password": "admin-pass",
            "question_policy": {
                "total_question_count": 10,
                "bloom_ratios": {
                    "기억": 0,
                    "이해": 2,
                    "적용": 2,
                    "분석": 1,
                    "평가": 1,
                    "창안": 0,
                },
            },
        },
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["question_policy"]["bloom_distribution"] == {
        "기억": 0,
        "이해": 3,
        "적용": 3,
        "분석": 2,
        "평가": 2,
        "창안": 0,
    }



@pytest.mark.parametrize(
    ("total_question_count", "expected_distribution"),
    [
        (
            1,
            {
                "기억": 1,
                "이해": 0,
                "적용": 0,
                "분석": 0,
                "평가": 0,
                "창안": 0,
            },
        ),
        (
            20,
            {
                "기억": 4,
                "이해": 4,
                "적용": 3,
                "분석": 3,
                "평가": 3,
                "창안": 3,
            },
        ),
    ],
)
def test_create_evaluation_accepts_question_count_policy_boundaries(
    total_question_count: int,
    expected_distribution: dict[str, int],
) -> None:
    resp = client.post(
        "/api/project-evaluations",
        json={
            "project_name": "경계 문항 수 프로젝트",
            "candidate_name": "정책 지원자",
            "description": "문항 수 정책 경계값 검증",
            "room_name": "경계 문항 수 방",
            "room_password": "room-pass",
            "admin_password": "admin-pass",
            "question_policy": {
                "total_question_count": total_question_count,
                "bloom_ratios": {level: 1 for level in BLOOM_LEVELS},
            },
        },
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["question_policy"]["total_question_count"] == total_question_count
    assert resp.json()["question_policy"]["bloom_distribution"] == expected_distribution


@pytest.mark.parametrize("total_question_count", [0, 21])
def test_create_evaluation_rejects_question_count_outside_policy_range(
    total_question_count: int,
) -> None:
    resp = client.post(
        "/api/project-evaluations",
        json={
            "project_name": "잘못된 문항 수 프로젝트",
            "candidate_name": "정책 지원자",
            "description": "정책 문항 수 범위 검증",
            "room_name": "문항 수 오류 방",
            "room_password": "room-pass",
            "admin_password": "admin-pass",
            "question_policy": {
                "total_question_count": total_question_count,
                "bloom_ratios": {level: 1 for level in BLOOM_LEVELS},
            },
        },
    )

    assert resp.status_code == 422, total_question_count


def test_create_evaluation_rejects_all_zero_bloom_ratios() -> None:
    resp = client.post(
        "/api/project-evaluations",
        json={
            "project_name": "잘못된 정책 프로젝트",
            "candidate_name": "정책 지원자",
            "description": "모든 Bloom 비율 0 검증",
            "room_name": "오류 방",
            "room_password": "room-pass",
            "admin_password": "admin-pass",
            "question_policy": {
                "total_question_count": 6,
                "bloom_ratios": {level: 0 for level in BLOOM_LEVELS},
            },
        },
    )

    assert resp.status_code == 422
    assert "Bloom 비율" in str(resp.json()["detail"])



@pytest.mark.parametrize(
    "bloom_ratios",
    [
        ["기억", "이해"],
        {"기억": -1, "이해": 1},
        {"기억": 1.5, "이해": 1},
        {"기억": True, "이해": 1},
        {"기억": 11, "이해": 1},
    ],
)
def test_create_evaluation_rejects_malformed_bloom_ratios(
    bloom_ratios: object,
) -> None:
    resp = client.post(
        "/api/project-evaluations",
        json={
            "project_name": "잘못된 비율 프로젝트",
            "candidate_name": "정책 지원자",
            "description": "Bloom 비율 mapping 검증",
            "room_name": "비율 오류 방",
            "room_password": "room-pass",
            "admin_password": "admin-pass",
            "question_policy": {
                "total_question_count": 6,
                "bloom_ratios": bloom_ratios,
            },
        },
    )

    assert resp.status_code == 422
    assert "Bloom 비율" in str(resp.json()["detail"])


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
    assert data["processing_limits"] == {
        "max_zip_bytes": 50 * 1024 * 1024,
        "max_file_bytes": 10 * 1024 * 1024,
        "max_files": 120,
    }
    assert set(data["supported_extensions"]) >= {
        ".py",
        ".md",
        ".pdf",
        ".pptx",
        ".docx",
        ".yaml",
        ".json",
    }


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
    assert data["rag_status"]["enabled"] is True
    assert data["rag_status"]["status"] == "indexed"
    assert data["rag_status"]["inserted_count"] == 4


def test_generate_questions(evaluation_with_context: str) -> None:
    resp = client.post(
        f"/api/project-evaluations/{evaluation_with_context}/questions/generate",
        headers={"X-Admin-Password": "admin-pass"},
    )
    assert resp.status_code == 200
    questions = resp.json()
    assert len(questions) == 6
    assert (
        Counter(question["bloom_level"] for question in questions)
        == DEFAULT_BLOOM_DISTRIBUTION
    )
    q = questions[0]
    assert "question" in q
    forbidden_terms = ["회사", "직무", "입사", "지원 동기", "채용"]
    assert not any(term in q["question"] for term in forbidden_terms)
    assert any(
        term in q["question"] for term in ["설명", "흐름", "구조", "이유", "개선"]
    )
    assert "main.py" in q["question"] or "models.py" in q["question"]
    assert q["bloom_level"] in BLOOM_LEVELS
    assert q["source_refs"]
    assert q["verification_focus"] == "FastAPI 라우터와 README 설명의 연결"
    assert q["expected_evidence"] == "main.py, README.md"
    assert q["source_ref_requirements"] == "코드 구현 근거와 문서 설명 근거를 함께 사용해야 합니다."



def test_generate_questions_follows_requested_total_count_and_bloom_distribution() -> None:
    create_resp = client.post(
        "/api/project-evaluations",
        json={
            "project_name": "질문 생성 정책 프로젝트",
            "candidate_name": "생성 지원자",
            "description": "요청한 문항 수와 Bloom 분포 검증",
            "room_name": "생성 방",
            "room_password": "room-pass",
            "admin_password": "admin-pass",
            "question_policy": {
                "total_question_count": 8,
                "bloom_ratios": {
                    "기억": 1,
                    "이해": 0,
                    "적용": 3,
                    "분석": 0,
                    "평가": 0,
                    "창안": 0,
                },
            },
        },
    )
    assert create_resp.status_code == 200, create_resp.text
    evaluation_id = create_resp.json()["id"]

    upload_resp = client.post(
        f"/api/project-evaluations/{evaluation_id}/artifacts/zip",
        files={"file": ("project.zip", _make_zip(), "application/zip")},
        headers={"X-Admin-Password": "admin-pass"},
    )
    assert upload_resp.status_code == 200, upload_resp.text
    extract_resp = client.post(
        f"/api/project-evaluations/{evaluation_id}/extract",
        headers={"X-Admin-Password": "admin-pass"},
    )
    assert extract_resp.status_code == 200, extract_resp.text

    question_resp = client.post(
        f"/api/project-evaluations/{evaluation_id}/questions/generate",
        headers={"X-Admin-Password": "admin-pass"},
    )

    assert question_resp.status_code == 200, question_resp.text
    questions = question_resp.json()
    assert len(questions) == 8
    assert Counter(question["bloom_level"] for question in questions) == {
        "기억": 2,
        "적용": 6,
    }


def test_generate_questions_supports_twenty_question_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    question_llm = FakeLlm()
    original_init = ProjectEvaluationService.__init__

    def init_with_observed_question_llm(self, repository, settings):
        original_init(self, repository, settings)
        self._analysis_llm = FakeLlm()
        self._question_llm = question_llm
        self._eval_llm = FakeLlm()
        self._report_llm = FakeLlm()

    monkeypatch.setattr(ProjectEvaluationService, "__init__", init_with_observed_question_llm)
    create_resp = client.post(
        "/api/project-evaluations",
        json={
            "project_name": "20문항 질문 생성 프로젝트",
            "candidate_name": "생성 지원자",
            "description": "20문항 질문 생성 검증",
            "room_name": "20문항 생성 방",
            "room_password": "room-pass",
            "admin_password": "admin-pass",
            "question_policy": {
                "total_question_count": 20,
                "bloom_ratios": {level: 1 for level in BLOOM_LEVELS},
            },
        },
    )
    assert create_resp.status_code == 200, create_resp.text
    evaluation_id = create_resp.json()["id"]

    upload_resp = client.post(
        f"/api/project-evaluations/{evaluation_id}/artifacts/zip",
        files={"file": ("project.zip", _make_zip(), "application/zip")},
        headers={"X-Admin-Password": "admin-pass"},
    )
    assert upload_resp.status_code == 200, upload_resp.text
    extract_resp = client.post(
        f"/api/project-evaluations/{evaluation_id}/extract",
        headers={"X-Admin-Password": "admin-pass"},
    )
    assert extract_resp.status_code == 200, extract_resp.text

    question_resp = client.post(
        f"/api/project-evaluations/{evaluation_id}/questions/generate",
        headers={"X-Admin-Password": "admin-pass"},
    )

    assert question_resp.status_code == 200, question_resp.text
    questions = question_resp.json()
    assert len(questions) == 20
    assert Counter(question["bloom_level"] for question in questions) == {
        "기억": 4,
        "이해": 4,
        "적용": 3,
        "분석": 3,
        "평가": 3,
        "창안": 3,
    }
    assert question_llm.calls[-1]["max_tokens"] == 20 * QUESTION_GENERATION_TOKENS_PER_QUESTION
    assert question_llm.calls[-1]["max_tokens"] > QUESTION_GENERATION_BASE_TOKENS


def test_rag_disabled_blocks_context_extraction(
    evaluation_with_upload: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(app.state.settings, "RAG_ENABLED", False)

    extract_resp = client.post(
        f"/api/project-evaluations/{evaluation_with_upload}/extract",
        headers={"X-Admin-Password": "admin-pass"},
    )

    assert extract_resp.status_code == 409
    assert extract_resp.json()["detail"]["reason"] == "rag_disabled"


def test_rag_ingest_failure_is_exposed_before_question_generation(
    evaluation_with_upload: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    def failing_ingest(self, evaluation_id: str, artifacts: list) -> IngestResult:
        raise RuntimeError("Qdrant collection unavailable")

    monkeypatch.setattr(ProjectEvaluationService, "_ingest_rag", failing_ingest)

    extract_resp = client.post(
        f"/api/project-evaluations/{evaluation_with_upload}/extract",
        headers={"X-Admin-Password": "admin-pass"},
    )

    assert extract_resp.status_code == 502
    detail = extract_resp.json()["detail"]
    assert detail["stage"] == "rag_ingestion"
    assert "Qdrant collection unavailable" in detail["message"]

    question_resp = client.post(
        f"/api/project-evaluations/{evaluation_with_upload}/questions/generate",
        headers={"X-Admin-Password": "admin-pass"},
    )
    assert question_resp.status_code == 404


def test_extract_context_again_after_questions_replaces_context(evaluation_with_questions: str) -> None:
    resp = client.post(
        f"/api/project-evaluations/{evaluation_with_questions}/extract",
        headers={"X-Admin-Password": "admin-pass"},
    )

    assert resp.status_code == 200, resp.text
    assert "summary" in resp.json()
    questions_resp = client.get(
        f"/api/project-evaluations/{evaluation_with_questions}/questions",
        headers={"X-Admin-Password": "admin-pass"},
    )
    assert questions_resp.status_code == 200
    assert questions_resp.json() == []


def test_list_questions(evaluation_with_questions: str) -> None:
    resp = client.get(
        f"/api/project-evaluations/{evaluation_with_questions}/questions",
        headers={"X-Admin-Password": "admin-pass"},
    )
    assert resp.status_code == 200
    assert len(resp.json()) >= 1


def test_generate_questions_after_session_start_is_rejected(evaluation_with_questions: str) -> None:
    evaluation_id = evaluation_with_questions
    resp = client.post(
        f"/api/project-evaluations/{evaluation_id}/join",
        json={"participant_name": "테스트 지원자", "room_password": "room-pass"},
    )
    assert resp.status_code == 200

    resp = client.post(
        f"/api/project-evaluations/{evaluation_id}/questions/generate",
        headers={"X-Admin-Password": "admin-pass"},
    )

    assert resp.status_code == 409
    assert "질문을 다시 생성할 수 없습니다" in resp.json()["detail"]


def test_generate_questions_rejects_unknown_llm_source_ref(
    evaluation_with_context: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    def init_with_unknown_ref(self, repository, settings):
        self.repository = repository
        self.settings = settings
        self._analysis_llm = FakeLlm()
        self._question_llm = FakeLlm(question_source_paths=["hallucinated.py"])
        self._eval_llm = FakeLlm()
        self._report_llm = FakeLlm()
        self._openai = None
        self._qdrant = None

    monkeypatch.setattr(ProjectEvaluationService, "__init__", init_with_unknown_ref)

    resp = client.post(
        f"/api/project-evaluations/{evaluation_with_context}/questions/generate",
        headers={"X-Admin-Password": "admin-pass"},
    )

    assert resp.status_code == 502
    detail = resp.json()["detail"]
    assert detail["stage"] == "question_generation"
    assert "제공되지 않은 source ref" in detail["message"]



def test_generate_questions_rejects_code_only_llm_source_ref(
    evaluation_with_context: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    def init_with_code_only_ref(self, repository, settings):
        self.repository = repository
        self.settings = settings
        self._analysis_llm = FakeLlm()
        self._question_llm = FakeLlm(question_source_paths=["main.py"])
        self._eval_llm = FakeLlm()
        self._report_llm = FakeLlm()
        self._openai = None
        self._qdrant = None

    monkeypatch.setattr(ProjectEvaluationService, "__init__", init_with_code_only_ref)

    resp = client.post(
        f"/api/project-evaluations/{evaluation_with_context}/questions/generate",
        headers={"X-Admin-Password": "admin-pass"},
    )

    assert resp.status_code == 502
    detail = resp.json()["detail"]
    assert detail["stage"] == "question_generation"
    assert "문서/개요 source ref" in detail["message"]



def test_generate_questions_rejects_docs_only_llm_source_ref(
    evaluation_with_context: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    def init_with_docs_only_ref(self, repository, settings):
        self.repository = repository
        self.settings = settings
        self._analysis_llm = FakeLlm()
        self._question_llm = FakeLlm(question_source_paths=["README.md"])
        self._eval_llm = FakeLlm()
        self._report_llm = FakeLlm()
        self._openai = None
        self._qdrant = None

    monkeypatch.setattr(ProjectEvaluationService, "__init__", init_with_docs_only_ref)

    resp = client.post(
        f"/api/project-evaluations/{evaluation_with_context}/questions/generate",
        headers={"X-Admin-Password": "admin-pass"},
    )

    assert resp.status_code == 502
    detail = resp.json()["detail"]
    assert detail["stage"] == "question_generation"
    assert "구현 code source ref" in detail["message"]



def test_generate_questions_llm_failure_is_exposed(
    evaluation_with_context: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    def init_with_question_failure(self, repository, settings):
        self.repository = repository
        self.settings = settings
        self._analysis_llm = FakeLlm()
        self._question_llm = FakeLlm(fail_schema=QuestionsSchema)
        self._eval_llm = FakeLlm()
        self._report_llm = FakeLlm()
        self._openai = None
        self._qdrant = None

    monkeypatch.setattr(ProjectEvaluationService, "__init__", init_with_question_failure)

    resp = client.post(
        f"/api/project-evaluations/{evaluation_with_context}/questions/generate",
        headers={"X-Admin-Password": "admin-pass"},
    )

    assert resp.status_code == 502
    detail = resp.json()["detail"]
    assert detail["stage"] == "question_generation"
    assert "forced QuestionsSchema failure" in detail["message"]


def test_submit_turn_llm_failure_is_exposed(
    evaluation_with_questions: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    def init_with_eval_failure(self, repository, settings):
        self.repository = repository
        self.settings = settings
        self._analysis_llm = FakeLlm()
        self._question_llm = FakeLlm()
        self._eval_llm = FakeLlm(fail_schema=AnswerEvalSchema)
        self._report_llm = FakeLlm()
        self._openai = None
        self._qdrant = None

    monkeypatch.setattr(ProjectEvaluationService, "__init__", init_with_eval_failure)
    evaluation_id = evaluation_with_questions

    resp = client.post(
        f"/api/project-evaluations/{evaluation_id}/join",
        json={"participant_name": "테스트 지원자", "room_password": "room-pass"},
    )
    assert resp.status_code == 200
    session = resp.json()["session"]
    session_id = session["id"]
    session_token = session["session_token"]
    question = client.get(
        f"/api/project-evaluations/{evaluation_id}/questions",
        headers={"X-Admin-Password": "admin-pass"},
    ).json()[0]

    resp = client.post(
        f"/api/project-evaluations/{evaluation_id}/sessions/{session_id}/turns",
        json={"question_id": question["id"], "answer_text": "테스트 답변입니다."},
        headers={"X-Session-Token": session_token},
    )

    assert resp.status_code == 502
    assert resp.json()["detail"]["stage"] == "answer_evaluation"
    assert "forced AnswerEvalSchema failure" in resp.json()["detail"]["message"]


def test_submit_turn_requires_session_token(evaluation_with_questions: str) -> None:
    evaluation_id = evaluation_with_questions
    resp = client.post(
        f"/api/project-evaluations/{evaluation_id}/join",
        json={"participant_name": "테스트 지원자", "room_password": "room-pass"},
    )
    assert resp.status_code == 200
    session_id = resp.json()["session"]["id"]
    question = client.get(
        f"/api/project-evaluations/{evaluation_id}/questions",
        headers={"X-Admin-Password": "admin-pass"},
    ).json()[0]

    resp = client.post(
        f"/api/project-evaluations/{evaluation_id}/sessions/{session_id}/turns",
        json={"question_id": question["id"], "answer_text": "테스트 답변입니다."},
    )

    assert resp.status_code == 403
    assert "세션 토큰" in resp.json()["detail"]


def test_golden_path_session_and_report(evaluation_with_questions: str) -> None:
    evaluation_id = evaluation_with_questions

    resp = client.post(
        f"/api/project-evaluations/{evaluation_id}/join",
        json={"participant_name": "테스트 지원자", "room_password": "room-pass"},
    )
    assert resp.status_code == 200
    session = resp.json()["session"]
    session_id = session["id"]
    session_token = session["session_token"]

    # List questions and submit answers in order
    questions = client.get(
        f"/api/project-evaluations/{evaluation_id}/questions",
        headers={"X-Admin-Password": "admin-pass"},
    ).json()
    for q in questions:
        resp = client.post(
            f"/api/project-evaluations/{evaluation_id}/sessions/{session_id}/turns",
            json={"question_id": q["id"], "answer_text": "테스트 답변입니다. 직접 구현했습니다."},
            headers={"X-Session-Token": session_token},
        )
        assert resp.status_code == 200, resp.text

    # Complete session → report
    resp = client.post(
        f"/api/project-evaluations/{evaluation_id}/sessions/{session_id}/complete",
        headers={"X-Session-Token": session_token},
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


def test_report_llm_failure_does_not_save_report(
    evaluation_with_questions: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    evaluation_id = evaluation_with_questions
    resp = client.post(
        f"/api/project-evaluations/{evaluation_id}/join",
        json={"participant_name": "테스트 지원자", "room_password": "room-pass"},
    )
    assert resp.status_code == 200
    session = resp.json()["session"]
    session_id = session["id"]
    session_token = session["session_token"]
    questions = client.get(
        f"/api/project-evaluations/{evaluation_id}/questions",
        headers={"X-Admin-Password": "admin-pass"},
    ).json()
    for question in questions:
        turn_resp = client.post(
            f"/api/project-evaluations/{evaluation_id}/sessions/{session_id}/turns",
            json={"question_id": question["id"], "answer_text": "테스트 답변입니다. 직접 구현했습니다."},
            headers={"X-Session-Token": session_token},
        )
        assert turn_resp.status_code == 200, turn_resp.text

    def init_with_report_failure(self, repository, settings):
        self.repository = repository
        self.settings = settings
        self._analysis_llm = FakeLlm()
        self._question_llm = FakeLlm()
        self._eval_llm = FakeLlm()
        self._report_llm = FakeLlm(fail_schema=ReportSchema)
        self._openai = None
        self._qdrant = None

    monkeypatch.setattr(ProjectEvaluationService, "__init__", init_with_report_failure)

    resp = client.post(
        f"/api/project-evaluations/{evaluation_id}/sessions/{session_id}/complete",
        headers={"X-Session-Token": session_token},
    )

    assert resp.status_code == 502
    detail = resp.json()["detail"]
    assert detail["stage"] == "report_generation"
    assert "forced ReportSchema failure" in detail["message"]

    latest_resp = client.get(
        f"/api/project-evaluations/{evaluation_id}/reports/latest",
        headers={"X-Admin-Password": "admin-pass"},
    )
    assert latest_resp.status_code == 404


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
