# Six-phase roadmap

## Phase 1 — Foundation and working MVP (current)

Implemented: empty-workspace audit, modular API/worker, secure multi-user auth,
digital-PDF upload/ingestion, configurable embeddings, tenant-scoped Qdrant retrieval,
Gemini answer adapter, page citations, persistent conversations, Streamlit, migrations,
Compose, locked dependencies, CI and automated tests. See `docs/validation.md` for
executed results and `docs/setup/local-development.md` for reproducible commands.

Local milestone identifier: `v0.1.0-mvp` on branch `main`, with commit message
`feat: establish SmartRAG Pro MVP`. Resolve the exact baseline with
`git rev-parse v0.1.0-mvp^{commit}`. Both automated modes pass 35 tests; see validation.

GitHub destination: **not supplied** (no remote existed at audit). Baseline push and
remote tag verification: **pending**, not claimed. Live Gemini acceptance: **pending**
the locally configured `GEMINI_API_KEY`. Local JWT/database/S3 credentials have been
generated in ignored `.env`; the local Compose application runs and readiness correctly
reports missing Gemini configuration. After the user supplies the repository URL and
local GitHub authentication, preserve remote history, push without force, verify branch
and tag hashes with `git ls-remote`, and record remote verification here on resume.

## Phase 2 — Rich document ingestion

OCR, image/table extraction, extraction quality tests, parsing isolation and ingestion
observability. Start only after Phase 1 acceptance and explicit user direction.

## Phase 3 — Conversational orchestration

LangGraph orchestration, contextual query rewriting, constrained memory and streaming.

## Phase 4 — Security, tenancy and reliability

Email verification/reset, refresh tokens, quotas, stronger database tenant constraints,
concurrency/load tests, least-privilege service identities and operational retries.

## Phase 5 — Retrieval quality and evaluation

Curated ground-truth datasets, citation entailment evaluation, hybrid search/reranking,
adversarial documents and cost/latency benchmarks.

## Phase 6 — Production operations

Deployment, TLS, monitoring/alerts, backups and restore drills, disaster recovery,
retention policies, dependency/security scanning and production acceptance gates.

Phases 3–6 are proposed scopes, subject to future user specifications. Do not start
them automatically. Phase 1 does not claim public production deployment readiness.
