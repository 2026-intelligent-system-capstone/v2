from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING

from openai import OpenAI
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PointStruct,
    VectorParams,
)

from services.api.app.project_evaluations.domain.models import ArtifactRole, ArtifactSourceType
from services.api.app.project_evaluations.rag.redaction import redact_sensitive_text
from services.api.app.project_evaluations.rag.splitters import split_artifact

if TYPE_CHECKING:
    from services.api.app.project_evaluations.persistence.models import ProjectArtifactRow

VECTOR_DIMENSIONS = {
    "text-embedding-3-small": 1536,
    "text-embedding-3-large": 3072,
}
_EMBED_BATCH = 100


@dataclass(frozen=True)
class IngestResult:
    inserted_count: int
    code_chunk_count: int
    document_chunk_count: int
    manifest_chunk_count: int
    skipped_count: int


def ensure_collection(
    client: QdrantClient, collection_name: str, vector_size: int
) -> None:
    existing = {c.name for c in client.get_collections().collections}
    if collection_name not in existing:
        client.create_collection(
            collection_name=collection_name,
            vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE),
        )
        return

    collection = client.get_collection(collection_name)
    vectors = collection.config.params.vectors
    existing_size = vectors.get("").size if isinstance(vectors, dict) else vectors.size
    if existing_size != vector_size:
        raise RuntimeError(
            f"Qdrant collection vector size mismatch: collection={collection_name}, "
            f"existing={existing_size}, expected={vector_size}. "
            "OPENAI_EMBEDDING_MODEL을 바꿨다면 collection을 재생성해야 합니다."
        )


def _is_codebase_role(role: str | None) -> bool:
    return role in {
        ArtifactRole.CODEBASE_SOURCE.value,
        ArtifactRole.CODEBASE_TEST.value,
        ArtifactRole.CODEBASE_CONFIG.value,
        ArtifactRole.CODEBASE_API_SPEC.value,
        ArtifactRole.CODEBASE_OVERVIEW.value,
    }


def _is_project_document_role(role: str | None) -> bool:
    return role in {
        ArtifactRole.PROJECT_REPORT.value,
        ArtifactRole.PROJECT_PRESENTATION.value,
        ArtifactRole.PROJECT_DESIGN_DOC.value,
        ArtifactRole.PROJECT_DESCRIPTION.value,
    }


def _embed_batch(texts: list[str], client: OpenAI, model: str) -> list[list[float]]:
    resp = client.embeddings.create(input=texts, model=model)
    return [item.embedding for item in resp.data]


def ingest_evaluation(
    evaluation_id: str,
    artifacts: list[ProjectArtifactRow],
    openai_client: OpenAI,
    qdrant_client: QdrantClient,
    collection_name: str,
    embedding_model: str = "text-embedding-3-small",
) -> IngestResult:
    vector_size = VECTOR_DIMENSIONS.get(embedding_model)
    if vector_size is None:
        sample = _embed_batch(["dimension probe"], openai_client, embedding_model)
        vector_size = len(sample[0])
    ensure_collection(qdrant_client, collection_name, vector_size)

    chunks = [
        chunk
        for artifact in artifacts
        for chunk in split_artifact(evaluation_id, artifact)
    ]
    skipped_count = sum(1 for artifact in artifacts if not artifact.raw_text.strip())
    if not chunks:
        return IngestResult(
            inserted_count=0,
            code_chunk_count=0,
            document_chunk_count=0,
            manifest_chunk_count=0,
            skipped_count=skipped_count,
        )

    vectors: list[list[float]] = []
    texts = [redact_sensitive_text(chunk.text) for chunk in chunks]
    for i in range(0, len(texts), _EMBED_BATCH):
        batch = texts[i : i + _EMBED_BATCH]
        vectors.extend(_embed_batch(batch, openai_client, embedding_model))

    ingest_version = str(uuid.uuid4())
    points = []
    for i, chunk in enumerate(chunks):
        payload = {**chunk.payload(), "ingest_version": ingest_version}
        payload["text"] = redact_sensitive_text(str(payload["text"]))
        points.append(PointStruct(id=str(uuid.uuid4()), vector=vectors[i], payload=payload))
    qdrant_client.upsert(collection_name=collection_name, points=points)
    inserted = qdrant_client.count(
        collection_name=collection_name,
        count_filter=Filter(
            must=[
                FieldCondition(
                    key="evaluation_id",
                    match=MatchValue(value=evaluation_id),
                ),
                FieldCondition(
                    key="ingest_version",
                    match=MatchValue(value=ingest_version),
                ),
            ]
        ),
        exact=True,
    ).count
    if inserted != len(points):
        raise RuntimeError(
            f"Qdrant ingest verification failed: inserted={inserted}, expected={len(points)}"
        )
    qdrant_client.delete(
        collection_name=collection_name,
        points_selector=Filter(
            must=[
                FieldCondition(
                    key="evaluation_id",
                    match=MatchValue(value=evaluation_id),
                ),
            ],
            must_not=[
                FieldCondition(
                    key="ingest_version",
                    match=MatchValue(value=ingest_version),
                ),
            ],
        ),
    )
    code_chunk_count = sum(
        1
        for chunk in chunks
        if chunk.source_type == ArtifactSourceType.CODE.value
        or _is_codebase_role(chunk.artifact_role)
    )
    if code_chunk_count == 0:
        raise RuntimeError("RAG 인덱싱 결과 코드베이스 근거 chunk가 없습니다. 질문 생성에는 codebase source/config/test/overview 근거가 필요합니다.")
    return IngestResult(
        inserted_count=len(points),
        code_chunk_count=code_chunk_count,
        document_chunk_count=sum(
            1
            for chunk in chunks
            if chunk.source_type == ArtifactSourceType.DOCUMENT.value
            or _is_project_document_role(chunk.artifact_role)
        ),
        manifest_chunk_count=sum(1 for chunk in chunks if chunk.chunk_type == "file_manifest"),
        skipped_count=skipped_count,
    )
