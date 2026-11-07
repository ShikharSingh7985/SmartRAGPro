# SmartRAG Pro

A multi-user PDF assistant with page citations, private object storage,
durable background ingestion, and persistent context-aware chat, with measured retrieval alternatives.

FastAPI + Streamlit · PostgreSQL / SQLAlchemy / Alembic · Qdrant · Redis · S3
(SeaweedFS locally) · Gemini generation · configurable Google/OpenAI embeddings.

## Quick start

Requires Python 3.12, [uv](https://docs.astral.sh/uv/), Git, and Docker Desktop.
For an existing `.env`, preserve it and skip `configure_local`.

```powershell
uv sync --frozen --python 3.12
uv run python -m scripts.configure_local
```

The setup script generates unique local JWT/database/S3 credentials and preserves
existing configuration. Set `GEMINI_API_KEY` locally in `.env` using your key from
[Google AI Studio](https://aistudio.google.com/apikey).
Provider use may incur charges; never paste keys in chat or commit `.env`.

```powershell
uv run python -m scripts.configure_security
docker compose up --build -d
```

Open http://localhost:8501, register, upload a text PDF, refresh its processing status,
select ready documents, create a chat, and ask questions and follow-ups. Saved chats
restore their document selection and context after login or restart. API docs:
http://localhost:8000/docs. Health: `/health/live` and `/health/ready`.
Logout revokes all sessions. Deleting a source clears derived history and checkpoints
while preserving conversation shells for recovery with available documents.

## Verify without API keys

```powershell
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest
./scripts/test_services.ps1
```

Default tests use isolated SQLite and test doubles; the service script uses real
PostgreSQL, Qdrant, Redis and S3 with deterministic model/embedding doubles. Live Gemini
checks are separate and must never be represented as covered by mocked tests.
Use `./scripts/test_services.ps1 -Stop` to stop disposable services.

See [full setup](docs/setup/local-development.md), [system design](docs/architecture/system-design.md),
[database design](docs/architecture/database-design.md), [data flow](docs/architecture/data-flow.md),
[initial audit](docs/architecture/initial-audit.md), [decisions](docs/architecture/adr/),
[validation evidence](docs/validation.md), and [roadmap / GitHub milestone](docs/roadmap.md).

The local S3 server uses SeaweedFS because the attempted MinIO image is unavailable
and upstream is archived; [ADR 0004](docs/architecture/adr/0004-local-object-storage.md)
records the evidence. The adapter also supports existing MinIO/S3 endpoints.

Phase 2 adds Docling structure, selective Tesseract OCR, table JSON, secure figure
assets/previews, optional Gemini vision, progress/cancel/retry, deduplication and
versioned reindexing. See [Phase 2 operation](docs/setup/phase2-ingestion.md) and
[Phase 2 evidence and limitations](docs/phase2-validation.md).

Phase 3 adds a deterministic LangGraph, transactional PostgreSQL checkpoints,
incremental bounded summaries, distant-turn recall, contextual rewriting and verified
scoped citations. Rename, change selected PDFs, export or delete saved conversations
from Streamlit. See [conversation architecture](docs/architecture/conversations.md),
[setup and API](docs/setup/conversations.md), and [Phase 3 validation](docs/phase3-validation.md).
Responses appear after source verification; live token streaming is not enabled.

The user-revised Phase 4 adds tenant-scoped persistent BM25, weighted rank fusion,
bounded optional reranking and a query-vector cache. Validation retained dense as
default; the synthetic held-out experiment did not justify replacing it. See
[evaluation commands and label review](evaluation/README.md),
[measured comparison](docs/benchmarks/retrieval-comparison.md),
[latency/memory](docs/benchmarks/latency-and-memory.md) and
[methodology/limits](docs/benchmarks/evaluation-methodology.md).

New uploads populate the SQL lexical index. After upgrading, existing ready documents
can be indexed without new embedding calls:

```powershell
docker compose exec api python -m scripts.backfill_lexical
```

Run migrations/bootstrap first. `RETRIEVAL_MODE=dense|bm25|hybrid|hybrid_rerank` and
other bounded retrieval settings are documented in `.env.example`; restart API after
environment changes. Incomplete lexical indexes fall back to dense with explicit
internal telemetry. Never change embedding model/dimensions in the same vector index.

Citation metadata validates provenance, not factual entailment. Persistent bounded-context
follow-ups are implemented. Public hosting still requires the deployment gates in the
security report and final release checklist.

## Security hardening (Phase 5)

After configuring `.env`, run `uv run python -m scripts.configure_security` before
`docker compose up -d --build`. This preserves provider settings and creates ignored
role-specific environments, database runtime credentials, Redis authentication and
Qdrant read/write keys. Rerun the helper after changing `.env`.

Sessions now use rotating refresh tokens; existing access tokens require a new login.
Streamlit refreshes server-side and supports password change/account deletion. PDF
previews are worker-generated; reindex older documents to create previews. Content
inspection can quarantine suspicious pages; owner-authorized reasons are available at
`GET /api/v1/documents/{id}/security`. Security heuristics do not prove safety.

See [local hardening and validation](docs/security/local-hardening.md),
[threat model](docs/security/threat-model.md), [authentication](docs/security/authentication.md),
[authorization](docs/security/authorization.md) and [adversarial results](docs/security/adversarial-test-report.md).

## Operations and release validation (Phase 6)

The integrated application adds content-free OpenTelemetry spans, correlated JSON
logs, Prometheus metrics, a provisioned Grafana dashboard and local Tempo tracing.
SQL job trace context survives the API/worker boundary. Bounded model retries,
worker heartbeats, finite cleanup retries and an operator recovery command improve
outage handling. `/health/live` includes a package version and source fingerprint.

```powershell
uv run python -m scripts.configure_security
docker compose -f docker-compose.yml -f docker-compose.observability.yml up -d --build
```

Grafana: http://localhost:3000 (`admin`; generated password in ignored
`.docker-local/grafana-password`). Prometheus: http://localhost:9090. Monitoring and
infrastructure endpoints must stay private in hosted deployments. External Langfuse
export is disabled by default and requires explicit consent plus locally configured
credentials. No prompt/PDF content capture is enabled. Token counts come from the
provider; estimated cost is unavailable until operator-verified prices are supplied.

See [final architecture](docs/architecture/final-review.md),
[monitoring](docs/operations/observability.md), [recovery/backups](docs/operations/recovery.md),
[cloud deployment guide](docs/deployment/cloud.md),
[reproducible acceptance/load commands](evaluation/release/README.md),
[final engineering report](docs/benchmarks/final-report.md),
[release checklist](docs/release/readiness.md) and
[resume description](docs/resume/project-description.md).

The final report distinguishes native tests, disposable real-service tests,
synthetic concurrent clients and live Gemini acceptance. Historical retrieval
metrics use synthetic unreviewed relevance labels; they are not production accuracy.
Responses are published only after citation verification, so token streaming and
time-to-first-token metrics remain unavailable. Public cloud deployment, hosted
tracing and production-scale certification are not claimed.
