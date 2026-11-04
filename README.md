# SmartRAG Pro

A multi-user digital-PDF assistant with page citations, private object storage,
durable background ingestion, and persistent chat. Phase 1 MVP.

FastAPI + Streamlit · PostgreSQL / SQLAlchemy / Alembic · Qdrant · Redis · S3
(SeaweedFS locally) · Gemini generation · configurable Google/OpenAI embeddings.

## Quick start

Requires Python 3.12, [uv](https://docs.astral.sh/uv/), Git, and Docker Desktop.

```powershell
uv sync --frozen --python 3.12
uv run python -m scripts.configure_local
```

The setup script generates unique local JWT/database/S3 credentials and preserves
existing configuration. Set `GEMINI_API_KEY` locally in `.env` using your key from
[Google AI Studio](https://aistudio.google.com/apikey).
Provider use may incur charges; never paste keys in chat or commit `.env`.

```powershell
docker compose up --build -d
```

Open http://localhost:8501, register, upload a text PDF, refresh its processing status,
select ready documents, create a chat, and ask a self-contained question. API docs:
http://localhost:8000/docs. Health: `/health/live` and `/health/ready`.
Logout revokes all sessions. Deleting a document also removes conversations using it.

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

This phase supports digital text, not OCR, images or advanced tables. Citation metadata
validates provenance, not factual entailment. Chat history is stored/displayed; contextual
follow-up rewriting is deferred. Public hosting requires the hardening listed in the
system design. Phase 2 does not start automatically.
