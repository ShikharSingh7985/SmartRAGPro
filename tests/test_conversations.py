"""Real extraction/vector retrieval, deterministic model outputs only inside tests."""

import json
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text

from backend.app.conversations import checkpoints
from backend.app.conversations.memory import reconstruct, resolve, token_count
from backend.app.main import app
from backend.app.models.entities import Conversation, ConversationSummary, Message
from scripts.textbook_fixture import textbook_pdf
from tests.conftest import authenticate, ingest
from tests.test_workflow import new_conversation


def ask(client, headers, chat, content, request_id=None):
    return client.post(
        f"/api/v1/conversations/{chat}/messages",
        headers=headers,
        json={"content": content, "request_id": request_id or str(uuid4())},
    )


@pytest.mark.parametrize(
    "question",
    [
        "what this pdf is about",
        "What is this document about?",
        "Summarize this PDF",
        "Give me an overview of the uploaded book",
        "i ajkm asking about this pdf\\",
        "What about this PDF?",
        "Tell me about this document",
        "Explain this file",
    ],
)
def test_explicit_document_references_are_not_unresolved_pronouns(question):
    from backend.app.conversations.memory import document_overview

    result = resolve(question, "", {}, [], [])
    assert result["clarification"] == ""
    assert not result["is_followup"]
    assert document_overview(question)


def test_document_reference_keeps_a_specific_topic_query_specific():
    from backend.app.conversations.memory import document_overview

    query = "What does this PDF say about regularization?"
    assert not document_overview(query)
    assert not document_overview("Summarize this PDF's chapter 5")
    result = resolve(query, "", {}, [], [])
    assert not result["clarification"]
    assert "regularization" in result["rewritten_question"]


def test_overview_uses_real_scoped_evidence_after_a_clarification(stack, pdf, monkeypatch):
    client, _, resources = stack
    headers = authenticate(client)
    chosen = ingest(stack, textbook_pdf(), headers)
    unselected = ingest(stack, pdf, headers)
    other = authenticate(client, "bob@example.com")
    ingest(stack, pdf, other)
    chat = new_conversation(client, headers, [chosen])
    unclear = ask(client, headers, chat, "Explain it")
    assert unclear.status_code == 201 and not unclear.json()["citations"]

    def no_generic_embedding(_query):
        raise AssertionError("A source overview must not depend on generic-query vector similarity")

    monkeypatch.setattr(resources.embedding, "embed_query", no_generic_embedding)

    def summarize(prompt, context):
        assert "sampled source excerpts" in prompt
        assert "Overfitting" in context
        assert "Alpha revenue" not in context
        return "The document discusses overfitting in machine learning. [1]"

    resources._generator.answer.side_effect = summarize
    response = ask(client, headers, chat, "what this pdf is about")
    assert response.status_code == 201, response.text
    assert response.json()["citations"]
    assert {c["document_id"] for c in response.json()["citations"]} == {chosen}
    assert response.json()["citations"][0]["page"] == 1
    assert "earlier statement" not in response.json()["content"]
    both = new_conversation(client, headers, [chosen, unselected])
    ambiguous = ask(client, headers, both, "What is this PDF about?")
    assert ambiguous.status_code == 201
    assert "Which selected document" in ambiguous.json()["content"]
    assert not ambiguous.json()["citations"]
    assert resources._generator.answer.call_count == 1


@pytest.mark.parametrize("references, status", [("[1, 2]", 201), ("[1, 999]", 502)])
def test_grouped_citations_validate_every_source_before_persisting(stack, pdf, references, status):
    client, factory, resources = stack
    headers = authenticate(client)
    doc = ingest(stack, pdf, headers)
    chat = new_conversation(client, headers, [doc])
    resources._generator.answer.return_value = "Source evidence. " + references
    response = ask(client, headers, chat, "What is Alpha revenue and leave policy?")
    assert response.status_code == status
    if status == 201:
        assert {citation["page"] for citation in response.json()["citations"]} == {1, 2}
        assert response.json()["content"].endswith("[1][2]")
    else:
        assert client.get(f"/api/v1/conversations/{chat}/messages", headers=headers).json() == []


