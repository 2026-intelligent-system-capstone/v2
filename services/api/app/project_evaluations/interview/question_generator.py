import re
from collections import Counter
from collections.abc import Callable

from services.api.app.project_evaluations.analysis.llm_client import LlmClient
from services.api.app.project_evaluations.analysis.prompts import (
    QuestionsSchema,
    build_questions_prompt,
)
from services.api.app.project_evaluations.domain.models import (
    BLOOM_ORDER,
    BloomLevel,
    Difficulty,
    QuestionGenerationPolicy,
    normalize_bloom_level,
)
from services.api.app.project_evaluations.interview.rubric import DEFAULT_RUBRIC
from services.api.app.project_evaluations.persistence.models import (
    ExtractedProjectContextRow,
    ProjectAreaRow,
    ProjectArtifactRow,
)
from services.api.app.project_evaluations.persistence.repository import from_json
from services.api.app.project_evaluations.rag.chunk_models import RetrievedChunk
from services.api.app.project_evaluations.rag.context_pack import build_question_context_pack

BLOOM_SEQUENCE = BLOOM_ORDER
BLOOM_MAP = {level.value: level for level in BLOOM_SEQUENCE} | {"창조": BloomLevel.CREATE}
QUESTION_GENERATION_BASE_TOKENS = 4000
QUESTION_GENERATION_TOKENS_PER_QUESTION = 1500


def generate_questions(
    evaluation_id: str,
    areas: list[ProjectAreaRow],
    context: ExtractedProjectContextRow | None = None,
    artifacts: list[ProjectArtifactRow] | None = None,
    llm: LlmClient | None = None,
    retriever: Callable[..., list[RetrievedChunk]] | None = None,
    require_rag: bool = True,
    question_policy: QuestionGenerationPolicy | None = None,
) -> list[dict[str, object]]:
    policy = question_policy or QuestionGenerationPolicy()
    bloom_sequence = _bloom_sequence(policy)
    if context is None:
        raise RuntimeError("프로젝트 분석 context가 없습니다.")
    if not require_rag:
        raise RuntimeError("질문 생성에는 RAG 근거가 필요합니다. RAG_ENABLED와 Qdrant 설정을 확인하세요.")
    if llm is None or not llm.enabled():
        raise RuntimeError("LLM client is disabled (OPENAI_API_KEY를 확인하세요).")
    return _generate_with_llm(
        evaluation_id, areas, context, artifacts or [], llm, retriever, policy, bloom_sequence
    )


