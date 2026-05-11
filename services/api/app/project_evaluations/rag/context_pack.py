from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass

from services.api.app.project_evaluations.domain.models import ArtifactRole
from services.api.app.project_evaluations.rag.chunk_models import RetrievedChunk
from services.api.app.project_evaluations.rag.redaction import redact_sensitive_text

Retriever = Callable[..., list[RetrievedChunk]]

CODE_ROLES = [
    ArtifactRole.CODEBASE_SOURCE.value,
    ArtifactRole.CODEBASE_TEST.value,
    ArtifactRole.CODEBASE_CONFIG.value,
    ArtifactRole.CODEBASE_API_SPEC.value,
]
DOCUMENT_ROLES = [
    ArtifactRole.CODEBASE_OVERVIEW.value,
    ArtifactRole.PROJECT_REPORT.value,
    ArtifactRole.PROJECT_PRESENTATION.value,
    ArtifactRole.PROJECT_DESIGN_DOC.value,
    ArtifactRole.PROJECT_DESCRIPTION.value,
]


@dataclass(frozen=True)
class ContextPack:
    snippets: list[str]
    source_refs: list[dict[str, object]]
    chunks: list[RetrievedChunk]

    def empty(self) -> bool:
        return not self.snippets


def build_question_context_pack(
    retriever: Retriever,
    project_summary: str,
    areas: list[dict[str, str]],
    max_chunks: int = 18,
) -> ContextPack:
    queries = _question_queries(project_summary, areas)
    chunks: list[RetrievedChunk] = []
    for query in queries:
        chunks.extend(retriever(query, artifact_roles=CODE_ROLES, top_k=8))
        chunks.extend(retriever(query, artifact_roles=DOCUMENT_ROLES, top_k=3))

    selected = _diverse_chunks(chunks, max_chunks=max_chunks)
    if selected and not any((chunk.artifact_role or "") in CODE_ROLES for chunk in selected):
        raise RuntimeError("질문 생성에 필요한 코드베이스 근거가 없습니다. docs-only RAG 근거로는 질문을 만들 수 없습니다.")
    return ContextPack(
        snippets=_format_snippets(selected),
        source_refs=_source_refs(selected),
        chunks=selected,
    )


def _question_queries(project_summary: str, areas: list[dict[str, str]]) -> list[str]:
    area_text = " ".join(f"{area.get('name', '')} {area.get('summary', '')}" for area in areas[:6])
    summary = project_summary[:800]
    return [
        f"프로젝트 전체 아키텍처 주요 모듈 데이터 흐름 {summary} {area_text}",
        f"zip 업로드 파일 추출 artifact 저장 전처리 흐름 {area_text}",
        f"RAG embedding Qdrant ingest retrieval context 질문 생성 흐름 {area_text}",
        f"프로젝트 문서 보고서 발표자료 설계 문서에 설명된 목표 기능 아키텍처 {summary}",
        f"문서 주장과 코드 구현이 연결되는 지점 불일치 위험 검증 질문 {area_text}",
        f"예외 처리 오류 실패 TODO FIXME 트러블슈팅 한계 개선 {summary}",
    ]


def _diverse_chunks(chunks: list[RetrievedChunk], max_chunks: int) -> list[RetrievedChunk]:
    unique = []
    seen = set()
    for chunk in sorted(chunks, key=_rank_key):
        key = (chunk.source_path, chunk.chunk_type, chunk.text[:120])
        if key in seen or not chunk.text.strip():
            continue
        seen.add(key)
        unique.append(chunk)

    selected: list[RetrievedChunk] = []
    path_counts: Counter[str] = Counter()
    role_counts: Counter[str] = Counter()
    for chunk in unique:
        if path_counts[chunk.source_path] >= 3:
            continue
        role = chunk.artifact_role or "unknown"
        if role_counts[role] >= _role_limit(role, max_chunks):
            continue
        selected.append(chunk)
        path_counts[chunk.source_path] += 1
        role_counts[role] += 1
        if len(selected) >= max_chunks:
            break
    return selected


def _role_limit(role: str, max_chunks: int) -> int:
    if role in CODE_ROLES:
        return max(4, max_chunks)
    if role in DOCUMENT_ROLES:
        return max(2, max_chunks // 3)
    return max(3, max_chunks // 2)


def _rank_key(chunk: RetrievedChunk) -> tuple[int, float, str]:
    type_priority = {
        "file_manifest": 0,
        "code_symbol": 1,
        "project_document_semantic": 2,
        "codebase_overview": 3,
        "structured_config": 4,
    }.get(chunk.chunk_type or "", 5)
    role_priority = 0 if (chunk.artifact_role or "") in CODE_ROLES else 1
    score = chunk.score if chunk.score is not None else 0.0
    return (role_priority, type_priority, -score, chunk.source_path)


def _format_snippets(chunks: list[RetrievedChunk]) -> list[str]:
    snippets = []
    for chunk in chunks:
        role = chunk.artifact_role or "unknown"
        chunk_type = chunk.chunk_type or "unknown"
        label = redact_sensitive_text(chunk.source_label())
        snippets.append(f"[{role} | {chunk_type} | {label}]\n{redact_sensitive_text(chunk.text)[:1200]}")
    return snippets


def _source_refs(chunks: list[RetrievedChunk]) -> list[dict[str, object]]:
    refs = []
    seen = set()
    for chunk in chunks:
        key = (chunk.source_path, chunk.line_start, chunk.page_number, chunk.slide_number, chunk.text[:80])
        if key in seen:
            continue
        seen.add(key)
        refs.append(
            {
                "path": redact_sensitive_text(chunk.source_path),
                "snippet": redact_sensitive_text(" ".join(chunk.text.split()))[:240],
                "artifact_id": chunk.artifact_id,
                "page_or_slide": _page_or_slide(chunk),
                "line_start": chunk.line_start,
                "line_end": chunk.line_end,
                "artifact_role": chunk.artifact_role,
                "chunk_type": chunk.chunk_type,
            }
        )
    return refs


def _page_or_slide(chunk: RetrievedChunk) -> str | None:
    if chunk.page_number:
        return f"page {chunk.page_number}"
    if chunk.slide_number:
        return f"slide {chunk.slide_number}"
    return None