def test_ordinal_memory_drops_grouped_source_markers():
    from backend.app.conversations.memory import answer_methods

    methods = answer_methods("1. Validation [1]\n2. Early stopping [2, 3]")
    assert methods == ["Validation", "Early stopping"]
    resolved = resolve("Explain the second method", "overfitting", {"methods": methods}, [], [])
    assert "Early stopping" in resolved["rewritten_question"]
    assert "[2" not in resolved["rewritten_question"]


def test_latest_prose_reorders_known_methods_without_inventing_entities():
    from backend.app.conversations.memory import answer_methods

    previous = ["Cross-validation", "Regularization", "Early stopping"]
    assert answer_methods("Early stopping and regularization are discussed [1].", previous) == [
        "Early stopping",
        "Regularization",
    ]
    assert answer_methods("Unrecognized options need clarification.", previous) == []


def test_live_parenthetical_descriptions_do_not_hide_method_labels():
    from backend.app.conversations.memory import answer_methods

    previous = [
        "Cross-validation (estimates generalization using held-out folds)",
        "Regularization (reduces overfitting by penalizing large weights)",
        "Early stopping (ends training when validation loss rises)",
    ]
    assert answer_methods(
        "Chapter 5 explains regularization (which penalizes weights) and "
        "early stopping (which ends training when validation loss rises). [1]",
        previous,
    ) == ["Regularization", "Early stopping"]
    # Parenthetical method variants are not silently discarded as descriptions.
    assert answer_methods("Regularization is discussed.", ["Regularization (L1)"]) == []


def grounded_test_model(prompt, context):
    """Extract actual fixture sentences from evidence, never fabricate retrieval."""
    original = prompt.split("Resolved retrieval question:")[0].casefold()
    blocks = re.split(r"(?m)(?=^\[\d+\])", context)
    blocks = [" ".join(block.split()) for block in blocks]
    if "overcome" in original:
        match = next(block for block in blocks if "Chapter 2:" in block)
        source = re.search(r"\[(\d+)\]", match)[1]
        return (
            f"1. Cross-validation [{source}]\n2. Regularization [{source}]\n"
            f"3. Early stopping [{source}]"
        )
    if "chapter 5" in original:
        match = next(block for block in blocks if "Chapter 5:" in block)
        source = re.search(r"\[(\d+)\]", match)[1]
        return f"1. Regularization [{source}]\n2. Early stopping [{source}]"
    if "second method" in original:
        match = next(block for block in blocks if "Early stopping ends" in block)
        source = re.search(r"\[(\d+)\]", match)[1]
        return f"Early stopping ends training when validation loss rises. [{source}]"
    match = next(block for block in blocks if "Overfitting occurs" in block)
    source = re.search(r"\[(\d+)\]", match)[1]
    return f"Overfitting occurs when a model memorizes training noise. [{source}]"


