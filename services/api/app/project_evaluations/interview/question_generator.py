import re
from collections.abc import Callable

from services.api.app.project_evaluations.analysis.llm_client import LlmClient
from services.api.app.project_evaluations.analysis.prompts import (
    QuestionsSchema,
    build_questions_prompt,
)
from services.api.app.project_evaluations.domain.models import BloomLevel, Difficulty
from services.api.app.project_evaluations.interview.rubric import DEFAULT_RUBRIC
from services.api.app.project_evaluations.persistence.models import (
    ExtractedProjectContextRow,
    ProjectAreaRow,
    ProjectArtifactRow,
)
from services.api.app.project_evaluations.persistence.repository import from_json

ROOT_DOC_NAMES = {"claude.md", "readme.md", "pyproject.toml"}

BLOOM_SEQUENCE = [
    BloomLevel.UNDERSTAND,
    BloomLevel.APPLY,
    BloomLevel.ANALYZE,
    BloomLevel.EVALUATE,
    BloomLevel.CREATE,
]
QUESTION_FOCUS = [
    "전체 동작 흐름과 각 단계가 이어지는 방식을 설명해주세요",
    "설계 의사결정과 그 이유를 설명해주세요",
    "주요 모듈/컴포넌트의 책임과 서로 연결되는 방식을 설명해주세요",
    "구현 중 문제가 생겼던 지점이나 디버깅 경험을 설명해주세요",
    "지금 다시 개선한다면 무엇을 먼저 바꾸고 어떤 위험을 확인할지 설명해주세요",
]
INTENTS = [
    "전체 흐름과 구현 경로 검증",
    "설계 의사결정 검증",
    "구조와 동작 이해도 검증",
    "트러블슈팅 경험 검증",
    "한계 인식과 개선 판단 검증",
]
EXPECTED_SIGNALS = [
    "자료의 실제 파일명, 모듈 책임, 데이터 흐름을 연결해서 답변해야 합니다.",
    "대안과 trade-off를 포함해 본인이 결정한 이유를 말해야 합니다.",
    "핵심은 구조, 역할 분담, 연결 방식이며 함수·클래스·설정명은 필요한 경우 예시로만 언급하면 됩니다.",
    "실제 오류, 원인 파악, 수정 과정을 시간 순서로 설명해야 합니다.",
    "현재 구현의 한계와 우선순위 판단이 자료와 일치해야 합니다.",
]
BLOOM_MAP = {
    "기억": BloomLevel.REMEMBER,
    "이해": BloomLevel.UNDERSTAND,
    "적용": BloomLevel.APPLY,
    "분석": BloomLevel.ANALYZE,
    "평가": BloomLevel.EVALUATE,
    "창조": BloomLevel.CREATE,
}


def generate_questions(
    evaluation_id: str,
    areas: list[ProjectAreaRow],
    context: ExtractedProjectContextRow | None = None,
    artifacts: list[ProjectArtifactRow] | None = None,
    llm: LlmClient | None = None,
    retriever: Callable[[str], list[str]] | None = None,
) -> list[dict[str, object]]:
    if context is None:
        raise RuntimeError("프로젝트 분석 context가 없습니다.")
    if llm is None or not llm.enabled():
        raise RuntimeError("LLM client is disabled (OPENAI_API_KEY를 확인하세요).")
    return _generate_with_llm(
        evaluation_id, areas, context, artifacts or [], llm, retriever
    )


