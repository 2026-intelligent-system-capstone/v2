from __future__ import annotations

from openai import OpenAI
from qdrant_client import QdrantClient
from qdrant_client.models import FieldCondition, Filter, MatchValue


def retrieve_chunks(
    query: str,
    evaluation_id: str,
    openai_client: OpenAI,
    qdrant_client: QdrantClient,
    collection_name: str,
    embedding_model: str = "text-embedding-3-small",
    top_k: int = 5,
) -> list[str]:
    resp = openai_client.embeddings.create(input=[query], model=embedding_model)
    query_vector = resp.data[0].embedding
    results = qdrant_client.search(
        collection_name=collection_name,
        query_vector=query_vector,
        query_filter=Filter(
            must=[
                FieldCondition(key="evaluation_id", match=MatchValue(value=evaluation_id))
            ]
        ),
        limit=top_k,
    )
    return [r.payload["text"] for r in results if r.payload and "text" in r.payload]
