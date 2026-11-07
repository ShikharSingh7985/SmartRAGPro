from uuid import UUID

from fastapi import HTTPException
from langsmith import tracing_context
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from backend.app.conversations import checkpoints
from backend.app.conversations.workflow import build_graph, initial_state
from backend.app.core.telemetry import observed
from backend.app.models.entities import Conversation, ConversationDocument, Document, Message
from backend.app.schemas.api import Question
from backend.app.services.resources import Resources


def owned_conversation(
    db: Session, conversation_id: UUID, user_id: UUID, *, lock: bool = False
) -> Conversation:
    query = select(Conversation).where(
        Conversation.id == conversation_id, Conversation.user_id == user_id
    )
    if lock:
        query = query.with_for_update(nowait=True)
    try:
        conversation = db.scalar(query)
    except OperationalError as exc:
        db.rollback()
        if getattr(exc.orig, "sqlstate", None) == "55P03":
            raise HTTPException(
                409, "Conversation is busy; retry with the same request_id"
            ) from exc
        raise
    if not conversation:
        raise HTTPException(404, "Conversation not found")
    return conversation


@observed("chat.end_to_end")
def answer(
    db: Session, resources: Resources, conversation_id: UUID, user_id: UUID, question: Question
) -> Message:
    conversation = owned_conversation(db, conversation_id, user_id, lock=True)
    existing = db.scalar(
        select(Message).where(
            Message.conversation_id == conversation_id,
            Message.request_id == question.request_id,
            Message.role == "assistant",
        )
    )
    if existing:
        original = db.scalar(
            select(Message.content).where(
                Message.conversation_id == conversation_id,
                Message.request_id == question.request_id,
                Message.role == "user",
            )
        )
        if original != question.content:
            raise HTTPException(409, "request_id was already used for a different message")
        return existing
    documents = list(
        db.scalars(
            select(Document)
            .join(ConversationDocument)
            .where(
                ConversationDocument.conversation_id == conversation_id,
                ConversationDocument.active.is_(True),
                Document.user_id == user_id,
                Document.status == "ready",
            )
            .order_by(Document.id)
            .with_for_update(read=True)
        )
    )
    with checkpoints.checkpoint_store(db) as saver:
        graph = build_graph(db, resources, conversation, documents, question, saver)
        with tracing_context(enabled=False):
            result = graph.invoke(
                initial_state(conversation, documents, question, resources),
                {"configurable": {"thread_id": checkpoints.thread_id(conversation)}},
                durability="exit",
            )
        checkpoints.prune_checkpoint(db, conversation, saver)
        db.commit()
        reply = db.get(Message, UUID(result["response_id"]))
        assert reply is not None
        return reply
