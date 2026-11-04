from datetime import timedelta
from unittest.mock import Mock
from uuid import UUID, uuid4

from sqlalchemy import select

from backend.app.models.entities import Document, IngestionJob, User, now
from backend.app.workers.ingestion import process_one
from tests.conftest import authenticate, ingest


def test_abandoned_upload_cleanup(stack):
    client, factory, resources = stack
    authenticate(client)
    with factory() as db:
        user = db.scalar(select(User))
        document = Document(
            user_id=user.id,
            filename="abandoned.pdf",
            object_key=f"{user.id}/{uuid4()}.pdf",
            status="uploading",
        )
        db.add(document)
        db.flush()
        document_id, key = document.id, document.object_key
        db.add(IngestionJob(document_id=document_id, kind="cleanup"))
        resources.store.put(key, b"partial upload")
        db.commit()
        assert process_one(db, resources)
        assert db.get(Document, document_id) is None


def test_storage_failure_has_durable_compensation(stack, pdf):
    client, factory, resources = stack
    headers = authenticate(client)
    original = resources.store
    resources.store = Mock(wraps=original)
    resources.store.put.side_effect = RuntimeError("sensitive-storage-response")
    response = client.post(
        "/api/v1/documents", headers=headers, files={"file": ("report.pdf", pdf, "application/pdf")}
    )
    assert response.status_code == 503
    assert "sensitive" not in response.text
    resources.store = original
    with factory() as db:
        job = db.scalar(select(IngestionJob))
        assert job.kind == "cleanup"
        job.available_at = now()
        db.commit()
        assert process_one(db, resources)
        assert not list(db.scalars(select(Document)))


def test_deletion_outage_retries_without_reexposing_content(stack, pdf):
    client, factory, resources = stack
    headers = authenticate(client)
    document_id = ingest(stack, pdf, headers)
    assert client.delete(f"/api/v1/documents/{document_id}", headers=headers).status_code == 202
    original = resources.store
    resources.store = Mock(wraps=original)
    resources.store.delete.side_effect = RuntimeError("storage offline")
    with factory() as db:
        assert process_one(db, resources)
        document = db.get(Document, UUID(document_id))
        assert document.status == "deleting"
        job = db.scalar(select(IngestionJob).where(IngestionJob.kind == "delete"))
        assert job.status == "queued"
        job.available_at = now()
        db.commit()
    assert (
        client.post(
            "/api/v1/conversations", headers=headers, json={"document_ids": [document_id]}
        ).status_code
        == 404
    )
    resources.store = original
    with factory() as db:
        assert process_one(db, resources)
    assert client.get(f"/api/v1/documents/{document_id}", headers=headers).status_code == 404


def test_expired_worker_lease_recovery(stack, pdf):
    client, factory, resources = stack
    headers = authenticate(client)
    response = client.post(
        "/api/v1/documents", headers=headers, files={"file": ("report.pdf", pdf, "application/pdf")}
    )
    with factory() as db:
        job = db.scalar(select(IngestionJob))
        job.status = "running"
        job.attempts = 1
        job.available_at = now() - timedelta(minutes=1)
        db.commit()
        assert process_one(db, resources)
        assert db.get(IngestionJob, job.id).status == "succeeded"
        assert db.get(IngestionJob, job.id).attempts == 2
    assert (
        client.get(f"/api/v1/documents/{response.json()['id']}", headers=headers).json()["status"]
        == "ready"
    )


def test_filename_cannot_escape_object_namespace(stack, pdf):
    client, factory, _ = stack
    headers = authenticate(client)
    response = client.post(
        "/api/v1/documents",
        headers=headers,
        files={"file": ("../../private/report.pdf", pdf, "application/pdf")},
    )
    assert response.status_code == 202
    assert response.json()["filename"] == "report.pdf"
    with factory() as db:
        doc = db.get(Document, UUID(response.json()["id"]))
        assert doc.object_key == f"{doc.user_id}/{doc.id}.pdf"


def test_authentication_required_for_mutations(stack):
    client, _, _ = stack
    assert (
        client.post("/api/v1/conversations", json={"document_ids": [str(uuid4())]}).status_code
        == 401
    )
    assert client.delete(f"/api/v1/documents/{uuid4()}").status_code == 401
    assert (
        client.post(
            f"/api/v1/conversations/{uuid4()}/messages",
            json={"content": "question", "request_id": str(uuid4())},
        ).status_code
        == 401
    )
