from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, text

from backend.app.models.entities import Conversation
from backend.app.schemas.api import Question
from backend.app.services.chat import answer
from tests.conftest import authenticate, ingest
from tests.test_workflow import new_conversation


def test_direct_graph_transaction(stack, pdf):
    client, factory, resources = stack
    headers = authenticate(client)
    chat = new_conversation(client, headers, [ingest(stack, pdf, headers)])
    with factory() as db:
        conv = db.get(Conversation, UUID(chat))
        reply = answer(
            db,
            resources,
            conv.id,
            conv.user_id,
            Question(content="What is alpha revenue?", request_id=uuid4()),
        )
        assert reply.position == 2
        if db.get_bind().dialect.name == "postgresql":
            checkpoint = db.scalar(text("SELECT checkpoint_id FROM checkpoints"))
            resources._generator.answer.side_effect = TimeoutError("test-only interrupted call")
            with pytest.raises(TimeoutError):
                answer(
                    db,
                    resources,
                    conv.id,
                    conv.user_id,
                    Question(content="What about alpha revenue?", request_id=uuid4()),
                )
            db.rollback()
            assert db.scalar(text("SELECT checkpoint_id FROM checkpoints")) == checkpoint
            from backend.app.models.entities import Message

            assert db.scalar(select(func.count()).select_from(Message)) == 2
