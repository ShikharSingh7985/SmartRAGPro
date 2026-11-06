"""SQL-authorized retrieval with active-run and page provenance validation."""

import re
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from qdrant_client import models as qm

from backend.app.conversations.memory import token_count, truncate
from backend.app.models.entities import Document
from backend.app.rag.types import embedding_fingerprint
from backend.app.rag.vectors import tenant_filter
from backend.app.schemas.api import Citation
from backend.app.services.resources import Resources


def retrieve(
    resources: Resources, user_id: UUID, documents: list[Document], query: str, plan: dict[str, Any]
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
    vector = resources.embedding.embed_query(query)
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
        points = resources.qdrant.query_points(
            settings.qdrant_collection,
            query=vector,
            query_filter=scoped,
            limit=24,
            with_payload=True,
            score_threshold=0.25,
        ).points
        by_id = {str(doc.id): doc for doc in group}
        for point in points:
            payload = point.payload or {}
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
                chunk_id=str(payload.get("chunk_id") or point.id),
                element_id=payload.get("element_id"),
                section_heading=payload.get("section_heading"),
                preview_path=f"/api/v1/documents/{doc.id}/preview/{page}",
            )
            evidence.append(citation.model_dump(mode="json"))
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
