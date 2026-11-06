# Evaluation methodology and limits

This is the user-requested Phase 4 retrieval/evaluation scope, replacing the earlier
roadmap order. No later phase has started. Initial audit: origin/main at
`d4e63ab74a581fdde5bcb180735de0047167dd59`, authenticated scoped RAG, multimodal worker,
durable messages and PostgreSQL checkpoints existed. Retrieval was dense-only with
24 candidates, cosine threshold .25, and active-run/owner/document filtering. There
was no chunk-level lexical index or retrieval evaluation dataset. The untracked
Gemini diagnostic script from the preceding session was preserved.

The retained dense configuration preserves that ranking policy. New production modes
are BM25, hybrid RRF and hybrid plus bounded lexical reranking. SQL stores term
frequencies/chunk lengths with cascading owner/document references and run fencing.
N, average document length, term document frequencies and candidate queries are all
scoped to owned ready selected documents before scoring. BM25 is Okapi k1=1.5, b=.75,
positive IDF `ln(1+(N-df+.5)/(df+.5))`. SQL/reference score parity is regression-tested.
Failed ingestion and nonactive runs cannot enter lexical candidates. Incomplete legacy
indexes explicitly fall back to dense, including lexical-weight=1 configurations.

## Fixed experimental contract

- One immutable fingerprinted dataset per run; 108 query records, 60 authored chunks,
  10 synthetic books. Each chunk is one labeled page. Queries have IDs, text, selected
  document IDs, relevant chunk IDs, expected answers, categories, answerability,
  optional conversation context, provenance and reviewer status.
- All labels and questions were generated during engineering, not independently human
  reviewed. Reviewed_by starts null. These are not a representative public benchmark.
- Validation topics 0–3; test topics 4–9. Cross-book cases avoid the topic boundary.
  All corpus text is available to unsupervised indexing, but only validation labels
  select fusion weight/reranking. Shared templates make the split correlated and easier
  than novel real documents. Do not tune on the held-out evaluation results.
- Identical scope and queries for TF-IDF, BM25, Google dense, weighted RRF and reranking.
  Weighted RRF is `w/(60+lexical_rank)+(1-w)/(60+dense_rank)`; missing rank contributes
  zero. The first share is lexical. Endpoints w=0 and w=1 are pure dense/lexical ranks.
  There is no arbitrary addition of cosine and raw BM25 scores.
- Validation selection maximizes Recall@5 then MRR, with deterministic tie preference
  for the simpler unfused configuration. The observed winner is w=0; dense remains the
  application default. Report the 70/30 hypothesis and regressions, not only winners.
- The reranker is a documented non-neural alternative: bounded query-term coverage,
  ordered bigram overlap, then fused rank. At most 24 candidates and 8000 characters
  per candidate are examined by default. It has no weights to download, repeated model
  loads or network cost. It is not a cross-encoder, and no neural-reranking claim is made.
  It regressed Recall@5 here and remains disabled unless explicitly selected.

## Retrieval metrics

Relevance unit is the dataset **chunk**, not the whole document. Binary labels only.
Deduplicate ranked IDs before metrics. For each answerable query and K=1,3,5,10:

- Recall@K = relevant IDs in top K / total known relevant IDs.
- Precision@K = relevant IDs in top K / K, including empty result slots.
- Hit Rate@K = 1 when at least one relevant ID occurs in top K, otherwise 0.
- MRR@10 = reciprocal rank of first relevant result in the evaluated top ten (zero if absent).
- nDCG@K uses binary gain and log2(rank+1) discount, divided by ideal DCG.
- Coverage = fraction of known relevant chunk IDs found in the evaluated top-ten set.

Macro-average query scores. Exclude ambiguous/unanswerable queries from positive
retrieval aggregates; do not hide them from the dataset or answer evaluation. Per-query
metrics remain in CSV, where zero scores on negative cases are bookkeeping, not positive
recall measurements. Never call these metrics generic accuracy. Comparisons of rewriting
ablation use only the same six held-out follow-up IDs on both sides. Deduplication has
no effect on this one-chunk-per-page corpus; no general benefit is established.

The seeded 1000-resample bootstrap interval is IID over queries. Template/topic
correlation means it understates uncertainty about a new corpus. Dense's synthetic
Recall@5 ceiling does not prove real-world 90%+ Recall@5.

## Source fidelity and answer measures

