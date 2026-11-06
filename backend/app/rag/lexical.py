"""Persistent inverted index, scoped statistics and database-ranked BM25 candidates."""

import math
from collections import Counter
from typing import Any
from uuid import UUID

from sqlalchemy import case, delete, func, or_, select
from sqlalchemy.orm import Session

from backend.app.models.entities import Document, SearchChunk, SearchTerm
from backend.app.rag.ranking import terms


def store_chunk(db: Session, identifier: str, payload: dict[str, Any]) -> None:
    identity = UUID(identifier)
    row = db.get(SearchChunk, identity)
    if row and row.run_token == payload["run_token"]:
        return
    if row is None:
        row = SearchChunk(id=identity)
        db.add(row)
    row.user_id, row.document_id = UUID(payload["user_id"]), UUID(payload["document_id"])
    row.run_token, row.page, row.text = payload["run_token"], payload["page"], payload["text"]
    row.details = {key: value for key, value in payload.items() if key != "text"}
    frequencies = Counter(terms(row.text))
    row.length = sum(frequencies.values())
    db.flush()
    db.execute(delete(SearchTerm).where(SearchTerm.chunk_id == identity))
    db.add_all(
        [
            SearchTerm(chunk_id=identity, term=term, frequency=count)
            for term, count in frequencies.items()
        ]
    )


def search(
    db: Session,
    user_id: UUID,
    documents: list[Document],
    query: str,
    limit: int,
    chapter: str | None = None,
) -> tuple[list[dict[str, Any]], bool]:
    if not documents:
        return [], False
    # Tenant and SQL-authorized ready scope constrain N, average length, DF and candidates.
    scope = [
        SearchChunk.user_id == user_id,
        SearchChunk.document_id.in_([d.id for d in documents]),
        or_(
            *[
                (SearchChunk.document_id == d.id) & (SearchChunk.run_token == d.active_run)
                for d in documents
            ]
        ),
        SearchChunk.document_id.in_(
            select(Document.id)
            .where(
                Document.user_id == user_id,
                Document.status == "ready",
                Document.active_run == SearchChunk.run_token,
            )
            .correlate(SearchChunk)
        ),
    ]
    index_scope = list(scope)
    if chapter:
        scope.append(
            or_(
                SearchChunk.text.ilike(f"%chapter {chapter}%"),
                SearchChunk.details["section_heading"].as_string().ilike(f"%chapter {chapter}%"),
            )
        )
    count, average = db.execute(
        select(func.count(), func.avg(SearchChunk.length)).where(*scope)
    ).one()
    indexed = {
        identifier: count
        for identifier, count in db.execute(
            select(SearchChunk.document_id, func.count())
            .where(*index_scope)
            .group_by(SearchChunk.document_id)
        )
    }
    complete = all(
        indexed.get(doc.id, 0) == doc.chunk_count and doc.chunk_count > 0 for doc in documents
    )
    query_terms = list(dict.fromkeys(terms(query)))[:80]
    if not count or not query_terms:
        return [], complete
    dfs: dict[str, int] = {
        term: int(count)
        for term, count in (
            db.execute(
                select(SearchTerm.term, func.count())
                .join(SearchChunk)
                .where(*scope, SearchTerm.term.in_(query_terms))
                .group_by(SearchTerm.term)
            ).all()
        )
    }
    weights = {
        term: math.log(1 + (count - frequency + 0.5) / (frequency + 0.5))
        for term, frequency in dfs.items()
    }
    if not weights:
        return [], complete
    idf = case(weights, value=SearchTerm.term, else_=0.0)
    tf = SearchTerm.frequency
    score = func.sum(
        idf * tf * 2.5 / (tf + 1.5 * (0.25 + 0.75 * SearchChunk.length / (average or 1)))
    )
    ranked = (
        select(SearchTerm.chunk_id, score.label("score"))
        .join(SearchChunk)
        .where(*scope, SearchTerm.term.in_(query_terms))
        .group_by(SearchTerm.chunk_id)
        .order_by(score.desc(), SearchTerm.chunk_id)
        .limit(limit)
    )
    scores = list(db.execute(ranked))
    rows = {
        row.id: row
        for row in db.scalars(
            select(SearchChunk).where(
                *scope, SearchChunk.id.in_([identifier for identifier, _ in scores])
            )
        )
    }
    return [
        {
            "id": str(identifier),
            "text": rows[identifier].text,
            **rows[identifier].details,
            "lexical_score": float(value),
        }
        for identifier, value in scores
        if identifier in rows
    ], complete
