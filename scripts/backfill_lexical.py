"""Backfill ready active-run lexical chunks without making embedding calls."""

from qdrant_client import models as qm
from sqlalchemy import select

from backend.app.db.session import session_factory
from backend.app.models.entities import Document
from backend.app.rag.lexical import store_chunk
from backend.app.rag.vectors import tenant_filter
from backend.app.services.resources import get_resources


def main() -> None:
    resources = get_resources()
    count = 0
    try:
        with session_factory()() as db:
            ids = list(db.scalars(select(Document.id).where(Document.status == "ready")))
        for identifier in ids:
            offset = None
            while True:
                with session_factory()() as db:
                    doc = db.scalar(
                        select(Document)
                        .where(Document.id == identifier, Document.status == "ready")
                        .with_for_update(read=True)
                    )
                    if not doc or not doc.active_run:
                        break
                    scope = tenant_filter(doc.user_id, [doc.id])
                    assert isinstance(scope.must, list)
                    scope.must.append(
                        qm.FieldCondition(
                            key="run_token", match=qm.MatchValue(value=doc.active_run)
                        )
                    )
                    points, next_offset = resources.qdrant.scroll(
                        doc.index_collection or resources.settings.qdrant_collection,
                        scroll_filter=scope,
                        limit=32,
                        offset=offset,
                        with_payload=True,
                    )
                    for point in points:
                        payload = point.payload or {}
                        if (
                            payload.get("user_id") != str(doc.user_id)
                            or payload.get("document_id") != str(doc.id)
                            or payload.get("run_token") != doc.active_run
                        ):
                            continue
                        if not 1 <= int(payload.get("page", 0)) <= doc.page_count:
                            continue
                        store_chunk(db, str(point.id), payload)
                        count += 1
                    db.commit()
                    offset = next_offset
                    if offset is None:
                        break
        print(f"Backfilled {count} active chunks; no embedding calls made")
    except Exception:
        raise SystemExit("Lexical backfill failed; details suppressed. Safe to rerun.") from None
    finally:
        resources.close()


if __name__ == "__main__":
    main()
