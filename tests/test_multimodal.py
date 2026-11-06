import json
import shutil
from unittest.mock import Mock
from uuid import uuid4

import pytest
from sqlalchemy import select

from backend.app.models.entities import DocumentAsset, IngestionJob, PageExtraction
from backend.app.rag.extraction import extract_pages, text_quality
from backend.app.rag.types import structured_chunks
from backend.app.workers.ingestion import process_one
from scripts.pdf_fixtures import synthetic_pdf
from tests.conftest import authenticate, ingest


def test_table_structure_and_page_provenance(stack, tmp_path):
    _, _, resources = stack
    source = tmp_path / "table.pdf"
    source.write_bytes(synthetic_pdf("table"))
    pages = list(extract_pages(source, resources.settings, "text-first"))
    tables = [element for element in pages[0].elements if element.kind == "table"]
    assert tables and tables[0].page == 1
    serialized = json.dumps(tables[0].data)
    assert "Model B" in serialized and "94" in serialized and "Accuracy" in serialized
    chunks = structured_chunks(tables, resources.settings)
    assert all("Headers:" in chunk.text for chunk in chunks)
    assert any("Model B" in chunk.text and "94" in chunk.text for chunk in chunks)


def test_dedup_and_reindex_reuses_embeddings(stack, pdf):
    client, factory, resources = stack
    headers = authenticate(client)
    resources._embedding = Mock(wraps=resources._embedding)
    identifier = ingest(stack, pdf, headers)
    before = resources._embedding.embed_documents.call_count
    repeated = client.post(
        "/api/v1/documents",
        headers=headers,
        files={"file": ("duplicate.pdf", pdf, "application/pdf")},
    )
    assert repeated.json()["id"] == identifier
    assert (
        client.post(f"/api/v1/documents/{identifier}/reindex", headers=headers).status_code == 202
    )
    with factory() as db:
        assert process_one(db, resources)
    assert resources._embedding.embed_documents.call_count == before
    document = client.get(f"/api/v1/documents/{identifier}", headers=headers).json()
    assert document["status"] == "ready" and document["chunk_count"] > 0


def test_cancel_retry_and_job_progress(stack, pdf):
    client, factory, resources = stack
    headers = authenticate(client)
    response = client.post(
        "/api/v1/documents", headers=headers, files={"file": ("report.pdf", pdf, "application/pdf")}
    )
    identifier = response.json()["id"]
    assert client.post(f"/api/v1/documents/{identifier}/cancel", headers=headers).status_code == 202
    with factory() as db:
        assert process_one(db, resources)
    jobs = client.get(f"/api/v1/documents/{identifier}/jobs", headers=headers).json()
    assert jobs[0]["stage"] == "cancelled"
    assert client.post(f"/api/v1/documents/{identifier}/retry", headers=headers).status_code == 202
    with factory() as db:
        assert process_one(db, resources)
    job = client.get(f"/api/v1/documents/{identifier}/jobs", headers=headers).json()[0]
    assert job["stage"] == "completed" and job["pages_processed"] == job["total_pages"] == 2


def test_figure_assets_preview_isolation_and_cleanup(stack):
    client, factory, resources = stack
    headers = authenticate(client)
    other = authenticate(client, "bob@example.com")
    identifier = ingest(stack, synthetic_pdf("figure"), headers)
    assets = client.get(f"/api/v1/documents/{identifier}/assets", headers=headers).json()
    assert assets and assets[0]["page"] == 1
    endpoint = f"/api/v1/documents/{identifier}/assets/{assets[0]['id']}"
    assert client.get(endpoint, headers=headers).headers["content-type"] == "image/png"
    assert client.get(endpoint, headers=other).status_code == 404
    assert (
        client.get(f"/api/v1/documents/{identifier}/preview/1", headers=headers).status_code == 200
    )
    assert client.get(f"/api/v1/documents/{identifier}/preview/1", headers=other).status_code == 404
    page = client.get(f"/api/v1/documents/{identifier}/pages/1", headers=headers).json()
    assert page["strategy"] == "pymupdf"
    client.delete(f"/api/v1/documents/{identifier}", headers=headers)
    assert client.get(endpoint, headers=headers).status_code == 409
    with factory() as db:
        assert process_one(db, resources)
        assert not list(db.scalars(select(DocumentAsset)))
        assert not list(db.scalars(select(PageExtraction)))


