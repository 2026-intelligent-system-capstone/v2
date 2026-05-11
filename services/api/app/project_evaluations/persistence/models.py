from datetime import UTC, datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def utc_now() -> datetime:
    return datetime.now(UTC)


class ProjectEvaluationRow(Base):
    __tablename__ = "project_evaluations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_name: Mapped[str] = mapped_column(String(200), nullable=False)
    candidate_name: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    room_name: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    room_password_hash: Mapped[str] = mapped_column(Text, nullable=False, default="")
    admin_password_hash: Mapped[str] = mapped_column(Text, nullable=False, default="")
    question_policy_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="created")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class ProjectArtifactRow(Base):
    __tablename__ = "project_artifacts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    evaluation_id: Mapped[str] = mapped_column(
        ForeignKey("project_evaluations.id"), index=True, nullable=False
    )
    source_path: Mapped[str] = mapped_column(Text, nullable=False)
    source_type: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    raw_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    char_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    metadata_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )


class ExtractedProjectContextRow(Base):
    __tablename__ = "extracted_project_contexts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    evaluation_id: Mapped[str] = mapped_column(
        ForeignKey("project_evaluations.id"), unique=True, index=True, nullable=False
    )
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    tech_stack_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    features_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    architecture_notes_json: Mapped[str] = mapped_column(
        Text, nullable=False, default="[]"
    )
    data_flow_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    risk_points_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    question_targets_json: Mapped[str] = mapped_column(
        Text, nullable=False, default="[]"
    )
    rag_status_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )


class ProjectAreaRow(Base):
    __tablename__ = "project_areas"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    evaluation_id: Mapped[str] = mapped_column(
        ForeignKey("project_evaluations.id"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    source_refs_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")


class InterviewQuestionRow(Base):
    __tablename__ = "interview_questions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    evaluation_id: Mapped[str] = mapped_column(
        ForeignKey("project_evaluations.id"), index=True, nullable=False
    )
    project_area_id: Mapped[str | None] = mapped_column(
        ForeignKey("project_areas.id"), nullable=True
    )
    question: Mapped[str] = mapped_column(Text, nullable=False)
    intent: Mapped[str] = mapped_column(Text, nullable=False)
    bloom_level: Mapped[str] = mapped_column(String(40), nullable=False)
    difficulty: Mapped[str] = mapped_column(String(40), nullable=False)
    rubric_criteria_json: Mapped[str] = mapped_column(
        Text, nullable=False, default="[]"
    )
    source_refs_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    expected_signal: Mapped[str] = mapped_column(Text, nullable=False, default="")
    verification_focus: Mapped[str] = mapped_column(Text, nullable=False, default="")
    expected_evidence: Mapped[str] = mapped_column(Text, nullable=False, default="")
    source_ref_requirements: Mapped[str] = mapped_column(Text, nullable=False, default="")
    order_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )


class InterviewSessionRow(Base):
    __tablename__ = "interview_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    evaluation_id: Mapped[str] = mapped_column(
        ForeignKey("project_evaluations.id"), index=True, nullable=False
    )
    participant_name: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    session_token_hash: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="created")
    current_question_index: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class InterviewTurnRow(Base):
    __tablename__ = "interview_turns"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("interview_sessions.id"), index=True, nullable=False
    )
    question_id: Mapped[str] = mapped_column(
        ForeignKey("interview_questions.id"), index=True, nullable=False
    )
    question_text: Mapped[str] = mapped_column(Text, nullable=False)
    answer_text: Mapped[str] = mapped_column(Text, nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    evaluation_summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    evidence_matches_json: Mapped[str] = mapped_column(
        Text, nullable=False, default="[]"
    )
    evidence_mismatches_json: Mapped[str] = mapped_column(
        Text, nullable=False, default="[]"
    )
    suspicious_points_json: Mapped[str] = mapped_column(
        Text, nullable=False, default="[]"
    )
    strengths_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    follow_up_question: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )


class RubricScoreRow(Base):
    __tablename__ = "rubric_scores"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    turn_id: Mapped[str] = mapped_column(
        ForeignKey("interview_turns.id"), index=True, nullable=False
    )
    criterion: Mapped[str] = mapped_column(String(80), nullable=False)
    score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rationale: Mapped[str] = mapped_column(Text, nullable=False, default="")


class EvaluationReportRow(Base):
    __tablename__ = "evaluation_reports"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    evaluation_id: Mapped[str] = mapped_column(
        ForeignKey("project_evaluations.id"), index=True, nullable=False
    )
    session_id: Mapped[str] = mapped_column(
        ForeignKey("interview_sessions.id"), index=True, nullable=False
    )
    final_decision: Mapped[str] = mapped_column(String(40), nullable=False)
    authenticity_score: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0
    )
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    area_analyses_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    question_evaluations_json: Mapped[str] = mapped_column(
        Text, nullable=False, default="[]"
    )
    bloom_summary_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    rubric_summary_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    evidence_alignment_json: Mapped[str] = mapped_column(
        Text, nullable=False, default="[]"
    )
    strengths_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    suspicious_points_json: Mapped[str] = mapped_column(
        Text, nullable=False, default="[]"
    )
    recommended_followups_json: Mapped[str] = mapped_column(
        Text, nullable=False, default="[]"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )
