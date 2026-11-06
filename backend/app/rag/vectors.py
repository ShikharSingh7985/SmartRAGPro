from uuid import NAMESPACE_URL, UUID, uuid5

from qdrant_client import models as qm
from sqlalchemy.orm import Session

from backend.app.rag.pdf import Chunk
from backend.app.rag.types import KnowledgeChunk, embedding_fingerprint
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
            metadata={"embedding_fingerprint": embedding_fingerprint(settings)},
        )
        client.create_payload_index(
            settings.qdrant_collection,
            "user_id",
            qm.KeywordIndexParams(type=qm.KeywordIndexType.KEYWORD, is_tenant=True),
        )
        client.create_payload_index(
            settings.qdrant_collection, "run_token", qm.PayloadSchemaType.KEYWORD
        )
        client.create_payload_index(
            settings.qdrant_collection, "document_id", qm.PayloadSchemaType.KEYWORD
        )
    else:
        info = client.get_collection(settings.qdrant_collection)
        vectors = info.config.params.vectors
        if (
            not isinstance(vectors, qm.VectorParams)
            or vectors.size != settings.embedding_dimensions
        ):
            raise ValueError("Vector dimension mismatch; configure a fresh QDRANT_COLLECTION")
        fingerprint = (info.config.metadata or {}).get("embedding_fingerprint")
        if fingerprint and fingerprint != embedding_fingerprint(settings):
            raise ValueError("Embedding space mismatch; configure a fresh QDRANT_COLLECTION")


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


def index_knowledge(
    resources: Resources,
    user_id: UUID,
    document_id: UUID,
    filename: str,
    run_token: str,
    chunks: list[KnowledgeChunk],
    db: Session | None = None,
) -> None:
    from backend.app.models.entities import now

    ensure_collection(resources)
    settings = resources.settings
    fingerprint = embedding_fingerprint(settings)
    for start in range(0, len(chunks), settings.embedding_batch_size):
        batch = chunks[start : start + settings.embedding_batch_size]
        identifiers = [
            str(uuid5(NAMESPACE_URL, f"{document_id}:{fingerprint}:{c.chunk_id}")) for c in batch
        ]
        previous = {
            str(point.id): point.vector
            for point in resources.qdrant.retrieve(
                settings.qdrant_collection, identifiers, with_vectors=True, with_payload=False
            )
        }
        missing = [
            index for index, identifier in enumerate(identifiers) if identifier not in previous
        ]
        embedded = (
            resources.embedding.embed_documents([batch[index].text for index in missing])
            if missing
            else []
        )
        fresh = dict(zip(missing, embedded, strict=True))
        points = []
        for index, chunk in enumerate(batch):
            vector = previous.get(identifiers[index]) or fresh.get(index)
            if not isinstance(vector, list) or len(vector) != settings.embedding_dimensions:
                raise ValueError("Embedding provider returned incompatible dimensions")
            payload = {
                "user_id": str(user_id),
                "document_id": str(document_id),
                "filename": filename,
                "page": chunk.page,
                "page_end": chunk.page_end,
                "text": chunk.text,
                "chunk_id": chunk.chunk_id,
                "parent_id": chunk.parent_id,
                "embedding_fingerprint": fingerprint,
                "embedding_model": (
                    settings.local_embedding_model
                    if settings.embedding_provider == "local"
                    else settings.embedding_model
                ),
                "embedding_version": settings.embedding_version,
                "run_token": run_token,
                "processed_at": now().isoformat(),
                **chunk.metadata,
            }
            points.append(qm.PointStruct(id=identifiers[index], vector=vector, payload=payload))
        resources.qdrant.upsert(settings.qdrant_collection, points=points, wait=True)
        if db is not None:
            from backend.app.rag.lexical import store_chunk

            for point in points:
                store_chunk(db, str(point.id), point.payload or {})
