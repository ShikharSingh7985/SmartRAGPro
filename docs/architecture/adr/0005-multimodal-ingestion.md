# ADR 0005: Page-bounded multimodal ingestion and Redis delivery

Accepted for Phase 2, 2026-11-06.

Docling 2.148 is the primary structural parser in the CPU worker image. PyMuPDF 1.28
inspects pages, detects vector tables, extracts original raster streams, and renders
bounded previews. Tesseract performs selective OCR; unreadable pages can use Docling's
Tesseract CLI integration so table structure is recovered after OCR. Parse failures
fall back explicitly with warnings rather than pretending Docling succeeded.

The application retains a modular monolith, one dispatcher and a separate worker.
Dramatiq 2.2 delivers UUID-only job messages through Redis. PostgreSQL remains the
durable job outbox and state authority; broker loss or dead letters cannot erase work.
The dispatcher redelivers due queued/expired-leased work. Worker claims, per-document
PostgreSQL advisory locks, lease heartbeats and run tokens serialize retries and cleanup.
Only an atomically published ready run can be retrieved. No OCR/embedding runs in HTTP.

Page-sized extraction and embedding batches bound normal working memory. Uploaded
files and S3 downloads use streams/temporary files. Raster dimensions, image counts,
OCR timeouts, parser timeouts, job deadlines and extracted characters have configurable
limits. Container limits are a final safety boundary, not a measured performance claim.

Tables retain JSON cells/spans, row arrays, captions and repeated multi-level header
context. A too-wide single row stays intact and is flagged rather than silently
flattened. Figures retain original streams where safe, bounded previews, captions and
optional label OCR. Gemini vision requires both enhanced mode and VISION_ENABLED.
Its descriptions are explicitly marked model-derived and never treated as exact chart
data. No multimodal embedding capability is claimed; image assets are ready for it later.

Model identity/dimension/version fingerprints guard vector indexes. Content-derived
chunk IDs let retries retrieve/reuse existing vectors. Owner/hash/mode uniqueness
deduplicates uploads without exposing another user's files. A new model requires a new
collection and explicit authorized reindexing; historical index references remain in
job records so deletion cleans every known collection.

References: [Docling options](https://docling-project.github.io/docling/reference/pipeline_options/),
[PyMuPDF pages](https://pymupdf.readthedocs.io/en/latest/page.html),
[Dramatiq delivery and retries](https://dramatiq.io/guide.html).
