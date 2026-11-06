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
type checks and staged secret/artifact scanning passed. Implementation commit
`6434b2c87175e3ff74324c579daaef8ac12d90bd` was pushed to origin/main and independently
verified with `git ls-remote` on 2026-11-06. The following documentation-only commit
records that verified milestone. Do not start Phase 4 automatically.

## Phase 4 — Retrieval quality, grounding and performance (user-revised scope)

The user explicitly replaced the earlier proposed order with retrieval quality,
grounding, performance and reproducible evaluation. Implemented persistent scoped SQL
BM25, configurable dense/BM25/RRF/rerank modes, bounded query-vector caching, legacy
backfill without reembedding, 108 labeled synthetic questions with fixed splits,
real Google embedding experiments, separate real Gemini answer samples, vectorizer
RSS comparisons, real-service probes and generated reports/charts.

Dense remains default because validation chose zero lexical share. This synthetic
held-out corpus has a dense Recall@5 ceiling; there is no claim of improved real-world
accuracy. See [measured results and limits](benchmarks/retrieval-comparison.md),
[performance](benchmarks/latency-and-memory.md) and [reproduction/review](../evaluation/README.md).
Representative human-reviewed documents and semantic answer review remain outstanding.
Full validation: 69 native tests passed with three expected host/service skips; all
72 real-service tests passed. The final focused PostgreSQL regression also checks
the complete-index fallback and cleanup. Formatting, lint and type checks pass.
Implementation commit `04ed2a6f52728ed9a50ef4dc88486bdc173999eb` was pushed to the
existing origin/main and independently verified with `git ls-remote` on 2026-11-06.
A following documentation-only commit records this verified milestone. Phase 5 had not started at that milestone.

The earlier live Gemini gate is now resolved for the locally selected
`gemini-3.5-flash-lite`: the rebuilt application completed all four live HTTP turns,
fresh-client login/history restoration and expected page citations. Full ingestion
and whole-turn timings are captured in evaluation/results/live_workflow.json.

## Phase 5 - Security hardening (explicit user scope)

Implemented session rotation/reuse revocation, account lifecycle controls, upload and
processing limits, versioned ingestion/retrieval/memory poisoning defenses, private
object-key checks, worker-generated previews, plain-text model rendering, runtime DB
roles and authenticated Redis/Qdrant. Architecture and all security documents live in
[the security report](security/adversarial-test-report.md), with machine-readable
adversarial, dependency, infrastructure and regression evidence under evaluation/security/.

The final native suite passed 128 tests with five expected skips. The complete
disposable-service suite passed 132 tests; five final focused PostgreSQL/
security regressions also passed. The synthetic retrieval regression preserved earlier
metrics. Historical live model failures remain recorded. The existing deployed image
passed seven of eight HTTP acceptance checks but falsely quarantined educational text;
the current v3 source fixes quotation handling and passes the exact PDF regression.
The final application rebuild was declined, so deployment acceptance remains open.
No production-readiness or general prompt-injection immunity is claimed.

Git milestone: source validation and the authorized plain-English commit/push are being
finalized against the existing origin/main. Do not start Phase 6 automatically. See
[secure setup and final acceptance commands](security/local-hardening.md).

## Phase 6 — Production operations

Deployment, TLS, monitoring/alerts, backups and restore drills, disaster recovery,
retention policies, dependency/security scanning and production acceptance gates.

Phases 3–6 are proposed scopes, subject to future user specifications. Do not start
them automatically. Phase 1 does not claim public production deployment readiness.
