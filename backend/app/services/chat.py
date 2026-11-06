import re
from uuid import UUID

from fastapi import HTTPException
from qdrant_client import models as qm
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.models.entities import Conversation, ConversationDocument, Document, Message
from backend.app.rag.types import embedding_fingerprint
from backend.app.rag.vectors import tenant_filter
from backend.app.schemas.api import Citation, Question
from backend.app.services.resources import Resources


def owned_conversation(db: Session, conversation_id: UUID, user_id: UUID) -> Conversation:
    conversation = db.scalar(
        select(Conversation)
        .where(Conversation.id == conversation_id, Conversation.user_id == user_id)
        .with_for_update()
    )
    if not conversation:
        raise HTTPException(404, "Conversation not found")
    return conversation


def answer(
    db: Session, resources: Resources, conversation_id: UUID, user_id: UUID, question: Question
) -> Message:
    owned_conversation(db, conversation_id, user_id)
    existing = db.scalar(
        select(Message).where(
            Message.conversation_id == conversation_id,
            Message.request_id == question.request_id,
            Message.role == "assistant",
        )
    )
    if existing:
        return existing
    # Hold ready document locks until messages commit: deletion cannot race publication.
    documents = list(
        db.scalars(
            select(Document)
            .join(ConversationDocument)
            .where(
                ConversationDocument.conversation_id == conversation_id,
                Document.user_id == user_id,
                Document.status == "ready",
            )
            .order_by(Document.id)
            .with_for_update()
        )
    )
    if not documents:
        raise HTTPException(409, "Conversation has no ready documents")
    by_id = {str(document.id): document for document in documents}
    if any(
        doc.index_fingerprint and doc.index_fingerprint != embedding_fingerprint(resources.settings)
        for doc in documents
    ):
        raise HTTPException(
            409, "Selected documents need reindexing for the configured embedding model"
        )
    if any(
        doc.index_collection and doc.index_collection != resources.settings.qdrant_collection
        for doc in documents
    ):
        raise HTTPException(
            409, "Selected documents belong to a different vector index; reindex first"
        )
    scoped_filter = tenant_filter(user_id, [doc.id for doc in documents])
    scoped_filter.should = [
        qm.Filter(
            must=[
                qm.FieldCondition(key="document_id", match=qm.MatchValue(value=str(doc.id))),
                qm.FieldCondition(key="run_token", match=qm.MatchValue(value=doc.active_run)),
            ]
        )
        if doc.active_run
        else qm.FieldCondition(key="document_id", match=qm.MatchValue(value=str(doc.id)))
        for doc in documents
    ]
    points = resources.qdrant.query_points(
        resources.settings.qdrant_collection,
        query=resources.embedding.embed_query(question.content),
        query_filter=scoped_filter,
        limit=6,
        with_payload=True,
        score_threshold=0.25,
    ).points
    citations: list[Citation] = []
    context: list[str] = []
    for point in points:
        payload = point.payload or {}
        document = by_id.get(str(payload.get("document_id")))
        if not document or payload.get("user_id") != str(user_id):
            continue
        citation = Citation(
            source=len(citations) + 1,
            document_id=document.id,
            filename=document.filename,
            page=int(payload["page"]),
            excerpt=str(payload["text"])[:8000],
            page_end=payload.get("page_end"),
            content_type=payload.get("content_type", "text"),
            asset_id=payload.get("asset_id"),
            model_derived=payload.get("model_derived", False),
        )
        citations.append(citation)
        context.append(
            f"[{citation.source}] {citation.filename}, page {citation.page}:\n{citation.excerpt}"
        )
    content = "I don't know based on the selected documents."
    if citations:
        content = resources.generator.answer(question.content, "\n\n".join(context))
        cited = {int(number) for number in re.findall(r"\[(\d+)\]", content)}
        allowed = {citation.source for citation in citations}
        if not cited or not cited.issubset(allowed):
            # Fail closed rather than presenting unsupported or fictitious citation numbers.
            raise HTTPException(502, "Model returned an answer without valid source references")
        citations = [citation for citation in citations if citation.source in cited]
    position = (
        db.scalar(
            select(func.coalesce(func.max(Message.position), 0)).where(
                Message.conversation_id == conversation_id
            )
        )
        or 0
    )
    user_message = Message(
        conversation_id=conversation_id,
        role="user",
        position=position + 1,
        content=question.content,
        request_id=question.request_id,
        citations=[],
    )
    reply = Message(
        conversation_id=conversation_id,
        role="assistant",
        position=position + 2,
        content=content,
        request_id=question.request_id,
        citations=[citation.model_dump(mode="json") for citation in citations],
    )
    db.add_all([user_message, reply])
    db.commit()
    return reply