def _generate_with_llm(
    evaluation_id: str,
    areas: list[ProjectAreaRow],
    context: ExtractedProjectContextRow,
    artifacts: list[ProjectArtifactRow],
    llm: LlmClient,
    retriever: Callable[..., list[RetrievedChunk]] | None = None,
    question_policy: QuestionGenerationPolicy | None = None,
    bloom_sequence: list[BloomLevel] | None = None,
) -> list[dict[str, object]]:
    area_dicts = [{"name": a.name, "summary": a.summary} for a in areas]
    if retriever is None:
        raise RuntimeError("질문 생성에 사용할 RAG 검색기가 없습니다. Qdrant와 embedding 설정을 확인하세요.")
    context_pack = build_question_context_pack(
        retriever=retriever,
        project_summary=context.summary,
        areas=area_dicts,
    )
    if context_pack.empty():
        raise RuntimeError("질문 생성에 사용할 RAG 근거가 없습니다. zip 추출, artifact role 분류, Qdrant ingest 상태를 확인하세요.")

    sequence = bloom_sequence or _bloom_sequence(question_policy or QuestionGenerationPolicy())
    messages = build_questions_prompt(
        context.summary,
        area_dicts,
        context_pack.snippets,
        question_policy or QuestionGenerationPolicy(),
        available_source_paths=_available_source_paths(context_pack.source_refs),
        available_source_refs=context_pack.source_refs,
    )
    max_tokens = _question_generation_max_tokens(len(sequence))
    result: QuestionsSchema = llm.parse(messages, QuestionsSchema, max_tokens=max_tokens)
    if len(result.questions) != len(sequence):
        raise RuntimeError(f"LLM이 질문 {len(sequence)}개를 생성하지 못했습니다.")

    parsed_questions = []
    for q in result.questions:
        try:
            bloom = BLOOM_MAP[normalize_bloom_level(q.bloom_level)]
        except (KeyError, ValueError) as exc:
            raise RuntimeError(f"LLM이 지원하지 않는 Bloom 단계를 반환했습니다: {q.bloom_level}") from exc
        parsed_questions.append((q, bloom))

    expected_counts = Counter(level.value for level in sequence)
    actual_counts = Counter(bloom.value for _q, bloom in parsed_questions)
    if actual_counts != expected_counts:
        if sum(actual_counts.values()) == len(sequence):
            # LLM returned correct count but wrong bloom distribution — remap in order
            parsed_questions = [(q, bloom) for (q, _), bloom in zip(parsed_questions, sequence)]
        else:
            raise RuntimeError(
                f"LLM 질문 분포가 요청 정책과 다릅니다. expected={dict(expected_counts)}, actual={dict(actual_counts)}"
            )

    buckets: dict[BloomLevel, list] = {level: [] for level in BLOOM_SEQUENCE}
    for q, bloom in parsed_questions:
        buckets[bloom].append(q)

    ordered_questions = [buckets[level].pop(0) for level in sequence]
    questions = []
    for index, q in enumerate(ordered_questions):
        bloom = sequence[index]
        difficulty = _parse_difficulty(q.difficulty)
        area = areas[index % len(areas)] if areas else None
        preferred_paths = [ref.path for ref in q.source_refs]
        _validate_llm_source_refs(q.question, preferred_paths, context_pack.source_refs)
        source_refs = _question_source_refs(
            context_pack.source_refs,
            text=f"{q.question} {q.intent} {q.verification_focus} {q.expected_signal} {q.expected_evidence}",
            preferred_paths=preferred_paths,
        )
        if not source_refs and area and _is_structural_question(q):
            source_refs = _structural_source_refs(area, context_pack.source_refs)
        source_refs = _ensure_question_source_refs(q.question, source_refs)
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
                "verification_focus": q.verification_focus,
                "expected_evidence": q.expected_evidence,
                "source_ref_requirements": q.source_ref_requirements,
            }
        )
    return questions


def _bloom_sequence(policy: QuestionGenerationPolicy) -> list[BloomLevel]:
    sequence = []
    for level in BLOOM_SEQUENCE:
        sequence.extend([level] * policy.bloom_distribution.get(level.value, 0))
    if not sequence:
        raise RuntimeError("질문 생성 정책에 배정된 Bloom 문항 수가 없습니다.")
    return sequence


def _question_generation_max_tokens(question_count: int) -> int:
    return max(
        QUESTION_GENERATION_BASE_TOKENS,
        question_count * QUESTION_GENERATION_TOKENS_PER_QUESTION,
    )


def _question_source_refs(
    source_refs: list[dict[str, object]],
    text: str,
    preferred_paths: list[str] | None = None,
) -> list[dict[str, object]]:
    if not source_refs:
        return []
    preferred = _refs_by_preferred_paths(source_refs, preferred_paths or [])
    scored = sorted(
        ((ref, _ref_overlap_score(ref, text)) for ref in source_refs),
        key=lambda item: (-item[1], str(item[0].get("path", ""))),
    )
    selected = [*preferred, *[ref for ref, score in scored if score > 0]]
    return _unique_refs(selected)[:3]


