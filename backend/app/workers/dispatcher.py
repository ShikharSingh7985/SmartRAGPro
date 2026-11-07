"""SQL outbox/recovery dispatcher: Redis delivery never determines durable job truth."""

import logging
import signal
import time
from datetime import timedelta

from redis import Redis
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from backend.app.core.config import get_settings
from backend.app.core.telemetry import (
    HEARTBEAT,
    QUEUE,
    STORAGE,
    configure,
    observed,
    start_metrics,
)
from backend.app.db.session import session_factory
from backend.app.models.entities import Document, IngestionJob, now
from backend.app.services.accounts import maintain_security


@observed("queue.dispatch")
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
    settings = get_settings()
    configure(settings)
    start_metrics(settings)
    connection = Redis.from_url(settings.redis_url, socket_timeout=3)
    stop = False

    def halt(_signum, _frame):  # type: ignore[no-untyped-def]
        nonlocal stop
        stop = True

    signal.signal(signal.SIGTERM, halt)
    signal.signal(signal.SIGINT, halt)
    last_maintenance = 0.0
    while not stop:
        try:
            with session_factory()() as db:
                dispatch_due(db)
                for status in ("queued", "running", "succeeded", "failed"):
                    QUEUE.labels(status).set(
                        db.scalar(
                            select(func.count(IngestionJob.id)).where(IngestionJob.status == status)
                        )
                        or 0
                    )
                original, derived = db.execute(
                    select(
                        func.coalesce(func.sum(Document.size_bytes), 0),
                        func.coalesce(func.sum(Document.derived_bytes), 0),
                    )
                ).one()
                STORAGE.labels("original").set(original)
                STORAGE.labels("derived").set(derived)
                connection.set("smartrag:health:dispatcher", str(time.time()), ex=120)
                HEARTBEAT.labels("dispatcher").set(time.time())
                if time.monotonic() - last_maintenance > 3600:
                    maintain_security(db, get_settings().security_audit_retention_days)
                    last_maintenance = time.monotonic()
        except Exception:
            logging.warning("Job dispatch temporarily unavailable (details suppressed)")
        time.sleep(2)
    connection.close()


if __name__ == "__main__":
    main()
