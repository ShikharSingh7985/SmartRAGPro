from uuid import UUID

import pytest
from sqlalchemy import func, select

from backend.app.conversations.evidence import retrieve
from backend.app.models.entities import Document, SearchChunk, SearchTerm
from backend.app.rag.cache import VectorCache
from backend.app.rag.lexical import search
from backend.app.rag.ranking import bm25_scores, deduplicate, rerank, rrf, terms
from evaluation.dataset import build, load
from evaluation.metrics import retrieval_metrics
from tests.conftest import authenticate, ingest


def test_grounded_abstention_is_safe_but_uncited_claims_still_fail(stack, pdf):
    from uuid import uuid4

    from backend.app.services.resources import ABSTENTION
    from tests.test_workflow import new_conversation

    client, _, resources = stack
    headers = authenticate(client)
    doc = ingest(stack, pdf, headers)
    chat = new_conversation(client, headers, [doc])
    endpoint = f"/api/v1/conversations/{chat}/messages"
    resources._generator.answer.return_value = "Alpha revenue is 999 million."
    failed = client.post(
        endpoint, headers=headers, json={"content": "alpha revenue", "request_id": str(uuid4())}
    )
    assert failed.status_code == 502
    assert client.get(endpoint, headers=headers).json() == []
    resources._generator.answer.return_value = ABSTENTION
    reply = client.post(
        endpoint, headers=headers, json={"content": "alpha revenue", "request_id": str(uuid4())}
    )
    assert reply.status_code == 201 and reply.json()["content"] == ABSTENTION
    assert reply.json()["citations"] == []


def test_metrics_exact_relevance_definitions():
    scores = retrieval_metrics(["wrong", "a", "a", "b"], ["a", "b", "c"])
    assert scores["recall@1"] == 0
    assert scores["recall@3"] == pytest.approx(2 / 3)
    assert scores["precision@5"] == 0.4
    assert scores["hit_rate@3"] == 1
    assert scores["mrr"] == 0.5


def test_dataset_scopes_splits_and_review_provenance():
    assert len(load().queries) >= 60
    dataset = build()
    assert len(dataset.queries) >= 60
    assert len({q.category for q in dataset.queries}) >= 10
    assert all(q.reviewed_by is None for q in dataset.queries)
    invalid = dataset.model_dump()
    invalid["queries"][0]["relevant_ids"] = ["unknown"]
    with pytest.raises(ValueError):
        type(dataset).model_validate(invalid)


def test_rank_fusion_dedup_and_lexical_reranker():
    assert rrf(["b", "a"], ["a", "c"], 1) == ["b", "a"]
    assert rrf(["b", "a"], ["a", "c"], 0) == ["a", "c"]
    assert rrf(["a", "a"], ["a", "b"])[0] == "a"
    candidates = [
        {"id": "a", "text": "calibration record"},
        {"id": "b", "text": "ZX-47 calibration record"},
    ]
    assert rerank("ZX-47", candidates, 2)[0]["id"] == "b"
    assert terms("ZX-47 Foo_bar") == ["zx-47", "foo", "bar"]
    assert (
        len(
            deduplicate(
                [
                    {"text": "alpha beta", "document_id": "a", "page": 1},
                    {"text": "alpha beta", "document_id": "a", "page": 1},
                    {"text": "alpha beta", "document_id": "b", "page": 1},
                ]
            )
        )
        == 2
    )


def test_cache_capacity_ttl_and_tenant_keys(monkeypatch):
    cache = VectorCache(1, 5)
    first = cache.key("alice", "model1", "private query")
    assert first != cache.key("bob", "model1", "private query")
    assert first != cache.key("alice", "model2", "private query")
    assert "private query" not in first
    cache.put(first, [1.0])
    vector = cache.get(first)
    vector[0] = 2.0
    assert cache.get(first) == [1.0]
    cache.put("new", [2.0])
    assert cache.get(first) is None
    monkeypatch.setattr("backend.app.rag.cache.monotonic", lambda: 10**12)
    assert cache.get("new") is None


def test_sql_bm25_parity_isolation_and_cleanup(stack, pdf):
    client, factory, resources = stack
    alice, bob = authenticate(client), authenticate(client, "bob@example.com")
    first, second = ingest(stack, pdf, alice), ingest(stack, pdf, bob)
    with factory() as db:
        doc = db.get(Document, UUID(first))
        foreign = db.get(Document, UUID(second))
        rows = list(
            db.scalars(
                select(SearchChunk)
                .where(SearchChunk.document_id == doc.id)
                .order_by(SearchChunk.id)
            )
        )
        assert rows
        result, complete = search(db, doc.user_id, [doc], "alpha revenue", 24)
        expected = bm25_scores("alpha revenue", [row.text for row in rows])
        by_id = {str(row.id): score for row, score in zip(rows, expected, strict=True)}
        assert complete
        assert all(row["document_id"] == first for row in result)
        assert [row["lexical_score"] for row in result] == pytest.approx(
            [by_id[row["id"]] for row in result]
        )
        none, _ = search(db, foreign.user_id, [doc], "alpha revenue", 24)
        assert none == []
        for mode in ["bm25", "hybrid", "hybrid_rerank"]:
            resources.settings.retrieval_mode = mode
            plan = {}
            evidence = retrieve(resources, doc.user_id, [doc], "alpha revenue", plan, db=db)
            assert evidence and all(str(e["document_id"]) == first for e in evidence)
            assert "lexical_ms" in plan["retrieval_metrics"]
        doc.active_run = "other-run"
        assert search(db, doc.user_id, [doc], "alpha revenue", 24)[0] == []
        db.rollback()
        resources.settings.retrieval_mode = "hybrid"
        resources.settings.retrieval_lexical_weight = 1.0
        db.delete(rows[0])
        db.flush()
        plan = {}
        assert retrieve(resources, doc.user_id, [doc], "alpha revenue", plan, db=db)
        assert plan["retrieval_metrics"]["fallback"] == "lexical_index_incomplete"
        db.rollback()
    assert client.delete(f"/api/v1/documents/{first}", headers=alice).status_code == 202
    from backend.app.workers.ingestion import process_one

    with factory() as db:
        assert process_one(db, resources)
        assert not db.scalar(
            select(func.count())
            .select_from(SearchChunk)
            .where(SearchChunk.document_id == UUID(first))
        )
        assert db.scalar(select(func.count()).select_from(SearchTerm)) > 0