@pytest.mark.parametrize("chapter_format", ["numbered", "prose", "prose_descriptions"])
def test_overfitting_followups_survive_logout_and_fresh_client(stack, chapter_format):
    client, factory, resources = stack
    headers = authenticate(client)
    doc = ingest(stack, textbook_pdf(), headers)
    chat = new_conversation(client, headers, [doc])

    def model(prompt, context):
        result = grounded_test_model(prompt, context)
        original = prompt.split("Resolved retrieval question:")[0].casefold()
        if chapter_format == "prose_descriptions" and "overcome" in original:
            result = result.replace("Regularization", "Regularization (reduces overfitting)")
            result = result.replace(
                "Early stopping", "Early stopping (ends training when validation loss rises)"
            )
        if chapter_format.startswith("prose") and "chapter 5" in original:
            return result.replace("1. ", "").replace("\n2. ", " and ")
        return result

    resources._generator.answer.side_effect = model
    first = ask(client, headers, chat, "What is overfitting?")
    assert first.status_code == 201, first.text
    assert first.json()["citations"][0]["page"] == 1
    second = ask(client, headers, chat, "How can I overcome it?")
    assert second.status_code == 201, second.text
    assert "Regularization" in second.json()["content"]
    assert "overfitting" in resources._generator.answer.call_args.args[0].casefold()
    assert second.json()["citations"][0]["page"] == 2
    assert client.post("/api/v1/auth/logout", headers=headers).status_code == 204
    # Every invocation constructs a fresh graph and opens a new persistent saver/SQL session.
    with TestClient(app) as restarted:
        token = restarted.post(
            "/api/v1/auth/login",
            json={"email": "alice@example.com", "password": "strong-test-password"},
        ).json()["access_token"]
        headers = {"Authorization": "Bearer " + token}
        path = f"/api/v1/conversations/{chat}"
        assert restarted.get(path, headers=headers).json()["document_ids"] == [doc]
        assert len(restarted.get(path + "/messages", headers=headers).json()) == 4
        third = ask(
            restarted, headers, chat, "Which of those techniques is explained in chapter 5?"
        )
        assert third.status_code == 201, third.text
        assert {c["page"] for c in third.json()["citations"]} == {3}
        fourth = ask(restarted, headers, chat, "Can you explain the second method with an example?")
        assert fourth.status_code == 201, fourth.text
        assert "Early stopping" in fourth.json()["content"]
        prompt = resources._generator.answer.call_args.args[0]
        rewritten = prompt.split("Resolved retrieval question:")[1].split("UNTRUSTED")[0]
        assert "Early stopping" in rewritten
        assert {c["document_id"] for c in fourth.json()["citations"]} == {doc}
    with factory() as db:
        conv = db.get(Conversation, UUID(chat))
        with checkpoints.checkpoint_store(db) as saver:
            entries = list(saver.list({"configurable": {"thread_id": checkpoints.thread_id(conv)}}))
            assert len(entries) == 1
            state = entries[0].checkpoint["channel_values"]
            assert state["topic"] == "overfitting"
            assert state["history"] == [] and state["evidence"] == []
            assert state["current_message"] == ""
        if db.get_bind().dialect.name == "postgresql":
            assert db.scalar(text("SELECT count(*) FROM checkpoint_writes")) == 0
            assert db.scalar(text("SELECT count(*) FROM checkpoint_blobs")) < 60
        assert db.scalar(select(func.count()).select_from(Message)) == 8
        measured = [
            m.turn_metadata["timings_ms"]
            for m in db.scalars(select(Message).where(Message.role == "assistant"))
        ]
        print("\nSynthetic model stage timings (ms): " + json.dumps(measured))
        if db.get_bind().dialect.name == "postgresql":
            # A separate interpreter has no access to this graph, saver or ORM objects.
            program = (
                "import os,sys; from langgraph.checkpoint.postgres import PostgresSaver; "
                "url=os.environ['TEST_DATABASE_URL'].replace("
                "'postgresql+psycopg://','postgresql://'); "
                "\nwith PostgresSaver.from_conn_string(url) as saver:\n"
                " state=saver.get_tuple({'configurable':{'thread_id':sys.argv[1]}})\n"
                " assert state.checkpoint['channel_values']['topic']=='overfitting'\n"
                " assert state.checkpoint['channel_values']['response_id']==sys.argv[2]\n"
            )
            result = subprocess.run(
                [sys.executable, "-c", program, checkpoints.thread_id(conv), fourth.json()["id"]],
                capture_output=True,
                timeout=30,
            )
            assert result.returncode == 0, "Fresh-process checkpoint restore failed"


@pytest.mark.parametrize(
    ("question", "topic", "references", "expected"),
    [
        ("How can I overcome it?", "overfitting", {}, "overfitting"),
        ("What about the disadvantages?", "random forests", {}, "random forests"),
        (
            "Explain the second method",
            "overfitting",
            {"methods": ["validation", "regularization"]},
            "regularization",
        ),
        (
            "Which of those techniques are in chapter 5?",
            "overfitting",
            {"methods": ["validation"]},
            "validation",
        ),
    ],
)
def test_contextual_resolution(question, topic, references, expected):
    result = resolve(question, topic, references, [], [])
    assert expected in result["rewritten_question"]
    assert not result["clarification"]
    restored = resolve(
        "How can I overcome it?", "", {}, [{"role": "user", "content": "What is overfitting?"}], []
    )
    assert restored["topic"] == "overfitting"


