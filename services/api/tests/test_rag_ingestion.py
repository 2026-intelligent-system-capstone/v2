from __future__ import annotations

from services.api.app.project_evaluations.analysis.context_builder import _representative_snippets
from services.api.app.project_evaluations.domain.models import ArtifactRole, ArtifactSourceType
from services.api.app.project_evaluations.ingestion.file_classifier import classify_artifact
from services.api.app.project_evaluations.persistence.models import ProjectArtifactRow
from services.api.app.project_evaluations.persistence.repository import to_json
from services.api.app.project_evaluations.rag.chunk_models import ChunkType, RetrievedChunk
from services.api.app.project_evaluations.rag.context_pack import build_question_context_pack
from services.api.app.project_evaluations.rag.redaction import redact_sensitive_text
from services.api.app.project_evaluations.rag.splitters import split_artifact


def test_classify_codebase_and_project_documents() -> None:
    assert classify_artifact("src/main.py").artifact_role == ArtifactRole.CODEBASE_SOURCE
    assert classify_artifact("tests/test_main.py").artifact_role == ArtifactRole.CODEBASE_TEST
    assert classify_artifact("pyproject.toml").artifact_role == ArtifactRole.CODEBASE_CONFIG
    assert classify_artifact("openapi.yaml").artifact_role == ArtifactRole.CODEBASE_API_SPEC
    assert classify_artifact("README.md").artifact_role == ArtifactRole.CODEBASE_OVERVIEW
    assert classify_artifact("docs/final-report.pdf").artifact_role == ArtifactRole.PROJECT_REPORT
    assert classify_artifact("slides/demo.pptx").artifact_role == ArtifactRole.PROJECT_PRESENTATION
    assert classify_artifact("docs/design.docx").artifact_role == ArtifactRole.PROJECT_DESIGN_DOC


def test_split_python_artifact_preserves_symbols_and_lines() -> None:
    artifact = _artifact(
        source_path="src/main.py",
        source_type=ArtifactSourceType.CODE.value,
        metadata={"artifact_role": ArtifactRole.CODEBASE_SOURCE.value, "language": "python"},
        raw_text="class Service:\n    pass\n\ndef run():\n    return Service()\n",
    )

    chunks = split_artifact("eval-1", artifact)

    assert [chunk.chunk_type for chunk in chunks].count(ChunkType.FILE_MANIFEST) == 1
    symbols = [chunk.symbol_name for chunk in chunks if chunk.chunk_type == ChunkType.CODE_SYMBOL]
    assert symbols == ["Service", "run"]
    run_chunk = next(chunk for chunk in chunks if chunk.symbol_name == "run")
    assert run_chunk.line_start == 4
    assert run_chunk.line_end == 5


def test_split_project_document_uses_page_markers() -> None:
    artifact = _artifact(
        source_path="docs/report.pdf",
        source_type=ArtifactSourceType.DOCUMENT.value,
        metadata={"artifact_role": ArtifactRole.PROJECT_REPORT.value},
        raw_text="[page 1]\n프로젝트 목표 설명\n\n[page 2]\n시스템 아키텍처 설명",
    )

    chunks = split_artifact("eval-1", artifact)

    assert {chunk.page_number for chunk in chunks} == {1, 2}
    assert all(chunk.chunk_type == ChunkType.PROJECT_DOCUMENT for chunk in chunks)


def test_representative_snippets_use_splitter_chunks_not_file_prefix_only() -> None:
    raw_text = "\n".join(
        ["# 앞부분 설명"]
        + [f"# filler {index}" for index in range(220)]
        + ["def late_pipeline():", "    return 'included'"]
    )
    artifact = _artifact(
        source_path="src/pipeline.py",
        source_type=ArtifactSourceType.CODE.value,
        metadata={"artifact_role": ArtifactRole.CODEBASE_SOURCE.value, "language": "python"},
        raw_text=raw_text,
    )

    snippets = _representative_snippets([artifact])

    assert any("late_pipeline" in snippet for snippet in snippets)


