"""SQL outbox/recovery dispatcher: Redis delivery never determines durable job truth."""

import logging
import time
from datetime import timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from backend.app.db.session import session_factory
from backend.app.models.entities import IngestionJob, now


def dispatch_due(db: Session) -> int:
    from backend.app.workers.tasks import ingest_document

    jobs = list(
        db.scalars(
            select(IngestionJob)
            .where(
                IngestionJob.status.in_(["queued", "running"]),
                IngestionJob.available_at <= now(),
                or_(
                    IngestionJob.dispatched_at.is_(None),
                    IngestionJob.dispatched_at < now() - timedelta(seconds=30),
                ),
            )
            .with_for_update(skip_locked=True)
            .limit(50)
        )
    )
    for job in jobs:
        ingest_document.send(str(job.id))
        job.dispatched_at = now()
    db.commit()
    return len(jobs)


def main() -> None:
    while True:
        try:
            with session_factory()() as db:
                dispatch_due(db)
        except Exception:
            logging.warning("Job dispatch temporarily unavailable (details suppressed)")
        time.sleep(2)


if __name__ == "__main__":
    main()