def test_ambiguous_reference_requests_clarification_without_provider(stack, pdf):
    client, _, resources = stack
    headers = authenticate(client)
    chat = new_conversation(client, headers, [ingest(stack, pdf, headers)])
    result = ask(client, headers, chat, "How can I overcome it?")
    assert result.status_code == 201
    assert "refer to" in result.json()["content"]
    assert result.json()["citations"] == []
    resources._generator.answer.assert_not_called()
    missing = resolve("Explain the fifth method", "overfitting", {"methods": ["L2"]}, [], [])
    assert missing["clarification"]


def test_long_history_incremental_summary_and_distant_recall(stack, pdf):
    client, factory, resources = stack
    headers = authenticate(client)
    chat = new_conversation(client, headers, [ingest(stack, pdf, headers)])
    resources.settings.chat_recent_messages = 4
    resources.settings.chat_summary_batch = 10
    resources.settings.chat_summary_tokens = 100
    with factory() as db:
        conv = db.get(Conversation, UUID(chat))
        for position in range(1, 41):
            db.add(
                Message(
                    conversation_id=conv.id,
                    position=position,
                    role="user" if position % 2 else "assistant",
                    request_id=uuid4(),
                    content="What is overfitting?"
                    if position == 1
                    else "Discuss random forests " * 30,
                    citations=[],
                    turn_metadata={"scope_version": 1},
                )
            )
        db.commit()
        one = reconstruct(
            db, conv, "Return to my first question: how can I overcome it?", resources.settings
        )
        assert one["covered_through"] == 10
        assert token_count(one["summary"]) <= 100
        assert any("overfitting" in m["content"] for m in one["recalled"])
        two = reconstruct(db, conv, "overfitting", resources.settings)
        assert two["covered_through"] == 20 and two["summary_version"] == 2
        assert db.get(ConversationSummary, conv.id).provenance[0]["from"] > 10
        resolved = resolve(
            "Return to my first question: how can I overcome it?",
            "random forests",
            {},
            one["history"],
            one["recalled"],
        )
        assert resolved["topic"] == "overfitting"
        db.commit()
    refresh = client.post(f"/api/v1/conversations/{chat}/summary/refresh", headers=headers)
    assert refresh.status_code == 200
    assert refresh.json()["covered_through"] == 10


def test_document_scope_management_comparison_and_unauthorized_threads(stack, pdf):
    client, _, resources = stack
    alice, bob = authenticate(client), authenticate(client, "bob@example.com")
    first, other = ingest(stack, pdf, alice), ingest(stack, textbook_pdf(), alice)
    foreign = ingest(stack, textbook_pdf(), bob)
    chat = new_conversation(client, alice, [first])
    path = f"/api/v1/conversations/{chat}"
    for method in ("GET", "PATCH", "DELETE"):
        response = client.request(
            method,
            path,
            headers=bob,
            **({"json": {"title": "intrusion"}} if method == "PATCH" else {}),
        )
        assert response.status_code == 404
    assert client.patch(path, headers=alice, json={"document_ids": [foreign]}).status_code == 404
    clarification = ask(client, alice, chat, "Compare alpha revenue across both books")
    assert "Select both" in clarification.json()["content"]
    assert not resources._generator.answer.called
    updated = client.patch(
        path, headers=alice, json={"title": "Comparison", "document_ids": [first, other]}
    )
    assert updated.status_code == 200 and updated.json()["scope_version"] == 2
    resources._generator.answer.return_value = "The books discuss different topics. [1] [2]"
    # The test embedding 'alpha overfitting' matches both genuinely indexed documents.
    result = ask(client, alice, chat, "Compare alpha revenue and overfitting across the books")
    assert result.status_code == 201, result.text
    assert {c["document_id"] for c in result.json()["citations"]} == {first, other}
    for citation in result.json()["citations"]:
        assert citation["chunk_id"] and citation["preview_path"]
    assert client.patch(path, headers=alice, json={"document_ids": [first]}).status_code == 200
    resources._generator.answer.return_value = "Alpha revenue is 42 million. [1]"
    result = ask(client, alice, chat, "What is alpha revenue?")
    assert {c["document_id"] for c in result.json()["citations"]} == {first}
    assert ask(client, alice, chat, "Explain foreign.pdf").json()["citations"] == []
    assert client.delete(path, headers=alice).status_code == 204
    assert client.get(path, headers=alice).status_code == 404


