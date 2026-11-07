from unittest.mock import Mock
from uuid import UUID

from sqlalchemy import select

from backend.app.models.entities import Document, IngestionJob, now
from backend.app.workers.ingestion import process_one
from scripts.retry_cleanup import recover
from tests.conftest import authenticate, ingest


def test_cleanup_exhausts_without_reexposure_and_operator_can_recover(stack, pdf):
    client, factory, resources = stack
    headers = authenticate(client)
    identifier = UUID(ingest(stack, pdf, headers))
    client.delete(f"/api/v1/documents/{identifier}", headers=headers)
    original = resources.store
    resources.store = Mock(wraps=original)
    resources.store.delete.side_effect = TimeoutError("private storage error")
    with factory() as db:
        job = db.scalar(
            select(IngestionJob).where(
                IngestionJob.document_id == identifier, IngestionJob.kind == "delete"
            )
        )
        for _ in range(resources.settings.ingestion_max_attempts):
            job.available_at = now()
            db.commit()
            assert process_one(db, resources, job.id)
        assert job.status == "failed"
        assert db.get(Document, identifier).status == "deleting"
        assert not process_one(db, resources, job.id)
        assert recover(db, identifier)
        resources.store = original
        assert process_one(db, resources, job.id)
        assert db.get(Document, identifier) is None
