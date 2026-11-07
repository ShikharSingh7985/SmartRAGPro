from pathlib import Path

from sqlalchemy import select
from streamlit.testing.v1 import AppTest

from backend.app.models.entities import Document, IngestionJob
from backend.app.workers.ingestion import process_one
from tests.conftest import authenticate


def test_streamlit_login_navigation_and_logout(stack, monkeypatch):
    client, _, _ = stack
    authenticate(client)

    def request(method, url, **kwargs):
        kwargs.pop("timeout", None)
        path = "/api/v1" + url.split("/api/v1", 1)[1]
        return client.request(method, path, **kwargs)

    monkeypatch.setattr("httpx.request", request)
    app = AppTest.from_file(str(Path("frontend/app.py").resolve()), default_timeout=20).run()
    assert not app.exception
    app.text_input[0].set_value("alice@example.com")
    app.text_input[1].set_value("strong-test-password")
    app.button[0].click().run()
    assert not app.exception
    assert any(title.value == "Ask your documents" for title in app.title)
    app.radio[0].set_value("Documents").run()
    assert any(title.value == "Your documents" for title in app.title)
    assert not app.exception
    next(button for button in app.button if button.label == "Log out").click().run()
    assert not app.exception
    assert app.title[0].value == "SmartRAG Pro"
    assert "token" not in app.session_state


def test_document_progress_refreshes_from_authenticated_api(stack, monkeypatch, pdf):
    import streamlit

    client, factory, resources = stack
    headers = authenticate(client)
    upload = client.post(
        "/api/v1/documents",
        headers=headers,
        files={"file": ("progress.pdf", pdf, "application/pdf")},
    )
    identifier = upload.json()["id"]
    intervals = []
    requests_seen = []
    original_fragment = streamlit.fragment

    def fragment(*args, **kwargs):
        intervals.append(kwargs.get("run_every"))
        return original_fragment(*args, **kwargs)

    def request(method, url, **kwargs):
        kwargs.pop("timeout", None)
        path = "/api/v1" + url.split("/api/v1", 1)[1]
        requests_seen.append(path)
        return client.request(method, path, **kwargs)

    monkeypatch.setattr("httpx.request", request)
    monkeypatch.setattr(streamlit, "fragment", fragment)
    app = AppTest.from_file(str(Path("frontend/app.py").resolve()), default_timeout=20).run()
    app.text_input[0].set_value("alice@example.com")
    app.text_input[1].set_value("strong-test-password")
    app.button[0].click().run()
    app.radio[0].set_value("Documents").run()
    assert not app.exception
    assert "15s" in intervals
    assert any("Queued" in caption.value for caption in app.caption)

    with factory() as db:
        job = db.scalar(select(IngestionJob))
        document = db.get(Document, job.document_id)
        document.page_count = job.total_pages = 2
        job.status, job.stage, job.attempts, job.pages_processed = "running", "extracting", 1, 1
        db.commit()
    app.run()
    assert not app.exception
    assert any("Processing" in caption.value for caption in app.caption), [
        caption.value for caption in app.caption
    ]
    assert any("1/2 pages" in progress.proto.text for progress in app.get("progress"))

    with factory() as db:
        assert process_one(db, resources)
    app.run()
    assert not app.exception
    assert any("Ready" in caption.value for caption in app.caption)
    assert not app.get("progress")
    assert (
        client.get(f"/api/v1/documents/{identifier}", headers=headers).json()["status"] == "ready"
    )
    next(button for button in app.button if button.label == "Load page").click().run()
    assert not app.exception
    preview = f"/api/v1/documents/{identifier}/preview/1"
    first_load = requests_seen.count(preview)
    assert first_load > 0
    app.run()
    assert not app.exception
    assert requests_seen.count(preview) == first_load + 1
