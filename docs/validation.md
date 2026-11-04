# Phase 1 validation evidence

Executed 2026-11-04. These are actual results, not proposed checks.

| Check | Actual result |
| --- | --- |
| `uv sync --frozen` / locked dependency installation | Passed on Python 3.12; lockfile includes platform wheels |
| `ruff check .` | All checks passed |
| `ruff format --check .` | Passed (53 files in final check) |
| `mypy` | Success, 27 source files |
| `pytest` on Windows / Python 3.12.5 | **35 passed**, 22.91 seconds, backend statement coverage 89% |
| Container integration suite / Python 3.12.12 | **35 passed**, 41.35 seconds, backend statement coverage 90% |
| Runtime Docker build and `docker compose up --build -d` | Passed; bootstrap exited 0; API, worker and Streamlit started |
| Real HTTP `/health/live` | 200 |
| Real HTTP `/openapi.json` | 200 |
| Real Streamlit `/_stcore/health` | 200 |
| Real HTTP `/health/ready` without Gemini key | 503, as designed |
| Ignore verification | `.env`, venv, dependency cache, upload PDFs and local database paths excluded |
| Staged secret/artifact scan | Passed; source/config/docs/lockfile only, no private PDFs or environment secrets |

The isolated suite has one expected Qdrant warning: payload indexes are ineffective in
in-process mode. The real Qdrant integration run validates those indexes without that
warning. Coverage excludes frontend from its backend percentage; Streamlit login,
navigation and logout are exercised using Streamlit AppTest against the real API stack.

## What ran for real

The Linux suite used PostgreSQL **17.11**, Qdrant **1.20.0**, Redis **7.4.12** and
SeaweedFS **4.52** S3 in dedicated containers. Real database migrations, constraints,
transactions, vector indexing/search/filter/delete, Redis rate limits, and S3
put/get/delete were exercised. Synthetic PDFs were generated in memory, parsed by
pypdf, split using LangChain, and returned through FastAPI's HTTP test client.
The application runtime itself was built and started separately with private local
service credentials; its health endpoints were checked over real HTTP.

Tests cover registration/login/logout and revocation; wrong passwords; JWT signature,
algorithm, issuer, audience, expiry and required claims; unauthenticated reads/writes;
PDF MIME/signature/size, encrypted/blank/malformed PDFs; page mapping and long-text
chunking; full ingestion/retrieval/answer/history; idempotent messages; two-user
isolation; source formatting; deletion and physical cleanup; upload compensation;
expired worker leases; storage/model outages; no-evidence abstention; invalid model
citations; migration upgrade/downgrade and schema drift; health/OpenAPI; rate-limit
failure behavior; Streamlit auth/navigation; Gemini text/content-block response parsing.

## What was mocked or remains unverified

- All automated generation and embedding calls are deterministic **test-only doubles**.
  The Gemini adapter response-format tests mock transport. No runtime mock-provider
  switch exists. The isolated suite additionally doubles Redis/S3 and uses SQLite
  and in-process Qdrant; the Linux integration run uses real datastore services.
- Initial validation had no Gemini key. On 2026-11-04, after the user configured it
  locally, a real Google document embedding call **passed**. Gemini generation
  returned HTTP **503**; the sanitized diagnostic found no invalid-key, quota or
  missing-model indication. **Live Gemini answer generation, the combined provider
  probe, and the full live PDF/chat acceptance flow have not passed.** Live query
  embeddings and optional OpenAI embeddings are also not claimed verified. Nothing
  was silently substituted for these checks. Retry `scripts.live_providers` and the
  UI acceptance flow when the configured provider is available.
- Streamlit was tested through AppTest and server health; no manual browser acceptance,
  live model quality evaluation, concurrency/load benchmark or public TLS deployment
  is claimed.
- GitHub baseline push and tag are **verified** at
  https://github.com/ShikharSingh7985/SmartRAGPro. Baseline commit
  `82f41c6098fe14e20ee5a3109665e9edec719890` and dereferenced tag `v0.1.0-mvp`
  matched direct remote inspection on 2026-11-04. Hosted CI execution remains
  unverified; CI configuration exists. Follow-up documentation commits do not move
  the baseline tag.

## Resolved issues and remaining gates

Resolved: duplicate-timestamp message ordering using database positions; provider
text/content-block compatibility; unavailable archived MinIO image via maintained S3
replacement; native sandbox/cache permission conflicts via Linux test containers;
Streamlit test script-path/title ordering assumptions. A clean dependency reinstall
was performed after an initial lint command touched the dependency cache; subsequent
checks explicitly exclude dependency directories.

Phase 1 local implementation and initial GitHub push are verified. Completion still
requires successful live generation and full credentialed acceptance after the provider
503 resolves. Phase 2 has not started. Public deployment
hardening and later-phase features are listed in the system design and roadmap.
