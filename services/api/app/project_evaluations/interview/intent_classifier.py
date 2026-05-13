from __future__ import annotations

from enum import StrEnum

from services.api.app.project_evaluations.analysis.llm_client import LlmClient


class StudentIntent(StrEnum):
    ANSWER = "answer"
    SKIP = "skip"
    END_EXAM = "end_exam"


def classify_student_intent(text: str, llm: LlmClient) -> StudentIntent:
    if not llm.enabled():
        raise RuntimeError("학생 답변 의도 판별에 사용할 LLM client가 비활성화되어 있습니다.")

    response = llm.chat(
        [
            {
                "role": "user",
                "content": (
                    "프로젝트 수행 진위 검증 인터뷰 중 학생이 다음과 같이 말했습니다:\n"
                    f'"{text}"\n\n'
                    "학생 의도를 아래 셋 중 하나로만 분류하세요.\n"
                    "- answer: 현재 질문에 답변하거나 추가 설명을 하는 경우\n"
                    "- skip: 현재 질문을 건너뛰거나 다음 질문으로 넘어가자고 하는 경우\n"
                    "- end_exam: 인터뷰 전체를 끝내자고 하는 경우\n\n"
                    "반드시 answer, skip, end_exam 중 하나만 출력하세요."
                ),
            }
        ],
        temperature=0.0,
        max_tokens=8,
    )
    normalized = response.strip().lower()
    if not normalized:
        raise RuntimeError(
            f"학생 답변 의도 판별 LLM 응답이 비어 있습니다: {response!r}"
        )
    try:
        return StudentIntent(normalized)
    except ValueError as exc:
        raise RuntimeError(f"학생 답변 의도 판별 결과가 허용 형식이 아닙니다: {response!r}") from exc


def is_decline_response(text: str, llm: LlmClient) -> bool:
    if not llm.enabled():
        raise RuntimeError("추가 답변 완료 의사 판별에 사용할 LLM client가 비활성화되어 있습니다.")

    response = llm.chat(
        [
            {
                "role": "user",
                "content": (
                    "학생에게 '더 하실 말씀이 있으신가요?'라고 물었을 때 "
                    "다음과 같이 답했습니다:\n"
                    f'"{text}"\n\n'
                    "이 답변이 '더 할 말이 없다'는 의미인가요? "
                    "'yes' 또는 'no'로만 답하세요."
                ),
            }
        ],
        temperature=0.0,
        max_tokens=8,
    )
    normalized = response.strip().lower()
    if normalized == "yes":
        return True
    if normalized == "no":
        return False
    raise RuntimeError(f"추가 답변 완료 의사 판별 결과가 yes/no 형식이 아닙니다: {response!r}")
