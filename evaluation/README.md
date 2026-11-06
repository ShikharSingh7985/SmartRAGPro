# SmartRAG retrieval and answer evaluation

These tools use the existing application's ranking, query rewriting and retrieval
modules. They are experiments over an explicitly **synthetic, unreviewed** corpus;
no real-world accuracy claim follows from their results. Production defaults remain
dense because validation did not justify deploying hybrid/reranking by default.

## Reproduce

Python 3.12, the locked dev dependencies, and existing local `.env` configuration:

```powershell
uv sync --frozen
uv run python -m evaluation.dataset
uv run python -m evaluation.pdf_corpus
uv run python -m evaluation.retrieval
uv run python -m evaluation.memory --documents 20000
uv run python -m evaluation.quality --limit 12 --model gemini-3.5-flash-lite
uv run python -m evaluation.report --input-price-per-million 0.30 --output-price-per-million 2.50
```

`dataset` **replaces** the generated synthetic JSON; do not rerun it over reviewed
edits without saving them. `load()` validates labels, scopes, references and splits.
The committed JSON is the dataset used for the reported results; it has 108 queries,
10 synthetic books and 60 authored page-chunks. Categories include facts, explanations,
tables, figures, multi-hop, cross-page/document, follow-up, ambiguous, unanswerable
and rare identifiers. Validation/test topics and IDs are assigned before tuning.

`retrieval` compares TF-IDF, BM25, real Google dense embeddings, weighted RRF at lexical
shares 0/.3/.5/.7/1, hybrid plus a bounded non-neural reranker, deduplication and a
matched follow-up rewriting ablation. Every method receives identical scopes and
labels. It uses actual in-process Qdrant unless `--qdrant http://localhost:56333` is
specified. A separate server run is in `results/server/`. `--output` selects its
result folder. Real embeddings require `GEMINI_API_KEY`; they are never replaced by
mock vectors. Cache files are ignored under `evaluation/.cache/`, keyed by corpus hash,
model and dimension. Failed runs retain completed vectors; reruns resume. Rate-limit
backoff is bounded, and private provider strings are suppressed.

`quality` makes real Gemini calls for a predeclared category-stratified sample of held-out
questions, comparing dense with `--challenger rrf_0.5_rerank`. This challenger is an
experiment, not the validation-selected default. `--resume` retries only failed cases,
retaining failed-attempt records and successful original answers. A four-second pacing
delay is outside measured generation time. Provider-fixed sampling defaults are
recorded. `usage_metadata` supplies actual token counts. Optional price arguments are
scenario assumptions, not measured billing. Check current provider pricing before
reusing the example rates. Google free quotas vary; provider requests can incur charges.

## Real service microbenchmark

Start `docker compose -p smartrag-test -f docker-compose.test.yml up -d --wait`.
Use the disposable `smartrag_test` database only; never set TEST_DATABASE_URL to production.
Run the service benchmark **after** the integration suite because tests migrate that
database up/down. Configure its test URL through local environment variables, then:

```powershell
uv run python -m evaluation.performance
```

It accepts `TEST_DATABASE_URL` (PostgreSQL, database name must be `smartrag_test`) and
`TEST_QDRANT_URL` (default local test port 56333). It inserts synthetic SQL search rows
and a uniquely named Qdrant collection, measures the actual application retriever and
removes its synthetic rows/collection afterwards. It never substitutes a model double:
hot cases preload recorded real Google embeddings; one separate cold/warm pair makes
a real embedding call and then tests the production cache. Hot retrieval excludes LLM
and live embedding time. This is not HTTP/end-to-end app latency. It leaves application
migrations installed on the disposable test database. Do not run it concurrently with
tests that downgrade that schema.

## Artifacts and human review

`results/retrieval.json` contains fingerprints, environment, model identity, selection,
aggregate metrics/intervals, stage timings and rankings; `retrieval.csv` contains every
query/variant. `quality.json` contains actual synthetic-document answers, usage,
deterministic proxies, failures and blank human scores. `memory.json`, `ingestion.json`
and `performance.json` identify measured scope and environment. `report` regenerates
comparison tables, analysis JSON and standalone SVG charts from those values.

To review ground truth, edit `data/synthetic.json`: inspect each question against the
referenced chunk text, correct relevant_ids/expected_answer/answerable and record your
identity in reviewed_by. Keep validation/test assignments fixed. Save a new version and
run `python -c "from evaluation.dataset import load; print(load().fingerprint())"`.
Re-evaluate all methods; fingerprint checks prevent mixing old rankings and new labels.
Never revise held-out labels or weights just to make a method win. For answer review,
score human_correctness and human_faithfulness 0–1 against the source, and mark each
unsupported factual claim before setting human_unsupported_claim_rate. Preserve the
original model output and reviewer/rubric notes in a separate review copy.

Private user documents, embeddings and answer exports belong in ignored local folders,
not this public synthetic result directory. To obtain representative evidence, supply
lawfully usable documents locally, create reviewed labels using the same schema and
keep private outputs under ignored `evaluation/.cache/private/`. No secret is needed
for lexical/memory experiments. Never paste API keys or private documents into chat.

See [methodology](../docs/benchmarks/evaluation-methodology.md),
[retrieval comparison](../docs/benchmarks/retrieval-comparison.md) and
[latency/memory](../docs/benchmarks/latency-and-memory.md).
