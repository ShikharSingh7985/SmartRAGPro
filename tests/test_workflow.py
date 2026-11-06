from io import BytesIO
from uuid import uuid4

import pytest
from pypdf import PdfWriter
from sqlalchemy import select

from backend.app.models.entities import IngestionJob, Message, now
from backend.app.rag.pdf import extract_chunks
from backend.app.workers.ingestion import process_one
from tests.conftest import authenticate, ingest


def new_conversation(client, headers, document_ids):
    response = client.post(
        "/api/v1/conversations",
        headers=headers,
        json={"title": "Revenue", "document_ids": document_ids},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_complete_workflow_and_idempotency(stack, pdf):
    client, factory, resources = stack
    headers = authenticate(client)
    document_id = ingest(stack, pdf, headers)
    conversation_id = new_conversation(client, headers, [document_id])
    request = {"content": "What is Alpha revenue?", "request_id": str(uuid4())}
    endpoint = f"/api/v1/conversations/{conversation_id}/messages"
    response = client.post(endpoint, headers=headers, json=request)
    assert response.status_code == 201, response.text
    reply = response.json()
    assert "42 million" in reply["content"]
    assert reply["citations"][0]["filename"] == "report.pdf"
    assert reply["citations"][0]["page"] == 1
    assert reply["citations"][0]["document_id"] == document_id
    assert client.post(endpoint, headers=headers, json=request).json()["id"] == reply["id"]
    messages = client.get(endpoint, headers=headers).json()
    assert [message["role"] for message in messages] == ["user", "assistant"]
    assert len(client.get("/api/v1/conversations", headers=headers).json()) == 1
    with factory() as db:
        assert len(list(db.scalars(select(Message)))) == 2
    resources._generator.answer.assert_called_once()


def test_two_user_isolation_and_deletion(stack, pdf):
    client, factory, resources = stack
    alice = authenticate(client)
    bob = authenticate(client, "bob@example.com")
    alice_doc = ingest(stack, pdf, alice)
    bob_doc = ingest(stack, pdf, bob)
    alice_chat = new_conversation(client, alice, [alice_doc])
    bob_chat = new_conversation(client, bob, [bob_doc])
    assert len(client.get("/api/v1/documents", headers=bob).json()) == 1
    for method in ["GET", "DELETE"]:
        assert (
            client.request(method, f"/api/v1/documents/{alice_doc}", headers=bob).status_code == 404
        )
    assert (
        client.post(
            "/api/v1/conversations", headers=bob, json={"document_ids": [alice_doc]}
        ).status_code
        == 404
    )
    endpoint = f"/api/v1/conversations/{alice_chat}/messages"
    assert client.get(endpoint, headers=bob).status_code == 404
    assert (
        client.post(
            endpoint, headers=bob, json={"content": "alpha revenue", "request_id": str(uuid4())}
        ).status_code
        == 404
    )
    response = client.post(
        endpoint, headers=alice, json={"content": "alpha revenue", "request_id": str(uuid4())}
    )
    assert {item["document_id"] for item in response.json()["citations"]} == {alice_doc}
    assert client.delete(f"/api/v1/documents/{alice_doc}", headers=alice).status_code == 202
    assert client.get(endpoint, headers=alice).status_code == 404
    with factory() as db:
        assert process_one(db, resources)
    assert client.get(f"/api/v1/documents/{alice_doc}", headers=alice).status_code == 404
    points = resources.qdrant.scroll(resources.settings.qdrant_collection, limit=100)[0]
    assert all(point.payload["document_id"] == bob_doc for point in points)
    assert client.get(f"/api/v1/conversations/{bob_chat}/messages", headers=bob).status_code == 200
    with factory() as db:
        assert not list(db.scalars(select(Message)))


def test_chunking_and_page_mapping(pdf):
    pages, chunks = extract_chunks(pdf)
    assert pages == 2
    assert [chunk.page for chunk in chunks] == [1, 2]
    assert "42 million" in chunks[0].text
    from reportlab.pdfgen.canvas import Canvas

    output = BytesIO()
    canvas = Canvas(output)
    canvas.drawString(72, 740, "Alpha revenue policy " * 200)
    canvas.save()
    pages, long_chunks = extract_chunks(output.getvalue())
    assert pages == 1 and len(long_chunks) > 1
    assert all(chunk.page == 1 and len(chunk.text) <= 1200 for chunk in long_chunks)


@pytest.mark.parametrize("data", [b"invalid", b"%PDF-broken"])
def test_bad_pdf(data):
    with pytest.raises(ValueError):
        extract_chunks(data)


def test_empty_encrypted_and_page_limit(pdf):
    writer = PdfWriter()
    writer.add_blank_page(width=600, height=800)
    output = BytesIO()
    writer.write(output)
    with pytest.raises(ValueError, match="No digital text"):
        extract_chunks(output.getvalue())
    writer.encrypt("test-password")
    output = BytesIO()
    writer.write(output)
    with pytest.raises(ValueError, match="Encrypted"):
        extract_chunks(output.getvalue())
    with pytest.raises(ValueError, match="pages"):
        extract_chunks(pdf, max_pages=1)


def test_upload_validation(stack):
    client, _, resources = stack
    headers = authenticate(client)
    assert (
        client.post(
            "/api/v1/documents",
            headers=headers,
            files={"file": ("x.txt", b"invalid", "text/plain")},
        ).status_code
        == 415
    )
    assert (
        client.post(
            "/api/v1/documents",
            headers=headers,
            files={"file": ("x.pdf", b"invalid", "application/pdf")},
        ).status_code
        == 422
    )
    resources.settings.max_upload_bytes = 1024
    assert (
        client.post(
            "/api/v1/documents",
            headers=headers,
            files={"file": ("x.pdf", b"%PDF-" + b"x" * 1024, "application/pdf")},
        ).status_code
        == 413
    )


def test_worker_failure_and_retry(stack, pdf):
    client, factory, resources = stack
    headers = authenticate(client)
    response = client.post(
        "/api/v1/documents",
        headers=headers,
        files={"file": ("report.pdf", pdf, "application/pdf")},
    )
    document_id = response.json()["id"]
    from unittest.mock import Mock

    resources.store = Mock(wraps=resources.store)
    resources.store.get.side_effect = RuntimeError("Temporary storage outage")
    for _ in range(3):
        with factory() as db:
            job = db.scalar(select(IngestionJob))
            job.available_at = now()
            db.commit()
            assert process_one(db, resources)
    assert (
        client.get(f"/api/v1/documents/{document_id}", headers=headers).json()["status"] == "failed"
    )


def test_provider_failure_rolls_back_and_bad_citations(stack, pdf):
    client, factory, resources = stack
    headers = authenticate(client)
    doc = ingest(stack, pdf, headers)
    chat = new_conversation(client, headers, [doc])
    endpoint = f"/api/v1/conversations/{chat}/messages"
    resources._generator.answer.side_effect = RuntimeError("private provider error")
    response = client.post(
        endpoint, headers=headers, json={"content": "alpha revenue", "request_id": str(uuid4())}
    )
    assert response.status_code == 503
    assert "private" not in response.text
    resources._generator.answer.side_effect = None
    resources._generator.answer.return_value = "Unsupported claim [999]"
    assert (
        client.post(
            endpoint, headers=headers, json={"content": "alpha revenue", "request_id": str(uuid4())}
        ).status_code
        == 502
    )
    with factory() as db:
        assert not list(db.scalars(select(Message)))


def test_no_evidence_abstains(stack, pdf):
    client, _, resources = stack
    headers = authenticate(client)
    doc = ingest(stack, pdf, headers)
    chat = new_conversation(client, headers, [doc])
    response = client.post(
        f"/api/v1/conversations/{chat}/messages",
        headers=headers,
        json={"content": "unrelated question", "request_id": str(uuid4())},
    )
    assert response.status_code == 201
    assert response.json()["citations"] == []
    assert "don't know" in response.json()["content"]
    resources._generator.answer.assert_not_called()
