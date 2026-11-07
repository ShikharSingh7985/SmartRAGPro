"""Content-free telemetry. Never instrument SDK bodies, headers, SQL text or exceptions."""

import base64
import contextvars
import functools
import json
import logging
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any, ParamSpec, TypeVar
from uuid import uuid4

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
from prometheus_client import Counter, Gauge, Histogram, start_http_server

from backend.app.core.config import Settings

REQUESTS = Counter("smartrag_http_requests_total", "HTTP responses", ["method", "route", "status"])
HTTP_SECONDS = Histogram(
    "smartrag_http_seconds",
    "HTTP latency",
    ["method", "route"],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30, 60, 180),
)
ACTIVE = Gauge("smartrag_http_active", "Active API requests")
STAGES = Histogram(
    "smartrag_operation_seconds",
    "Stage duration",
    ["operation", "outcome"],
    buckets=(0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1, 2, 5, 15, 60, 180, 600),
)
EVENTS = Counter("smartrag_events_total", "Bounded operational events", ["operation", "outcome"])
TOKENS = Counter("smartrag_llm_tokens_total", "Provider-reported tokens", ["direction"])
COST = Counter("smartrag_llm_estimated_usd_total", "Configured price estimate, not billing")
COST_CONFIGURED = Gauge("smartrag_cost_configured", "Both token prices configured")
QUEUE = Gauge("smartrag_jobs", "Durable SQL job counts", ["status"])
PAGES = Counter("smartrag_pages_total", "Pages processed", ["method"])
STORAGE = Gauge("smartrag_storage_bytes", "SQL-recorded bytes, not bucket inventory", ["kind"])
HEARTBEAT = Gauge("smartrag_heartbeat_timestamp", "Last successful service heartbeat", ["service"])
DEPENDENCY = Gauge("smartrag_dependency_up", "Dependency connectivity", ["dependency"])
VALUES = Histogram(
    "smartrag_rag_values",
    "Non-content RAG counts",
    ["kind"],
    buckets=(0, 1, 2, 4, 8, 16, 32, 64, 128, 512, 2048, 8192),
)

request_id: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="")
_provider: TracerProvider | None = None
_configured = False
_service = "smartrag"
_metrics_server: Any = None
P = ParamSpec("P")
T = TypeVar("T")
ALLOWED = {
    "http.route",
    "http.request.method",
    "http.response.status_code",
    "operation",
    "outcome",
    "error.category",
    "retryable",
    "retry.attempt",
    "count",
    "pages",
    "cache.hit",
    "prompt.version",
    "gen_ai.request.model",
    "gen_ai.provider.name",
    "gen_ai.usage.input_tokens",
    "gen_ai.usage.output_tokens",
    "request.id",
    "langfuse.observation.type",
    "langfuse.observation.model",
    "langfuse.observation.usage_details",
    "langfuse.observation.cost_details",
    "guardrail.decision",
    "db.system.name",
    "db.operation.name",
}


def attributes(values: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in values.items()
        if key in ALLOWED
        and isinstance(value, (str, int, float, bool))
        and (not isinstance(value, str) or len(value) <= 200)
    }


