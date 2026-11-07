"""Operator-only recovery; no public administrative API or automatic unlimited retries."""

import argparse
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.db.session import session_factory
from backend.app.models.entities import AuditEvent, Document, IngestionJob, now


def recover(db: Session, document_id: UUID) -> bool:
    document = db.scalar(select(Document).where(Document.id == document_id).with_for_update())
    if not document or document.status != "deleting":
        return False
    job = db.scalar(
        select(IngestionJob)
        .where(
            IngestionJob.document_id == document_id,
            IngestionJob.kind.in_(["delete", "cleanup"]),
            IngestionJob.status == "failed",
        )
        .order_by(IngestionJob.created_at.desc())
        .with_for_update()
        .limit(1)
    )
    if not job:
        return False
    job.status, job.stage, job.error = "queued", "queued", None
    job.attempts, job.available_at, job.dispatched_at = 0, now(), None
    job.run_token = None
    document.error = None
    db.add(AuditEvent(event="cleanup_requeued", resource_id=document_id))
    db.commit()
    return True


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("document_id", type=UUID)
    args = parser.parse_args()
    with session_factory()() as db:
        if not recover(db, args.document_id):
            raise SystemExit("No failed cleanup found for a deleting document")
    print("Cleanup requeued with a fresh bounded retry budget")


if __name__ == "__main__":
    main()