def test_two_users_different_books_and_checkpoint_threads(stack, pdf):
    client, factory, resources = stack
    alice, bob = authenticate(client), authenticate(client, "bob@example.com")
    alpha, ml = ingest(stack, pdf, alice), ingest(stack, textbook_pdf(), bob)
    first, second = new_conversation(client, alice, [alpha]), new_conversation(client, bob, [ml])

    def model(question, context):
        if "Original question: alpha" in question:
            assert "Overfitting occurs" not in context
            return "Alpha revenue is 42 million. [1]"
        assert "42 million" not in context
        return "Overfitting memorizes training noise. [1]"

    resources._generator.answer.side_effect = model
    if factory.kw["bind"].dialect.name == "postgresql":
        with ThreadPoolExecutor(max_workers=2) as pool:
            calls = [
                pool.submit(ask, client, alice, first, "alpha revenue"),
                pool.submit(ask, client, bob, second, "What is overfitting?"),
            ]
            replies = [call.result(timeout=30) for call in calls]
    else:
        replies = [
            ask(client, alice, first, "alpha revenue"),
            ask(client, bob, second, "What is overfitting?"),
        ]
    for response, doc in zip(replies, [alpha, ml], strict=True):
        assert response.status_code == 201, response.text
        assert {c["document_id"] for c in response.json()["citations"]} == {doc}
    with factory() as db:
        for chat in [first, second]:
            conv = db.get(Conversation, UUID(chat))
            with checkpoints.checkpoint_store(db) as saver:
                state = saver.get_tuple(
                    {"configurable": {"thread_id": checkpoints.thread_id(conv)}}
                )
                assert state.checkpoint["channel_values"]["user_id"] == str(conv.user_id)


def test_export_pagination_optional_rewrite_and_budgets(stack, pdf, monkeypatch):
    from unittest.mock import Mock

    from backend.app.conversations import workflow
    from backend.app.conversations.rewriting import QueryResolution

    client, _, resources = stack
    headers = authenticate(client)
    chat = new_conversation(client, headers, [ingest(stack, pdf, headers)])
    resources.settings.chat_llm_rewrite = True
    rewrite = Mock(return_value=QueryResolution(query="alpha revenue", topic="alpha revenue"))
    monkeypatch.setattr(workflow, "rewrite_followup", rewrite)
    first = ask(client, headers, chat, "What is alpha revenue?")
    assert first.status_code == 201 and rewrite.call_count == 0
    assert ask(client, headers, chat, "What about it?").status_code == 201
    rewrite.assert_called_once()
    exported = client.get(f"/api/v1/conversations/{chat}/export?limit=2", headers=headers)
    assert exported.status_code == 200
    assert len(exported.json()["messages"]) == 2 and exported.json()["next_offset"] == 2
    resources.settings.chat_llm_rewrite = False
    resources.settings.chat_context_tokens = 2000
    assert ask(client, headers, chat, "alpha " + "漢" * 3500).status_code == 422
    assert len(client.get(f"/api/v1/conversations/{chat}/messages", headers=headers).json()) == 4