def test_representative_snippets_tolerate_malformed_metadata_json() -> None:
    artifact = _artifact(
        source_path="src/broken_metadata.py",
        source_type=ArtifactSourceType.CODE.value,
        metadata={"artifact_role": ArtifactRole.CODEBASE_SOURCE.value, "language": "python"},
        raw_text="def still_analyzed():\n    return True\n",
    )
    artifact.metadata_json = "{not-json"

    snippets = _representative_snippets([artifact])

    assert any("still_analyzed" in snippet for snippet in snippets)


def test_llm_context_uses_representative_code_source_refs_for_area_evidence() -> None:
    from services.api.app.project_evaluations.analysis.context_builder import _build_with_llm
    from services.api.app.project_evaluations.analysis.prompts import AreaSchema, ProjectContextSchema

    class FakeLlm:
        def parse(self, _messages, _schema, max_tokens):
            return ProjectContextSchema(
                summary="API와 Streamlit 기반 평가 서비스",
                tech_stack=["FastAPI"],
                features=["질문 생성"],
                architecture_notes=["서비스 계층"],
                data_flow=["업로드 후 질문 생성"],
                risk_points=[],
                question_targets=["API(백엔드) 기본 엔드포인트"],
                areas=[
                    AreaSchema(
                        name="API(백엔드) 기본 엔드포인트",
                        summary="health API 영역",
                        confidence=0.8,
                    )
                ],
            )

    artifact = _artifact(
        source_path="services/api/app/main.py",
        source_type=ArtifactSourceType.CODE.value,
        metadata={"artifact_role": ArtifactRole.CODEBASE_SOURCE.value, "language": "python"},
        raw_text="from fastapi import FastAPI\napp = FastAPI()\n",
    )
    document_artifact = _artifact(
        source_path="docs/report.txt",
        source_type=ArtifactSourceType.DOCUMENT.value,
        metadata={"artifact_role": ArtifactRole.PROJECT_DESCRIPTION.value},
        raw_text="문서 설명입니다.",
    )

    context = _build_with_llm([document_artifact, artifact], FakeLlm())

    assert context["areas"][0]["source_refs"][0]["path"] == "services/api/app/main.py"
    assert context["areas"][0]["source_refs"][0]["artifact_role"] == ArtifactRole.CODEBASE_SOURCE.value



def test_representative_snippets_redact_source_path_labels() -> None:
    artifact = _artifact(
        source_path="src/OPENAI_API_KEY=sk-testsecret1234567890.py",
        source_type=ArtifactSourceType.CODE.value,
        metadata={"artifact_role": ArtifactRole.CODEBASE_SOURCE.value, "language": "python"},
        raw_text="def path_is_redacted():\n    return True\n",
    )

    snippets = _representative_snippets([artifact])

    assert "sk-testsecret" not in "\n".join(snippets)
    assert "[REDACTED_SECRET]" in "\n".join(snippets)


def test_redact_sensitive_text_masks_common_secret_shapes() -> None:
    text = "OPENAI_API_KEY=sk-testsecret1234567890 token: abc password=hunter2"

    redacted = redact_sensitive_text(text)

    assert "sk-testsecret" not in redacted
    assert "hunter2" not in redacted
    assert redacted.count("[REDACTED_SECRET]") >= 2


def test_context_pack_prioritizes_code_chunks_before_document_chunks() -> None:
    code_chunk = RetrievedChunk(
        text="FastAPI 라우터에서 zip 업로드 후 extract_context를 호출합니다.",
        source_path="services/api/app/project_evaluations/router.py",
        artifact_id="code-artifact",
        source_type="code",
        artifact_role=ArtifactRole.CODEBASE_SOURCE.value,
        chunk_type=ChunkType.CODE_SYMBOL.value,
        score=0.55,
    )
    document_chunk = RetrievedChunk(
        text="보고서에는 zip 업로드와 RAG 기반 질문 생성 흐름이 설명되어 있습니다.",
        source_path="docs/final-report.pdf",
        artifact_id="doc-artifact",
        source_type="document",
        artifact_role=ArtifactRole.PROJECT_REPORT.value,
        chunk_type=ChunkType.PROJECT_DOCUMENT.value,
        score=0.99,
        page_number=3,
    )

    pack = build_question_context_pack(
        retriever=lambda *_args, **_kwargs: [document_chunk, code_chunk],
        project_summary="zip 업로드와 질문 생성 흐름",
        areas=[{"name": "ingestion", "summary": "zip 처리와 RAG context pack"}],
        max_chunks=2,
    )

    assert [chunk.artifact_id for chunk in pack.chunks] == ["code-artifact", "doc-artifact"]
    assert pack.source_refs[0]["artifact_role"] == ArtifactRole.CODEBASE_SOURCE.value
    assert pack.source_refs[1]["artifact_role"] == ArtifactRole.PROJECT_REPORT.value



