# Six-phase roadmap

## Phase 1 — Foundation and working MVP (delivered baseline)

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

## Phase 2 — Rich document ingestion (implemented)

Implemented after explicit user direction on 2026-11-06: Docling structure, selective
Tesseract OCR, PyMuPDF fallback, table JSON/header context, private figure assets and
previews, quality metadata, configurable modes, token-aware chunks, embedding index
identity/vector reuse, content-hash deduplication, Redis/Dramatiq delivery with SQL
outbox recovery, progress/cancel/retry/reindex, frontend controls, additive migrations
and synthetic representative fixtures. See [actual Phase 2 evidence](phase2-validation.md).

Validation: 49 native tests passed (2 expected OCR skips), 51 real-service tests passed,
real Docling digital/rasterized table probes passed, and all four synthetic document
types reached ready through the real application and Google embedding provider.
The 520-page synthetic extraction benchmark measured 3.625 s / 171.30 MiB sampled RSS;
its scope excludes embeddings, vision and Docling inference.

Git destination remains `origin` / `main` at the supplied SmartRAGPro repository.
Phase 2 commit message: `Improve PDF processing and background ingestion` (plain English,
as requested). The Phase 1 milestone tag is preserved. Resolve the phase commit by
that message in Git history; the completion report records the remote-verified hash.

Optional live Gemini vision and local-embedding acceptance remain unverified; no chart
understanding accuracy is claimed. Live Gemini answer generation's earlier 503 is not
silently considered repaired by successful embedding calls. Core ingestion is ready
for review/Phase 3 planning. Phase 3 requires a new explicit user instruction.

## Phase 3 — Conversational orchestration

Implemented after explicit user direction: deterministic LangGraph orchestration,
PostgreSQL checkpointer/message transactions, finite recent context, incremental
extractive synopses and distant recall, contextual query rewriting, ordered answer
references, strict scoped evidence/citations, multi-document comparisons, conversation
rename/delete/export/scope management and Streamlit recovery controls. Historical source
associations preserve deletion privacy even after scope changes. SSE was considered;
this phase returns complete verified replies with processing indicators.

See [Phase 3 validation and live-service gate](phase3-validation.md),
[architecture](architecture/conversations.md) and [setup/API](setup/conversations.md).
The synthetic overfitting conversation passes across fresh clients, with checkpoint
restore additionally checked in a separate interpreter. Native and real-service
regressions, atomic rollback and cross-user isolation are documented in that evidence.
The live HTTP check ingested its synthetic PDF, then returned 503 on the first chat turn;
real Gemini conversation acceptance remains unverified. Optional Gemini rewriting is
also not claimed live-validated. No production-readiness or unlimited-context claim.

Git milestone uses the existing origin/main and plain English message
`Add persistent document conversations`. Final checks: 63 native tests passed with
3 expected host/service skips; all 66 real-service tests passed. Formatting, lint,
type checks and staged secret/artifact scanning passed. Push verification is pending
the Git operation; record its exact hash after remote verification. Do not start Phase 4 automatically.

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
