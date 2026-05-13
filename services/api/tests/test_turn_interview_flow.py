from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from services.api.app.main import app
from services.api.app.project_evaluations.analysis.prompts import (
    AnswerEvalSchema,
    ReportSchema,
    RubricScoreSchema,
)
from services.api.app.project_evaluations.domain.models import (
    FinalDecision,
    InterviewTurnCreate,
    RubricCriterion,
)
from services.api.app.project_evaluations.persistence.repository import (
    ProjectEvaluationRepository,
)
from services.api.app.project_evaluations.service import ProjectEvaluationService

client = TestClient(app)


class FakeInterviewLlm:
    def __init__(
        self,
        chat_responses: list[str] | None = None,
        follow_up_question: str | None = None,
    ) -> None:
        self.chat_responses = list(chat_responses or ["answer"])
        self.follow_up_question = follow_up_question
        self.chat_calls: list[dict[str, object]] = []
        self.parse_calls: list[type] = []

    def enabled(self) -> bool:
        return True

    def chat(self, messages, temperature, max_tokens) -> str:
        self.chat_calls.append(
            {"messages": messages, "temperature": temperature, "max_tokens": max_tokens}
        )
        if len(self.chat_responses) > 1:
            return self.chat_responses.pop(0)
        return self.chat_responses[0]

    def parse(self, messages, schema, max_tokens):
        self.parse_calls.append(schema)
        if schema is AnswerEvalSchema:
            return AnswerEvalSchema(
                score=80.0,
                evaluation_summary="제출 자료와 일치하는 답변입니다.",
                rubric_scores=[
                    RubricScoreSchema(
                        criterion=criterion.value,
                        score=2,
                        rationale="근거가 확인됩니다.",
                    )
                    for criterion in RubricCriterion
                ],
                evidence_matches=["질문 근거와 답변이 일치합니다."],
                evidence_mismatches=[],
                suspicious_points=[],
                strengths=["구현 흐름을 설명했습니다."],
                authenticity_signals=["구체적인 구현 설명"],
                missing_expected_signals=[],
                confidence=0.82,
                follow_up_question=self.follow_up_question,
            )
        if schema is ReportSchema:
            return ReportSchema(
                final_decision=FinalDecision.VERIFIED.value,
                authenticity_score=82.0,
                summary="답변이 제출 자료와 대체로 일치합니다.",
                area_analyses=[{"area": "API", "confidence": 0.82}],
                question_evaluations=[{"summary": "자료 근거와 일치"}],
                bloom_summary={"기억": 1},
                rubric_summary={"자료 근거 일치도": "양호"},
                evidence_alignment=["자료와 답변이 일치합니다."],
                strengths=["구현 설명"],
                suspicious_points=[],
                recommended_followups=[],
            )
        raise AssertionError(f"unexpected schema: {schema}")


@pytest.fixture()
def fake_llm(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeInterviewLlm]:
    llm = FakeInterviewLlm()
    original_init = ProjectEvaluationService.__init__

    def init_with_fake_llms(self, repository, settings):
        original_init(self, repository, settings)
        self._eval_llm = llm
        self._report_llm = llm

    monkeypatch.setattr(ProjectEvaluationService, "__init__", init_with_fake_llms)
    yield llm


