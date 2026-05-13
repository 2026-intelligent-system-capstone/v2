from __future__ import annotations

import json
import logging
import re
from enum import StrEnum

from services.api.app.project_evaluations.analysis.llm_client import LlmClient

logger = logging.getLogger(__name__)


class StudentIntent(StrEnum):
    ANSWER = "answer"
    SKIP = "skip"
    END_EXAM = "end_exam"


_INTENT_KEYWORDS: tuple[tuple[str, StudentIntent], ...] = (
    ("end_exam", StudentIntent.END_EXAM),
    ("end-exam", StudentIntent.END_EXAM),
    ("endexam", StudentIntent.END_EXAM),
    ("skip", StudentIntent.SKIP),
    ("answer", StudentIntent.ANSWER),
)


def _parse_intent(response: str) -> StudentIntent | None:
    normalized = response.strip().lower()
    if not normalized:
        return None
    try:
        return StudentIntent(normalized)
    except ValueError:
        pass
    try:
        payload = json.loads(normalized)
        if isinstance(payload, dict):
            value = payload.get("intent")
            if isinstance(value, str):
                try:
                    return StudentIntent(value.strip().lower())
                except ValueError:
                    pass
    except (ValueError, TypeError):
        pass
    match = re.search(r"\"intent\"\s*:\s*\"([a-z_\-]+)\"", normalized)
    if match:
        try:
            return StudentIntent(match.group(1).replace("-", "_"))
        except ValueError:
            pass
    for keyword, intent in _INTENT_KEYWORDS:
        if keyword in normalized:
            return intent
    return None


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
                    "- answer: 현재 질문에 답변하거나 추가 설명을 하는 경우. "
                    "여기에는 '모른다', '잘 모르겠다', '기억이 안 난다', '생각 안 난다' 같은 "
                    "지식 부족/회상 실패 답변도 포함됩니다. 이런 표현은 의미 있는 답변이므로 반드시 answer입니다.\n"
                    "- skip: 현재 질문을 명시적으로 건너뛰자고 하거나 \"다음 문제로 넘어가자\" 같이 말한 경우\n"
                    "- end_exam: 인터뷰 전체를 끝내자고 하는 경우\n\n"
                    "출력 형식: 다음 JSON 한 줄만 출력하세요. 다른 텍스트 금지.\n"
                    '{"intent":"answer"} 또는 {"intent":"skip"} 또는 {"intent":"end_exam"}'
                ),
            }
        ],
        temperature=0.0,
        max_tokens=32,
    )
    parsed = _parse_intent(response)
    if parsed is not None:
        return parsed
    logger.warning(
        "intent parse failed: response=%r — falling back to ANSWER (answer text preserved)",
        response,
    )
    return StudentIntent.ANSWER
