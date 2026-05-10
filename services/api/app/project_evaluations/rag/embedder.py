from __future__ import annotations

import uuid
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

if TYPE_CHECKING:
    from services.api.app.project_evaluations.persistence.models import ProjectArtifactRow

VECTOR_DIM = 1536
CHUNK_SIZE = 400
_EMBED_BATCH = 100


def ensure_collection(client: QdrantClient, collection_name: str) -> None:
    existing = {c.name for c in client.get_collections().collections}
    if collection_name not in existing:
        client.create_collection(
            collection_name=collection_name,
            vectors_config=VectorParams(size=VECTOR_DIM, distance=Distance.COSINE),
        )


def _chunk(text: str) -> list[str]:
    chunks = []
    for i in range(0, len(text), CHUNK_SIZE):
        part = text[i : i + CHUNK_SIZE].strip()
        if part:
            chunks.append(part)
    return chunks


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
) -> int:
    ensure_collection(qdrant_client, collection_name)
    try:
        qdrant_client.delete(
            collection_name=collection_name,
            points_selector=Filter(
                must=[
                    FieldCondition(
                        key="evaluation_id",
                        match=MatchValue(value=evaluation_id),
                    )
                ]
            ),
        )
    except Exception:
        pass

    records: list[dict] = []
    for artifact in artifacts:
        if not artifact.raw_text:
            continue
        for chunk_index, chunk in enumerate(_chunk(artifact.raw_text)):
            records.append(
                {
                    "text": chunk,
                    "evaluation_id": evaluation_id,
                    "artifact_id": artifact.id,
                    "source_path": artifact.source_path,
                    "chunk_index": chunk_index,
                }
            )

    if not records:
        return 0

    vectors: list[list[float]] = []
    for i in range(0, len(records), _EMBED_BATCH):
        batch = [r["text"] for r in records[i : i + _EMBED_BATCH]]
        vectors.extend(_embed_batch(batch, openai_client, embedding_model))

    points = [
        PointStruct(id=str(uuid.uuid4()), vector=vectors[i], payload=records[i])
        for i in range(len(records))
    ]
    qdrant_client.upsert(collection_name=collection_name, points=points)
    return len(points)
