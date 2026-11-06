import os
from unittest.mock import Mock

import dramatiq
from dramatiq.brokers.redis import RedisBroker
from dramatiq.brokers.stub import StubBroker
from sqlalchemy import select

from backend.app.models.entities import IngestionJob
from tests.conftest import authenticate


def test_dispatcher_outbox_survives_duplicate_delivery(stack, pdf, monkeypatch):
    from backend.app.workers.dispatcher import dispatch_due
    from backend.app.workers.tasks import ingest_document

    client, _, _ = stack
    authenticate(client)
    send = Mock()
    monkeypatch.setattr(ingest_document, "send", send)
    # The durable test DB is used by the dispatcher; no broker credentials are logged.
    headers = {
        "Authorization": "Bearer "
        + client.post(
            "/api/v1/auth/login",
            json={"email": "alice@example.com", "password": "strong-test-password"},
        ).json()["access_token"]
    }
    client.post(
        "/api/v1/documents", headers=headers, files={"file": ("report.pdf", pdf, "application/pdf")}
    )
    _, factory, _ = stack
    with factory() as db:
        assert dispatch_due(db) == 1
        assert dispatch_due(db) == 0
        job = db.scalar(select(IngestionJob))
        assert job.status == "queued" and job.dispatched_at
    send.assert_called_once()


def test_actual_dramatiq_delivery(stack, pdf, monkeypatch):
    from backend.app.workers import tasks

    client, factory, resources = stack
    headers = authenticate(client)
    response = client.post(
        "/api/v1/documents", headers=headers, files={"file": ("report.pdf", pdf, "application/pdf")}
    )
    with factory() as db:
        identifier = str(db.scalar(select(IngestionJob.id)))
    broker = (
        RedisBroker(url=os.environ["TEST_REDIS_URL"], namespace="smartrag-delivery-test")
        if "TEST_REDIS_URL" in os.environ
        else StubBroker()
    )
    monkeypatch.setattr(tasks, "session_factory", lambda: factory)
    monkeypatch.setattr(tasks, "get_resources", lambda: resources)
    monkeypatch.setattr(tasks.ingest_document, "broker", broker)
    broker.declare_actor(tasks.ingest_document)
    worker = dramatiq.Worker(broker, worker_threads=1, worker_timeout=50)
    worker.start()
    try:
        tasks.ingest_document.send(identifier)
        broker.join("default", timeout=15000)
        worker.join()
        result = client.get(f"/api/v1/documents/{response.json()['id']}", headers=headers).json()
        assert result["status"] == "ready"
    finally:
        worker.stop(timeout=5000)
        broker.close()
