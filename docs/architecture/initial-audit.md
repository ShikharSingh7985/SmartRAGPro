# Initial repository audit

Audit date: 2026-11-04 (Asia/Calcutta). Workspace: `SmartRAGpro`.

## Evidence before modifications

- `Get-ChildItem -Force -Recurse` and `rg --files --hidden` found an empty directory.
- No source, README, requirements, tests, generated files, local engineering instructions,
  credentials, architecture, or reusable RAG implementation existed.
- `git status`, `git branch`, `git remote -v`, and `git log` each reported no Git repository.
  There was no commit history, remote, branch, or CI to preserve.
- Python 3.12 is installed (Anaconda reports 3.12.7; standalone interpreter is 3.12.5).
  `uv`, Git 2.51.0 and Docker 28.3.2 are installed. Docker daemon and package downloads
  require execution authorization in this workspace.

## Decisions

Create a modular Python monolith and separate PostgreSQL-backed worker. Use FastAPI,
Streamlit, SQLAlchemy 2, Alembic, Argon2id, JWT, Qdrant, Redis and S3. Keep production
providers real; deterministic doubles exist only in tests. Use LangChain's provider
adapters and splitter without pulling in an unnecessary agent framework. LangGraph
orchestration is deferred until conversation semantics require it in Phase 3.

The initially selected MinIO Docker image could not be pulled. Upstream is archived.
Use maintained SeaweedFS 4.52 for local S3 instead (ADR 0004). This preserves the
S3 interface and supports managed S3 or an existing maintained MinIO installation.

No previous code or Git history was discarded. Git will be initialized on `main`.
No intended GitHub repository can be inferred from an empty workspace. A user-supplied
repository URL is required before adding a remote and pushing.

## Risks found during implementation

External service failure requires durable upload compensation, idempotent indexing,
retryable cleanup, and fail-closed authorization. Generated answers can retain source
content, so deletion removes affected conversation messages as well as vectors/PDFs.
RAG source references validate provenance, not semantic truth; live quality evaluation
and adversarial document testing remain later work.