def test_context_pack_accepts_overview_only_question_evidence() -> None:
    overview_chunk = RetrievedChunk(
        text="README에는 zip 업로드와 RAG 기반 질문 생성 흐름이 설명되어 있습니다.",
        source_path="README.md",
        artifact_id="overview-artifact",
        source_type="document",
        artifact_role=ArtifactRole.CODEBASE_OVERVIEW.value,
        chunk_type=ChunkType.CODEBASE_OVERVIEW.value,
        score=0.99,
    )

    pack = build_question_context_pack(
        retriever=lambda *_args, **_kwargs: [overview_chunk],
        project_summary="zip 업로드와 질문 생성 흐름",
        areas=[{"name": "ingestion", "summary": "zip 처리와 RAG context pack"}],
        max_chunks=2,
    )

    assert len(pack.chunks) == 1
    assert pack.source_refs[0]["path"] == "README.md"
    assert pack.source_refs[0]["artifact_role"] == ArtifactRole.CODEBASE_OVERVIEW.value



def test_context_pack_accepts_docs_only_question_evidence() -> None:
    document_chunk = RetrievedChunk(
        text="보고서에는 zip 업로드와 RAG 기반 질문 생성 흐름이 설명되어 있습니다.",
        source_path="docs/final-report.pdf",
        artifact_id="doc-artifact",
        source_type="document",
        artifact_role=ArtifactRole.PROJECT_REPORT.value,
        chunk_type=ChunkType.PROJECT_DOCUMENT.value,
        score=0.99,
        page_number=3,
    )

    pack = build_question_context_pack(
        retriever=lambda *_args, **_kwargs: [document_chunk],
        project_summary="zip 업로드와 질문 생성 흐름",
        areas=[{"name": "ingestion", "summary": "zip 처리와 RAG context pack"}],
        max_chunks=2,
    )

    assert len(pack.chunks) == 1
    assert pack.source_refs[0]["path"] == "docs/final-report.pdf"
    assert pack.source_refs[0]["artifact_role"] == ArtifactRole.PROJECT_REPORT.value



def test_context_pack_source_refs_are_redacted() -> None:
    chunk = RetrievedChunk(
        text="설정 파일은 OPENAI_API_KEY=sk-testsecret1234567890 값을 사용합니다.",
        source_path=".env.example",
        artifact_id="artifact-1",
        source_type="code",
        artifact_role=ArtifactRole.CODEBASE_CONFIG.value,
        chunk_type=ChunkType.STRUCTURED_CONFIG.value,
        score=0.9,
    )

    pack = build_question_context_pack(
        retriever=lambda *_args, **_kwargs: [chunk],
        project_summary="환경 설정",
        areas=[{"name": "config", "summary": "환경 설정"}],
    )

    assert "sk-testsecret" not in "\n".join(pack.snippets)
    assert "sk-testsecret" not in str(pack.source_refs)
    assert "[REDACTED_SECRET]" in str(pack.source_refs)


def _artifact(
    source_path: str,
    source_type: str,
    metadata: dict[str, object],
    raw_text: str,
) -> ProjectArtifactRow:
    return ProjectArtifactRow(
        id="artifact-1",
        evaluation_id="eval-1",
        source_path=source_path,
        source_type=source_type,
        status="extracted",
        raw_text=raw_text,
        char_count=len(raw_text),
        metadata_json=to_json(metadata),
    )