def _validate_llm_source_refs(
    question: str,
    preferred_paths: list[str],
    available_refs: list[dict[str, object]],
) -> None:
    if not preferred_paths:
        raise RuntimeError(f"LLM 질문 결과에 source_refs가 없습니다: {question}")
    available_by_path = {
        _clean_source_path(str(ref.get("path", ""))): ref
        for ref in available_refs
        if _clean_source_path(str(ref.get("path", "")))
    }
    unknown_paths = [path for path in preferred_paths if _clean_source_path(path) not in available_by_path]
    if unknown_paths:
        raise RuntimeError(f"LLM이 제공되지 않은 source ref 경로를 반환했습니다: {unknown_paths}")


def _refs_by_preferred_paths(
    source_refs: list[dict[str, object]], preferred_paths: list[str]
) -> list[dict[str, object]]:
    if not preferred_paths:
        return []
    normalized_paths = {_normalize_path(path) for path in preferred_paths}
    return [
        ref
        for ref in source_refs
        if _normalize_path(str(ref.get("path", ""))) in normalized_paths
    ]


def _structural_source_refs(area: ProjectAreaRow, source_refs: list[dict[str, object]]) -> list[dict[str, object]]:
    area_refs = from_json(area.source_refs_json, [])
    code_refs = [
        ref
        for ref in source_refs
        if str(ref.get("artifact_role", "")).startswith("codebase_")
    ]
    document_refs = [
        ref
        for ref in source_refs
        if str(ref.get("artifact_role", "")).startswith("project_")
    ]
    return _unique_refs([*area_refs, *code_refs[:2], *document_refs[:1]])[:3]


def _is_structural_question(question: object) -> bool:
    text = " ".join(
        str(getattr(question, field, ""))
        for field in ("question", "intent", "verification_focus", "expected_signal", "expected_evidence")
    )
    structural_markers = ("구조", "아키텍처", "architecture", "설계", "계층", "모듈", "흐름", "연결", "분리", "책임")
    return any(marker.lower() in text.lower() for marker in structural_markers)


def _ensure_question_source_refs(question: str, source_refs: list[dict[str, object]]) -> list[dict[str, object]]:
    selected = _unique_refs(source_refs)
    if not selected:
        raise RuntimeError(f"질문에 연결할 source refs가 없습니다: {question}")
    return selected


def _unique_refs(source_refs: list[dict[str, object]]) -> list[dict[str, object]]:
    selected = []
    seen = set()
    for ref in source_refs:
        key = str(ref.get("path", "")) + str(ref.get("snippet", ""))
        if not key.strip() or key in seen:
            continue
        seen.add(key)
        selected.append(ref)
    return selected


def _available_source_paths(source_refs: list[dict[str, object]]) -> list[str]:
    paths = []
    seen = set()
    for ref in source_refs:
        path = _normalize_path(str(ref.get("path", "")))
        if path and path not in seen:
            seen.add(path)
            paths.append(path)
    return paths


def _normalize_path(path: str) -> str:
    normalized = _clean_source_path(path)
    normalized = normalized.split(":L", 1)[0]
    normalized = normalized.split(":page", 1)[0]
    normalized = normalized.split(":slide", 1)[0]
    return normalized.strip().strip("[]` ")


def _clean_source_path(path: str) -> str:
    normalized = path.strip().strip("` ")
    if normalized.startswith("[") and "]" in normalized:
        normalized = normalized[1 : normalized.index("]")]
    normalized = normalized.split(" | ")[-1]
    return normalized.strip().strip("[]` ")


def _ref_overlap_score(ref: dict[str, object], text: str) -> int:
    haystack = f"{ref.get('path', '')} {ref.get('snippet', '')} {ref.get('artifact_role', '')} {ref.get('chunk_type', '')}".lower()
    tokens = re.findall(r"[A-Za-z_][A-Za-z0-9_]{3,}|[가-힣]{2,}", text.lower())
    return sum(1 for token in set(tokens) if token in haystack)
def _parse_difficulty(value: str) -> Difficulty:
    try:
        return Difficulty(value.lower())
    except ValueError as exc:
        raise RuntimeError(f"LLM이 지원하지 않는 난이도를 반환했습니다: {value}") from exc
