from pydantic import BaseModel, Field


# ── structured output schemas ──────────────────────────────────────────────


class AreaSchema(BaseModel):
    name: str = Field(description="영역 이름 (예: 백엔드 API, RAG 파이프라인)")
    summary: str = Field(description="이 영역의 역할과 핵심 구현 내용 요약 (2~3문장)")
    confidence: float = Field(
        ge=0.0, le=1.0, description="자료 기반 분석 신뢰도 (0~1)"
    )


class ProjectContextSchema(BaseModel):
    summary: str = Field(description="프로젝트 전체 목적과 핵심 기능 요약 (3~5문장)")
    tech_stack: list[str] = Field(description="사용된 기술/프레임워크 목록")
    features: list[str] = Field(description="주요 기능 목록 (각 1문장)")
    architecture_notes: list[str] = Field(
        description="아키텍처 구조, 계층 분리, 주요 디렉터리 역할 노트 목록"
    )
    data_flow: list[str] = Field(
        description="데이터 흐름 단계 목록 (예: 업로드→추출→임베딩→검색)"
    )
    risk_points: list[str] = Field(
        description="구현 리스크 또는 수행 진위 의심 지점 목록"
    )
    question_targets: list[str] = Field(description="질문 대상 영역 이름 목록")
    areas: list[AreaSchema] = Field(
        description="프로젝트 주요 영역별 분석 (3~6개)", min_length=1
    )


class QuestionSchema(BaseModel):
    question: str = Field(description="자료 기반 프로젝트 수행 진위 검증 질문 (1문장)")
    intent: str = Field(description="이 질문의 검증 의도 (1문장)")
    bloom_level: str = Field(description="Bloom 단계: 기억|이해|적용|분석|평가|창조")
    expected_signal: str = Field(
        description="실제 수행자라면 설명할 흐름, 구조, 근거, 경험, 판단 기준 (1~2문장)"
    )
    difficulty: str = Field(description="난이도: easy|medium|hard")


class QuestionsSchema(BaseModel):
    questions: list[QuestionSchema] = Field(
        description="생성된 질문 목록 (5개)", min_length=5, max_length=5
    )


class RubricScoreSchema(BaseModel):
    criterion: str
    score: int = Field(ge=0, le=3, description="루브릭 점수 (0~3)")
    rationale: str = Field(description="점수 근거 (1문장)")


class AnswerEvalSchema(BaseModel):
    score: float = Field(ge=0.0, le=100.0, description="0~100 점수")
    evaluation_summary: str = Field(description="종합 평가 요약 (1~2문장)")
    rubric_scores: list[RubricScoreSchema]
    evidence_matches: list[str] = Field(description="자료와 일치하는 근거 목록")
    evidence_mismatches: list[str] = Field(description="자료와 불일치하거나 모호한 지점 목록")
    suspicious_points: list[str] = Field(description="수행 진위 의심 지점 목록")
    strengths: list[str] = Field(description="답변의 강점 목록")
    follow_up_question: str | None = Field(
        default=None, description="추가 확인이 필요하면 꼬리질문, 불필요하면 null"
    )


# ── prompt builders ────────────────────────────────────────────────────────

CONTEXT_SYSTEM = """당신은 교수의 프로젝트 과제 수행 진위 검증을 돕는 전문 분석가입니다.
학생이 제출한 자료(코드, 문서, README 등)를 읽고 프로젝트 구조와 핵심 포인트를 JSON으로 구조화하세요.
- 자료에 명시되지 않은 내용을 추측하지 마세요.
- tech_stack, features, areas는 자료에서 실제로 확인된 내용만 포함하세요.
- risk_points에는 구현 의심 지점이나 자료 불일치를 포함하세요."""


def build_context_prompt(artifact_snippets: list[str]) -> list[dict[str, str]]:
    joined = "\n\n---\n\n".join(artifact_snippets[:20])
    return [
        {"role": "system", "content": CONTEXT_SYSTEM},
        {
            "role": "user",
            "content": f"다음은 학생이 제출한 프로젝트 자료입니다. 분석해주세요.\n\n{joined}",
        },
    ]


