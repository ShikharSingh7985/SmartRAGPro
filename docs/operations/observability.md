# Monitoring and tracing

Run `uv run python -m scripts.configure_security`, then:

```powershell
docker compose -f docker-compose.yml -f docker-compose.observability.yml up -d --build
```

Grafana: http://localhost:3000, user `admin`, password in ignored
`.docker-local/grafana-password`. Prometheus: http://localhost:9090. The provisioned
SmartRAG dashboard uses real counters and histograms; Explore → Tempo searches traces.
Collector, Tempo, worker metrics and dispatcher metrics have no published ports.
Keep `/metrics` and all monitoring endpoints private behind an authenticated network
in hosted environments. These interfaces contain operational metadata.

The API supplies generated `X-Request-ID` values. JSON logs contain timestamp,
severity, service, request/trace ID, operation, safe metadata and error category.
Free-form library messages, formatting arguments, SQL text, tracebacks and exception
strings are deliberately omitted. Debug failures using the operation/category and
correlated stage traces. Do not enable SDK HTTP debugging for private workloads.

Spans cover API requests, SQL timing without statements, storage operations, PDF
inspection/extraction, OCR, chunking, embedding batches/queries, lexical/vector search,
reranking, graph nodes, guardrails, generation and citations. SQL outbox traceparent
links API upload to worker execution. No user/document identifiers or text are exported.
The local overlay samples every trace for acceptance; ordinary configuration samples
10%. Prometheus counters are unsampled. Export queues are bounded to 512 spans per
processor; unavailable telemetry drops traces without failing chat.

Prometheus stores seven days with a 1 GB cap; local Tempo retention is 24 hours.
Retention is not a substitute for disk monitoring. The dashboard includes HTTP
count/errors/latency, auth/rate-limit responses, active requests, stage timings,
tokens, configured cost, cache outcomes, guardrails, SQL job states, page strategies,
storage counters, process RSS/CPU/start time, dependency probes and heartbeats.
Histogram p99 is an estimate and is unreliable for tiny samples. SQL storage gauges
are not physical bucket/disk inventory. Heartbeat proves process activity, not that
every job is making progress; inspect SQL leases and failed jobs too.

Alert rules cover unavailable scrape targets, stale worker heartbeat and ingestion
failures. Configure an Alertmanager receiver and incident ownership before production;
the repository does not send notifications. Host disk, container restarts, managed
database saturation and cloud billing require platform monitoring beyond this stack.

Langfuse is optional. Obtain an account or run a supported self-hosted instance,
review data processing and possible paid usage, then set `LANGFUSE_ENDPOINT`,
`LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_EXPORT_CONSENT=true` and
`LANGFUSE_ENABLED=true` in local ignored configuration. Run configure_security again
and restart API/worker. Never paste keys in chat. External export also requires
`TELEMETRY_ENABLED=true`. This integration exports model identity, prompt version,
latency, usage and bounded decisions only; source text capture is not implemented.
Live hosted Langfuse delivery remains NOT VERIFIED until credentials are supplied.
Prices in `LLM_INPUT_PRICE_PER_MILLION` and `LLM_OUTPUT_PRICE_PER_MILLION` must match
the selected provider/model/tier; empty values intentionally hide cost estimates.