@pytest.fixture()
def evaluation_with_session(fake_llm: FakeInterviewLlm) -> dict[str, object]:
    create_resp = client.post(
        "/api/project-evaluations",
        json={
            "project_name": "턴 인터뷰 프로젝트",
            "candidate_name": "지원자",
            "description": "턴 단위 인터뷰 테스트",
            "room_name": "턴 인터뷰 방",
            "room_password": "room-pass",
            "admin_password": "admin-pass",
            "question_policy": {
                "total_question_count": 2,
                "bloom_ratios": {
                    "기억": 1,
                    "이해": 1,
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
                    "question": "업로드 이후 API 흐름을 설명해 주세요.",
                    "intent": "구현 경로 확인",
                    "bloom_level": "기억",
                    "difficulty": "medium",
                    "rubric_criteria": [criterion.value for criterion in RubricCriterion],
                    "source_refs": [{"path": "main.py", "snippet": "FastAPI app"}],
                    "expected_signal": "FastAPI 라우터 흐름",
                    "verification_focus": "API 흐름",
                    "expected_evidence": "main.py",
                    "source_ref_requirements": "코드 근거 필요",
                },
                {
                    "question": "리포트 생성 흐름을 설명해 주세요.",
                    "intent": "평가 경로 확인",
                    "bloom_level": "이해",
                    "difficulty": "medium",
                    "rubric_criteria": [criterion.value for criterion in RubricCriterion],
                    "source_refs": [{"path": "report.py", "snippet": "report"}],
                    "expected_signal": "리포트 생성 흐름",
                    "verification_focus": "리포트 흐름",
                    "expected_evidence": "report.py",
                    "source_ref_requirements": "코드 근거 필요",
                },
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


def _headers(data: dict[str, object]) -> dict[str, str]:
    return {"X-Session-Token": str(data["session_token"])}


def test_open_page_validates_token_before_setting_cookie(
    evaluation_with_session: dict[str, object],
) -> None:
    browser = TestClient(app)
    evaluation_id = evaluation_with_session["evaluation_id"]
    session_id = evaluation_with_session["session_id"]

    invalid_resp = browser.post(
        f"/interview/{evaluation_id}/{session_id}/open",
        data={"session_token": "invalid-token"},
        follow_redirects=False,
    )
    assert invalid_resp.status_code == 403, invalid_resp.text
    assert "set-cookie" not in invalid_resp.headers

    valid_resp = browser.post(
        f"/interview/{evaluation_id}/{session_id}/open",
        data={"session_token": evaluation_with_session["session_token"]},
        follow_redirects=False,
    )
    assert valid_resp.status_code == 303, valid_resp.text
    assert f"interview_session_{session_id}" in valid_resp.headers["set-cookie"]


def test_cookie_session_token_allows_interview_state_and_answer(
    evaluation_with_session: dict[str, object],
    fake_llm: FakeInterviewLlm,
) -> None:
    browser = TestClient(app)
    evaluation_id = evaluation_with_session["evaluation_id"]
    session_id = evaluation_with_session["session_id"]
    open_resp = browser.post(
        f"/interview/{evaluation_id}/{session_id}/open",
        data={"session_token": evaluation_with_session["session_token"]},
        follow_redirects=False,
    )
    assert open_resp.status_code == 303, open_resp.text

    state_resp = browser.get(
        f"/api/project-evaluations/{evaluation_id}/sessions/{session_id}/interview/state"
    )
    assert state_resp.status_code == 200, state_resp.text
    current_question_id = state_resp.json()["question"]["id"]

    fake_llm.follow_up_question = None
    answer_resp = browser.post(
        f"/api/project-evaluations/{evaluation_id}/sessions/{session_id}/interview/answer",
        json={
            "mode": "answer",
            "answer_text": "zip 업로드 후 FastAPI 라우터가 분석 작업을 시작합니다.",
            "draft_answer": "",
            "current_question_id": current_question_id,
        },
    )
    assert answer_resp.status_code == 200, answer_resp.text
    assert answer_resp.json()["status"] == "need_more"


def test_interview_state_returns_current_question(
    evaluation_with_session: dict[str, object],
) -> None:
    resp = client.get(
        f"/api/project-evaluations/{evaluation_with_session['evaluation_id']}"
        f"/sessions/{evaluation_with_session['session_id']}/interview/state",
        headers=_headers(evaluation_with_session),
    )

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["current_question_index"] == 0
    assert data["total_questions"] == 2
    assert data["question"]["question"] == "업로드 이후 API 흐름을 설명해 주세요."
    assert data["turns"] == []
    assert data["is_completed"] is False


def test_answer_with_follow_up_preview_returns_need_follow_up(
    evaluation_with_session: dict[str, object],
    fake_llm: FakeInterviewLlm,
) -> None:
    fake_llm.chat_responses = ["answer"]
    fake_llm.follow_up_question = "구체적으로 어떤 파일에서 처리되나요?"

    resp = client.post(
        f"/api/project-evaluations/{evaluation_with_session['evaluation_id']}"
        f"/sessions/{evaluation_with_session['session_id']}/interview/answer",
        headers=_headers(evaluation_with_session),
        json={
            "mode": "answer",
            "answer_text": "zip 업로드 후 FastAPI 라우터가 분석 작업을 시작합니다.",
            "draft_answer": "",
        },
    )

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "need_follow_up"
    assert data["next_mode"] == "follow_up"
    assert data["draft_answer"] == "zip 업로드 후 FastAPI 라우터가 분석 작업을 시작합니다."
    assert data["follow_up_question"] == "구체적으로 어떤 파일에서 처리되나요?"


def test_follow_up_answer_is_submitted_as_single_turn(
    evaluation_with_session: dict[str, object],
    fake_llm: FakeInterviewLlm,
) -> None:
    fake_llm.chat_responses = ["answer"]
    fake_llm.follow_up_question = None

    resp = client.post(
        f"/api/project-evaluations/{evaluation_with_session['evaluation_id']}"
        f"/sessions/{evaluation_with_session['session_id']}/interview/answer",
        headers=_headers(evaluation_with_session),
        json={
            "mode": "follow_up",
            "answer_text": "router.py의 업로드 endpoint가 service를 호출합니다.",
            "draft_answer": "zip 업로드 후 FastAPI 라우터가 분석 작업을 시작합니다.",
            "follow_up_question": "구체적으로 어떤 파일에서 처리되나요?",
        },
    )

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "turn_submitted"
    assert data["turn"]["question_text"] == "업로드 이후 API 흐름을 설명해 주세요."
    assert "zip 업로드 후" in data["turn"]["answer_text"]
    assert "구체적으로 어떤 파일에서 처리되나요?" in data["turn"]["answer_text"]
    assert "router.py의 업로드 endpoint" in data["turn"]["answer_text"]
    assert data["next_question"]["question"] == "리포트 생성 흐름을 설명해 주세요."


def test_more_decline_submits_current_draft(
    evaluation_with_session: dict[str, object],
    fake_llm: FakeInterviewLlm,
) -> None:
    fake_llm.chat_responses = ["answer", "yes"]
    fake_llm.follow_up_question = None

    resp = client.post(
        f"/api/project-evaluations/{evaluation_with_session['evaluation_id']}"
        f"/sessions/{evaluation_with_session['session_id']}/interview/answer",
        headers=_headers(evaluation_with_session),
        json={
            "mode": "more",
            "answer_text": "없습니다.",
            "draft_answer": "이미 설명한 답변입니다.",
        },
    )

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "turn_submitted"
    assert data["turn"]["answer_text"] == "이미 설명한 답변입니다."
    assert data["next_mode"] == "answer"


def test_skip_intent_submits_skip_turn(
    evaluation_with_session: dict[str, object],
    fake_llm: FakeInterviewLlm,
) -> None:
    fake_llm.chat_responses = ["skip"]

    resp = client.post(
        f"/api/project-evaluations/{evaluation_with_session['evaluation_id']}"
        f"/sessions/{evaluation_with_session['session_id']}/interview/answer",
        headers=_headers(evaluation_with_session),
        json={
            "mode": "answer",
            "answer_text": "이 질문은 넘어가겠습니다.",
            "draft_answer": "",
        },
    )

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "turn_submitted"
    assert data["turn"]["answer_text"] == "(건너뜀)"


def test_stale_question_id_rejects_draft_submission(
    evaluation_with_session: dict[str, object],
    fake_llm: FakeInterviewLlm,
) -> None:
    state_resp = client.get(
        f"/api/project-evaluations/{evaluation_with_session['evaluation_id']}"
        f"/sessions/{evaluation_with_session['session_id']}/interview/state",
        headers=_headers(evaluation_with_session),
    )
    assert state_resp.status_code == 200, state_resp.text
    current_question_id = state_resp.json()["question"]["id"]
    fake_llm.chat_responses = ["skip"]
    first_resp = client.post(
        f"/api/project-evaluations/{evaluation_with_session['evaluation_id']}"
        f"/sessions/{evaluation_with_session['session_id']}/interview/answer",
        headers=_headers(evaluation_with_session),
        json={
            "mode": "answer",
            "answer_text": "첫 질문은 넘어가겠습니다.",
            "draft_answer": "",
            "current_question_id": current_question_id,
        },
    )
    assert first_resp.status_code == 200, first_resp.text

    fake_llm.chat_responses = ["end_exam"]
    stale_resp = client.post(
        f"/api/project-evaluations/{evaluation_with_session['evaluation_id']}"
        f"/sessions/{evaluation_with_session['session_id']}/interview/answer",
        headers=_headers(evaluation_with_session),
        json={
            "mode": "answer",
            "answer_text": "이제 인터뷰를 끝내겠습니다.",
            "draft_answer": "오래된 질문의 draft 답변입니다.",
            "current_question_id": current_question_id,
        },
    )

    assert stale_resp.status_code == 409, stale_resp.text
    assert stale_resp.json()["detail"]["reason"] == "stale_question"


def test_duplicate_question_turn_is_rejected(
    evaluation_with_session: dict[str, object],
    fake_llm: FakeInterviewLlm,
) -> None:
    with app.state.session_factory() as session:
        repo = ProjectEvaluationRepository(session)
        question = repo.list_question_rows(str(evaluation_with_session["evaluation_id"]))[0]
        service = ProjectEvaluationService(repo, app.state.settings)
        service._eval_llm = fake_llm
        service.submit_turn(
            str(evaluation_with_session["evaluation_id"]),
            str(evaluation_with_session["session_id"]),
            payload=InterviewTurnCreate(question_id=question.id, answer_text="첫 제출"),
            session_token=str(evaluation_with_session["session_token"]),
        )
        with pytest.raises(IntegrityError):
            repo.create_turn(
                session_id=str(evaluation_with_session["session_id"]),
                question=question,
                answer_text="중복 제출",
                score=0.0,
                evaluation_summary="중복",
                rubric_scores=[],
                evidence_matches=[],
                evidence_mismatches=[],
                suspicious_points=[],
                strengths=[],
                follow_up_question=None,
            )


def test_follow_up_skip_preserves_main_draft_answer(
    evaluation_with_session: dict[str, object],
    fake_llm: FakeInterviewLlm,
) -> None:
    fake_llm.chat_responses = ["skip"]

    resp = client.post(
        f"/api/project-evaluations/{evaluation_with_session['evaluation_id']}"
        f"/sessions/{evaluation_with_session['session_id']}/interview/answer",
        headers=_headers(evaluation_with_session),
        json={
            "mode": "follow_up",
            "answer_text": "그 부분은 넘어가겠습니다.",
            "draft_answer": "본답변은 API 흐름 설명입니다.",
            "follow_up_question": "세부 파일은 무엇인가요?",
        },
    )

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "turn_submitted"
    assert data["turn"]["answer_text"] == "본답변은 API 흐름 설명입니다."


def test_end_exam_intent_marks_remaining_questions_unanswered_and_completes(
    evaluation_with_session: dict[str, object],
    fake_llm: FakeInterviewLlm,
) -> None:
    fake_llm.chat_responses = ["end_exam"]

    resp = client.post(
        f"/api/project-evaluations/{evaluation_with_session['evaluation_id']}"
        f"/sessions/{evaluation_with_session['session_id']}/interview/answer",
        headers=_headers(evaluation_with_session),
        json={
            "mode": "answer",
            "answer_text": "이제 인터뷰를 끝내겠습니다.",
            "draft_answer": "",
        },
    )

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "completed"
    assert data["report"]["final_decision"] == "검증 통과"

    turns_resp = client.get(
        f"/api/project-evaluations/{evaluation_with_session['evaluation_id']}"
        f"/sessions/{evaluation_with_session['session_id']}/turns",
        headers=_headers(evaluation_with_session),
    )
    assert turns_resp.status_code == 200, turns_resp.text
    assert [turn["answer_text"] for turn in turns_resp.json()] == ["(미응답)", "(미응답)"]


def test_end_exam_on_later_question_preserves_current_draft_answer(
    evaluation_with_session: dict[str, object],
    fake_llm: FakeInterviewLlm,
) -> None:
    fake_llm.chat_responses = ["skip"]
    first_resp = client.post(
        f"/api/project-evaluations/{evaluation_with_session['evaluation_id']}"
        f"/sessions/{evaluation_with_session['session_id']}/interview/answer",
        headers=_headers(evaluation_with_session),
        json={
            "mode": "answer",
            "answer_text": "첫 질문은 넘어가겠습니다.",
            "draft_answer": "",
        },
    )
    assert first_resp.status_code == 200, first_resp.text

    fake_llm.chat_responses = ["end_exam"]
    end_resp = client.post(
        f"/api/project-evaluations/{evaluation_with_session['evaluation_id']}"
        f"/sessions/{evaluation_with_session['session_id']}/interview/answer",
        headers=_headers(evaluation_with_session),
        json={
            "mode": "answer",
            "answer_text": "이제 인터뷰를 끝내겠습니다.",
            "draft_answer": "두 번째 질문 draft 답변입니다.",
        },
    )
    assert end_resp.status_code == 200, end_resp.text
    assert end_resp.json()["status"] == "completed"

    turns_resp = client.get(
        f"/api/project-evaluations/{evaluation_with_session['evaluation_id']}"
        f"/sessions/{evaluation_with_session['session_id']}/turns",
        headers=_headers(evaluation_with_session),
    )
    assert turns_resp.status_code == 200, turns_resp.text
    assert [turn["answer_text"] for turn in turns_resp.json()] == [
        "(건너뜀)",
        "두 번째 질문 draft 답변입니다.",
    ]