def _generate_with_llm(
    evaluation_id: str,
    areas: list[ProjectAreaRow],
    context: ExtractedProjectContextRow,
    artifacts: list[ProjectArtifactRow],
    llm: LlmClient,
    retriever: Callable[[str], list[str]] | None = None,
) -> list[dict[str, object]]:
    area_dicts = [{"name": a.name, "summary": a.summary} for a in areas]
    artifact_snippets = [
        f"[{a.source_path}]\n{a.raw_text[:800]}" for a in artifacts if a.raw_text.strip()
    ][:10]
    if not artifact_snippets:
        raise RuntimeError("질문 생성에 사용할 업로드 자료 발췌가 없습니다.")

    snippets = list(artifact_snippets)
    if retriever is not None:
        query = " ".join(a.name for a in areas[:5]) + " " + context.summary[:200]
        snippets.extend(f"[RAG]\n{chunk}" for chunk in retriever(query))

    messages = build_questions_prompt(context.summary, area_dicts, snippets)
    result: QuestionsSchema = llm.parse(messages, QuestionsSchema, max_tokens=3000)
    if len(result.questions) != 5:
        raise RuntimeError("LLM이 질문 5개를 생성하지 못했습니다.")

    questions = []
    for index, q in enumerate(result.questions):
        bloom = BLOOM_MAP.get(q.bloom_level, BLOOM_SEQUENCE[index % len(BLOOM_SEQUENCE)])
        difficulty = _parse_difficulty(q.difficulty)
        area = areas[index % len(areas)] if areas else None
        source_refs = from_json(area.source_refs_json, []) if area else []
        questions.append(
            {
                "evaluation_id": evaluation_id,
                "project_area_id": area.id if area else None,
                "question": q.question,
                "intent": q.intent,
                "bloom_level": bloom.value,
                "difficulty": difficulty.value,
                "rubric_criteria": [c.value for c in DEFAULT_RUBRIC],
                "source_refs": source_refs,
                "expected_signal": q.expected_signal,
            }
        )
    return questions


def _generate_rule_based(
    evaluation_id: str, areas: list[ProjectAreaRow]
) -> list[dict[str, object]]:
    selected = areas or []
    questions = []
    for index, bloom_level in enumerate(BLOOM_SEQUENCE):
        area = selected[index % len(selected)] if selected else None
        source_refs = from_json(area.source_refs_json, []) if area else []
        paths = _source_paths(source_refs)
        question = _fallback_question(index, area.name if area else "프로젝트 전체", source_refs)
        questions.append(
            {
                "evaluation_id": evaluation_id,
                "project_area_id": area.id if area else None,
                "question": question,
                "intent": INTENTS[index],
                "bloom_level": bloom_level.value,
                "difficulty": Difficulty.MEDIUM.value,
                "rubric_criteria": [c.value for c in DEFAULT_RUBRIC],
                "source_refs": source_refs,
                "expected_signal": (
                    "자료 발췌 기반 fallback 질문입니다. "
                    f"답변에는 {', '.join(paths) if paths else '제출 자료'}를 근거로 한 전체 흐름, 구조, 경험, 판단이 포함되어야 합니다. "
                    f"{EXPECTED_SIGNALS[index]}"
                ),
            }
        )
    return questions


def _fallback_question(index: int, area_name: str, source_refs: list[dict]) -> str:
    paths = _source_paths(source_refs)
    keyword_text = _keywords_from_refs(source_refs)
    if paths:
        path_text = "와 ".join(paths[:2]) if len(paths) <= 2 else f"{paths[0]}, {paths[1]} 등"
        keyword_clause = f" 특히 `{keyword_text}` 단서를 포함해" if keyword_text else ""
        return f"{path_text}를 근거로,{keyword_clause} {QUESTION_FOCUS[index]}"
    keyword_clause = f" `{keyword_text}` 단서를 근거로" if keyword_text else ""
    return f"{area_name} 자료에서 확인되는{keyword_clause} 프로젝트 구현 맥락을 바탕으로 {QUESTION_FOCUS[index]}"


def _source_paths(source_refs: list[dict]) -> list[str]:
    paths = []
    for ref in source_refs:
        path = str(ref.get("path", "")).strip()
        if path and path not in paths:
            paths.append(path)
    code_paths = [path for path in paths if "/" in path or path.lower() not in ROOT_DOC_NAMES]
    return (code_paths or paths)[:3]


def _keywords_from_refs(source_refs: list[dict]) -> str:
    text = " ".join(str(ref.get("snippet", "")) for ref in source_refs)
    words = re.findall(r"[A-Za-z_][A-Za-z0-9_]{3,}|[가-힣]{3,}", text)
    ignored = {"from", "import", "class", "return", "self", "def", "프로젝트", "기반"}
    keywords = []
    for word in words:
        if word.lower() in ignored or word in keywords:
            continue
        keywords.append(word)
        if len(keywords) == 3:
            break
    return ", ".join(keywords)


def _parse_difficulty(value: str) -> Difficulty:
    try:
        return Difficulty(value.lower())
    except ValueError:
        return Difficulty.MEDIUM
