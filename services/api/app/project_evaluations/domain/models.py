from collections.abc import Mapping
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


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
    CREATE = "창안"


BLOOM_ORDER = [
    BloomLevel.REMEMBER,
    BloomLevel.UNDERSTAND,
    BloomLevel.APPLY,
    BloomLevel.ANALYZE,
    BloomLevel.EVALUATE,
    BloomLevel.CREATE,
]
DEFAULT_BLOOM_RATIOS = {level.value: 1 for level in BLOOM_ORDER}
DEFAULT_TOTAL_QUESTION_COUNT = len(BLOOM_ORDER)
MAX_BLOOM_RATIO = 10


class QuestionGenerationPolicy(BaseModel):
    total_question_count: int = Field(
        default=DEFAULT_TOTAL_QUESTION_COUNT,
        ge=1,
        le=20,
    )
    bloom_ratios: dict[str, int] = Field(default_factory=lambda: dict(DEFAULT_BLOOM_RATIOS))
    bloom_distribution: dict[str, int] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def normalize_policy(cls, data: object) -> object:
        if data is None:
            data = {}
        if not isinstance(data, dict):
            return data
        normalized = dict(data)
        if "total_questions" in normalized and "total_question_count" not in normalized:
            normalized["total_question_count"] = normalized["total_questions"]
        ratios = _normalize_bloom_ratios(normalized.get("bloom_ratios"))
        normalized["bloom_ratios"] = ratios
        if sum(ratios.values()) == 0:
            raise ValueError("Bloom 비율은 하나 이상 1 이상이어야 합니다.")
        normalized["bloom_distribution"] = distribute_bloom_questions(
            int(normalized.get("total_question_count", DEFAULT_TOTAL_QUESTION_COUNT)),
            ratios,
        )
        return normalized


def normalize_bloom_level(value: object) -> str:
    text = value.value if isinstance(value, BloomLevel) else str(value)
    if text == "창조":
        return BloomLevel.CREATE.value
    if text not in {level.value for level in BLOOM_ORDER}:
        raise ValueError(f"지원하지 않는 Bloom 단계입니다: {text}")
    return text


def _normalize_bloom_ratios(ratios: Mapping[str, int] | None) -> dict[str, int]:
    source = ratios or DEFAULT_BLOOM_RATIOS
    if not isinstance(source, Mapping):
        raise ValueError("Bloom 비율은 단계별 숫자 mapping이어야 합니다.")
    normalized = {level.value: 0 for level in BLOOM_ORDER}
    for key, value in source.items():
        level = normalize_bloom_level(key)
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("Bloom 비율은 0부터 10까지의 정수여야 합니다.")
        if value < 0 or value > MAX_BLOOM_RATIO:
            raise ValueError("Bloom 비율은 0부터 10까지의 정수여야 합니다.")
        normalized[level] = value
    return normalized


def distribute_bloom_questions(
    total_question_count: int,
    bloom_ratios: dict[str, int],
) -> dict[str, int]:
    ratios = _normalize_bloom_ratios(bloom_ratios)
    ratio_sum = sum(ratios.values())
    if ratio_sum == 0:
        raise ValueError("Bloom 비율은 하나 이상 1 이상이어야 합니다.")
    raw_counts = {
        level.value: total_question_count * ratios[level.value] / ratio_sum
        for level in BLOOM_ORDER
    }
    distribution = {level: int(raw_counts[level]) for level in raw_counts}
    remaining = total_question_count - sum(distribution.values())
    remainder_order = sorted(
        raw_counts,
        key=lambda level: (
            -(raw_counts[level] - distribution[level]),
            [item.value for item in BLOOM_ORDER].index(level),
        ),
    )
    for level in remainder_order[:remaining]:
        distribution[level] += 1
    return distribution


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
    line_start: int | None = None
    line_end: int | None = None
    artifact_role: str | None = None
    chunk_type: str | None = None


class RubricScoreItem(BaseModel):
    criterion: RubricCriterion
    score: int = Field(ge=0, le=3)
    rationale: str = ""


