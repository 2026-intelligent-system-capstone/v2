from __future__ import annotations

from collections.abc import Iterable

from openai import OpenAI
from qdrant_client import QdrantClient
from qdrant_client.models import FieldCondition, Filter, MatchAny, MatchValue

from services.api.app.project_evaluations.rag.chunk_models import RetrievedChunk


def retrieve_chunks(
    query: str,
    evaluation_id: str,
    openai_client: OpenAI,
    qdrant_client: QdrantClient,
    collection_name: str,
    embedding_model: str = "text-embedding-3-small",
    top_k: int = 5,
    artifact_roles: Iterable[str] | None = None,
    chunk_types: Iterable[str] | None = None,
    source_types: Iterable[str] | None = None,
) -> list[RetrievedChunk]:
    resp = openai_client.embeddings.create(input=[query], model=embedding_model)
    query_vector = resp.data[0].embedding
    response = qdrant_client.query_points(
        collection_name=collection_name,
        query=query_vector,
        query_filter=_build_filter(
            evaluation_id=evaluation_id,
            artifact_roles=artifact_roles,
            chunk_types=chunk_types,
            source_types=source_types,
        ),
        limit=top_k,
        with_payload=True,
    )
    return [
        RetrievedChunk.from_payload(point.payload, score=getattr(point, "score", None))
        for point in response.points
        if point.payload and "text" in point.payload
    ]


def retrieve_texts(
    query: str,
    evaluation_id: str,
    openai_client: OpenAI,
    qdrant_client: QdrantClient,
    collection_name: str,
    embedding_model: str = "text-embedding-3-small",
    top_k: int = 5,
) -> list[str]:
    return [
        chunk.text
        for chunk in retrieve_chunks(
            query=query,
            evaluation_id=evaluation_id,
            openai_client=openai_client,
            qdrant_client=qdrant_client,
            collection_name=collection_name,
            embedding_model=embedding_model,
            top_k=top_k,
        )
    ]


def _build_filter(
    evaluation_id: str,
    artifact_roles: Iterable[str] | None,
    chunk_types: Iterable[str] | None,
    source_types: Iterable[str] | None,
) -> Filter:
    must = [FieldCondition(key="evaluation_id", match=MatchValue(value=evaluation_id))]
    must.extend(_match_any("artifact_role", artifact_roles))
    must.extend(_match_any("chunk_type", chunk_types))
    must.extend(_match_any("source_type", source_types))
    return Filter(must=must)


def _match_any(key: str, values: Iterable[str] | None) -> list[FieldCondition]:
    selected = [value for value in values or [] if value]
    if not selected:
        return []
    if len(selected) == 1:
        return [FieldCondition(key=key, match=MatchValue(value=selected[0]))]
    return [FieldCondition(key=key, match=MatchAny(any=selected))]