@pytest.mark.parametrize("kind,pages", [("scan", 1), ("mixed", 2)])
def test_real_selective_tesseract_ocr(stack, tmp_path, kind, pages):
    _, _, resources = stack
    if not shutil.which(resources.settings.tesseract_cmd):
        pytest.skip("Tesseract is required; Docker test image includes it")
    source = tmp_path / "scan.pdf"
    source.write_bytes(synthetic_pdf(kind))
    results = list(extract_pages(source, resources.settings, "auto"))
    assert len(results) == pages
    text = " ".join(element.text for page in results for element in page.elements)
    assert "42" in text and "REVENUE" in text.upper()
    assert results[-1].strategy == "tesseract"
    assert "ocr_mean_word_confidence" in results[-1].quality
    if kind == "mixed":
        assert results[0].strategy == "pymupdf"


def test_two_column_order_and_furniture(stack, tmp_path):
    _, _, resources = stack
    source = tmp_path / "columns.pdf"
    source.write_bytes(synthetic_pdf("columns", pages=4))
    result = list(extract_pages(source, resources.settings, "text-first"))[0]
    text = "\n".join(element.text for element in result.elements)
    assert "Left column" in text and "Right column" in text
    assert "SYNTHETIC RESEARCH BOOK" not in text


def test_invalid_pdf_terminal_failure(stack):
    client, factory, resources = stack
    headers = authenticate(client)
    response = client.post(
        "/api/v1/documents",
        headers=headers,
        files={"file": ("bad.pdf", b"%PDF-broken", "application/pdf")},
    )
    with factory() as db:
        assert process_one(db, resources)
        job = db.scalar(select(IngestionJob))
        assert job.status == "failed" and not job.retryable and job.attempts == 1
    assert (
        client.get(f"/api/v1/documents/{response.json()['id']}", headers=headers).json()["status"]
        == "failed"
    )


def test_embedding_space_change_rejected(stack, pdf):
    client, _, resources = stack
    headers = authenticate(client)
    identifier = ingest(stack, pdf, headers)
    resources.settings.embedding_version = "incompatible-v2"
    from backend.app.rag.vectors import ensure_collection

    with pytest.raises(ValueError, match="Embedding space mismatch"):
        ensure_collection(resources)
    assert (
        client.get(f"/api/v1/documents/{identifier}", headers=headers).json()["status"] == "ready"
    )


def test_no_fabricated_quality_confidence():
    quality = text_quality("A sufficient amount of useful digital text for extraction.")
    assert quality["usable_text"]
    assert not any("confidence" in name for name in quality)


def test_table_question_receives_headers_values_and_citation(stack):
    client, _, resources = stack
    headers = authenticate(client)
    identifier = ingest(stack, synthetic_pdf("table"), headers)
    conversation = client.post(
        "/api/v1/conversations", headers=headers, json={"document_ids": [identifier]}
    ).json()["id"]
    resources._generator.answer.return_value = "Model B has accuracy 94 percent in Table 3. [1]"
    response = client.post(
        f"/api/v1/conversations/{conversation}/messages",
        headers=headers,
        json={"content": "What is model B accuracy in Table 3?", "request_id": str(uuid4())},
    )
    assert response.status_code == 201
    citations = response.json()["citations"]
    assert citations[0]["content_type"] == "table" and citations[0]["page"] == 1
    assert "94" in citations[0]["excerpt"] and "Accuracy" in citations[0]["excerpt"]
    context = resources._generator.answer.call_args.args[1]
    assert "Table 3" in context and "Model B" in context


@pytest.mark.parametrize(
    "enabled,mode,expected",
    [
        (True, "auto", False),
        (False, "enhanced-multimodal", False),
        (True, "enhanced-multimodal", True),
    ],
)
def test_vision_requires_explicit_mode_and_flag(stack, tmp_path, enabled, mode, expected):
    _, _, resources = stack
    source = tmp_path / "figure.pdf"
    source.write_bytes(synthetic_pdf("figure"))
    settings = resources.settings.model_copy(update={"vision_enabled": enabled})
    vision = Mock(return_value="Synthetic model-derived chart description; values uncertain.")
    results = list(extract_pages(source, settings, mode, vision=vision))
    figures = [
        element for result in results for element in result.elements if element.kind == "figure"
    ]
    assert figures and all(element.model_derived == expected for element in figures)
    assert vision.called == expected
