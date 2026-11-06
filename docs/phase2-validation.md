# Phase 2 completion evidence

Executed 2026-11-06. Fixtures are synthetic; results do not establish real-world
accuracy on books, research papers, handwriting or arbitrary charts.

## Implemented

Docling primary structure, PyMuPDF inspection/fallback, selective Tesseract OCR,
page classification/quality/warnings, four extraction modes, JSON tables with cells
and spans, repeated header context, original raster assets and bounded previews,
optional model-derived vision descriptions, token-budgeted structured chunks and
provenance, embedding fingerprints and vector reuse, owner-scoped upload deduplication,
Redis/Dramatiq delivery with durable SQL recovery, progress/cancel/retry/reindex APIs,
and Streamlit controls/source images. Migration `20261106_multimodal` is additive.

## Actual checks

| Check | Result |
| --- | --- |
| `uv sync --frozen --cache-dir .uv-cache` | Passed; locked base environment checked |
| Ruff lint / format | Passed; 69 files formatted in the final check |
| mypy | Passed, 35 backend/frontend source files |
| Native Windows suite | **49 passed, 2 skipped**, 73.69 s; backend coverage 83% |
| Linux real-service suite | **51 passed**, 203.51 s; backend coverage 86% |
| Primary Docling table probe | Passed with real downloaded layout/table models |
| Primary Docling + Tesseract full-page scan-table probe | Passed; raster-only table detected and values 94/15 preserved |
| Synthetic 520-page benchmark | 520 pages, 1560 chunks, **3.625 s**, sampled peak process RSS **171.30 MiB** |
| Actual application ingestion | Text, scan, table and figure PDFs all reached ready through the real worker and configured embedding API |

The benchmark includes synthetic PDF generation, PyMuPDF extraction and chunking.
It excludes embeddings, vision, Docling model inference, queue waiting and network
storage. RSS was sampled every 20 ms with psutil; it is a process sample, not a
container peak or universal bound. An earlier run measured 5.078 s / 159.19 MiB;
machine contention and implementation changes affect results. No 500-page real book
was supplied, and no 500-page Docling/OCR/live-embedding throughput claim is made.

The native skips are exactly the scan/mixed OCR tests because native Tesseract is
absent. The Linux image installs it and runs both. Other deterministic tests use real
parsing, synthetic PDFs and provider doubles; Linux integration uses real PostgreSQL,
Redis/Dramatiq, Qdrant and S3. The 35 original Phase 1 tests remain represented; the
retry case now tests a transient storage outage because malformed PDFs correctly fail
without retries. Tests also exercise unauthorized preview/asset access, physical
cleanup, cancellation, lease recovery, deduplication, vector reuse, model-space checks,
schema drift and round trips, table-answer context and explicit vision opt-in.

## Actual extraction examples

The digital merged-header fixture yielded caption `Table 3. Model accuracy and latency
comparison`, a four-column grid, the four-column span of `Model comparison`, second-level
headers `Approach`, `Accuracy (%)`, `Latency (ms)`, `Dataset`, and rows:

| Approach | Accuracy (%) | Latency (ms) | Dataset |
| --- | --- | --- | --- |
| Model A | 88 | 20 | Test |
| Model B | 94 | 15 | Test |

The original Docling probe recorded full cell bounding boxes and span indices. A
separate rasterized-table probe on current source used Docling's installed
`OcrMode.FULL_PAGE` API with real Tesseract and verified one table and values 94/15.
The table-question integration test verified header/value evidence and a page-1 table
citation; its answer generator and embeddings were explicit test doubles.

The real Tesseract scan/mixed tests recovered `42` and `REVENUE`; the digital page of
the mixed fixture kept its digital extraction path. Figure fixtures retain original
image streams, bounded previews and captions. Mixed-page figure label OCR can read
printed labels, but this is not chart interpretation.

## Normal application acceptance with real embeddings

The `scripts.live_ingestion` utility registered synthetic accounts and uploaded these
synthetic files through the actual HTTP API, SQL dispatcher, Redis broker and Docling
worker. It used the configured real Google embedding provider, not a runtime mock.

| Fixture | Pages | Chunks | Elapsed to ready |
| --- | --- | --- | --- |
| text.pdf | 2 | 5 | 34.99 s |
| scan.pdf | 1 | 2 | 26.92 s |
| table.pdf | 1 | 3 | 18.41 s |
| figure.pdf | 1 | 2 | 33.34 s |

Those timings include polling/queue/storage/provider work and reflect that run only.
An initial attempt hit an HTTP keepalive disconnect during polling; the utility was
corrected to use fresh connections and then all four passed. Documents were queued
for deletion in its finally block; synthetic account metadata remains. No personal
source documents, passwords, keys or bearer tokens were committed. An early heuristic
also counted a table grid as a figure; current extraction excludes detected table grids
from that vector-figure heuristic. This does not establish a figure detection accuracy.

## Limits and unverified optional paths

- Gemini vision is **implemented but not live-validated**; it remains disabled in local
  configuration. Tests inject an explicit vision callback and verify opt-in and
  model-derived labeling. They do not demonstrate visual understanding. A separate
  live probe and human chart/figure review are required before claiming that capability.
- Local sentence-transformer embeddings are an optional adapter/extra, **not accepted
  by a live model run** in this phase. Default Docker images use Google/OpenAI adapters.
- No claim is made for perfect merged/nested/scanned tables, handwritten text, complex
  mathematical OCR, arbitrary two-column reading order or chart values. Formula text
  is retained where the extractor emits it; extra formula-recognition models are not enabled.
- Fallback column ordering, furniture removal and vector-figure detection are heuristics.
  Table cell grids and extraction warnings remain inspectable instead of being flattened.
- Oversized table rows retain integrity and are flagged; extremely wide rows can exceed
  provider limits and require source inspection. Cancellation/timeouts are cooperative
  at native call boundaries. Container limits/restart recovery remain necessary.
- Old index content stays private until coordinated deletion/retirement. Choose a new
  collection for an embedding-space change and reindex explicitly. Model quality,
  adversarial documents, multi-host load and public production hardening remain later work.
- Phase 1 live Gemini **answer generation** previously returned 503; successful Phase 2
  ingestion proves real embedding calls, not that answer-generation acceptance was repaired.

## Git and next phase

The existing user-owned GitHub remote and Phase 1 tag are preserved. The Phase 2 commit
uses plain English, `Improve PDF processing and background ingestion`, and is pushed
only after checks and staged-content review. Resolve its exact hash in Git history;
the final completion report supplies the verified remote hash. Do not move the Phase 1
tag or force-push. Phase 2 core ingestion is ready for review and Phase 3 planning.
Phase 3 has not started; optional vision acceptance is explicitly outstanding.
