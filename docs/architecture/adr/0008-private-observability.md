# Content-free operational telemetry (Phase 6)

Phase 6 keeps the modular monolith, PostgreSQL transaction boundary and separate
Redis/Dramatiq worker. It adds manual OpenTelemetry spans instead of automatic SDK,
SQL or HTTP-client capture: private prompts, bind parameters, PDF text, object keys,
headers, identifiers and provider exception strings never enter telemetry attributes.
An allowlist bounds attributes; metric labels use route templates and operation enums.
W3C trace context is stored with the durable SQL outbox job, then restored in the
worker. A job remains recoverable without an active trace or available exporter.

Prometheus and local Tempo/Grafana are optional Compose services. Async bounded OTLP
queues may drop traces under pressure; core requests do not wait for delivery.
Langfuse receives the same metadata-only spans through its supported OTLP endpoint,
without a second orchestration SDK. Export is disabled unless two explicit flags
and credentials are configured. Hosted delivery is not verified without that service.
No LangSmith prompt capture or third-party tracing callback is enabled.

Live acceptance exposed an overly broad abstention on a partly answerable follow-up:
the source described early stopping but supplied no example. Generation prompt v3
asks for the supported explanation while stating which details are absent; it does
not authorize invented examples. Grouped numeric citations are normalized before
verification so every listed source is checked, and all source markers are removed
from ordinal-reference memory. Unknown grouped source IDs fail before persistence.

Provider-reported token counts are recorded when available. Cost is unavailable
unless both operator-verified per-million prices are configured. Token estimates
used for context management are not billing measurements. No streaming is introduced:
citation verification precedes publishing an answer, so TTFT is unavailable.

Cleanup retries now have the same finite attempt budget as ingestion. Exhaustion
preserves an inaccessible deleting document and a failed recoverable job. The trusted
operator command requeues cleanup; it does not expose an administrative HTTP endpoint.

References: [OTel Python](https://opentelemetry.io/docs/languages/python/instrumentation/),
[Langfuse OTLP](https://langfuse.com/integrations/native/opentelemetry),
[Tempo configuration](https://grafana.com/docs/tempo/latest/configuration/).
