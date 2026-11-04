from uuid import NAMESPACE_URL, UUID, uuid5

from qdrant_client import models as qm

from backend.app.rag.pdf import Chunk
from backend.app.services.resources import Resources


def tenant_filter(user_id: UUID, document_ids: list[UUID]) -> qm.Filter:
    return qm.Filter(
        must=[
            qm.FieldCondition(key="user_id", match=qm.MatchValue(value=str(user_id))),
            qm.FieldCondition(
                key="document_id", match=qm.MatchAny(any=[str(x) for x in document_ids])
            ),
        ]
    )


def ensure_collection(resources: Resources) -> None:
    settings = resources.settings
    client = resources.qdrant
    if not client.collection_exists(settings.qdrant_collection):
        client.create_collection(
            settings.qdrant_collection,
            vectors_config=qm.VectorParams(
                size=settings.embedding_dimensions, distance=qm.Distance.COSINE
            ),
        )
        client.create_payload_index(
            settings.qdrant_collection,
            "user_id",
            qm.KeywordIndexParams(type=qm.KeywordIndexType.KEYWORD, is_tenant=True),
        )
        client.create_payload_index(
            settings.qdrant_collection, "document_id", qm.PayloadSchemaType.KEYWORD
        )


def index_chunks(
    resources: Resources, user_id: UUID, document_id: UUID, chunks: list[Chunk]
) -> None:
    ensure_collection(resources)
    # Deterministic IDs make retries replace points instead of duplicating evidence.
    for start in range(0, len(chunks), 32):
        batch = chunks[start : start + 32]
        vectors = resources.embedding.embed_documents([chunk.text for chunk in batch])
        points = [
            qm.PointStruct(
                id=str(uuid5(NAMESPACE_URL, f"{document_id}:{start + offset}")),
                vector=vector,
                payload={
                    "user_id": str(user_id),
                    "document_id": str(document_id),
                    "page": chunk.page,
                    "text": chunk.text,
                },
            )
            for offset, (chunk, vector) in enumerate(zip(batch, vectors, strict=True))
        ]
        resources.qdrant.upsert(resources.settings.qdrant_collection, points=points, wait=True)


def delete_vectors(resources: Resources, user_id: UUID, document_id: UUID) -> None:
    if resources.qdrant.collection_exists(resources.settings.qdrant_collection):
        resources.qdrant.delete(
            resources.settings.qdrant_collection,
            points_selector=qm.FilterSelector(filter=tenant_filter(user_id, [document_id])),
            wait=True,
        )
