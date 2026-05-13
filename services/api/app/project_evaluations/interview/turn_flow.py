from __future__ import annotations

from fastapi import HTTPException, status

from services.api.app.project_evaluations.domain.models import (
    FollowUpExchange,
    InterviewQuestionRead,
    InterviewTurnCreate,
    InterviewTurnFlowRequest,
    InterviewTurnFlowResponse,
    InterviewTurnFlowStatus,
    InterviewTurnMode,
    QuestionExchange,
    StudentInterviewStateRead,
)
from services.api.app.project_evaluations.interview.intent_classifier import (
    StudentIntent,
    classify_student_intent,
)
from services.api.app.project_evaluations.service import ProjectEvaluationService

SKIP_ANSWER_TEXT = "(건너뜀)"
UNANSWERED_TEXT = "(미응답)"


class InterviewTurnFlow:
    def __init__(self, service: ProjectEvaluationService) -> None:
        self.service = service

    def get_state(
        self,
        evaluation_id: str,
        session_id: str,
        session_token: str | None,
        client_id: str,
    ) -> StudentInterviewStateRead:
        session = self.service.ensure_session(
            evaluation_id, session_id, session_token, client_id
        )
        questions = [
            self.service.repository.to_question_read(row)
            for row in self.service.repository.list_question_rows(evaluation_id)
        ]
        turns = self.service.list_turns(evaluation_id, session_id, session_token, client_id)
        question = None
        if session.current_question_index < len(questions):
            question = questions[session.current_question_index]
        return StudentInterviewStateRead(
            session_id=session.id,
            current_question_index=session.current_question_index,
            total_questions=len(questions),
            question=question,
            turns=turns,
            is_completed=session.status.value == "completed",
        )

    def submit_answer(
        self,
        evaluation_id: str,
        session_id: str,
        payload: InterviewTurnFlowRequest,
        session_token: str | None,
        client_id: str,
    ) -> InterviewTurnFlowResponse:
        session = self.service.ensure_session(
            evaluation_id, session_id, session_token, client_id
        )
        questions = self.service.repository.list_question_rows(evaluation_id)
        if session.current_question_index >= len(questions):
            report = self.service.complete_session(
                evaluation_id, session_id, session_token, client_id
            )
            return InterviewTurnFlowResponse(
                status=InterviewTurnFlowStatus.COMPLETED,
                message="모든 질문 답변이 완료되어 리포트를 생성했습니다.",
                next_mode=None,
                report=report,
            )

        self._ensure_current_question_matches(payload, questions[session.current_question_index].id)
        if payload.mode == InterviewTurnMode.END:
            return self._complete_remaining(
                evaluation_id,
                session_id,
                self._combine_answer(payload.draft_answer, payload.answer_text) or UNANSWERED_TEXT,
                session_token,
                client_id,
            )
        intent = classify_student_intent(payload.answer_text, self.service._eval_llm)
        if payload.mode == InterviewTurnMode.FOLLOW_UP:
            if intent == StudentIntent.END_EXAM:
                return self._complete_remaining(
                    evaluation_id,
                    session_id,
                    payload.draft_answer.strip() or UNANSWERED_TEXT,
                    session_token,
                    client_id,
                )
            answer_text = (
                payload.draft_answer.strip()
                if intent == StudentIntent.SKIP
                else self._combine_follow_up(payload)
            )
            return self._submit_current_turn(
                evaluation_id,
                session_id,
                answer_text or UNANSWERED_TEXT,
                session_token,
                client_id,
                "꼬리질문 답변을 포함해 현재 질문 답변을 저장했습니다.",
                allow_follow_up_required=True,
                follow_up_question=payload.follow_up_question.strip() or None,
                follow_up_reason=payload.follow_up_reason.strip(),
                conversation_history=QuestionExchange(
                    student_answer=payload.draft_answer.strip() or UNANSWERED_TEXT,
                    follow_ups=[
                        FollowUpExchange(
                            question=payload.follow_up_question.strip(),
                            reason=payload.follow_up_reason.strip(),
                            answer=payload.answer_text.strip() or UNANSWERED_TEXT,
                        )
                    ],
                ),
            )

        if intent == StudentIntent.SKIP:
            return self._submit_current_turn(
                evaluation_id,
                session_id,
                SKIP_ANSWER_TEXT,
                session_token,
                client_id,
                "현재 질문을 건너뛰었습니다.",
                conversation_history=QuestionExchange(student_answer=SKIP_ANSWER_TEXT),
            )
        if intent == StudentIntent.END_EXAM:
            return self._complete_remaining(
                evaluation_id,
                session_id,
                self._combine_answer(payload.draft_answer, payload.answer_text) or UNANSWERED_TEXT,
                session_token,
                client_id,
            )

        draft_answer = self._combine_answer(payload.draft_answer, payload.answer_text)
        follow_up = self.service.preview_follow_up_question(
            evaluation_id,
            session_id,
            session.current_question_index,
            QuestionExchange(student_answer=draft_answer),
            session_token,
            client_id,
        )
        if follow_up:
            return InterviewTurnFlowResponse(
                status=InterviewTurnFlowStatus.NEED_FOLLOW_UP,
                message="답변 확인을 위해 꼬리질문이 필요합니다.",
                draft_answer=draft_answer,
                follow_up_question=follow_up["question"],
                follow_up_reason=follow_up["reason"],
                next_mode=InterviewTurnMode.FOLLOW_UP,
            )
        return self._submit_current_turn(
            evaluation_id,
            session_id,
            draft_answer or UNANSWERED_TEXT,
            session_token,
            client_id,
            "현재 질문 답변을 저장했습니다.",
            conversation_history=QuestionExchange(
                student_answer=draft_answer or UNANSWERED_TEXT
            ),
        )

    def _ensure_current_question_matches(
        self, payload: InterviewTurnFlowRequest, current_question_id: str
    ) -> None:
        if payload.current_question_id is None:
            return
        if payload.current_question_id != current_question_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "stage": "interview_turn",
                    "reason": "stale_question",
                    "message": "현재 질문이 변경되었습니다. 최신 상태를 다시 조회하세요.",
                    "current_question_id": current_question_id,
                    "submitted_question_id": payload.current_question_id,
                },
            )

    def _submit_current_turn(
        self,
        evaluation_id: str,
        session_id: str,
        answer_text: str,
        session_token: str | None,
        client_id: str,
        message: str,
        allow_follow_up_required: bool = False,
        follow_up_question: str | None = None,
        follow_up_reason: str = "",
        conversation_history: QuestionExchange | None = None,
    ) -> InterviewTurnFlowResponse:
        session = self.service.ensure_session(
            evaluation_id, session_id, session_token, client_id
        )
        questions = self.service.repository.list_question_rows(evaluation_id)
        if session.current_question_index >= len(questions):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="답변할 현재 질문이 없습니다.",
            )
        turn = self.service.submit_turn(
            evaluation_id,
            session_id,
            InterviewTurnCreate(
                question_id=questions[session.current_question_index].id,
                answer_text=answer_text.strip() or UNANSWERED_TEXT,
            ),
            session_token,
            client_id,
            allow_follow_up_required=allow_follow_up_required,
            follow_up_question=follow_up_question if allow_follow_up_required else None,
            follow_up_reason=follow_up_reason if allow_follow_up_required else "",
            conversation_history=conversation_history,
        )
        updated_session = self.service.ensure_session(
            evaluation_id, session_id, session_token, client_id
        )
        next_question = self._next_question(evaluation_id, updated_session.current_question_index)
        if next_question is None:
            return InterviewTurnFlowResponse(
                status=InterviewTurnFlowStatus.READY_TO_COMPLETE,
                message="모든 질문 답변이 저장되었습니다. 리포트를 생성할 수 있습니다.",
                turn=turn,
                next_mode=None,
            )
        return InterviewTurnFlowResponse(
            status=InterviewTurnFlowStatus.TURN_SUBMITTED,
            message=message,
            turn=turn,
            next_question=next_question,
            next_mode=InterviewTurnMode.ANSWER,
        )

    def _complete_remaining(
        self,
        evaluation_id: str,
        session_id: str,
        current_answer_text: str,
        session_token: str | None,
        client_id: str,
    ) -> InterviewTurnFlowResponse:
        starting_session = self.service.ensure_session(
            evaluation_id, session_id, session_token, client_id
        )
        current_question_index = starting_session.current_question_index
        while True:
            session = self.service.ensure_session(
                evaluation_id, session_id, session_token, client_id
            )
            questions = self.service.repository.list_question_rows(evaluation_id)
            if session.current_question_index >= len(questions):
                break
            answer_text = (
                current_answer_text
                if session.current_question_index == current_question_index
                else UNANSWERED_TEXT
            )
            self.service.submit_turn(
                evaluation_id,
                session_id,
                InterviewTurnCreate(
                    question_id=questions[session.current_question_index].id,
                    answer_text=answer_text.strip() or UNANSWERED_TEXT,
                ),
                session_token,
                client_id,
                allow_follow_up_required=True,
            )
        report = self.service.complete_session(
            evaluation_id, session_id, session_token, client_id
        )
        return InterviewTurnFlowResponse(
            status=InterviewTurnFlowStatus.COMPLETED,
            message="인터뷰를 조기 종료하고 남은 질문을 미응답으로 처리했습니다.",
            next_mode=None,
            report=report,
        )

    def _next_question(
        self, evaluation_id: str, question_index: int
    ) -> InterviewQuestionRead | None:
        questions = self.service.repository.list_question_rows(evaluation_id)
        if question_index >= len(questions):
            return None
        return self.service.repository.to_question_read(questions[question_index])

    def _combine_follow_up(self, payload: InterviewTurnFlowRequest) -> str:
        parts = [payload.draft_answer.strip()]
        if payload.follow_up_question and payload.answer_text.strip():
            parts.append(f"꼬리질문: {payload.follow_up_question.strip()}")
        parts.append(payload.answer_text.strip())
        return "\n".join(part for part in parts if part)

    def _combine_answer(self, existing: str, addition: str) -> str:
        return "\n".join(part for part in [existing.strip(), addition.strip()] if part)
