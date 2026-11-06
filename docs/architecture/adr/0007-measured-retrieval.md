# ADR 0007: Measured retrieval alternatives and bounded caches

Accepted for the user-revised Phase 4 retrieval/evaluation scope on 2026-11-06.

Preserve dense retrieval as default. Validation on the authored synthetic corpus
selected zero lexical share. Weighted hybrid and the bounded reranker did not improve
held-out Recall@5; enabling a worse default would be unjustified. All alternatives
remain explicit configuration for other reviewed corpora.

Add a persistent PostgreSQL inverted term index alongside Qdrant dense vectors.
`search_chunks` stores text, length, provenance, owner, document and ingestion run;
`search_terms` stores normalized term counts. Worker ingestion updates it idempotently
after vector publication and before ready state. Failed/nonactive runs cannot be
retrieved. Final publication removes obsolete SQL runs; document deletion cascades
terms/chunks. Legacy ready documents can be backfilled from existing active vectors
without reembedding. Until complete, hybrid/BM25 deliberately fall back to dense and
record `lexical_index_incomplete` in content-free retrieval telemetry.

BM25 N, mean length, DF and candidates are filtered by owner, ready document scope and
active run before ranking. SQL/reference parity and foreign-owner filtering are tested.
The production API never builds a vocabulary-sized per-user in-memory index. This
adds database storage, indexed writes and SQL round trips, not free or constant total
memory. SQL memory/cache usage still depends on corpus size.

Qdrant sparse/dense native fusion was considered. A normalized SQL term index avoids
changing the existing dense collection's vector schema and allows exact scope-specific
DF statistics without a global tenant-mixed lexical index. It uses the already-required
database rather than another service. RRF avoids incomparable raw score weights.
The lexical share w is explicit: w/(60+rank_lexical)+(1-w)/(60+rank_dense).

The optional reranker is a documented non-neural alternative, not a cross-encoder:
query coverage, bigram overlap, then prior rank, over at most the configured candidates
and 8000 characters per candidate. It has no provider/model load overhead; failures
retain the fused order. Its regression is reported, and it is not deployed by default.
Do not imply a downloaded neural model was benchmarked.

The query-embedding cache is bounded by entry count and TTL and keyed by SHA-256 of
owner, embedding fingerprint and query. It stores vectors, not plaintext query keys,
results or document content. Every retrieval still rechecks SQL readiness, tenant,
document scope and active run. Scope/deletion changes cannot expose cached evidence.
There is no cross-tenant embedding reuse or result-cache invalidation problem.

Near-duplicate removal is bounded and only within the same source document/page; it is
off by default because this corpus establishes no benefit. Multi-query LLM expansion,
semantic rechunking, adaptive top-k and parent expansion remain unadopted without
appropriate fixed-label experiments. Keep phase boundaries and the graph's evidence
verification unchanged.

Generation now has one canonical insufficient-evidence response that may be persisted
without citations. The model is instructed to use that exact abstention; the verifier
accepts only that fixed nonfactual response. Arbitrary uncited claims still fail closed
with 502 and roll back the turn. This prevents a legitimate abstention being mistaken
for an unsupported factual answer without weakening citation requirements.

See [methodology](../../benchmarks/evaluation-methodology.md), generated
[comparison](../../benchmarks/retrieval-comparison.md) and
[memory/latency evidence](../../benchmarks/latency-and-memory.md).