Authored page-chunks preserve table row/header text and visible chart-value
transcriptions. Generated PDFs mirror this content and include table grids/charts;
their extraction/chunking throughput is a separate experiment (90 extracted chunks).
Ranking labels cover the 60 authored units, not a claim that the 90 parser outputs
were end-to-end ingestion-labeled. Figure evaluation does not establish OCR or visual
reasoning accuracy. Existing ingestion regression tests cover those processing paths.

Live answer generation uses real Gemini 3.5 Flash-Lite with source-only instructions
and a category-stratified held-out sample, separately from retrieval. The fixed hybrid
challenger is compared even though validation retained dense. Initial provider rate-limit
failures are preserved, and successful cases are not rerun to improve scores.

Deterministic measures are deliberately narrow: expected phrase recall is substring
matching, context precision/recall and citation precision use relevance labels,
citation-index validity checks source numbering, sentence citation coverage detects
reference syntax, and numeric unsupported rate compares answer numbers to evidence.
These are **proxies**, not semantic correctness, citation entailment or hallucination
rates. Abstention is a documented text-pattern heuristic on negative cases. Lists,
paraphrases, incomplete relevance labels and legitimate arithmetic can cause false
positives/negatives. Human correctness, faithfulness and unsupported-claim rates remain
null pending source-based review; no LLM judge or claimed judge calibration is used.

## Performance contract

Record platform/Python/CPU count, corpus, model/dimensions, concurrency, sample count,
timing scope and cache state. Actual Google vectors are reused across variants to avoid
charging for duplicate embedding work. Separate provider timings from local ranking.
The real-service benchmark uses PostgreSQL and Qdrant with recorded real vectors for
hot cases; one cold/warm cache pair actually calls Google then reuses the production
cache. Hot p50/p95/p99 therefore exclude provider and generation time. Per-stage timings
and whole-retriever wall time are recorded. This is not whole-HTTP/graph end-to-end latency.
Live generation has its own wall-clock/token observations. No model-double latencies
are reported as live evidence. Time to first streamed token is null because streaming
is not implemented. The separate live HTTP conversation probe records whole-turn time.

Vectorizer RSS comparisons use three fresh processes per method, identical 20,000
synthetic inputs, 10 ms RSS sampling, tracemalloc and CPU-time deltas. TF-IDF and hashing
have different weighting/collision behavior; the memory comparison is not a claim of
equal retrieval quality. Imports and corpus buffers contribute to total RSS. Hashing
fixes feature dimension, not total memory; SQL index/database cache storage still grows
with corpus size. Local services/builds/tests may contend; no isolated-load SLA is claimed.

The native whole-service timing experiment was stopped because host loopback was slow.
The separately completed server retrieval run retains those observations. The completed
SQL/Qdrant service profile runs inside the Linux Docker test network; its lower timings
must not be interpreted as an algorithmic improvement over host-loopback measurements.
Whole-turn HTTP measurements are in live_workflow.json: the rebuilt API, real ingestion
worker/storage, real embeddings, real Gemini, verified citations and PostgreSQL history.
Four turns are too few for p95/p99 claims. Aborted synthetic native benchmark accounts
and collections were removed through the disposable fixture/targeted cleanup.

Empirical p50 always, p95 for n>=20, p99 for n>=100. Record mean, standard deviation and
sample counts; small tail samples are unstable. Model-cost estimates use measured token
usage and explicit dated list-price assumptions, not actual billing. Embedding cost,
failed calls, discounts, infrastructure and free eligibility are outside that estimate.

## Reproducibility and external resources

See evaluation/README.md. Keep uv.lock, dataset fingerprint and model/dimension identity
with results. Human-reviewed representative documents and labels remain needed before
production quality claims. Supply private data through ignored local storage; never
commit it or paste credentials into chat. Lexical/memory runs require no paid model.
Live embeddings/generation require the existing key and quota and may incur charges.
SQL migrations, persistent indexing, ownership/state regressions and conversation
restoration are tested separately against actual services with isolated model doubles.

Primary interfaces checked: [Qdrant hybrid queries](https://qdrant.tech/documentation/search/hybrid-queries/),
[scikit-learn HashingVectorizer](https://scikit-learn.org/stable/modules/generated/sklearn.feature_extraction.text.HashingVectorizer.html),
[CrossEncoder interface](https://www.sbert.net/docs/package_reference/cross_encoder/model.html).