class SafeJSON(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        # Do not format arbitrary library messages or exception strings, even on errors.
        context = trace.get_current_span().get_span_context()
        return json.dumps(
            {
                "timestamp": datetime.now(UTC).isoformat(),
                "severity": record.levelname,
                "service": _service,
                "request_id": request_id.get(),
                "trace_id": f"{context.trace_id:032x}" if context.is_valid else None,
                "operation": getattr(record, "operation", "runtime"),
                "error_category": type(record.exc_info[1]).__name__ if record.exc_info else None,
                "logger": record.name,
                "metadata": attributes(getattr(record, "safe_metadata", {})),
            }
        )


def configure(settings: Settings) -> None:
    global _provider, _configured, _service
    if _configured:
        return
    _configured = True
    _service = "smartrag-" + settings.service_role
    COST_CONFIGURED.set(
        int(
            settings.llm_input_price_per_million is not None
            and settings.llm_output_price_per_million is not None
        )
    )
    handler = logging.StreamHandler()
    handler.setFormatter(SafeJSON())
    logging.getLogger().handlers = [handler]
    logging.getLogger().setLevel(logging.INFO)
    for name in ("uvicorn.error", "uvicorn.access"):
        logging.getLogger(name).handlers = [handler]
        logging.getLogger(name).propagate = False
    if not settings.telemetry_enabled:
        return
    try:
        _provider = TracerProvider(
            resource=Resource({"service.name": _service}),
            sampler=ParentBased(TraceIdRatioBased(settings.telemetry_sample_ratio)),
        )
        exporters = [OTLPSpanExporter(endpoint=settings.telemetry_endpoint, timeout=2)]
        if settings.langfuse_enabled:
            credential = base64.b64encode(
                (
                    settings.langfuse_public_key.get_secret_value()
                    + ":"
                    + settings.langfuse_secret_key.get_secret_value()
                ).encode()
            ).decode()
            exporters.append(
                OTLPSpanExporter(
                    endpoint=settings.langfuse_endpoint,
                    timeout=2,
                    headers={"Authorization": "Basic " + credential},
                )
            )
        for exporter in exporters:
            _provider.add_span_processor(
                BatchSpanProcessor(
                    exporter,
                    max_queue_size=512,
                    max_export_batch_size=64,
                    schedule_delay_millis=1000,
                    export_timeout_millis=2000,
                )
            )
    except Exception:
        _provider = None
        logging.getLogger(__name__).warning(
            "telemetry unavailable", extra={"operation": "telemetry.setup"}
        )


def shutdown() -> None:
    if _provider is not None:
        try:
            _provider.force_flush(timeout_millis=2000)
            _provider.shutdown()
        except Exception:
            pass


def trace_parent() -> str | None:
    carrier: dict[str, str] = {}
    TraceContextTextMapPropagator().inject(carrier)
    return carrier.get("traceparent")


@contextmanager
def operation(
    name: str, *, parent: str | None = None, details: dict[str, Any] | None = None
) -> Iterator[Any]:
    tracer = _provider.get_tracer("smartrag") if _provider else trace.get_tracer("smartrag")
    context = TraceContextTextMapPropagator().extract({"traceparent": parent}) if parent else None
    started = time.perf_counter()
    outcome = "success"
    with tracer.start_as_current_span(
        name,
        context=context,
        attributes=attributes(details or {}),
        record_exception=False,
        set_status_on_exception=False,
    ) as span:
        try:
            yield span
        except BaseException as exc:
            outcome = "error"
            span.set_attribute("error.category", type(exc).__name__)
            span.set_status(trace.StatusCode.ERROR)
            logging.getLogger(__name__).warning(
                "operation failed",
                extra={"operation": name, "safe_metadata": {"error.category": type(exc).__name__}},
            )
            raise
        finally:
            STAGES.labels(name, outcome).observe(time.perf_counter() - started)
            span.set_attribute("outcome", outcome)


def observed(name: str) -> Callable[[Callable[P, T]], Callable[P, T]]:
    def decorate(function: Callable[P, T]) -> Callable[P, T]:
        @functools.wraps(function)
        def wrapped(*args: P.args, **kwargs: P.kwargs) -> T:
            with operation(name):
                return function(*args, **kwargs)

        return wrapped

    return decorate


def start_metrics(settings: Settings) -> None:
    global _metrics_server
    if settings.metrics_enabled and _metrics_server is None:
        try:
            _metrics_server = start_http_server(settings.metrics_port)
        except OSError:
            logging.getLogger(__name__).warning(
                "metrics unavailable", extra={"operation": "metrics.setup"}
            )


def new_request() -> str:
    return str(uuid4())
