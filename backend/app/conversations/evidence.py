"""SQL-authorized retrieval with active-run and page provenance validation."""

import re
from time import perf_counter
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from qdrant_client import models as qm
from sqlalchemy.orm import Session

from backend.app.conversations.memory import token_count, truncate
from backend.app.models.entities import Document
from backend.app.rag.cache import embed_query
from backend.app.rag.lexical import search
from backend.app.rag.ranking import deduplicate, rerank, rrf
from backend.app.rag.types import embedding_fingerprint
from backend.app.rag.vectors import tenant_filter
from backend.app.schemas.api import Citation
from backend.app.services.resources import Resources


def retrieve(
    resources: Resources,
    user_id: UUID,
    documents: list[Document],
    query: str,
    plan: dict[str, Any],
    db: Session | None = None,
) -> list[dict[str, Any]]:
    settings = resources.settings
    for document in documents:
        if (
            document.index_fingerprint
            and document.index_fingerprint != embedding_fingerprint(settings)
        ) or (
            document.index_collection and document.index_collection != settings.qdrant_collection
        ):
            raise HTTPException(409, "Selected documents need reindexing for the configured index")
    vector = None
    mode = settings.retrieval_mode
    metrics: dict[str, Any] = {
        "mode": mode,
        "lexical_ms": 0.0,
        "dense_ms": 0.0,
        "fusion_ms": 0.0,
        "rerank_ms": 0.0,
        "embedding_cache_hit": False,
    }
    if mode != "bm25":
        start = perf_counter()
        vector, hit = embed_query(resources, str(user_id), embedding_fingerprint(settings), query)
        metrics["embedding_ms"], metrics["embedding_cache_hit"] = (
            (perf_counter() - start) * 1000,
            hit,
        )
    evidence: list[dict[str, Any]] = []
    groups = [[doc] for doc in documents] if plan.get("compare") else [documents]
    for group in groups:
        scoped = tenant_filter(user_id, [doc.id for doc in group])
        scoped.should = [
            qm.Filter(
                must=[
                    qm.FieldCondition(key="document_id", match=qm.MatchValue(value=str(doc.id))),
                    qm.FieldCondition(key="run_token", match=qm.MatchValue(value=doc.active_run)),
                ]
            )
            if doc.active_run
            else qm.FieldCondition(key="document_id", match=qm.MatchValue(value=str(doc.id)))
            for doc in group
        ]
        lexical: list[dict[str, Any]] = []
        if mode != "dense" and db is not None:
            start = perf_counter()
            lexical, complete = search(
                db, user_id, group, query, settings.retrieval_candidates, plan.get("chapter")
            )
            metrics["lexical_ms"] += (perf_counter() - start) * 1000
            if not complete:
                metrics["fallback"] = "lexical_index_incomplete"
                lexical = []
        if mode == "bm25" and not metrics.get("fallback"):
            points = []
        else:
            if vector is None:
                vector, _ = embed_query(
                    resources, str(user_id), embedding_fingerprint(settings), query
                )
            start = perf_counter()
            points = resources.qdrant.query_points(
                settings.qdrant_collection,
                query=vector,
                query_filter=scoped,
                limit=settings.retrieval_candidates,
                with_payload=True,
                score_threshold=0.25,
            ).points
            metrics["dense_ms"] += (perf_counter() - start) * 1000
        dense = [{**(point.payload or {}), "id": str(point.id)} for point in points]
        start = perf_counter()
        by_identifier = {item["id"]: item for item in [*dense, *lexical]}
        if metrics.get("fallback") == "lexical_index_incomplete":
            ranked = dense
        elif mode in {"hybrid", "hybrid_rerank"}:
            ranked = [
                by_identifier[key]
                for key in rrf(
                    [p["id"] for p in lexical],
                    [p["id"] for p in dense],
                    settings.retrieval_lexical_weight,
                    settings.retrieval_rrf_k,
                )
            ]
        else:
            ranked = lexical if mode == "bm25" and not metrics.get("fallback") else dense
        metrics["fusion_ms"] += (perf_counter() - start) * 1000
        if mode == "hybrid_rerank":
            start = perf_counter()
            try:
                ranked = rerank(query, ranked, settings.retrieval_rerank_candidates)
            except (ValueError, TypeError, KeyError):
                metrics["fallback"] = "reranker_unavailable"
            metrics["rerank_ms"] += (perf_counter() - start) * 1000
        if settings.retrieval_deduplicate:
            ranked = deduplicate(ranked)
        by_id = {str(doc.id): doc for doc in group}
        for payload in ranked[: settings.retrieval_candidates]:
            doc = by_id.get(str(payload.get("document_id")))
            if not doc or payload.get("user_id") != str(user_id):
                continue
            if doc.active_run and payload.get("run_token") != doc.active_run:
                continue
            page = payload.get("page")
            page_end = payload.get("page_end", page)
            if (
                type(page) is not int
                or type(page_end) is not int
                or not 1 <= page <= page_end <= doc.page_count
            ):
                continue
            text = str(payload.get("text", ""))
            chapter = plan.get("chapter")
            if chapter and not re.search(
                rf"\bchapter\s+{re.escape(chapter)}\b",
                str(payload.get("section_heading", "")) + " " + text,
                re.I,
            ):
                continue
            if not text.strip():
                continue
            citation = Citation(
                source=len(evidence) + 1,
                document_id=doc.id,
                filename=doc.filename,
                page=page,
                page_end=page_end,
                excerpt=text[:8000],
                content_type=payload.get("content_type", "text"),
                asset_id=payload.get("asset_id"),
                model_derived=payload.get("model_derived", False),
                chunk_id=str(payload.get("chunk_id") or payload["id"]),
                element_id=payload.get("element_id"),
                section_heading=payload.get("section_heading"),
                preview_path=f"/api/v1/documents/{doc.id}/preview/{page}",
            )
            evidence.append(citation.model_dump(mode="json"))
    plan["retrieval_metrics"] = metrics
    return evidence


def select_evidence(evidence: list[dict[str, Any]], budget: int) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    groups: dict[str, list[dict[str, Any]]] = {}
    for item in evidence:
        groups.setdefault(item["document_id"], []).append(item)
    while groups and budget > 100 and len(selected) < 12:
        for key in list(groups):
            item = dict(groups[key].pop(0))
            item["excerpt"] = truncate(item["excerpt"], min(budget - 50, 700))
            budget -= token_count(item["excerpt"]) + 50
            item["source"] = len(selected) + 1
            selected.append(item)
            if not groups[key]:
                del groups[key]
            if budget <= 100:
                break
    return selected