def test_failed_interrupted_and_repeated_request_atomicity(stack, pdf):
    client, factory, resources = stack
    headers = authenticate(client)
    chat = new_conversation(client, headers, [ingest(stack, pdf, headers)])
    request_id = str(uuid4())
    for failure in [TimeoutError("private"), RuntimeError("rate limited private")]:
        resources._generator.answer.side_effect = failure
        failed = ask(client, headers, chat, "What is alpha revenue?", request_id)
        assert failed.status_code == 503 and "private" not in failed.text
        with factory() as db:
            assert db.scalar(select(func.count()).select_from(Message)) == 0
            if db.get_bind().dialect.name == "postgresql":
                assert db.scalar(text("SELECT count(*) FROM checkpoints")) == 0
    resources._generator.answer.side_effect = None
    reply = ask(client, headers, chat, "What is alpha revenue?", request_id)
    assert reply.status_code == 201, reply.text
    assert (
        ask(client, headers, chat, "What is alpha revenue?", request_id).json()["id"]
        == reply.json()["id"]
    )
    assert ask(client, headers, chat, "Different question", request_id).status_code == 409


def test_postgres_same_thread_busy_other_conversation_independent(stack, pdf):
    client, factory, resources = stack
    if factory.kw["bind"].dialect.name != "postgresql":
        pytest.skip("PostgreSQL row locking requires real-service acceptance")
    headers = authenticate(client)
    doc = ingest(stack, pdf, headers)
    first, second = (
        new_conversation(client, headers, [doc]),
        new_conversation(client, headers, [doc]),
    )
    entered, release = Event(), Event()

    def model(question, context):
        if "Hold alpha" in question:
            entered.set()
            assert release.wait(20)
        return "Alpha revenue is 42 million. [1]"

    resources._generator.answer.side_effect = model
    with ThreadPoolExecutor(max_workers=2) as pool:
        pending = pool.submit(ask, client, headers, first, "Hold alpha revenue")
        try:
            assert entered.wait(15)
            assert ask(client, headers, first, "alpha revenue").status_code == 409
            assert ask(client, headers, second, "alpha revenue").status_code == 201
        finally:
            release.set()
        assert pending.result(timeout=20).status_code == 201


def test_deleted_document_clears_checkpoint_and_can_recover(stack, pdf):
    client, factory, _ = stack
    headers = authenticate(client)
    doc, replacement = ingest(stack, pdf, headers), ingest(stack, textbook_pdf(), headers)
    chat = new_conversation(client, headers, [doc])
    assert ask(client, headers, chat, "What is alpha revenue?").status_code == 201
    assert client.delete(f"/api/v1/documents/{doc}", headers=headers).status_code == 202
    path = f"/api/v1/conversations/{chat}"
    assert client.get(path + "/messages", headers=headers).json() == []
    with factory() as db:
        conv = db.get(Conversation, UUID(chat))
        with checkpoints.checkpoint_store(db) as saver:
            assert (
                saver.get_tuple({"configurable": {"thread_id": checkpoints.thread_id(conv)}})
                is None
            )
    reply = ask(client, headers, chat, "What is overfitting?")
    assert "No selected source" in reply.json()["content"]
    assert (
        client.patch(path, headers=headers, json={"document_ids": [replacement]}).status_code == 200
    )
    assert client.get(path, headers=headers).json()["document_ids"] == [replacement]


def test_deleting_previous_scope_source_also_purges_derived_history(stack, pdf):
    client, _, _ = stack
    headers = authenticate(client)
    original, current = ingest(stack, pdf, headers), ingest(stack, textbook_pdf(), headers)
    chat = new_conversation(client, headers, [original])
    path = f"/api/v1/conversations/{chat}"
    assert ask(client, headers, chat, "alpha revenue").status_code == 201
    assert client.patch(path, headers=headers, json={"document_ids": [current]}).status_code == 200
    assert client.get(path, headers=headers).json()["document_ids"] == [current]
    assert len(client.get(path + "/messages", headers=headers).json()) == 2
    assert client.delete(f"/api/v1/documents/{original}", headers=headers).status_code == 202
    assert client.get(path + "/messages", headers=headers).json() == []
    assert client.get(path, headers=headers).json()["document_ids"] == [current]
