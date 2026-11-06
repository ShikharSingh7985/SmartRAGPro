# Phase 3 validation evidence

Recorded 2026-11-06. This evolves the existing Phase 2 application; Phase 4 has not started.

## Prerequisite audit and implementation

Started from clean `main`, Phase 2 commit `68671af87aa2b1970f42a7902ba4e9d1d6a28141`,
with the existing origin preserved. Read AGENTS, roadmap, architecture, migrations,
tests, routes, RAG services, workers and Git history. Accounts, document ownership,
ingestion, SQL messages and conversation document selection already existed. Chat used
only the current question; LangGraph, rewriting, summaries and checkpoints were absent.
Existing source deletion removed conversations entirely. Those behaviors were evolved
without recreating the application or rewriting history. The earlier live generation
503 was a known prerequisite limitation, not evidence that Gemini answers worked.

Implemented a typed deterministic LangGraph with input/context validation, reference
resolution, standalone rewriting, scoped planning/retrieval, evidence selection,
generation, citation verification and atomic persistence. PostgreSQL checkpoints share
the message transaction. A real-service test exposed the saver pruning API's isolation
change; a narrow transaction-local retention adapter under the conversation lock fixes
that without weakening atomic turn recovery. See ADR 0006.

Memory consists of full SQL messages plus finite recent context, incremental extractive
synopses with position provenance and lexical recall of distant turns. Default follow-up
rewriting and summarization make no additional model call. Optional structured Gemini
rewriting is explicitly configured. Scope changes retain historical source associations
for deletion, reset graph/topic/summary context and version messages. Source deletion
purges derived text/checkpoints and keeps recoverable shells. Conversation rename,
delete, export, scope editing and summary refresh are available in API/Streamlit.

## Commands and results

- `uv sync --frozen` (workspace cache selected with `--cache-dir .uv-cache`): passed.
- `uv run ruff check .`: passed.
- `uv run ruff format --check .`: passed.
- `uv run mypy`: passed, 43 backend/frontend source files.
- `uv run pytest`: **63 passed, 3 skipped**, 89.49 s, 85% backend statement coverage.
  Native host has no Tesseract (two OCR skips); PostgreSQL locking is the third skip.
- `./scripts/test_services.ps1`: rebuilt image and all **65 tests passed** in 228.36 s
  before the final historical-source deletion regression was added.
- Final full service rerun with current backend/tests/scripts mounted read-only into the
  same locked test image: **66 passed**, 278.29 s, 88% backend statement coverage.
  This includes the historical-source association migration and privacy regression.

The service suite uses real PostgreSQL 17.11, Qdrant 1.20, Redis 7.4.12, S3/SeaweedFS
4.52 and Tesseract. It intentionally uses deterministic test-only embeddings and model
outputs. Native tests additionally replace S3/Redis and use file-backed SQLite checkpointer
injection. There is no production in-memory/SQLite fallback or normal-use fake model.

The four-turn ML fixture test uses a synthetic PDF with known content on actual pages:
overfitting on page 1, prevention on page 2, chapter 5 regularization/early stopping on
page 3, random forests on page 4. Real PDF extraction and Qdrant retrieval supply the
model double's evidence. It checks pronouns, chapter constraints and ordered answer
references, logs out, authenticates through a fresh client, restores history/scope and
continues. PostgreSQL checkpoints are additionally read through a separate Python
interpreter. Latest state is compact, checkpoint writes are pruned and blobs stay bounded.

Other tests cover incremental summary batches/provenance, distant first-question recall,
budget rejection, optional rewrite dispatch, citation consistency, exports, two users
with different indexed books, unauthorized thread/resource access, same-thread 409,
independent concurrent conversations, provider timeouts/rate-limit errors, checkpoint
rollback after an existing successful turn, duplicate/conflicting UUIDs, scope changes,
source recovery and deleting a source from a previous scope. Existing auth, ingestion,
table/figure, job recovery, cleanup and Alembic round-trip/drift tests remain in the suite.

## Measured overhead

Four-turn synthetic-model PostgreSQL run, milliseconds; real SQL and Qdrant, mocked
embeddings/generation. These are four observations, not a production latency estimate.

| Stage | Turn 1 | Turn 2 | Turn 3 | Turn 4 |
| --- | ---: | ---: | ---: | ---: |
| Memory reconstruction | 35.355 | 5.149 | 6.463 | 11.177 |
| Reference resolution | 0.126 | 0.041 | 0.100 | 0.111 |
| Deterministic rewrite | 0.855 | 0.046 | 0.110 | 0.128 |
| Retrieval | 12.196 | 3.323 | 4.762 | 8.372 |
| Mock generation | 1.202 | 0.116 | 0.210 | 0.364 |

Reproduce timings with `pytest tests/test_conversations.py --capture=tee-sys` using the
service test environment. Turn metadata records timings without source text. No real
Gemini generation latency or cost measurement is claimed.

## Live application check and limitations

Rebuilt the integrated API, frontend, initializer and dispatcher. Bootstrap applied
application and official checkpoint schema initialization against the existing local
PostgreSQL without dropping data. `uv run python -m scripts.live_conversations` used a
new synthetic account, real HTTP, a generated ML PDF, the real ingestion worker/storage
and configured Google embeddings. Ingestion reached ready. **The first chat turn
returned HTTP 503**, so real four-turn Gemini acceptance remains blocked/unverified.
The script requested synthetic source/conversation cleanup and logout; synthetic account
metadata remains. A separate direct `scripts.live_providers` probe also failed against
the real configured provider; details were suppressed. Neither check is counted as a pass.

The optional Gemini rewrite adapter is dispatch-tested with an isolated model double;
its live structured-output call is unverified. Default deterministic heuristics are
English-oriented and may ask the user to name an ambiguous entity/method. Summaries are
lossy linguistic aids; full history remains in SQL. Chapter filtering needs chapter text
or headings in extracted chunks. Citation scope/indices/provenance are validated, but
semantic entailment is not proven. Responses are complete verified replies with a
processing indicator; SSE/token streaming and browser-disconnect provider cancellation
are not implemented. Interrupted uncommitted turns restart idempotently, not mid-token.
No manual browser visual acceptance or production load/backup test is claimed.

To finish live acceptance: check model availability/quota in Google AI Studio, keep a
valid `GEMINI_API_KEY` and available `GEMINI_MODEL` in the ignored `.env`, recreate the
API (`docker compose up -d --force-recreate api`), and rerun
`uv run python -m scripts.live_conversations`. Never paste secrets in chat. Gemini may
offer a free quota subject to eligibility; usage/billing and hosted infrastructure may
incur charges. No new secret is needed if this is transient provider capacity failure.

## Git milestone

Destination: existing `origin`, `main`,
`https://github.com/ShikharSingh7985/SmartRAGPro.git`.
Plain English commit message: `Add persistent document conversations`.
Implementation commit: `6434b2c87175e3ff74324c579daaef8ac12d90bd`. The push succeeded
and an independent `git ls-remote origin refs/heads/main` returned that exact hash on
2026-11-06. A following documentation-only commit records the verification. The final
report names the resulting remote head too. Phase 4 must not start automatically;
live-provider acceptance remains a
documented gate before claiming fully validated real-model conversational behavior.
