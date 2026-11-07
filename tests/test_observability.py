import json
import logging
from uuid import UUID

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from sqlalchemy import select

from backend.app.core import telemetry
from backend.app.models.entities import IngestionJob
from tests.conftest import authenticate


def test_private_text_never_enters_traces_and_jobs_continue_trace(stack, monkeypatch, pdf):
    client, factory, resources = stack
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(telemetry, "_provider", provider)
    private = "PRIVATE_PROMPT_MUST_NOT_LEAK"
    with telemetry.operation("test.root", details={"prompt": private, "authorization": private}):
        root = telemetry.trace.get_current_span().get_span_context().trace_id
        headers = authenticate(client)
        response = client.post(
            "/api/v1/documents",
            headers=headers,
            files={"file": ("report.pdf", pdf, "application/pdf")},
        )
        identifier = response.json()["id"]
        with factory() as db:
            job = db.scalar(
                select(IngestionJob).where(IngestionJob.document_id == UUID(identifier))
            )
            assert job.trace_parent
        with pytest.raises(ValueError), telemetry.operation("test.error"):
            raise ValueError(private)
    from backend.app.workers.ingestion import process_one

    with factory() as db:
        assert process_one(db, resources, job.id)
    spans = exporter.get_finished_spans()
    serialized = json.dumps([dict(span.attributes) for span in spans])
    assert private not in serialized
    assert "report.pdf" not in serialized and "Alpha revenue" not in serialized
    assert any(s.name == "ingestion.job" and s.context.trace_id == root for s in spans)
    assert any(s.name == "ingestion.chunk" for s in spans)
    provider.shutdown()


def test_safe_logs_drop_messages_arguments_and_exception_text():
    record = logging.LogRecord(
        "provider", logging.ERROR, "private-path", 1, "key=%s", ("PRIVATE_SECRET",), None
    )
    encoded = telemetry.SafeJSON().format(record)
    assert "PRIVATE_SECRET" not in encoded and "private-path" not in encoded
    assert set(json.loads(encoded)) >= {
        "timestamp",
        "severity",
        "operation",
        "request_id",
        "trace_id",
    }


def test_correlation_and_metrics_use_route_templates(stack):
    client, _, _ = stack
    response = client.get("/api/v1/documents/00000000-0000-0000-0000-000000000000")
    UUID(response.headers["x-request-id"])
    metrics = client.get("/metrics")
    assert metrics.status_code == 200
    assert "smartrag_http_requests_total" in metrics.text
    assert "00000000-0000-0000-0000-000000000000" not in metrics.text


def test_export_failure_does_not_break_core_request(stack, monkeypatch):
    class BrokenExporter(InMemorySpanExporter):
        def export(self, spans):
            raise RuntimeError("PRIVATE_EXPORT_ERROR")

    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(BrokenExporter()))
    monkeypatch.setattr(telemetry, "_provider", provider)
    assert stack[0].get("/health/live").status_code == 200
    provider.shutdown()


def test_external_export_requires_explicit_consent_and_empty_prices_are_unavailable(stack):
    from pydantic import ValidationError

    from backend.app.core.config import get_settings

    settings_type = type(get_settings())
    settings = settings_type(llm_input_price_per_million="", llm_output_price_per_million="")
    assert settings.llm_input_price_per_million is None
    with pytest.raises(ValidationError):
        settings_type(langfuse_enabled=True, langfuse_export_consent=False)


def test_unexpected_error_keeps_safe_body_correlation_and_actual_status():
    from fastapi.testclient import TestClient

    from backend.app.core.telemetry_http import TelemetryHTTP

    async def crash(scope, receive, send):
        raise RuntimeError("PRIVATE_PROVIDER_SECRET")

    before = telemetry.REQUESTS.labels("GET", "unmatched", "503")._value.get()
    response = TestClient(TelemetryHTTP(crash)).get("/")
    assert response.status_code == 503
    assert response.headers["x-request-id"] == response.json()["request_id"]
    UUID(response.json()["request_id"])
    assert "PRIVATE_PROVIDER_SECRET" not in response.text
    assert telemetry.REQUESTS.labels("GET", "unmatched", "503")._value.get() == before + 1
