import logging
import signal
import time
from datetime import timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from backend.app.db.session import close_database, session_factory
from backend.app.models.entities import Document, IngestionJob, now
from backend.app.rag.pdf import extract_chunks
from backend.app.rag.vectors import delete_vectors, index_chunks
from backend.app.services.resources import Resources, get_resources

logger = logging.getLogger(__name__)


def process_one(db: Session, resources: Resources) -> bool:
    job = db.scalar(
        select(IngestionJob)
        .where(IngestionJob.status.in_(["queued", "running"]), IngestionJob.available_at <= now())
        .order_by(IngestionJob.created_at)
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    if job is None:
        db.rollback()
        return False
    job.status = "running"
    job.attempts += 1
    job.available_at = now() + timedelta(minutes=10)
    job_id, document_id = job.id, job.document_id
    db.commit()
    # A document lock serializes ingestion, retry and deletion across worker processes.
    document = db.scalar(select(Document).where(Document.id == document_id).with_for_update())
    job = db.get(IngestionJob, job_id, populate_existing=True)
    if not job or not document:
        db.rollback()
        return True
    try:
        if (
            document.status == "deleting"
            or job.kind == "delete"
            or (job.kind == "cleanup" and document.status == "uploading")
        ):
            delete_vectors(resources, document.user_id, document.id)
            resources.store.delete(document.object_key)
            db.execute(delete(IngestionJob).where(IngestionJob.document_id == document.id))
            db.delete(document)
        elif job.kind == "cleanup":
            job.status = "succeeded"
        else:
            data = resources.store.get(document.object_key)
            page_count, chunks = extract_chunks(data, resources.settings.max_pdf_pages)
            index_chunks(resources, document.user_id, document.id, chunks)
            document.status, document.page_count, document.error = "ready", page_count, None
            job.status, job.error = "succeeded", None
        db.commit()
    except Exception:
        db.rollback()
        # Never persist provider error strings: they may contain credentials or document text.
        document = db.scalar(select(Document).where(Document.id == document_id).with_for_update())
        job = db.get(IngestionJob, job_id, populate_existing=True)
        if document and job:
            if job.kind == "cleanup":
                document.status = "deleting"
            retry = job.attempts < 3 or document.status == "deleting"
            job.status = "queued" if retry else "failed"
            job.error = "Processing dependency failed; inspect service availability"
            job.available_at = now() + timedelta(seconds=min(300, 10 * 2 ** min(job.attempts, 5)))
            if document.status != "deleting":
                document.status = "queued" if retry else "failed"
            document.error = job.error
            db.commit()
        logger.warning("Job processing failed (details suppressed); job_id=%s", job_id)
    return True


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    stopping = False

    def stop(_signal: int, _frame: object) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    resources = get_resources()
    try:
        while not stopping:
            try:
                with session_factory()() as db:
                    if not process_one(db, resources):
                        time.sleep(2)
            except Exception:
                logger.warning("Worker database unavailable; retrying")
                time.sleep(5)
    finally:
        resources.close()
        close_database()


if __name__ == "__main__":
    main()
