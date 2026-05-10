from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class EvaluationStatus(StrEnum):
    CREATED = "created"
    UPLOADED = "uploaded"
    ANALYZED = "analyzed"
    QUESTIONS_GENERATED = "questions_generated"
    INTERVIEWING = "interviewing"
    REPORTED = "reported"


class ArtifactSourceType(StrEnum):
    ZIP = "zip"
    DOCUMENT = "document"
    CODE = "code"
    TEXT = "text"
    IGNORED = "ignored"


class ArtifactRole(StrEnum):
    CODEBASE_SOURCE = "codebase_source"
    CODEBASE_TEST = "codebase_test"
    CODEBASE_CONFIG = "codebase_config"
    CODEBASE_API_SPEC = "codebase_api_spec"
    CODEBASE_OVERVIEW = "codebase_overview"
    PROJECT_REPORT = "project_report"
    PROJECT_PRESENTATION = "project_presentation"
    PROJECT_DESIGN_DOC = "project_design_doc"
    PROJECT_DESCRIPTION = "project_description"
    IGNORED = "ignored"


class ArtifactStatus(StrEnum):
    EXTRACTED = "extracted"
    SKIPPED = "skipped"
    FAILED = "failed"


class InterviewSessionStatus(StrEnum):
    CREATED = "created"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"


class FinalDecision(StrEnum):
    VERIFIED = "검증 통과"
    NEEDS_FOLLOWUP = "추가 확인 필요"
    LOW_CONFIDENCE = "신뢰 낮음"


class BloomLevel(StrEnum):
    REMEMBER = "기억"
    UNDERSTAND = "이해"
    APPLY = "적용"
    ANALYZE = "분석"
    EVALUATE = "평가"
    CREATE = "창조"


class Difficulty(StrEnum):
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"


class RubricCriterion(StrEnum):
    EVIDENCE_ALIGNMENT = "자료 근거 일치도"
    IMPLEMENTATION_SPECIFICITY = "구현 구체성"
    STRUCTURAL_UNDERSTANDING = "구조 이해도"
    DECISION_UNDERSTANDING = "의사결정 이해도"
    TROUBLESHOOTING_EXPERIENCE = "트러블슈팅 경험"
    LIMITATION_AWARENESS = "한계 인식"
    ANSWER_CONSISTENCY = "답변 일관성"


class SourceReference(BaseModel):
    path: str
    snippet: str = ""
    artifact_id: str | None = None
    page_or_slide: str | None = None


class RubricScoreItem(BaseModel):
    criterion: RubricCriterion
    score: int = Field(ge=0, le=3)
    rationale: str = ""


class ProjectEvaluationCreate(BaseModel):
    project_name: str = Field(min_length=1, max_length=200)
    candidate_name: str = Field(default="", max_length=200)
    description: str = Field(default="", max_length=2000)
    room_name: str = Field(default="", max_length=200)
    room_password: str = Field(default="", max_length=200, repr=False)
    admin_password: str = Field(default="", max_length=200, repr=False)


class ProjectEvaluationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_name: str
    candidate_name: str
    description: str
    room_name: str = ""
    status: EvaluationStatus
    created_at: datetime
    updated_at: datetime


class ProjectArtifactRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    evaluation_id: str
    source_path: str
    source_type: ArtifactSourceType
    status: ArtifactStatus
    char_count: int
    text_preview: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class ArtifactUploadResult(BaseModel):
    evaluation_id: str
    accepted_count: int
    skipped_count: int
    ignored_count: int = 0
    empty_text_count: int = 0
    file_too_large_count: int = 0
    processed_file_limit_count: int = 0
    failed_count: int = 0
    reason_counts: dict[str, int] = Field(default_factory=dict)
    artifacts: list[ProjectArtifactRead]


class ProjectAreaRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    evaluation_id: str
    name: str
    summary: str
    confidence: float
    source_refs: list[SourceReference] = Field(default_factory=list)


class ExtractedProjectContextRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    evaluation_id: str
    summary: str
    tech_stack: list[str] = Field(default_factory=list)
    features: list[str] = Field(default_factory=list)
    architecture_notes: list[str] = Field(default_factory=list)
    data_flow: list[str] = Field(default_factory=list)
    risk_points: list[str] = Field(default_factory=list)
    question_targets: list[str] = Field(default_factory=list)
    areas: list[ProjectAreaRead] = Field(default_factory=list)
    created_at: datetime


class InterviewQuestionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    evaluation_id: str
    project_area_id: str | None
    question: str
    intent: str
    bloom_level: BloomLevel
    difficulty: Difficulty
    rubric_criteria: list[RubricCriterion]
    source_refs: list[SourceReference] = Field(default_factory=list)
    expected_signal: str
    order_index: int
    created_at: datetime


class InterviewSessionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    evaluation_id: str
    participant_name: str = ""
    status: InterviewSessionStatus
    current_question_index: int
    created_at: datetime
    completed_at: datetime | None = None


class AdminVerifyRequest(BaseModel):
    admin_password: str = Field(min_length=1, max_length=200, repr=False)


class AdminVerifyRead(BaseModel):
    ok: bool


class JoinEvaluationRequest(BaseModel):
    participant_name: str = Field(min_length=1, max_length=200)
    room_password: str = Field(min_length=1, max_length=200, repr=False)


class JoinEvaluationRead(BaseModel):
    evaluation: ProjectEvaluationRead
    session: InterviewSessionRead
    interview_url_path: str


class InterviewTurnCreate(BaseModel):
    question_id: str
    answer_text: str = Field(min_length=1, max_length=10000)


class InterviewTurnRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    session_id: str
    question_id: str
    question_text: str
    answer_text: str
    score: float
    evaluation_summary: str
    rubric_scores: list[RubricScoreItem] = Field(default_factory=list)
    evidence_matches: list[str] = Field(default_factory=list)
    evidence_mismatches: list[str] = Field(default_factory=list)
    suspicious_points: list[str] = Field(default_factory=list)
    strengths: list[str] = Field(default_factory=list)
    follow_up_question: str | None = None
    created_at: datetime


class EvaluationReportRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    evaluation_id: str
    session_id: str
    final_decision: FinalDecision
    authenticity_score: float
    summary: str
    area_analyses: list[dict[str, Any]] = Field(default_factory=list)
    question_evaluations: list[dict[str, Any]] = Field(default_factory=list)
    bloom_summary: dict[str, Any] = Field(default_factory=dict)
    rubric_summary: dict[str, Any] = Field(default_factory=dict)
    evidence_alignment: list[str] = Field(default_factory=list)
    strengths: list[str] = Field(default_factory=list)
    suspicious_points: list[str] = Field(default_factory=list)
    recommended_followups: list[str] = Field(default_factory=list)
    created_at: datetime