class FollowUpExchange(BaseModel):
    question: str
    answer: str
    reason: str = ""


class QuestionExchange(BaseModel):
    student_answer: str
    follow_ups: list[FollowUpExchange] = Field(default_factory=list)


class ProjectEvaluationCreate(BaseModel):
    project_name: str = Field(min_length=1, max_length=200)
    candidate_name: str = Field(default="", max_length=200)
    description: str = Field(default="", max_length=2000)
    room_name: str = Field(default="", max_length=200)
    room_password: str = Field(default="", max_length=200, repr=False)
    admin_password: str = Field(default="", max_length=200, repr=False)
    question_policy: QuestionGenerationPolicy = Field(
        default_factory=QuestionGenerationPolicy
    )


class ProjectEvaluationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_name: str
    candidate_name: str
    description: str
    room_name: str = ""
    status: EvaluationStatus
    question_policy: QuestionGenerationPolicy
    created_at: datetime
    updated_at: datetime


class ProjectEvaluationStatusRead(BaseModel):
    evaluation_id: str
    status: str
    phase: str
    has_artifacts: bool
    has_context: bool
    rag_status: dict[str, Any] = Field(default_factory=dict)
    question_count: int
    expected_question_count: int
    questions_ready: bool
    can_generate_questions: bool
    can_join: bool
    blocked_reason: str = ""
    user_message: str
    check_targets: list[str] = Field(default_factory=list)
    retryable: bool = False


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
    processing_limits: dict[str, int] = Field(default_factory=dict)
    supported_extensions: list[str] = Field(default_factory=list)
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
    rag_status: dict[str, Any] = Field(default_factory=dict)
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
    verification_focus: str = ""
    expected_evidence: str = ""
    source_ref_requirements: str = ""
    order_index: int
    created_at: datetime


class InterviewSessionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    evaluation_id: str
    participant_name: str = ""
    session_token: str = Field(default="", repr=False)
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


class InterviewTurnMode(StrEnum):
    ANSWER = "answer"
    FOLLOW_UP = "follow_up"
    END = "end"


class InterviewTurnFlowStatus(StrEnum):
    NEED_FOLLOW_UP = "need_follow_up"
    TURN_SUBMITTED = "turn_submitted"
    READY_TO_COMPLETE = "ready_to_complete"
    COMPLETED = "completed"


class InterviewTranscriptionRead(BaseModel):
    transcript: str
    mode: InterviewTurnMode


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
    follow_up_reason: str = ""
    finalized_score: float | None = None
    conversation_history: QuestionExchange | None = None
    created_at: datetime


class StudentInterviewStateRead(BaseModel):
    session_id: str
    current_question_index: int
    total_questions: int
    question: InterviewQuestionRead | None = None
    turns: list[InterviewTurnRead] = Field(default_factory=list)
    is_completed: bool = False


class InterviewTurnFlowRequest(BaseModel):
    mode: InterviewTurnMode = InterviewTurnMode.ANSWER
    answer_text: str = Field(default="", max_length=10000)
    draft_answer: str = Field(default="", max_length=20000)
    follow_up_question: str = Field(default="", max_length=2000)
    follow_up_reason: str = Field(default="", max_length=4000)
    current_question_id: str | None = None


class InterviewTurnFlowResponse(BaseModel):
    status: InterviewTurnFlowStatus
    message: str
    draft_answer: str = ""
    follow_up_question: str | None = None
    follow_up_reason: str = ""
    next_mode: InterviewTurnMode | None = None
    turn: InterviewTurnRead | None = None
    next_question: InterviewQuestionRead | None = None
    report: "EvaluationReportRead | None" = None


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
    bloom_summary: list[dict[str, Any]] = Field(default_factory=list)
    rubric_summary: list[dict[str, Any]] = Field(default_factory=list)
    evidence_alignment: list[str] = Field(default_factory=list)
    strengths: list[str] = Field(default_factory=list)
    suspicious_points: list[str] = Field(default_factory=list)
    recommended_followups: list[str] = Field(default_factory=list)
    created_at: datetime