QUESTION_SYSTEM = """당신은 교수의 프로젝트 과제 평가를 위한 인터뷰 질문을 설계하는 전문가입니다.
목표: 학생/프로젝트 수행자가 제출한 프로젝트를 실제로 수행했고 전체 구조를 이해하는지 검증합니다.
- 질문은 자료에 명시된 source ref(파일명, 모듈, 설계 결정, 기술 선택)를 근거로 삼으세요.
- source ref는 암기 대상이 아니라 전체 동작 흐름, 구조, 설계 의도, 구현 선택, 문제 해결 경험, 한계 인식을 설명하게 하는 근거입니다.
- 회사, 직무, 입사, 지원 동기, 커리어 적합성, 조직 문화 적합성 질문은 절대 만들지 마세요.
- 특정 함수의 정확한 인자, 반환값, 라인, 분기 조건을 외워야 답할 수 있는 코드 암기형 질문은 만들지 마세요.
- 제출 자료와 무관한 일반 CS/기술 면접 질문은 피하고, 이 프로젝트에만 해당하는 질문을 만드세요.
- 5개 질문을 Bloom 단계 이해→적용→분석→평가→창조 순서로 각 1개씩 만드세요."""


def build_questions_prompt(
    project_summary: str,
    areas: list[dict],
    artifact_snippets: list[str],
) -> list[dict[str, str]]:
    area_text = "\n".join(
        f"- {a.get('name', '')}: {a.get('summary', '')}" for a in areas[:6]
    )
    snippet_text = "\n\n---\n\n".join(artifact_snippets[:8])
    return [
        {"role": "system", "content": QUESTION_SYSTEM},
        {
            "role": "user",
            "content": (
                f"## 프로젝트 요약\n{project_summary}\n\n"
                f"## 프로젝트 영역\n{area_text}\n\n"
                f"## 자료 발췌\n{snippet_text}\n\n"
                "위 자료를 기반으로 수행 진위 검증 질문 5개를 생성하세요."
            ),
        },
    ]


EVAL_SYSTEM = """당신은 교수의 프로젝트 과제 수행 진위 검증 답변을 평가하는 전문 평가자입니다.
목표: 학생/프로젝트 수행자의 답변이 실제 프로젝트 자료와 얼마나 일치하는지, 전체 흐름·구조·설계 의도·구현 경험·한계 인식을 설명하는지 평가합니다.
세부 코드 암기 여부가 아니라 자료 근거에 맞는 프로젝트 이해와 수행 경험을 평가하세요.
루브릭 점수 기준: 0=전혀 없음, 1=미흡, 2=보통, 3=우수"""

RUBRIC_CRITERIA = [
    "자료 근거 일치도",
    "구현 구체성",
    "구조 이해도",
    "의사결정 이해도",
    "트러블슈팅 경험",
    "한계 인식",
    "답변 일관성",
]


def build_eval_prompt(
    question: str,
    intent: str,
    expected_signal: str,
    answer_text: str,
    source_snippets: list[str],
) -> list[dict[str, str]]:
    snippets = "\n\n---\n\n".join(source_snippets[:5])
    rubric_text = "\n".join(f"- {c}" for c in RUBRIC_CRITERIA)
    return [
        {"role": "system", "content": EVAL_SYSTEM},
        {
            "role": "user",
            "content": (
                f"## 질문\n{question}\n\n"
                f"## 질문 의도\n{intent}\n\n"
                f"## 기대 신호\n{expected_signal}\n\n"
                f"## 학생/프로젝트 수행자 답변\n{answer_text}\n\n"
                f"## 자료 발췌 (근거 비교용)\n{snippets}\n\n"
                f"## 평가 루브릭\n{rubric_text}\n\n"
                "위 내용을 기반으로 답변을 평가하세요."
            ),
        },
    ]
