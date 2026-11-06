# Phase 4 completion evidence

The user's latest prompt moved retrieval/evaluation into Phase 4. No Phase 5 work
started. The previous proposed security-hardening scope was not silently implemented.

Prerequisites audited at origin/main `d4e63ab74a581fdde5bcb180735de0047167dd59`:
authentication, multimodal worker, owned ready-document scope, PostgreSQL conversation
history/checkpoints and dense retrieval existed. The preceding Gemini diagnostic helper
was preserved. Local configuration now selects the working Gemini 3.5 Flash-Lite.
The final actual HTTP upload/ingestion/four-turn/fresh-login workflow passed; both runs
are preserved in evaluation/results/live_workflow*.json.

Implemented: persistent tenant/run-scoped SQL BM25, weighted RRF, bounded optional
non-neural reranking, bounded query-vector cache, safe model abstention, additive
schema migration, legacy backfill without embedding calls, reproducible datasets,
rank/answer/performance/memory/ingestion experiments and measured charts/reports.

## Actual checks

- `uv sync --frozen`: passed (workspace cache selected). Initial Windows wheel-cache
  rename failures were resolved with `uv sync --no-cache --link-mode copy`.
- `uv run ruff check .`, `uv run ruff format --check .`: passed.
- `uv run mypy`: passed, 47 configured backend/frontend files.
- `uv run pytest`: **69 passed, 3 skipped**, 105.65 seconds, 86% backend coverage.
  Skips: two host OCR cases without Tesseract and PostgreSQL-only locking.
- Complete disposable PostgreSQL/Qdrant/Redis/S3/Tesseract suite: **72 passed**,
  350.51 seconds, 89% backend coverage. Final source/tests were mounted read-only into
  the locked Docker test image. `./scripts/test_services.ps1` remains the reproducible
  build/run entry point. An initial missing evaluation-package COPY was fixed.
- Final focused PostgreSQL index/fallback/cleanup tests passed before the additional
  safe-abstention case; that case is included in the final full suites.
- Real API/initializer/frontend/dispatcher and ingestion worker rebuilt; API healthy.
  SQL migrations applied without dropping production data. Legacy backfill command
  completed (zero active legacy chunks at execution); its paths and SQL index behavior
  are tested. Reindex explicitly when a legacy document has no published active run.

Tests isolate model/embedding doubles; they are not the source of live benchmark
timings. Ranking experiments used real Google embeddings and actual Qdrant, both
in-process and server runs. The service profile used real PostgreSQL/Qdrant and
recorded real embeddings for hot retrieval, with a separate actual cold embedding
request. The answer sample used 24 actual Gemini calls and recorded 8 earlier rate-limit
failures before a paced resume. All four actual HTTP conversation turns and page
citations passed after the final abstention rule.

## Evidence and decisions

The same held-out 53 answerable queries give dense Recall@5 1.0000, BM25 0.9906,
50/50 RRF 1.0000 and hybrid/coverage reranking 0.9528. Recall@5 is the fraction of
known relevant chunk IDs found in five results, not generic accuracy. Validation
selected zero lexical share; dense stays default. The synthetic corpus is small and
unreviewed and cannot validate real-world 90%+ recall. Non-neural reranking is opt-in.

The controlled vectorizer experiment measured mean peak process RSS 195.82 MiB
(TF-IDF) vs 168.76 MiB (hashing), three fresh processes per method. Hashing was slower
on average and does not bound total application memory or prove equal retrieval quality.
Actual hot service dense p50 was 5.20 ms; hybrid p50 18.15 ms. Real cold/warm embedding
probe was 752.87/0.045 ms (one pair). These do not include Gemini or whole-HTTP overhead.
Native host loopback was slow; incomplete native service probes were stopped and their
disposable synthetic artifacts cleaned. Do not interpret network-placement differences
as algorithmic speedups.

See [comparison](benchmarks/retrieval-comparison.md),
[latency/memory](benchmarks/latency-and-memory.md),
[methodology](benchmarks/evaluation-methodology.md),
[commands/review process](../evaluation/README.md) and all machine-readable
[results](../evaluation/results/). Figures are generated from measured values.

## Remaining work and external resources

Representative lawful user documents and human-reviewed relevance/semantic answer
labels remain necessary for real-world claims. Place private corpus/outputs in ignored
evaluation/.cache/private, follow the dataset schema, record reviewers, retain fixed
splits and rerun every method. Do not send documents or credentials through chat.
Lexical/memory runs need no provider key; live embeddings/generation use local
GEMINI_API_KEY and may incur charges or quota limits. No extra key is currently needed.

No neural cross-encoder, semantic entailment judge, representative production-load
test, streaming TTFT or global application-memory reduction is claimed. Deterministic
answer checks are labeled proxies; human semantic scores remain null. API retention,
tenant safety and existing conversation behavior remain covered by regression tests.

Git destination remains the supplied origin/main. Plain-English implementation message:
`Add measured retrieval options and benchmarks`. Remote verification is recorded after
the push; the final report identifies the exact implementation and documentation heads.
