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

GitHub milestone verified on 2026-11-04:

- Repository: https://github.com/ShikharSingh7985/SmartRAGPro
- Remote: `origin`; branch: `main`.
- Baseline commit: `82f41c6098fe14e20ee5a3109665e9edec719890`.
- Annotated tag: `v0.1.0-mvp`, resolving to that baseline commit.
- The supplied repository had no branches/tags. The baseline and tag were pushed
  atomically without force. Direct `git ls-remote` confirmed the branch hash and
  the annotated tag's dereferenced commit against the local baseline.
- This documentation update follows the tagged baseline; the tag remains unchanged.

Local JWT/database/S3 credentials remain in ignored `.env`. The user configured
`GEMINI_API_KEY` locally. A real document embedding call succeeded; Gemini generation
returned HTTP **503** from the provider. No invalid-key, quota or missing-model
indication was found in the sanitized diagnostic. Live generation and a full live
PDF/chat acceptance workflow remain **pending provider availability**, not mocked or
claimed successful. Retry the explicit provider probe when service availability
recovers. All 35 automated tests in each previously executed mode remain recorded
separately from this live check. Phase 2 has not started.

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
