"""Production checkpointers share the request's PostgreSQL transaction."""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, cast

from langgraph.checkpoint.postgres import PostgresSaver
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from backend.app.models.entities import Conversation


def thread_id(conversation: Conversation) -> str:
    return f"user:{conversation.user_id}:conversation:{conversation.id}"


@contextmanager
def checkpoint_store(db: Session) -> Iterator[Any]:
    if db.get_bind().dialect.name != "postgresql":
        raise RuntimeError(
            "Persistent chat requires PostgreSQL; use an explicit isolated test saver"
        )
    connection = db.connection().connection.driver_connection
    yield PostgresSaver(cast(Any, connection))


def setup_checkpoints(engine: Engine) -> None:
    if engine.dialect.name != "postgresql":
        return
    # The library owns its checkpoint schema/migrations; setup uses concurrent index DDL.
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        PostgresSaver(cast(Any, connection.connection.driver_connection)).setup()


def clear_checkpoint(db: Session, conversation: Conversation) -> None:
    with checkpoint_store(db) as saver:
        saver.delete_thread(thread_id(conversation))


def prune_checkpoint(db: Session, conversation: Conversation, saver: Any) -> None:
    """Compact a completed scalar-state thread under its owned conversation row lock.

    PostgresSaver.prune(keep_latest) starts REPEATABLE READ and cannot run inside an
    existing ORM transaction. Our per-thread SQL lock supplies exclusion instead.
    No DeltaChannels, graph forks or pending interrupts are used by this workflow.
    """
    thread = thread_id(conversation)
    if db.get_bind().dialect.name != "postgresql":
        saver.prune([thread], strategy="keep_latest")  # explicit test saver only
        return
    params = {"thread": thread}
    db.execute(
        text("""
        DELETE FROM checkpoints c WHERE c.thread_id = :thread AND c.checkpoint_id < (
            SELECT max(latest.checkpoint_id) FROM checkpoints latest
            WHERE latest.thread_id = c.thread_id AND latest.checkpoint_ns = c.checkpoint_ns)
    """),
        params,
    )
    db.execute(text("DELETE FROM checkpoint_writes WHERE thread_id = :thread"), params)
    db.execute(
        text("""
        DELETE FROM checkpoint_blobs b WHERE b.thread_id = :thread AND NOT EXISTS (
            SELECT 1 FROM checkpoints c WHERE c.thread_id = b.thread_id
            AND c.checkpoint_ns = b.checkpoint_ns
            AND c.checkpoint -> 'channel_versions' ->> b.channel = b.version)
    """),
        params,
    )
    db.execute(
        text("UPDATE checkpoints SET parent_checkpoint_id = NULL WHERE thread_id = :thread"), params
    )
