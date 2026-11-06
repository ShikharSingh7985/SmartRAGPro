"""SQL outbox/recovery dispatcher: Redis delivery never determines durable job truth."""

import logging
import time
from datetime import timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from backend.app.core.config import get_settings
from backend.app.db.session import session_factory
from backend.app.models.entities import IngestionJob, now
from backend.app.services.accounts import maintain_security


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
    last_maintenance = 0.0
    while True:
        try:
            with session_factory()() as db:
                dispatch_due(db)
                if time.monotonic() - last_maintenance > 3600:
                    maintain_security(db, get_settings().security_audit_retention_days)
                    last_maintenance = time.monotonic()
        except Exception:
            logging.warning("Job dispatch temporarily unavailable (details suppressed)")
        time.sleep(2)


if __name__ == "__main__":
    main()
