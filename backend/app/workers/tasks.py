import logging
from uuid import UUID

import dramatiq

from backend.app.db.session import session_factory
from backend.app.services.resources import get_resources
from backend.app.workers.broker import broker  # noqa: F401
from backend.app.workers.ingestion import process_one

for logger_name in ("httpx", "httpcore", "google_genai", "huggingface_hub"):
    logging.getLogger(logger_name).setLevel(logging.WARNING)


@dramatiq.actor(max_retries=3, min_backoff=10000, max_backoff=300000, time_limit=14_400_000)
def ingest_document(job_id: str) -> None:
    try:
        with session_factory()() as db:
            process_one(db, get_resources(), UUID(job_id))
    except Exception:
        raise RuntimeError("Ingestion job delivery failed; database unavailable") from None
