import json
from collections.abc import Iterable
from typing import Any
from uuid import uuid4

from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from services.api.app.project_evaluations.rag.redaction import redact_sensitive_text
from services.api.app.project_evaluations.domain.models import (
    ArtifactSourceType,
    ArtifactStatus,
    BloomLevel,
    Difficulty,
    EvaluationReportRead,
    EvaluationStatus,
    ExtractedProjectContextRead,
    FinalDecision,
    FollowUpExchange,
    InterviewQuestionRead,
    InterviewSessionRead,
    InterviewSessionStatus,
    InterviewTurnRead,
    ProjectAreaRead,
    ProjectArtifactRead,
    ProjectEvaluationCreate,
    ProjectEvaluationRead,
    QuestionExchange,
    QuestionGenerationPolicy,
    RubricCriterion,
    RubricScoreItem,
    SourceReference,
)
from services.api.app.project_evaluations.persistence.models import (
    EvaluationReportRow,
    ExtractedProjectContextRow,
    InterviewQuestionRow,
    InterviewSessionRow,
    InterviewTurnRow,
    ProjectAreaRow,
    ProjectArtifactRow,
    ProjectEvaluationRow,
    RubricScoreRow,
    utc_now,
)


def new_id() -> str:
    return str(uuid4())


def to_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def from_json(value: str, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError as exc:
        raise RuntimeError("저장된 JSON 데이터 파싱에 실패했습니다.") from exc


def refs_from_json(value: str) -> list[SourceReference]:
    return [SourceReference(**item) for item in from_json(value, [])]


def _normalize_legacy_value(value: str) -> str:
    return "창안" if value == "창조" else value


def rubric_from_json(value: str) -> list[RubricCriterion]:
    return [RubricCriterion(_normalize_legacy_value(item)) for item in from_json(value, [])]


def _validate_question_source_refs(question: dict[str, Any]) -> None:
    refs = question.get("source_refs")
    if not isinstance(refs, list) or not refs:
        raise RuntimeError("질문 저장에는 source refs가 필요합니다.")
    valid_refs = [ref for ref in refs if isinstance(ref, dict) and str(ref.get("path", "")).strip()]
    if not valid_refs:
        raise RuntimeError("질문 저장에는 유효한 source ref가 필요합니다.")


class ProjectEvaluationRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create_evaluation(
        self,
        payload: ProjectEvaluationCreate,
        room_password_hash: str = "",
        admin_password_hash: str = "",
    ) -> ProjectEvaluationRead:
        row = ProjectEvaluationRow(
            id=new_id(),
            project_name=payload.project_name,
            candidate_name=payload.candidate_name,
            description=payload.description,
            room_name=payload.room_name or payload.project_name,
            room_password_hash=room_password_hash,
            admin_password_hash=admin_password_hash,
            question_policy_json=to_json(payload.question_policy.model_dump()),
            status=EvaluationStatus.CREATED.value,
        )
        self.session.add(row)
        self.session.commit()
        self.session.refresh(row)
        return self.to_evaluation_read(row)

    def get_evaluation_row(self, evaluation_id: str) -> ProjectEvaluationRow | None:
        return self.session.get(ProjectEvaluationRow, evaluation_id)

    def get_evaluation(self, evaluation_id: str) -> ProjectEvaluationRead | None:
        row = self.get_evaluation_row(evaluation_id)
        if row is None:
            return None
        return self.to_evaluation_read(row)

    def get_question_policy(self, evaluation_id: str) -> QuestionGenerationPolicy:
        row = self.get_evaluation_row(evaluation_id)
        if row is None:
            return QuestionGenerationPolicy()
        return QuestionGenerationPolicy(**from_json(row.question_policy_json, {}))

    def update_evaluation_status(
        self, evaluation_id: str, status: EvaluationStatus
    ) -> ProjectEvaluationRead | None:
        row = self.get_evaluation_row(evaluation_id)
        if row is None:
            return None
        row.status = status.value
        row.updated_at = utc_now()
        self.session.commit()
        self.session.refresh(row)
        return self.to_evaluation_read(row)

    def create_artifact(
        self,
        evaluation_id: str,
        source_path: str,
        source_type: ArtifactSourceType,
        status: ArtifactStatus,
        raw_text: str,
        metadata: dict[str, Any] | None = None,
    ) -> ProjectArtifactRead:
        row = ProjectArtifactRow(
            id=new_id(),
            evaluation_id=evaluation_id,
            source_path=source_path,
            source_type=source_type.value,
            status=status.value,
            raw_text=raw_text,
            char_count=len(raw_text),
            metadata_json=to_json(metadata or {}),
        )
        self.session.add(row)
        self.session.commit()
        self.session.refresh(row)
        return self.to_artifact_read(row)

    def list_artifacts(self, evaluation_id: str) -> list[ProjectArtifactRead]:
        rows = self.session.scalars(
            select(ProjectArtifactRow)
            .where(ProjectArtifactRow.evaluation_id == evaluation_id)
            .order_by(ProjectArtifactRow.source_path)
        ).all()
        return [self.to_artifact_read(row) for row in rows]

    def list_artifact_rows(self, evaluation_id: str) -> list[ProjectArtifactRow]:
        return list(
            self.session.scalars(
                select(ProjectArtifactRow)
                .where(ProjectArtifactRow.evaluation_id == evaluation_id)
                .order_by(ProjectArtifactRow.source_path)
            ).all()
        )

    def has_artifacts(self, evaluation_id: str) -> bool:
        return (
            self.session.scalar(
                select(ProjectArtifactRow.id)
                .where(ProjectArtifactRow.evaluation_id == evaluation_id)
                .limit(1)
            )
            is not None
        )

    def has_questions(self, evaluation_id: str) -> bool:
        return (
            self.session.scalar(
                select(InterviewQuestionRow.id)
                .where(InterviewQuestionRow.evaluation_id == evaluation_id)
                .limit(1)
            )
            is not None
        )

    def has_sessions(self, evaluation_id: str) -> bool:
        return (
            self.session.scalar(
                select(InterviewSessionRow.id)
                .where(InterviewSessionRow.evaluation_id == evaluation_id)
                .limit(1)
            )
            is not None
        )

    def has_turn_for_question(self, session_id: str, question_id: str) -> bool:
        return (
            self.session.scalar(
                select(InterviewTurnRow.id)
                .where(InterviewTurnRow.session_id == session_id)
                .where(InterviewTurnRow.question_id == question_id)
                .limit(1)
            )
            is not None
        )

    def save_context(
        self,
        evaluation_id: str,
        summary: str,
        tech_stack: list[str],
        features: list[str],
        architecture_notes: list[str],
        data_flow: list[str],
        risk_points: list[str],
        question_targets: list[str],
        areas: list[dict[str, Any]],
        rag_status: dict[str, Any] | None = None,
    ) -> ExtractedProjectContextRead:
        if self.has_sessions(evaluation_id):
            raise RuntimeError("인터뷰가 시작된 평가는 context를 교체할 수 없습니다.")
        self.session.execute(
            delete(InterviewQuestionRow).where(
                InterviewQuestionRow.evaluation_id == evaluation_id
            )
        )
        self.session.execute(
            delete(ProjectAreaRow).where(ProjectAreaRow.evaluation_id == evaluation_id)
        )
        existing = self.session.scalar(
            select(ExtractedProjectContextRow).where(
                ExtractedProjectContextRow.evaluation_id == evaluation_id
            )
        )
        row = existing or ExtractedProjectContextRow(
            id=new_id(), evaluation_id=evaluation_id
        )
        row.summary = summary
        row.tech_stack_json = to_json(tech_stack)
        row.features_json = to_json(features)
        row.architecture_notes_json = to_json(architecture_notes)
        row.data_flow_json = to_json(data_flow)
        row.risk_points_json = to_json(risk_points)
        row.question_targets_json = to_json(question_targets)
        row.rag_status_json = to_json(rag_status or {})
        if existing is None:
            self.session.add(row)

        area_rows = []
        for area in areas:
            area_row = ProjectAreaRow(
                id=new_id(),
                evaluation_id=evaluation_id,
                name=str(area["name"]),
                summary=str(area.get("summary", "")),
                confidence=float(area.get("confidence", 0.0)),
                source_refs_json=to_json(area.get("source_refs", [])),
            )
            self.session.add(area_row)
            area_rows.append(area_row)

        self.session.commit()
        self.session.refresh(row)
        for area_row in area_rows:
            self.session.refresh(area_row)
        return self.to_context_read(row, area_rows)

    def get_context_row(
        self, evaluation_id: str
    ) -> ExtractedProjectContextRow | None:
        return self.session.scalar(
            select(ExtractedProjectContextRow).where(
                ExtractedProjectContextRow.evaluation_id == evaluation_id
            )
        )

    def get_context(self, evaluation_id: str) -> ExtractedProjectContextRead | None:
        row = self.get_context_row(evaluation_id)
        if row is None:
            return None
        return self.to_context_read(row, self.list_area_rows(evaluation_id))

    def list_area_rows(self, evaluation_id: str) -> list[ProjectAreaRow]:
        return list(
            self.session.scalars(
                select(ProjectAreaRow)
                .where(ProjectAreaRow.evaluation_id == evaluation_id)
                .order_by(ProjectAreaRow.name)
            ).all()
        )

    def list_areas(self, evaluation_id: str) -> list[ProjectAreaRead]:
        return [self.to_area_read(row) for row in self.list_area_rows(evaluation_id)]

    def save_questions(
        self, evaluation_id: str, questions: list[dict[str, Any]]
    ) -> list[InterviewQuestionRead]:
        if self.has_sessions(evaluation_id):
            raise RuntimeError("인터뷰가 시작된 평가는 질문을 교체할 수 없습니다.")
        for question in questions:
            _validate_question_source_refs(question)
        self.session.execute(
            delete(InterviewQuestionRow).where(
                InterviewQuestionRow.evaluation_id == evaluation_id
            )
        )
        rows = []
        for index, question in enumerate(questions):
            row = InterviewQuestionRow(
                id=new_id(),
                evaluation_id=evaluation_id,
                project_area_id=question.get("project_area_id"),
                question=str(question["question"]),
                intent=str(question.get("intent", "")),
                bloom_level=str(question["bloom_level"]),
                difficulty=str(question.get("difficulty", Difficulty.MEDIUM.value)),
                rubric_criteria_json=to_json(question.get("rubric_criteria", [])),
                source_refs_json=to_json(question.get("source_refs", [])),
                expected_signal=str(question.get("expected_signal", "")),
                verification_focus=str(question.get("verification_focus", "")),
                expected_evidence=str(question.get("expected_evidence", "")),
                source_ref_requirements=str(question.get("source_ref_requirements", "")),
                order_index=index,
            )
            self.session.add(row)
            rows.append(row)
        self.session.commit()
        for row in rows:
            self.session.refresh(row)
        return [self.to_question_read(row) for row in rows]

    def list_question_rows(self, evaluation_id: str) -> list[InterviewQuestionRow]:
        return list(
            self.session.scalars(
                select(InterviewQuestionRow)
                .where(InterviewQuestionRow.evaluation_id == evaluation_id)
                .order_by(InterviewQuestionRow.order_index)
            ).all()
        )

    def list_questions(self, evaluation_id: str) -> list[InterviewQuestionRead]:
        return [
            self.to_question_read(row) for row in self.list_question_rows(evaluation_id)
        ]

    def get_question_row(self, question_id: str) -> InterviewQuestionRow | None:
        return self.session.get(InterviewQuestionRow, question_id)

    def create_session(
        self,
        evaluation_id: str,
        participant_name: str = "",
        session_token_hash: str = "",
        session_token: str = "",
    ) -> InterviewSessionRead:
        row = InterviewSessionRow(
            id=new_id(),
            evaluation_id=evaluation_id,
            participant_name=participant_name,
            session_token_hash=session_token_hash,
            status=InterviewSessionStatus.IN_PROGRESS.value,
        )
        self.session.add(row)
        self.session.commit()
        self.session.refresh(row)
        return self.to_session_read(row, session_token=session_token)

    def get_session_row(self, session_id: str) -> InterviewSessionRow | None:
        return self.session.get(InterviewSessionRow, session_id)

    def get_session(self, session_id: str) -> InterviewSessionRead | None:
        row = self.get_session_row(session_id)
        if row is None:
            return None
        return self.to_session_read(row)

    def create_turn(
        self,
        session_id: str,
        question: InterviewQuestionRow,
        answer_text: str,
        score: float,
        evaluation_summary: str,
        rubric_scores: list[RubricScoreItem],
        evidence_matches: list[str],
        evidence_mismatches: list[str],
        suspicious_points: list[str],
        strengths: list[str],
        follow_up_question: str | None,
        follow_up_reason: str = "",
        finalized_score: float | None = None,
        conversation_history: QuestionExchange | None = None,
    ) -> InterviewTurnRead:
        turn = InterviewTurnRow(
            id=new_id(),
            session_id=session_id,
            question_id=question.id,
            question_text=question.question,
            answer_text=answer_text,
            score=score,
            evaluation_summary=evaluation_summary,
            evidence_matches_json=to_json(evidence_matches),
            evidence_mismatches_json=to_json(evidence_mismatches),
            suspicious_points_json=to_json(suspicious_points),
            strengths_json=to_json(strengths),
            follow_up_question=follow_up_question,
            follow_up_reason=follow_up_reason,
            finalized_score=finalized_score,
            conversation_history_json=to_json(
                conversation_history.model_dump() if conversation_history else {}
            ),
        )
        try:
            self.session.add(turn)
            self.session.flush()
            for item in rubric_scores:
                self.session.add(
                    RubricScoreRow(
                        id=new_id(),
                        turn_id=turn.id,
                        criterion=item.criterion.value,
                        score=item.score,
                        rationale=item.rationale,
                    )
                )
            session = self.get_session_row(session_id)
            if session is not None:
                session.current_question_index += 1
            self.session.commit()
        except IntegrityError:
            self.session.rollback()
            raise
        self.session.refresh(turn)
        return self.to_turn_read(turn, rubric_scores)

    def update_turn_evaluation(
        self,
        turn_id: str,
        score: float,
        evaluation_summary: str,
        rubric_scores: list[RubricScoreItem],
        evidence_matches: list[str],
        evidence_mismatches: list[str],
        suspicious_points: list[str],
        strengths: list[str],
        finalized_score: float | None = None,
    ) -> InterviewTurnRead:
        turn = self.session.get(InterviewTurnRow, turn_id)
        if turn is None:
            raise RuntimeError(f"답변 turn을 찾을 수 없습니다. turn_id={turn_id}")
        turn.score = score
        turn.evaluation_summary = evaluation_summary
        turn.evidence_matches_json = to_json(evidence_matches)
        turn.evidence_mismatches_json = to_json(evidence_mismatches)
        turn.suspicious_points_json = to_json(suspicious_points)
        turn.strengths_json = to_json(strengths)
        turn.finalized_score = finalized_score
        self.session.execute(delete(RubricScoreRow).where(RubricScoreRow.turn_id == turn_id))
        self.session.flush()
        for item in rubric_scores:
            self.session.add(
                RubricScoreRow(
                    id=new_id(),
                    turn_id=turn.id,
                    criterion=item.criterion.value,
                    score=item.score,
                    rationale=item.rationale,
                )
            )
        self.session.commit()
        self.session.refresh(turn)
        return self.to_turn_read(turn, rubric_scores)

    def list_turn_rows(self, session_id: str) -> list[InterviewTurnRow]:
        return list(
            self.session.scalars(
                select(InterviewTurnRow)
                .where(InterviewTurnRow.session_id == session_id)
                .order_by(InterviewTurnRow.created_at)
            ).all()
        )

    def list_turns(self, session_id: str) -> list[InterviewTurnRead]:
        rows = self.list_turn_rows(session_id)
        return [self.to_turn_read(row, self.get_rubric_scores(row.id)) for row in rows]

    def get_rubric_scores(self, turn_id: str) -> list[RubricScoreItem]:
        rows = self.session.scalars(
            select(RubricScoreRow).where(RubricScoreRow.turn_id == turn_id)
        ).all()
        return [
            RubricScoreItem(
                criterion=RubricCriterion(_normalize_legacy_value(row.criterion)),
                score=row.score,
                rationale=row.rationale,
            )
            for row in rows
        ]

    def rubric_scores_by_turn(self, turn_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
        if not turn_ids:
            return {}
        rows = self.session.scalars(
            select(RubricScoreRow).where(RubricScoreRow.turn_id.in_(turn_ids))
        ).all()
        scores: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            scores.setdefault(row.turn_id, []).append(
                {
                    "criterion": _normalize_legacy_value(row.criterion),
                    "score": row.score,
                    "rationale": row.rationale,
                }
            )
        return scores

    def complete_session(self, session_id: str) -> InterviewSessionRead | None:
        row = self.get_session_row(session_id)
        if row is None:
            return None
        row.status = InterviewSessionStatus.COMPLETED.value
        row.completed_at = utc_now()
        self.session.commit()
        self.session.refresh(row)
        return self.to_session_read(row)

    def save_completed_report(
        self,
        evaluation_id: str,
        session_id: str,
        final_decision: FinalDecision,
        authenticity_score: float,
        summary: str,
        area_analyses: list[dict[str, Any]],
        question_evaluations: list[dict[str, Any]],
        bloom_summary: list[dict[str, Any]],
        rubric_summary: list[dict[str, Any]],
        evidence_alignment: list[str],
        strengths: list[str],
        suspicious_points: list[str],
        recommended_followups: list[str],
    ) -> EvaluationReportRead:
        session = self.get_session_row(session_id)
        if session is not None:
            session.status = InterviewSessionStatus.COMPLETED.value
            session.completed_at = utc_now()
        row = EvaluationReportRow(
            id=new_id(),
            evaluation_id=evaluation_id,
            session_id=session_id,
            final_decision=final_decision.value,
            authenticity_score=authenticity_score,
            summary=summary,
            area_analyses_json=to_json(area_analyses),
            question_evaluations_json=to_json(question_evaluations),
            bloom_summary_json=to_json(bloom_summary),
            rubric_summary_json=to_json(rubric_summary),
            evidence_alignment_json=to_json(evidence_alignment),
            strengths_json=to_json(strengths),
            suspicious_points_json=to_json(suspicious_points),
            recommended_followups_json=to_json(recommended_followups),
        )
        self.session.add(row)
        self.session.execute(
            update(ProjectEvaluationRow)
            .where(ProjectEvaluationRow.id == evaluation_id)
            .values(status=EvaluationStatus.REPORTED.value, updated_at=utc_now())
        )
        self.session.commit()
        self.session.refresh(row)
        return self.to_report_read(row)

    def save_report(
        self,
        evaluation_id: str,
        session_id: str,
        final_decision: FinalDecision,
        authenticity_score: float,
        summary: str,
        area_analyses: list[dict[str, Any]],
        question_evaluations: list[dict[str, Any]],
        bloom_summary: list[dict[str, Any]],
        rubric_summary: list[dict[str, Any]],
        evidence_alignment: list[str],
        strengths: list[str],
        suspicious_points: list[str],
        recommended_followups: list[str],
    ) -> EvaluationReportRead:
        row = EvaluationReportRow(
            id=new_id(),
            evaluation_id=evaluation_id,
            session_id=session_id,
            final_decision=final_decision.value,
            authenticity_score=authenticity_score,
            summary=summary,
            area_analyses_json=to_json(area_analyses),
            question_evaluations_json=to_json(question_evaluations),
            bloom_summary_json=to_json(bloom_summary),
            rubric_summary_json=to_json(rubric_summary),
            evidence_alignment_json=to_json(evidence_alignment),
            strengths_json=to_json(strengths),
            suspicious_points_json=to_json(suspicious_points),
            recommended_followups_json=to_json(recommended_followups),
        )
        self.session.add(row)
        self.session.commit()
        self.session.refresh(row)
        return self.to_report_read(row)

    def get_report(self, report_id: str) -> EvaluationReportRead | None:
        row = self.session.get(EvaluationReportRow, report_id)
        if row is None:
            return None
        return self.to_report_read(row)

    def get_latest_report(self, evaluation_id: str) -> EvaluationReportRead | None:
        row = self.session.scalar(
            select(EvaluationReportRow)
            .where(EvaluationReportRow.evaluation_id == evaluation_id)
            .order_by(EvaluationReportRow.created_at.desc())
            .limit(1)
        )
        if row is None:
            return None
        return self.to_report_read(row)

    def get_latest_report_for_session(self, session_id: str) -> EvaluationReportRead | None:
        row = self.session.scalar(
            select(EvaluationReportRow)
            .where(EvaluationReportRow.session_id == session_id)
            .order_by(EvaluationReportRow.created_at.desc())
            .limit(1)
        )
        if row is None:
            return None
        return self.to_report_read(row)

    def to_evaluation_read(self, row: ProjectEvaluationRow) -> ProjectEvaluationRead:
        return ProjectEvaluationRead(
            id=row.id,
            project_name=row.project_name,
            candidate_name=row.candidate_name,
            description=row.description,
            room_name=row.room_name,
            status=EvaluationStatus(row.status),
            question_policy=QuestionGenerationPolicy(**from_json(row.question_policy_json, {})),
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    def to_artifact_read(self, row: ProjectArtifactRow) -> ProjectArtifactRead:
        return ProjectArtifactRead(
            id=row.id,
            evaluation_id=row.evaluation_id,
            source_path=row.source_path,
            source_type=ArtifactSourceType(row.source_type),
            status=ArtifactStatus(row.status),
            char_count=row.char_count,
            text_preview=redact_sensitive_text(row.raw_text)[:500],
            metadata=from_json(row.metadata_json, {}),
            created_at=row.created_at,
        )

    def to_context_read(
        self, row: ExtractedProjectContextRow, areas: Iterable[ProjectAreaRow]
    ) -> ExtractedProjectContextRead:
        return ExtractedProjectContextRead(
            id=row.id,
            evaluation_id=row.evaluation_id,
            summary=row.summary,
            tech_stack=from_json(row.tech_stack_json, []),
            features=from_json(row.features_json, []),
            architecture_notes=from_json(row.architecture_notes_json, []),
            data_flow=from_json(row.data_flow_json, []),
            risk_points=from_json(row.risk_points_json, []),
            question_targets=from_json(row.question_targets_json, []),
            rag_status=from_json(row.rag_status_json, {}),
            areas=[self.to_area_read(area) for area in areas],
            created_at=row.created_at,
        )

    def to_area_read(self, row: ProjectAreaRow) -> ProjectAreaRead:
        return ProjectAreaRead(
            id=row.id,
            evaluation_id=row.evaluation_id,
            name=row.name,
            summary=row.summary,
            confidence=row.confidence,
            source_refs=refs_from_json(row.source_refs_json),
        )

    def to_question_read(self, row: InterviewQuestionRow) -> InterviewQuestionRead:
        return InterviewQuestionRead(
            id=row.id,
            evaluation_id=row.evaluation_id,
            project_area_id=row.project_area_id,
            question=row.question,
            intent=row.intent,
            bloom_level=BloomLevel(_normalize_legacy_value(row.bloom_level)),
            difficulty=Difficulty(row.difficulty),
            rubric_criteria=rubric_from_json(row.rubric_criteria_json),
            source_refs=refs_from_json(row.source_refs_json),
            expected_signal=row.expected_signal,
            verification_focus=row.verification_focus,
            expected_evidence=row.expected_evidence,
            source_ref_requirements=row.source_ref_requirements,
            order_index=row.order_index,
            created_at=row.created_at,
        )

    def to_session_read(
        self, row: InterviewSessionRow, session_token: str = ""
    ) -> InterviewSessionRead:
        return InterviewSessionRead(
            id=row.id,
            evaluation_id=row.evaluation_id,
            participant_name=row.participant_name,
            session_token=session_token,
            status=InterviewSessionStatus(row.status),
            current_question_index=row.current_question_index,
            created_at=row.created_at,
            completed_at=row.completed_at,
        )

    def to_turn_read(
        self, row: InterviewTurnRow, rubric_scores: list[RubricScoreItem]
    ) -> InterviewTurnRead:
        conversation_data = from_json(row.conversation_history_json, {})
        conversation_history = None
        if conversation_data:
            follow_ups = [
                FollowUpExchange(**item)
                for item in conversation_data.get("follow_ups", [])
            ]
            conversation_history = QuestionExchange(
                student_answer=str(conversation_data.get("student_answer", "")),
                follow_ups=follow_ups,
            )
        return InterviewTurnRead(
            id=row.id,
            session_id=row.session_id,
            question_id=row.question_id,
            question_text=row.question_text,
            answer_text=row.answer_text,
            score=row.score,
            evaluation_summary=row.evaluation_summary,
            rubric_scores=rubric_scores,
            evidence_matches=from_json(row.evidence_matches_json, []),
            evidence_mismatches=from_json(row.evidence_mismatches_json, []),
            suspicious_points=from_json(row.suspicious_points_json, []),
            strengths=from_json(row.strengths_json, []),
            follow_up_question=row.follow_up_question,
            follow_up_reason=row.follow_up_reason,
            finalized_score=row.finalized_score,
            conversation_history=conversation_history,
            created_at=row.created_at,
        )

    def to_report_read(self, row: EvaluationReportRow) -> EvaluationReportRead:
        return EvaluationReportRead(
            id=row.id,
            evaluation_id=row.evaluation_id,
            session_id=row.session_id,
            final_decision=FinalDecision(row.final_decision),
            authenticity_score=row.authenticity_score,
            summary=row.summary,
            area_analyses=from_json(row.area_analyses_json, []),
            question_evaluations=from_json(row.question_evaluations_json, []),
            bloom_summary=from_json(row.bloom_summary_json, []),
            rubric_summary=from_json(row.rubric_summary_json, []),
            evidence_alignment=from_json(row.evidence_alignment_json, []),
            strengths=from_json(row.strengths_json, []),
            suspicious_points=from_json(row.suspicious_points_json, []),
            recommended_followups=from_json(row.recommended_followups_json, []),
            created_at=row.created_at,
        )
