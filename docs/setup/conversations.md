# Conversation setup and API

Install the locked environment with `uv sync --frozen`. For Compose rebuild the API,
frontend and initializer with `docker compose up -d --build`; use the existing setup
guide for first-run environment configuration. The initializer runs Alembic and then
the official PostgreSQL checkpointer setup before the API starts. For native startup
run `uv run python -m scripts.bootstrap` first. Existing Phase 1/2 data is preserved by
the additive `20261106_conversations` application migration. Checkpoint schema setup
requires DDL privileges during initialization; runtime credentials need table access.

No new external service or secret is required beyond the existing PostgreSQL/Qdrant/
Redis/S3 stack and Gemini key. PostgreSQL and LangGraph are free software. Hosted
infrastructure and Gemini requests can incur charges. Keep `GEMINI_API_KEY` in the
ignored `.env`, never in chat, URLs or commits. `GEMINI_MODEL` controls generation.
Optional `CHAT_LLM_REWRITE=true` and `CHAT_QUERY_MODEL` enable paid structured Gemini
follow-up rewriting; leaving CHAT_QUERY_MODEL empty uses GEMINI_MODEL. Defaults use
local deterministic reference resolution and extractive summaries.
The configured `gemini-3.8-flash` ID and structured-output capability were checked
against Google's [model documentation](https://aistudio.google.com/docs/models/gemini-3.8-flash);
documentation availability does not prove account quota or live service availability.

The `.env.example` lists CHAT_CONTEXT_TOKENS, CHAT_HISTORY_TOKENS, CHAT_SUMMARY_TOKENS,
CHAT_EVIDENCE_TOKENS, CHAT_RECENT_MESSAGES, CHAT_RECALL_MESSAGES and CHAT_SUMMARY_BATCH.
Use ENVIRONMENT=development and CHAT_TRACE_QUERIES=true only with nonprivate development
queries and DEBUG logging; both are required to log original and rewritten queries.
External LangSmith tracing is disabled for chat regardless of environment flags.

All routes require the existing Bearer access token:

| Route | Behavior |
| --- | --- |
| POST /api/v1/conversations | Create with 1–20 owned ready document_ids and optional title |
| GET /api/v1/conversations | Paginated saved titles, scope versions and source warnings |
| GET /api/v1/conversations/{id} | Saved authorized document selection and metadata |
| PATCH /api/v1/conversations/{id} | Rename and/or explicitly replace document_ids (0–20) |
| DELETE /api/v1/conversations/{id} | Delete messages, synopsis, associations and checkpoints |
| GET /api/v1/conversations/{id}/messages | Ordered durable history; limit 1–100, offset >= 0 |
| POST /api/v1/conversations/{id}/messages | content + stable request_id UUID; committed verified reply |
| GET /api/v1/conversations/{id}/export | Paginated conversation + messages + next_offset |
| POST /api/v1/conversations/{id}/summary/refresh | Reset synopsis and rebuild a bounded batch |

Foreign IDs return 404 before any checkpoint access. Busy conversations and conflicting
idempotency UUIDs return 409. Budget overflow returns 422, invalid source references 502,
unavailable providers 503. OpenAPI at `/docs` contains request/response schemas.

In Streamlit create a chat with selected ready PDFs. Saved sidebar buttons restore the
server-owned selection and history; logging out clears only the local token/session.
Manage current conversation to rename, change its PDF set, refresh its synopsis or
delete it. Export downloads owned history as JSON. Expand Sources for excerpts/pages
and figure assets. Responses appear when verified; the spinner indicates processing,
not token streaming. A deleted source produces an explicit privacy/recovery warning.

Run `uv run pytest tests/test_conversations.py` for deterministic model tests with real
PDF extraction and in-process Qdrant. SQLite checkpoints are confined to those isolated
tests. Run `./scripts/test_services.ps1` for actual PostgreSQL checkpoint/transaction/
locking behavior plus Qdrant, Redis and S3. No model-quality or Gemini latency claim
may be inferred from deterministic model outputs. See phase validation evidence.
